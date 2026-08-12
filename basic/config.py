
# basic/config.py
import struct
import cv2
import onnxruntime as ort

# 1. 라즈베리파이 5의 4개 코어를 모두 쓰도록 멀티스레딩 및 그래프 최적화 설정
options = ort.SessionOptions()
options.intra_op_num_threads = 1  
options.graph_optimization_level = ort.GraphOptimizationLevel.ORT_ENABLE_ALL

TIMER_INTERVAL = 1


VIDEO_SHM_NAME = "assist_video_shm"
WIDTH = 320
HEIGHT = 256
CHANNELS = 3
FRAME_SIZE = WIDTH * HEIGHT * CHANNELS

CAMERA_BACKEND = cv2.CAP_V4L2    
CAMERA_BUFFER_SIZE = 1  

PACKET_FORMAT = "!BfBB"
PACKET_SIZE = struct.calcsize(PACKET_FORMAT)

PIPE_PATH = "/tmp/assist_event_pipe"
SOCKET_HOST = "127.0.0.1"
SOCKET_PORT = 9999
SHOW_DISPLAY = False

# --- 일반 Bluetooth (Classic / RFCOMM) 정적 상수 ---
BT_RFCOMM_CHANNEL = 1
BT_DEVICE_NAME = "VIP_Guide"

# 기존 앱 프로토콜 호환 유지
SERVICE_UUID = "0000ffe0-0000-1000-8000-00805f9b34fb"
CHAR_YAW_NOTIFY_UUID = "0000ffe1-0000-1000-8000-00805f9b34fb"
CHAR_ERROR_WRITE_UUID = "0000ffe2-0000-1000-8000-00805f9b34fb"

YAW_TX_PERIOD_SEC = 0.1
DISCONNECT_TIMEOUT_SEC = 2.0
UART_PORT = "/dev/ttyAMA0"
BAUDRATE = 115200

# 내비게이션 및 AI 제어 하이퍼파라미터
ROTATION_THRESHOLD_DEG = 20.0  # Phase 1(회전)과 Phase 2(직진)를 가르는 기준 각도
ANGLE_UPDATE_DELTA_DEG = 2.0   # 큐(Queue) 폭주를 막기 위해, 각도가 이 값(2도) 이상 변했을 때만 ST로 실시간 전송
AI_AVOID_ANGLE = 70.0          # AI 장애물 감지 시 강제 회피 조향 각도