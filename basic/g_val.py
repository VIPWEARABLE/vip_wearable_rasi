# basic/g_val.py
from multiprocessing import Value

# 최초 1회 생성되어 모든 프로세스 간에 완벽히 동기화되는 전역 변수 방 개설
FRAME_OK = Value('b', False)
OD_PROCESSING = Value('b', True)
SEM_PROCESSING = Value('b', True)
OBJECT_EXIST = Value('b', False)
ANGLE_LEFT_RIGHT = Value('b', False)
ANGLE_OK = Value('b', False)
ANGLE_VALUE = Value('f', 0.0)
PITCH = Value('f', 0.0)
BLE_CONNECTED = Value('b', False) # BLE 연결 상태를 공유하는 플래그

# 프로세스 간 상태 공유 (Mutex/Semaphore 역할)
IS_ROTATING = Value('b', False)      # True: 제자리 회전 중 (오차 >= 20도)
AI_AVOIDING = Value('b', False)      # True: AI가 전방 장애물 강제 회피 중
FORCE_APP_RESEND = Value('b', False) # True: AI 회피 종료 즉시 앱 각도를 강제로 밀어넣기 위한 락 해제 트리거