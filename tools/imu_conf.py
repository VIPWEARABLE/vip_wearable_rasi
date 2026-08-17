import serial
import struct
import time
import sys

# ----------------------------------------------------
# 환경에 맞게 시리얼 포트 설정
# ----------------------------------------------------
PORT = '/dev/ttyUSB0'
BAUDRATE = 115200

def send_cmd(ser, cmd, desc="", wait_time=0.2):
    """EBIMU V5 프로토콜에 맞춘 명령어 전송 함수"""
    ser.write(cmd.encode())
    time.sleep(wait_time)
    print(f"  -> [전송] {cmd:<8} ({desc})")

def setup_ebimu_basic(ser):
    """지자기 상시 융합(sem1), LPF 필터 및 가속도/자이로 수평 0점 캘리브레이션"""
    print("\n[1. 기본 센서 융합 및 수평 0점 보정]")
    print("👉 센서를 평평한 바닥에 가만히 내려놓으세요. (흔들림 금지)")
    input("준비되었으면 [엔터]를 누르세요...")

    # sem1: 부팅 시 항상 지자기 센서를 100% 융합하도록 강제 (sem2는 실내에서 꺼질 수 있음)
    send_cmd(ser, "<sem1>", "지자기 상시 융합 활성화 (9DOF AHRS)")
    send_cmd(ser, "<lpfa4>", "가속도계 LPF 73Hz 설정")
    send_cmd(ser, "<lpfg4>", "자이로스코프 LPF 73Hz 설정")
    
    print("  * 수평 가속도 캘리브레이션 진행 중...")
    send_cmd(ser, "<cas>", "수평 가속도 캘리브레이션", wait_time=1.0)

    print("  * 자이로 바이어스 0점 측정 중 (2초 대기)...")
    send_cmd(ser, "<cg>", "자이로 캘리브레이션", wait_time=2.0)
    print("✅ 기본 수평/자이로 보정 완료! (기존 영점 오프셋은 보존됩니다)\n")

def run_magnetic_calibration(ser):
    """지자기 3D 8자 캘리브레이션 (정석)"""
    print("\n[2. 지자기 3D 캘리브레이션 (8자 돌리기)]")
    input("👉 센서를 장착한 기구를 들고 준비 후 [엔터]를 누르세요...")

    send_cmd(ser, "<cmf>", "지자기 3축 자유 캘리브레이션 시작")
    print("🌀 3차원 공중에서 8자(뫼비우스의 띠)로 천천히 회전시키세요. (X, Y, Z 모든 면)")

    for remaining in range(20, 0, -1):
        print(f"남은 시간: {remaining:02d}초... (데이터 수집 중)", end="\r")
        time.sleep(1)
    
    ser.write(b">")
    time.sleep(1.5)
    print("\n✅ 지자기 3D 캘리브레이션 및 자동 저장 완료!\n")

def set_manual_yaw_zero(ser):
    """원하는 방향을 Yaw 0도(정북)로 강제 영구 고정 (<cmoz>)"""
    print("\n[3. 수동 Yaw 0도(정북) 고정]")
    print("👉 센서를 수평으로 둔 상태에서,")
    print("👉 '0도'로 삼고 싶은 전방을 똑바로 향하게 고정해 두세요.")
    input("준비되었으면 [엔터]를 누르세요...")

    send_cmd(ser, "<cmoz>", "현재 방향을 Yaw 0도로 영점 고정", wait_time=0.5)
    print("✅ 현재 방향이 Yaw 0도로 영구 각인되었습니다!\n")

def parse_and_stream(ser):
    """HEX 모드 데이터 실시간 수신 및 파싱 출력"""
    print("\n=======================================================")
    print("📡 실시간 IMU 데이터 수신 중... (종료: Ctrl + C)")
    print("=======================================================")
    
    ser.reset_input_buffer()
    buffer = bytearray()

    while True:
        if ser.in_waiting > 0:
            buffer.extend(ser.read(ser.in_waiting))

        while len(buffer) >= 22:
            if buffer[0] == 0x55 and buffer[1] == 0x55:
                packet = buffer[:22]

                calc_checksum = sum(packet[:20]) & 0xFFFF
                recv_checksum = struct.unpack('>H', packet[20:22])[0]

                if calc_checksum == recv_checksum:
                    unpacked = struct.unpack('>9h', packet[2:20])

                    roll  = unpacked[0] / 100.0
                    pitch = unpacked[1] / 100.0
                    yaw   = unpacked[2] / 100.0

                    gyro_x = unpacked[3] / 10.0
                    gyro_y = unpacked[4] / 10.0
                    gyro_z = unpacked[5] / 10.0

                    acc_x = unpacked[6] / 1000.0
                    acc_y = unpacked[7] / 1000.0
                    acc_z = unpacked[8] / 1000.0

                    print(f"Roll: {roll:6.2f}° | Pitch: {pitch:6.2f}° | Yaw: {yaw:6.2f}° | "
                          f"Acc: ({acc_x:5.2f}, {acc_y:5.2f}, {acc_z:5.2f}) | "
                          f"Gyro: ({gyro_x:5.1f}, {gyro_y:5.1f}, {gyro_z:5.1f})")

                    buffer = buffer[22:]
                    continue
                else:
                    buffer.pop(0)
            else:
                buffer.pop(0)

        time.sleep(0.01)

def run_configuration_mode(ser):
    """센서 캘리브레이션 및 영점 설정 메뉴"""
    while True:
        print("\n--- [EBIMU 설정 메뉴] ---")
        print("  1. 기본 필터 + 수평/자이로 캘리브레이션 (<sem1>, <cas>, <cg>)")
        print("  2. 지자기 3D 8자 캘리브레이션 (<cmf>)")
        print("  3. 현재 방향을 Yaw 0도로 영구 고정 (<cmoz>)")
        print("  4. 영점 오프셋 초기화 (<cmco>)")
        print("  5. 실시간 데이터 모니터링 시작")
        print("  q. 메인 메뉴로 나가기")
        
        sub_choice = input("\n👉 원하는 설정 번호를 입력하세요: ").strip().lower()

        if sub_choice == '1':
            setup_ebimu_basic(ser)
        elif sub_choice == '2':
            run_magnetic_calibration(ser)
        elif sub_choice == '3':
            set_manual_yaw_zero(ser)
        elif sub_choice == '4':
            send_cmd(ser, "<cmco>", "오프셋 초기화", wait_time=0.5)
            print("✅ 기존 오프셋이 초기화되었습니다.\n")
        elif sub_choice == '5':
            parse_and_stream(ser)
            break
        elif sub_choice == 'q':
            break
        else:
            print("잘못된 입력입니다.")

def main():
    try:
        ser = serial.Serial(PORT, BAUDRATE, timeout=1)
        print(f"[{PORT}] EBIMU-9DOFV5 연결 성공!\n")
    except Exception as e:
        print(f"포트 연결 실패: {e}")
        return

    try:
        print("==============================")
        print(" [EBIMU 제어 모드 선택]")
        print("  1. 일반 출력 모드 (단순 모니터링)")
        print("  2. 센서 설정 모드 (영점/캘리브레이션)")
        print("==============================")
        mode = input("👉 모드를 선택하세요 (1/2): ").strip()

        if mode == '1':
            parse_and_stream(ser)
        elif mode == '2':
            run_configuration_mode(ser)
        else:
            print("프로그램을 종료합니다.")

    except KeyboardInterrupt:
        print("\n사용자에 의해 종료되었습니다.")
    finally:
        ser.close()
        print("시리얼 포트 종료.")

if __name__ == '__main__':
    main()