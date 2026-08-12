import time
import cv2
from ultralytics import YOLO
import numpy as np
from multiprocessing import shared_memory
from collections import deque, Counter  
import basic.config as config  
import basic.handler as handler
from utils import FPSCalculator
import torch
import gc

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

def run_segmentation(g_FRAME_OK, g_SEM_PROCESSING, g_ANGLE_OK, shared_queue):
    torch.set_num_threads(1) 
    print("🔍 [sem.py] 시맨틱 세그멘테이션 AI 엔진 가동...")
    
    shm = None
    try:
        shm = shared_memory.SharedMemory(name=config.VIDEO_SHM_NAME)
        raw_buf = shm.buf
    except FileNotFoundError:
        print(f"❌ 공유 메모리를 찾을 수 없습니다.")
        return

    YOLO_SEM_PATH = "/home/user15/work/project/VIP_WEARABLE/vip_wearable_rasi/models/Quantization_models/best_int8_freeze5.onnx"
    model = YOLO(YOLO_SEM_PATH, task="semantic")
    
    fps_calc = FPSCalculator(interval=1.0)
    status_filter = CurrentLocationStatus(window_size=15, min_stabilize_size=5)
    prev_status = "UNKNOWN"

    frame = None
    try:
        while True:
            if not g_FRAME_OK.value or not g_SEM_PROCESSING.value:                
                time.sleep(0.001)
                continue

            frame = np.frombuffer(raw_buf, dtype=np.uint8)[:config.FRAME_SIZE].reshape((config.HEIGHT, config.WIDTH, config.CHANNELS))
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

            if config.SHOW_DISPLAY:
                annotated_frame = results[0].plot(boxes=False)
                fps_calc.update()
                cv2.putText(annotated_frame, f"FPS: {fps_calc.get_fps():.1f}", (10, 30), 
                            cv2.FONT_HERSHEY_SIMPLEX, 0.6, (0, 255, 0), 2, cv2.LINE_AA)
                try:
                    if cv2.waitKey(1) & 0xFF == ord('q'):
                        break
                except Exception:
                    pass
            else:
                fps_calc.update()
                
    except KeyboardInterrupt:
        print("\n👋 sem.py 안전 종료.")
    except Exception as e:
        print(f"⚠️ [sem.py] 예외 발생: {e}")
    finally:
        # 🌟 핵심: SharedMemory 버퍼를 물고 있던 변수를 먼저 완전히 제거
        del frame
        del raw_buf
        gc.collect()  # 가비지 컬렉터로 메모리 포인터 정리 강제 실행
        
        if shm is not None:
            try:
                shm.close()
            except BufferError:
                pass
                
        if config.SHOW_DISPLAY:
            try:
                cv2.destroyAllWindows()
            except Exception:
                pass