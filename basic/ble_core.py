import time
import sys
import asyncio
import struct
import subprocess
import serial
import queue
import basic.g_val as g
import basic.config as config
from multiprocessing import Queue

try:
    import bluetooth
except ImportError:
    bluetooth = None

latest_stm32_yaw = 0.0
has_st_awakened = False
global_serial = None
bt_server = None
bt_client = None
bt_rx_buffer = bytearray()

ai_tx_queue = None

def init_ai_queue(shared_queue):
    global ai_tx_queue
    ai_tx_queue = shared_queue

async def watch_ai_commands_loop():
    global global_serial, has_st_awakened
    print("[ble_core.py] AI 제어 명령 수신 태스크 가동 완료.")
    
    while True:
        try:
            if ai_tx_queue and not ai_tx_queue.empty():
                try:
                    angle_error, state = ai_tx_queue.get_nowait()
                    st = 0x01 if state else 0x00
                    print(f"🚨 [ble_core] ST32로 회피 피드백 전송 -> Angle: {angle_error:.1f}, State: {st}")
                    if global_serial and global_serial.is_open:
                        packet = bytearray([0xAA]) + struct.pack('!f', angle_error) + bytearray([0x01]) + bytearray([st])
                        global_serial.write(packet)
                        global_serial.flush()
                except queue.Empty:
                    pass
        except Exception as e:
            print(f"[ble_core.py] AI 명령 전달 중 오류: {e}")
        await asyncio.sleep(0.02)

def reset_hardware_to_sleep():
    global has_st_awakened, latest_stm32_yaw, global_serial
    if has_st_awakened:
        has_st_awakened = False

        g.BLE_CONNECTED.value = False
        g.ANGLE_VALUE.value = 999.0
        g.ANGLE_OK.value = False

        print("\n==================================================")
        print("[ble_core.py] 연결 종료 명령(또는 단절) 수신! 대기 모드 진입")
        print("ST 보드를 슬립 모드(0x00)로 리셋 및 AI 비전 분석 중단")
        print("==================================================")
        send_control_flag_to_stm32(0x00)
        latest_stm32_yaw = 0.0
        if global_serial and global_serial.is_open:
            global_serial.reset_input_buffer()

def send_control_flag_to_stm32(flag_value):
    global global_serial
    if global_serial is None or not global_serial.is_open:
        return
    try:
        packet = bytearray([0xAA]) + struct.pack('!f', 0.0) + bytearray([flag_value]) + bytearray([0x00])
        global_serial.write(packet)
        global_serial.flush()
        status_text = "구동(Wake)" if flag_value == 0x01 else "대기/초기화(Sleep)"
        print(f"[ble_core.py] ST 보드로 {status_text} 명령 플래그 전송 완료.")
    except Exception as e:
        print(f"[ble_core.py] 오류: ST 플래그 전파 실패: {e}")

def handle_app_packet(value):
    global has_st_awakened
    try:
        if len(value) == 2 and value[0] == 0x33:
            app_state = value[1]

            if app_state == 0:
                print("\n[ble_core.py] 📱앱 명령: 연결 종료 (Sleep)")
                reset_hardware_to_sleep()

            elif app_state == 1:
                print("\n==================================================")
                print("[ble_core.py] 📱앱 명령: 연결됨/경로취소 (AI ON, 대기 중)")
                print("==================================================")
                g.ANGLE_VALUE.value = 999.0
                g.ANGLE_OK.value = False

                if not has_st_awakened:
                    has_st_awakened = True
                    g.BLE_CONNECTED.value = True
                    if global_serial and global_serial.is_open:
                        global_serial.reset_input_buffer()
                    send_control_flag_to_stm32(0x01)

                if ai_tx_queue:
                    try:
                        ai_tx_queue.put_nowait((0.0, False))
                    except queue.Full:
                        pass

            elif app_state == 2:
                print("\n[ble_core.py] 📱앱 명령: 목적지 입력! (내비게이션 시작)")
                g.ANGLE_OK.value = True  

        elif len(value) == 5 and value[0] == 0x22:
            g.ANGLE_VALUE.value = struct.unpack('!f', value[1:5])[0]
            direction = "중앙"
            if g.ANGLE_VALUE.value > 10.0:
                direction = "오른쪽"
            elif g.ANGLE_VALUE.value < -10.0:
                direction = "왼쪽"
            print(f"[ble_core.py] 수신: 앱 경로 오차: {g.ANGLE_VALUE.value:.1f}° -> {direction} 보정          ")

    except Exception as e:
        print(f"\n[ble_core.py] 오류: 앱 패킷 디코딩 실패: {e}")

