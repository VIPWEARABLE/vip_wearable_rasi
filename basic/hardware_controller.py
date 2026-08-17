import math
import struct
import time
import serial
import lgpio
import basic.g_val as g
import basic.config as config

# ==========================================
# 핀 설정 및 상수 정의
# ==========================================
PIN_MOTOR_LEFT = 12   # GPIO 12 (물리 32번)
PIN_MOTOR_RIGHT = 13  # GPIO 13 (물리 33번)
PWM_FREQ = 1000       # 1kHz

FALL_LOW_THRESHOLD = 0.5
FALL_HIGH_THRESHOLD = 2.5
FALL_GYRO_THRESHOLD = 150.0

HAPTIC_AVOID_TOGGLE_SEC = 0.5  # 500ms 회피 피드백 주기
MOTOR_MAX = 999                # PWM 최대값

HAPTIC_AVOID_TOGGLE_SEC = 0.5   # 장애물 회피 토글 주기 (0.5초 징- 0.5초 쉼)
HAPTIC_MAX_ANGLE_ERR = 100.0     # 최대 비례제어 각도 오차
HAPTIC_MIN_PWM = 300            # 최소 진동 세기 (기동 세기)
HAPTIC_MAX_PWM = 1000           # 최대 진동 세기

class HardwareController:
    def __init__(self, port=config.UART_PORT, baudrate=config.BAUDRATE):
        # 1. 시리얼 초기화 (EBIMU USB 연결)
        self.ser = serial.Serial(port=port, baudrate=baudrate, timeout=0.01)
        
        # 2. 라즈베리파이 5 메인 GPIO 칩 열기
        try:
            self.chip_handle = lgpio.gpiochip_open(4)
        except Exception:
            self.chip_handle = lgpio.gpiochip_open(0)

        # 3. 핀 출력 권한 선점 (claim_output 필수)
        try:
            lgpio.gpio_claim_output(self.chip_handle, PIN_MOTOR_LEFT)
            lgpio.gpio_claim_output(self.chip_handle, PIN_MOTOR_RIGHT)
        except Exception:
            pass

        # 초기 모터 정지
        self._set_raw_pwm(0, 0)
        
        # 4. IMU 상태 변수
        self.acc_x, self.acc_y, self.acc_z = 0.0, 0.0, 0.0
        self.gyro_x, self.gyro_y, self.gyro_z = 0.0, 0.0, 0.0
        self.rx_buffer = bytearray()
        
        # 5. 낙상 감지 상태
        self.fall_state = 0 
        self.fall_timer = 0.0
        
        # 6. 진동 토글 타이머
        self.last_toggle_time = time.time()
        self.avoid_toggle_state = False

    def update_imu(self, is_connected: bool):
        """BLE 연결 상태에 따라 IMU 데이터를 처리하거나 버림"""
        if not is_connected:
            if self.ser.in_waiting > 0:
                self.ser.reset_input_buffer()
                self.rx_buffer.clear()
            return

        if self.ser.in_waiting > 0:
            self.rx_buffer.extend(self.ser.read(self.ser.in_waiting))
            
        while len(self.rx_buffer) >= 22:
            if self.rx_buffer[0] == 0x55 and self.rx_buffer[1] == 0x55:
                packet = self.rx_buffer[:22]
                calc_chk = sum(packet[:20]) & 0xFFFF
                recv_chk = (packet[20] << 8) | packet[21]
                
                if calc_chk == recv_chk:
                    vals = struct.unpack(">hhhhhhh", packet[2:16])
                    
                    g.PITCH.value = vals[1] / 100.0
                    g.YAW.value = vals[2] / 100.0
                    
                    self.gyro_x = vals[3] / 10.0
                    self.gyro_y = vals[4] / 10.0
                    self.gyro_z = vals[5] / 10.0
                    
                    acc_vals = struct.unpack(">hhh", packet[16:22])
                    self.acc_x = acc_vals[0] / 1000.0
                    self.acc_y = acc_vals[1] / 1000.0
                    self.acc_z = acc_vals[2] / 1000.0
                    
                    self.rx_buffer = self.rx_buffer[22:]
                    continue
            self.rx_buffer.pop(0)

    def check_fall_detection(self) -> bool:
        svm = math.sqrt(self.acc_x**2 + self.acc_y**2 + self.acc_z**2)
        gvm = math.sqrt(self.gyro_x**2 + self.gyro_y**2 + self.gyro_z**2)
        curr_time = time.time()

        if self.fall_state == 0:  
            if svm < FALL_LOW_THRESHOLD:
                self.fall_state = 1  
                self.fall_timer = curr_time
        elif self.fall_state == 1: 
            if (curr_time - self.fall_timer) > 0.5:
                self.fall_state = 0
            else:
                if svm > FALL_HIGH_THRESHOLD and gvm > FALL_GYRO_THRESHOLD:
                    self.fall_state = 2  
                    self.fall_timer = curr_time
        elif self.fall_state == 2:  
            if (curr_time - self.fall_timer) > 1.0:
                self.fall_state = 0
                if gvm < 15.0 and 0.8 < svm < 1.2:
                    return True
        return False

    def _set_raw_pwm(self, left_val: int, right_val: int):
        """0~999 수치를 0~100% 듀티비로 변환하여 출력"""
        left_val = min(max(left_val, 0), MOTOR_MAX)
        right_val = min(max(right_val, 0), MOTOR_MAX)

        left_duty = (left_val / float(MOTOR_MAX)) * 100.0
        right_duty = (right_val / float(MOTOR_MAX)) * 100.0

        try:
            lgpio.tx_pwm(self.chip_handle, PIN_MOTOR_LEFT, PWM_FREQ, float(left_duty))
            lgpio.tx_pwm(self.chip_handle, PIN_MOTOR_RIGHT, PWM_FREQ, float(right_duty))
        except Exception as e:
            print(f"[PWM Error] {e}")

    def update_haptic(self, angle_error: float, is_avoidance: bool):
        curr_time = time.time()
        
        # 1. 장애물 회피 모드 (직진 중 장애물 감지 시 징-징-징 토글)
        if is_avoidance:
            if curr_time - self.last_toggle_time >= HAPTIC_AVOID_TOGGLE_SEC:
                self.last_toggle_time = curr_time
                self.avoid_toggle_state = not self.avoid_toggle_state
                
            if self.avoid_toggle_state:
                fixed_power = 800  # 강력한 고정 세기
                # angle_error가 음수(왼쪽 회피)면 왼쪽 모터, 양수(오른쪽 회피)면 오른쪽 모터
                if angle_error < 0:
                    self._set_raw_pwm(fixed_power, 0)
                else:
                    self._set_raw_pwm(0, fixed_power)
            else:
                self._set_raw_pwm(0, 0)
            return

        # 장애물 회피가 아닐 때는 토글 상태를 True로 초기화해두어 다음 회피 시 즉각 반응하도록 함
        self.avoid_toggle_state = True
        self.last_toggle_time = curr_time

        # 2. 일반 내비게이션 회전 모드 (|angle_error| > 15.0)
        abs_err = abs(angle_error)
        if abs_err <= 15.0:
            self._set_raw_pwm(0, 0)
            return

        # 선형 비례 제어 (각도 오차가 클수록 더 강하게 진동)
        clamped_err = min(abs_err, HAPTIC_MAX_ANGLE_ERR)
        power_ratio = (clamped_err - 15.0) / (HAPTIC_MAX_ANGLE_ERR - 15.0)
        pwm_val = int(HAPTIC_MIN_PWM + power_ratio * (HAPTIC_MAX_PWM - HAPTIC_MIN_PWM))

        if angle_error < 0:
            self._set_raw_pwm(pwm_val, 0)   # 좌회전 안내
        else:
            self._set_raw_pwm(0, pwm_val)   # 우회전 안내

    def close(self):
        try:
            self._set_raw_pwm(0, 0)
            lgpio.gpio_free(self.chip_handle, PIN_MOTOR_LEFT)
            lgpio.gpio_free(self.chip_handle, PIN_MOTOR_RIGHT)
            lgpio.gpiochip_close(self.chip_handle)
        except Exception:
            pass
            
        if self.ser.is_open:
            self.ser.close()