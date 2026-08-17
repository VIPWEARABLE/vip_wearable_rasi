# ai/sem.py
import os
import gc
import time
from datetime import datetime
import cv2
import numpy as np
import torch
from ultralytics import YOLO
from multiprocessing import shared_memory
from collections import deque, Counter
import signal
import sys

import basic.config as config
import basic.handler as handler
from ai.utils import FPSCalculator

class CurrentLocationStatus:
    def __init__(self, window_size=15, min_stabilize_size=5):
        self.buffer = deque(maxlen=window_size)
        self.min_size = min_stabilize_size

    def update(self, current_status):
        self.buffer.append(current_status)
        if len(self.buffer) < self.min_size:
            return "UNKNOWN", 0
        most_common_status, count = Counter(self.buffer).most_common(1)[0]
        return most_common_status, count

def analyze_terrain(class_map, pitch_offset=0):
    roi_ymin, roi_ymax = 180, 256
    roi_xmin, roi_xmax = 100, 220
    if pitch_offset != 0:
        roi_ymin = int(np.clip(roi_ymin + pitch_offset, 0, config.HEIGHT))
        roi_ymax = int(np.clip(roi_ymax + pitch_offset, 0, config.HEIGHT))

    road_roi = (class_map[roi_ymin:roi_ymax, roi_xmin:roi_xmax] == 0)
    sidewalk_roi = (class_map[roi_ymin:roi_ymax, roi_xmin:roi_xmax] == 1)
    crosswalk_roi = (class_map[roi_ymin:roi_ymax, roi_xmin:roi_xmax] == 2)
    
    roi_total_pixels = road_roi.size
    if roi_total_pixels == 0: return "UNKNOWN", 0.0, 0.0, 0.0

    road_score = np.sum(road_roi) / roi_total_pixels
    sidewalk_score = np.sum(sidewalk_roi) / roi_total_pixels
    crosswalk_score = np.sum(crosswalk_roi) / roi_total_pixels
    
    raw_status = "UNKNOWN"
    if sidewalk_score > 0.6: raw_status = "SIDEWALK"
    elif road_score > 0.6: raw_status = "ROAD"
    elif crosswalk_score > 0.4: raw_status = "CROSSWALK"
        
    return raw_status, road_score, sidewalk_score, crosswalk_score

def run_segmentation(g_FRAME_OK, g_SEM_PROCESSING, g_ANGLE_OK):
    signal.signal(signal.SIGTERM, lambda signum, frame: sys.exit(0))
    torch.set_num_threads(1) 
    print("🔍 [sem.py] 시맨틱 세그멘테이션 AI 엔진 가동 대기 중...", flush=True)
    
    shm = None
    try:
        shm = shared_memory.SharedMemory(name=config.VIDEO_SHM_NAME)
        raw_buf = shm.buf
    except FileNotFoundError:
        print(f"❌ [sem.py] 공유 메모리를 찾을 수 없습니다.", flush=True)
        return

    YOLO_SEM_PATH = "/home/user15/work/project/VIP_WEARABLE/vip_wearable_rasi/models/Quantization_models/best_int8_freeze5.onnx"
    model = YOLO(YOLO_SEM_PATH, task="semantic")
    
    fps_calc = FPSCalculator(interval=1.0)
    status_filter = CurrentLocationStatus(window_size=15, min_stabilize_size=5)
    prev_status = "UNKNOWN"
    frame = None
    out = None

    try:
        while True:
            # 1. 목적지 미입력 상태
            if not g_ANGLE_OK.value:
                if out is not None:
                    out.release()
                    out = None
                    print("💾 [sem.py] 목적지 해제 - 녹화 파일 저장 완료.", flush=True)
                time.sleep(0.01)
                continue

            # 2. 목적지 수신 시점에 동적으로 녹화기 시작
            if getattr(config, "ENABLE_RECORDING", False) and out is None:
                record_dir = "/home/user15/work/project/VIP_WEARABLE/vip_wearable_rasi/records/sem"
                os.makedirs(record_dir, exist_ok=True)
                timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
                video_path = os.path.join(record_dir, f"sem_nav_{timestamp}.avi") # 또는 .mp4
                fourcc = cv2.VideoWriter_fourcc(*'XVID') # mp4v 대신 XVID 권장
                out = cv2.VideoWriter(video_path, fourcc, 15.0, (config.WIDTH, config.HEIGHT))
                print(f"\n🎥 [sem.py] 📱 목적지 감지 -> 네비게이션 녹화 시작: {video_path}", flush=True)

            if not g_FRAME_OK.value or not g_SEM_PROCESSING.value:
                time.sleep(0.001)
                continue

            frame = np.frombuffer(raw_buf, dtype=np.uint8)[:config.FRAME_SIZE].reshape((config.HEIGHT, config.WIDTH, config.CHANNELS)).copy()
            g_SEM_PROCESSING.value = False 

            results = model(frame, imgsz=[256, 320], classes=[0, 1, 2], verbose=False, show=False)

            if hasattr(results[0], 'semantic_mask') and results[0].semantic_mask is not None:
                class_map = results[0].semantic_mask.data.cpu().numpy()
                raw_status, r_score, s_score, c_score = analyze_terrain(class_map, pitch_offset=0)
                fixed_status, count = status_filter.update(raw_status)
                
                if fixed_status != prev_status and fixed_status != "UNKNOWN":
                    if fixed_status == "SIDEWALK":
                        handler.handle_surface_changed(0.0, target_id=1, direction_id=1)
                    elif fixed_status == "ROAD":
                        handler.handle_surface_changed(0.0, target_id=0, direction_id=0)
                    elif fixed_status == "CROSSWALK":
                        handler.handle_surface_changed(0.0, target_id=2, direction_id=1)
                    prev_status = fixed_status

            fps_calc.update()

            annotated_frame = results[0].plot(boxes=False)
            cv2.putText(annotated_frame, f"SEM FPS: {fps_calc.get_fps():.1f} | {prev_status}", (10, 25), cv2.FONT_HERSHEY_SIMPLEX, 0.6, (0, 255, 255), 2)

            if out is not None:
                out.write(annotated_frame)

            if config.SHOW_DISPLAY:
                try:
                    cv2.imshow("VIP Semantic Segmentation", annotated_frame)
                    if cv2.waitKey(1) & 0xFF == ord('q'):
                        break
                except Exception:
                    pass
                
            time.sleep(0.002)
                
    except KeyboardInterrupt:
        print("\n👋 [sem.py] 안전 종료.", flush=True)
    except Exception as e:
        print(f"⚠️ [sem.py] 예외 발생: {e}", flush=True)
    finally:
        if out is not None:
            out.release()
            print("💾 [sem.py] 비디오 파일 릴리즈 완료.", flush=True)
        del frame
        del raw_buf
        gc.collect()
        if shm is not None:
            try:
                shm.close()
            except Exception:
                pass
        if config.SHOW_DISPLAY:
            try:
                cv2.destroyAllWindows()
            except Exception:
                pass