def handle_bt_payload(data):
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

def force_kernel_advertising():
    print("[ble_core.py] 일반 Bluetooth RFCOMM 서버 대기 준비 중...")

async def read_stm32_uart_loop():
    global latest_stm32_yaw, has_st_awakened, global_serial
    while True:
        try:
            if not has_st_awakened:
                if global_serial and global_serial.is_open and global_serial.in_waiting > 0:
                    global_serial.reset_input_buffer()
                await asyncio.sleep(0.1)
                continue

            if global_serial and global_serial.is_open and global_serial.in_waiting >= 9: 
                header = global_serial.read(1)
                if header == b'\xaa':
                    payload = global_serial.read(4)
                    parsed_yaw = struct.unpack('<f', payload)[0]
                    payload = global_serial.read(4)
                    parsed_pitch = struct.unpack('<f', payload)[0]
                    
                    if -180.0 <= parsed_yaw <= 180.0:
                        latest_stm32_yaw = parsed_yaw
                    if -90.0 <= parsed_pitch <= 90.0:
                        g.PITCH.value = parsed_pitch
        except Exception:
            pass
        await asyncio.sleep(0.01)

async def send_yaw_loop(_service_instance=None):
    global latest_stm32_yaw, has_st_awakened, bt_client  # 👈 bt_client 추가!
    print(f"[ble_core.py] {int(config.YAW_TX_PERIOD_SEC * 1000)}ms 주기 방위각 스트리밍 대기 중...")
    while True:
        try:
            if not has_st_awakened or bt_client is None:
                await asyncio.sleep(config.YAW_TX_PERIOD_SEC)
                continue

            raw_packet = bytearray([0x11]) + struct.pack('!f', latest_stm32_yaw)
            bt_client.sendall(bytes(raw_packet))
            print(f"[ble_core.py] 송신: STM32 방위각(Yaw) 전송 중: {latest_stm32_yaw:.2f}°")

        except Exception as e:
            print(f"\n[ble_core.py] 경고: 앱 연결 전송 중 오류 발생: {e}")
            try:
                if bt_client is not None:
                    bt_client.close()
            except Exception:
                pass
            bt_client = None
            reset_hardware_to_sleep()

        await asyncio.sleep(config.YAW_TX_PERIOD_SEC)

async def bt_accept_loop():
    global bt_server, bt_client, has_st_awakened

    if bluetooth is None:
        print("[ble_core.py] 경고: PyBluez(bluetooth)가 설치되어 있지 않습니다.")
        return

    try:
        bt_server = bluetooth.BluetoothSocket(bluetooth.RFCOMM)
        bt_server.bind(("", 1))
        bt_server.listen(1)
        print("\n==================================================")
        print("[ble_core.py] 일반 Bluetooth RFCOMM 서버 대기 중... (채널 1)")
        print("==================================================")

        while True:
            try:
                client, address = await asyncio.to_thread(bt_server.accept)
                bt_client = client
                g.BLE_CONNECTED.value = True
                has_st_awakened = True
                print(f"\n[ble_core.py] 📱 안드로이드 앱 연결 성공!: {address}")

                while True:
                    data = await asyncio.to_thread(client.recv, 1024)
                    if not data:
                        raise ConnectionError("앱 연결 종료")
                    handle_bt_payload(data)
            except Exception as e:
                print(f"\n[ble_core.py] 앱 Bluetooth 연결 종료 또는 에러: {e}")
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

async def async_ble_main():
    global global_serial
    print("[ble_core.py] STM32용 UART 채널 바인딩 중...")
    try:
        global_serial = serial.Serial(config.UART_PORT, baudrate=config.BAUDRATE, timeout=0.1)
    except Exception as e:
        print(f"[ble_core.py] 오류: UART 포트 실패: {e}")
        global_serial = None

    force_kernel_advertising()
    print("==================================================")
    print("라즈베리파이 일반 Bluetooth 가이드 서버")
    print("==================================================")

    await asyncio.gather(
        bt_accept_loop(),
        send_yaw_loop(),
        read_stm32_uart_loop(),
        watch_ai_commands_loop(),
    )

def run_ble_server_process(shared_queue):
    global ai_tx_queue, has_st_awakened, global_serial
    ai_tx_queue = shared_queue
    try:
        asyncio.run(async_ble_main())
    except KeyboardInterrupt:
        print("\n[ble_core.py] BLE 서버 종료 중...")
        has_st_awakened = True
        reset_hardware_to_sleep()
        if global_serial and global_serial.is_open:
            global_serial.close()
        if bt_client is not None:
            bt_client.close()
        if bt_server is not None:
            bt_server.close()
        sys.exit(0)