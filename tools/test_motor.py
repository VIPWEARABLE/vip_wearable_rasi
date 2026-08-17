import time
import lgpio

PIN_L = 12  # 물리 핀 32번
PIN_R = 13  # 물리 핀 33번

# 1. 칩 열기 (RPi 5는 기본 4번)
try:
    h = lgpio.gpiochip_open(4)
except Exception:
    h = lgpio.gpiochip_open(0)

# 2. 핀 출력 모드 점유 (필수)
lgpio.gpio_claim_output(h, PIN_L)
lgpio.gpio_claim_output(h, PIN_R)

print("--- [1단계] 100% 디지털 HIGH 신호 인가 테스트 (모터 돌아야 함) ---")
lgpio.gpio_write(h, PIN_L, 1) # 왼쪽 모터 100% ON
time.sleep(1.5)
lgpio.gpio_write(h, PIN_L, 0)

lgpio.gpio_write(h, PIN_R, 1) # 오른쪽 모터 100% ON
time.sleep(1.5)
lgpio.gpio_write(h, PIN_R, 0)

print("--- [2단계] 50% PWM 신호 인가 테스트 ---")
lgpio.tx_pwm(h, PIN_L, 1000, 80.0) # 50% 듀티비
time.sleep(1.5)
lgpio.tx_pwm(h, PIN_L, 1000, 0.0)

lgpio.tx_pwm(h, PIN_R, 1000, 80.0) # 50% 듀티비
time.sleep(1.5)
lgpio.tx_pwm(h, PIN_R, 1000, 0.0)

# 3. 해제
lgpio.gpio_free(h, PIN_L)
lgpio.gpio_free(h, PIN_R)
lgpio.gpiochip_close(h)
print("테스트 완료")