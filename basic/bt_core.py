import asyncio
import struct
import sys
import time
import basic.config as config
import basic.g_val as g

bluetooth = None
try:
    import bluetooth
except Exception:
    bluetooth = None
    
bt_rx_buffer = bytearray()

def reset_hardware_to_sleep():
    """앱 연결 종료 또는 단절 시 시스템 상태 초기화"""
    g.bt_CONNECTED.value = False
    g.ANGLE_VALUE.value = 999.0
    g.ANGLE_OK.value = False

    print("\n==================================================")
    print("[bt_core.py] 연결 종료 명령(또는 단절) 수신! 대기 모드 진입")
    print("[bt_core.py] 시스템 대기 모드로 리셋 및 AI 비전 분석 중단")
    print("==================================================")


def handle_app_packet(value):
    """안드로이드 앱으로부터 수신된 제어 패킷 파싱"""
    try:
        if len(value) == 2 and value[0] == 0x33:
            app_state = value[1]

            if app_state == 0:
                print("\n[bt_core.py] 📱 앱 명령: 연결 종료 (Sleep)", flush=True)
                reset_hardware_to_sleep()

            elif app_state == 1:
                print("\n==================================================", flush=True)
                print("[bt_core.py] 📱 앱 명령: 연결됨/경로취소 (AI ON, 대기 중)", flush=True)
                print("==================================================", flush=True)
                g.ANGLE_VALUE.value = 999.0
                g.ANGLE_OK.value = False  # 목적지 취소/대기
                g.bt_CONNECTED.value = True

            elif app_state == 2:
                print("\n[bt_core.py] 📱 앱 명령: 목적지 입력! (내비게이션 시작)", flush=True)
                g.ANGLE_OK.value = True  # ★ 오직 0x33, 0x02 명령이 올 때만 목적지 활성화!

        elif len(value) == 5 and value[0] == 0x22:
            g.ANGLE_VALUE.value = struct.unpack("!f", value[1:5])[0]
            # ❌ g.ANGLE_OK.value = True  <-- 이 줄을 반드시 삭제/주석 처리하세요!
            
            direction = "중앙"
            if g.ANGLE_VALUE.value > 10.0:
                direction = "오른쪽"
            elif g.ANGLE_VALUE.value < -10.0:
                direction = "왼쪽"
            print(
                f"[bt_core.py] 수신: 앱 경로 오차: {g.ANGLE_VALUE.value:.1f}° -> {direction} 보정",
                flush=True
            )

    except Exception as e:
        print(f"\n[bt_core.py] 오류: 앱 패킷 디코딩 실패: {e}", flush=True)


def handle_bt_payload(data):
    """블루투스 스트림 수신 버퍼링 및 패킷 분할 처리"""
    global bt_rx_buffer
    if not data:
        return

    bt_rx_buffer.extend(data)

    while True:
        if len(bt_rx_buffer) < 1:
            break

        header = bt_rx_buffer[0]

        if header == 0x33 and len(bt_rx_buffer) >= 2:
            handle_app_packet(bt_rx_buffer[:2])
            del bt_rx_buffer[:2]
            continue

        if header == 0x22 and len(bt_rx_buffer) >= 5:
            handle_app_packet(bt_rx_buffer[:5])
            del bt_rx_buffer[:5]
            continue

        if header not in (0x33, 0x22):
            del bt_rx_buffer[0]
            continue

        break


async def send_yaw_loop():
    """라즈베리파이 전역 변수(g.YAW)에 갱신된 IMU 방위각을 앱으로 주기적 스트리밍"""
    global bt_client
    print(
        f"[bt_core.py] {int(config.YAW_TX_PERIOD_SEC * 1000)}ms 주기 방위각 스트리밍 대기 중..."
    )
    while True:
        try:
            if not g.bt_CONNECTED.value or bt_client is None:
                await asyncio.sleep(config.YAW_TX_PERIOD_SEC)
                continue

            current_yaw = getattr(g, "YAW", None)
            yaw_val = current_yaw.value if current_yaw is not None else 0.0

            raw_packet = bytearray([0x11]) + struct.pack("!f", yaw_val)
            bt_client.sendall(bytes(raw_packet))
            # print(f"[bt_core.py] 송신: 앱으로 방위각(Yaw) 전송 중: {yaw_val:.2f}°")

        except Exception as e:
            print(f"\n[bt_core.py] 경고: 앱 연결 전송 중 오류 발생: {e}")
            try:
                if bt_client is not None:
                    bt_client.close()
            except Exception:
                pass
            bt_client = None
            reset_hardware_to_sleep()

        await asyncio.sleep(config.YAW_TX_PERIOD_SEC)


async def bt_accept_loop():
    """Bluetooth RFCOMM 연결 수락 및 수신 처리 루프"""
    global bt_server, bt_client

    if bluetooth is None:
        print("[bt_core.py] 경고: PyBluez(bluetooth)가 설치되어 있지 않습니다.")
        return

    try:
        bt_server = bluetooth.BluetoothSocket(bluetooth.RFCOMM)
        bt_server.bind(("", 1))
        bt_server.listen(1)
        print("\n==================================================")
        print("[bt_core.py] Bluetooth RFCOMM 서버 대기 중... (채널 1)")
        print("==================================================")

        while True:
            try:
                client, address = await asyncio.to_thread(bt_server.accept)
                bt_client = client
                g.bt_CONNECTED.value = True
                print(f"\n[bt_core.py] 📱 안드로이드 앱 연결 성공!: {address}")

                while True:
                    data = await asyncio.to_thread(client.recv, 1024)
                    if not data:
                        raise ConnectionError("앱 연결 종료")
                    handle_bt_payload(data)
            except Exception as e:
                print(f"\n[bt_core.py] 앱 Bluetooth 연결 종료 또는 에러: {e}")
                try:
                    if bt_client is not None:
                        bt_client.close()
                except Exception:
                    pass
                bt_client = None
                reset_hardware_to_sleep()
                await asyncio.sleep(0.5)
    finally:
        if bt_server is not None:
            bt_server.close()


async def async_bt_main():
    print("==================================================")
    print("라즈베리파이 Bluetooth 통신 서버 가동")
    print("==================================================")

    await asyncio.gather(
        bt_accept_loop(),
        send_yaw_loop(),
    )


def run_bt_server_process():
    try:
        asyncio.run(async_bt_main())
    except KeyboardInterrupt:
        print("\n[bt_core.py] bt 서버 종료 중...")
        reset_hardware_to_sleep()
        if bt_client is not None:
            bt_client.close()
        if bt_server is not None:
            bt_server.close()
        sys.exit(0)