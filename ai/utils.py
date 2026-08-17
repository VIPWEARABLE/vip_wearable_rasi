# c:\Users\KCCISTC\Desktop\raspi_communicaton\sem_utils.py
import cv2
import numpy as np
import time
from ultralytics import YOLO

import basic.handler as handler
import basic.g_val as g
import basic.config as config

prev_sent_angle = -999.0

def calculate_avoidance_direction(boxes, width, height):
    SAFE_WINDOW_WIDTH = 100        
    CRITICAL_MAP_THRESHOLD = 0.3   
    CENTER_MARGIN = 20             

    danger_map = np.zeros(width, dtype=np.float32)
    total_danger_score = 0.0

    for box in boxes:
        x1, y1, x2, y2 = box.xyxy[0].cpu().numpy()
        ix1, ix2 = int(np.clip(x1, 0, width)), int(np.clip(x2, 0, width))
        area_ratio = ((x2 - x1) * (y2 - y1)) / (width * height)
        danger_map[ix1:ix2] += area_ratio
        total_danger_score += area_ratio

    if total_danger_score <= CRITICAL_MAP_THRESHOLD:
        return 0, total_danger_score

    min_danger = float('inf')
    best_center_x = width // 2
    
    for s in range(0, width - SAFE_WINDOW_WIDTH + 1):
        e = s + SAFE_WINDOW_WIDTH
        window_danger = np.sum(danger_map[s:e])
        if window_danger < min_danger:
            min_danger = window_danger
            best_center_x = s + (SAFE_WINDOW_WIDTH // 2)
        elif window_danger == min_danger:
            if abs((s + SAFE_WINDOW_WIDTH // 2) - (width // 2)) < abs(best_center_x - (width // 2)):
                best_center_x = s + (SAFE_WINDOW_WIDTH // 2)

    screen_center = width // 2
    left_bound, right_bound = screen_center - CENTER_MARGIN, screen_center + CENTER_MARGIN

    if left_bound <= best_center_x <= right_bound: direction_id = 3
    elif best_center_x < left_bound: direction_id = 1
    else: direction_id = 2

    return direction_id, total_danger_score
## 이미지에 관심영역을 설정

def write_ROI(frame, width, height, img_x=None, img_y=None, color=(255, 0, 0), thickness=2, opacity=0.2):
    h_max, w_max = frame.shape[:2]
    
    if img_x is None:
        start_x = int((w_max / 2) - (width / 2))
    else:
        start_x = int(img_x)
        
    if img_y is None:
        start_y = int(h_max - height)
    else:
        start_y = int(img_y)
    
    x1, y1 = max(0, start_x), max(0, start_y)
    x2, y2 = min(w_max, int(x1 + width)), min(h_max, int(y1 + height))
    
    # [디버깅용 시각화]
    overlay = frame.copy()
    cv2.rectangle(overlay, (x1, y1), (x2, y2), color, -1)
    cv2.addWeighted(overlay, opacity, frame, 1 - opacity, 0, frame)
    
    cv2.rectangle(frame, (x1, y1), (x2, y2), color, thickness)
    cv2.putText(frame, "Foot ROI", (x1, y1 - 5), cv2.FONT_HERSHEY_SIMPLEX, 0.5, color, 1, cv2.LINE_AA)
                
    # 🎯 연산을 위해 frame과 함께 실제 좌표 쌍을 반환하도록 수정
    return frame, (x1, y1, x2, y2)
    """ 
    순수 7채널 세그멘테이션 출력 텐서를 받아 원본 이미지 위에 반투명 마스크를 오버레이하는 함수
    
    Args:
        display_img (numpy.ndarray): 화면 표시용 원본 이미지 (BGR)
        output_tensor (numpy.ndarray): 모델이 뱉은 생(Raw) 텐서 [7, 256, 320]
        color_map (dict): 클래스 ID별 BGR 색상 딕셔너리
        
    Returns:
        numpy.ndarray: 마스킹 시각화가 완료된 프레임
    """
def draw_semantic_mask(display_img, output_tensor, color_map):
    # 🔥 [수정] 데이터가 2차원이든 3차원이든 맨 뒤의 두 축을 높이, 너비로 안전하게 가져옴
    # 예: [256, 320] 이면 뒤에서부터 각각 h=256, w=320 추출
    input_h, input_w = output_tensor.shape[-2], output_tensor.shape[-1]
    display_h, display_w = display_img.shape[:2]
    
    # 1. 채널 축에서 가장 높은 확률의 클래스 인덱스 추출
    # 만약 데이터가 이미 2차원이면 argmax를 할 필요가 없으므로 차원 수 체크
    if len(output_tensor.shape) == 3:
        mask_indices = np.argmax(output_tensor, axis=0)
    else:
        # 이미 2차원 [256, 320] 맵인 경우 그대로 사용
        mask_indices = output_tensor

    # 2 & 3. 룩업 테이블(LUT) 가속 및 안전한 크기 확보
    try:
        max_cls_id = max(int(k) for k in color_map.keys())
    except ValueError:
        max_cls_id = int(np.max(mask_indices))
        
    max_id = max(max_cls_id, int(np.max(mask_indices)))
    lut = np.zeros((max_id + 1, 3), dtype=np.uint8)
    
    for cls_id, color in color_map.items():
        lut[int(cls_id)] = color

    # 4. 루프 없이 초고속 인덱싱 매핑
    seg_mask_img = lut[mask_indices]

    # 5. 마스크 확대 및 반투명 합성
    resized_mask = cv2.resize(seg_mask_img, (display_w, display_h), interpolation=cv2.INTER_LINEAR)
    annotated_frame = cv2.addWeighted(display_img, 0.7, resized_mask, 0.3, 0)
    
    return annotated_frame

def draw_semantic_int8_mask(display_img, output_tensor, color_map):
    # [INT8 구조 맞춤] TFLite 출력 규격(NHWC)에 따라 채널 위치가 맨 뒤인지 확인하여 해상도 추출
    if output_tensor.shape[-1] == 7:
        input_h, input_w = output_tensor.shape[0], output_tensor.shape[1]
        axis_target = -1  # [256, 320, 7] 구조일 때 채널 축 기준 argmax
    else:
        input_h, input_w = output_tensor.shape[1], output_tensor.shape[2]
        axis_target = 0   # 기존 구조일 때 채널 축 기준 argmax

    display_h, display_w = display_img.shape[:2]
    
    # 1. 7개 채널 중 가장 값이 높은 클래스의 인덱스를 픽셀별로 추출 [256, 320]
    mask_indices = np.argmax(output_tensor, axis=axis_target)

    # 2. 색을 입힐 빈 마스크 캔버스 생성 [256, 320, 3] 대신 룩업 테이블(LUT) 배열 생성
    # 0~255 범위의 인덱스를 RGB 색상으로 다이렉트 매핑할 수 있는 가속 배열을 만듭니다.
    COLOR_LOOKUP = np.zeros((256, 3), dtype=np.uint8)
    for cls_id, color in color_map.items():
        COLOR_LOOKUP[cls_id] = color

    # 3. 넘파이 인덱싱 가속 수식으로 클래스별 색상 칠하기 🌟
    # 기존의 파이썬 for 루프 검사를 통째로 지우고, 단 한 줄의 넘파이 배열 매핑으로 0.001초 만에 끝냅니다.
    seg_mask_img = COLOR_LOOKUP[mask_indices.astype(np.uint8)]

    # 4. [256x320] 크기의 마스크 지도를 최종 디스플레이 화면 크기로 확대
    resized_mask = cv2.resize(seg_mask_img, (display_w, display_h), interpolation=cv2.INTER_LINEAR)

    # 5. 원본 이미지와 복원된 마스크를 7:3 비율로 합성 (반투명 효과)
    annotated_frame = cv2.addWeighted(display_img, 0.7, resized_mask, 0.3, 0)
    
    return annotated_frame

import time

class FPSCalculator:
    def __init__(self, interval=1.0):
        self.interval = interval       # FPS를 갱신할 주기 (초)
        self.last_update = time.time()  # 마지막 갱신 시간
        self.frame_count = 0           # 프레임 카운터
        self.current_fps = 0.0         # 계산된 현재 FPS 값

    def update(self):
        """프레임이 처리될 때마다 호출하여 카운트를 올립니다."""
        self.frame_count += 1

    def get_fps(self):
        """지정된 interval 주기마다 FPS를 계산하여 반환합니다."""
        now = time.time()
        elapsed = now - self.last_update
        
        if elapsed >= self.interval:
            self.current_fps = self.frame_count / elapsed
            self.frame_count = 0
            self.last_update = now
            
        return self.current_fps


def process_navigation_vibration(angle: float):
    """ 이제 단순히 앱 각도가 너무 커서 제자리 회전 중인지(Phase 1) 판별만 합니다 """
    clipped_angle = max(-100.0, min(100.0, angle))
    if abs(clipped_angle) >= config.ROTATION_THRESHOLD_DEG:
        g.IS_ROTATING.value = True
    else:
        g.IS_ROTATING.value = False