# basic/g_val.py
from multiprocessing import Value

# 최초 1회 생성되어 모든 프로세스 간에 완벽히 동기화되는 전역 변수 방 개설
FRAME_OK = Value('b', False)
OD_PROCESSING = Value('b', True)
SEM_PROCESSING = Value('b', True)
OBJECT_EXIST = Value('b', False)
ANGLE_LEFT_RIGHT = Value('b', False)
ANGLE_OK = Value('b', False)       # 목적지 입력 여부 (이게 True일 때만 AI 가동)
ANGLE_VALUE = Value('f', 999.0)    # 앱에서 넘겨주는 각도 (999.0은 초기/대기 상태)
BLE_CONNECTED = Value('b', False)  # BLE 연결 상태

# IMU 데이터 공유용 변수 추가
YAW = Value('f', 0.0)
PITCH = Value('f', 0.0)

# 프로세스 간 상태 공유
AI_AVOID_ANGLE_VALUE = Value('f', 0.0)
IS_ROTATING = Value('b', False)      
AI_AVOIDING = Value('b', False)      
FORCE_APP_RESEND = Value('b', False)