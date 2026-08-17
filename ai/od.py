# ai/od.py
import os
import gc
import time
from datetime import datetime
import cv2
import numpy as np
import torch
from ultralytics import YOLO
from multiprocessing import shared_memory
import signal
import sys

import basic.config as config
import basic.g_val as g
import basic.handler as handler
from ai.utils import FPSCalculator, calculate_avoidance_direction

def run_object_detection(g_FRAME_OK, g_OD_PROCESSING, g_OBJECT_EXIST, g_ANGLE_OK):
    signal.signal(signal.SIGTERM, lambda signum, frame: sys.exit(0))
    torch.set_num_threads(1)
    print("🔍 [od.py] 정적 객체 AI 엔진 가동 대기 중...", flush=True)

    try:
        shm = shared_memory.SharedMemory(name=config.VIDEO_SHM_NAME)
        raw_buf = shm.buf
    except FileNotFoundError:
        print("❌ [od.py] 공유 메모리를 찾을 수 없습니다.", flush=True)
        return

    STATIC_CLASSES = [0, 1, 2]
    YOLO_OD_PATH = "/home/user15/work/project/VIP_WEARABLE/vip_wearable_rasi/models/Quantization_models/yolo26n.onnx"
    model = YOLO(YOLO_OD_PATH, task="detect")
    fps_calc = FPSCalculator(interval=1.0)

    prev_direction = 3
    candidate_direction = 3
    direction_confirm_count = 0
    missing_frame_count = 0  # ★ 프레임 깜빡임 방지용 카운터 추가
    
    frame = None
    out = None  

    try:
        while True:
            if not g_ANGLE_OK.value:
                if out is not None:
                    out.release()
                    out = None
                    print("💾 [od.py] 목적지 해제 - 녹화 파일 저장 완료.", flush=True)
                time.sleep(0.01)
                continue

            if getattr(config, "ENABLE_RECORDING", False) and out is None:
                record_dir = "/home/user15/work/project/VIP_WEARABLE/vip_wearable_rasi/records/od"
                os.makedirs(record_dir, exist_ok=True)
                timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
                video_path = os.path.join(record_dir, f"od_nav_{timestamp}.avi") 
                fourcc = cv2.VideoWriter_fourcc(*'XVID') 
                out = cv2.VideoWriter(video_path, fourcc, 15.0, (config.WIDTH, config.HEIGHT))
                print(f"\n🎥 [od.py] 📱 목적지 감지 -> 네비게이션 녹화 시작: {video_path}", flush=True)

            if not g_FRAME_OK.value or not g_OD_PROCESSING.value:
                time.sleep(0.001)
                continue

            frame = np.frombuffer(raw_buf, dtype=np.uint8)[: config.FRAME_SIZE].reshape((config.HEIGHT, config.WIDTH, config.CHANNELS)).copy()
            g_OD_PROCESSING.value = False

            # 모델 추론
            results = model(frame, imgsz=[256, 320], classes=STATIC_CLASSES, verbose=False, conf=0.60, max_det=5)
            num_boxes = len(results[0].boxes) if results[0].boxes is not None else 0

            # 1. 박스가 있으면 점수와 방향 계산, 없으면 0점 처리
            if num_boxes > 0:
                direction_id, total_score = calculate_avoidance_direction(results[0].boxes, config.WIDTH, config.HEIGHT)
            else:
                direction_id, total_score = 3, 0.0

            # 2. 장애물 감지 로직 (깜빡임 필터링 적용)
            if total_score > 0.3:
                # 장애물이 확인되면 사라짐 카운터 초기화
                missing_frame_count = 0
                g_OBJECT_EXIST.value = True
                
                if direction_id != prev_direction:
                    if direction_id == candidate_direction:
                        direction_confirm_count += 1
                    else:
                        candidate_direction = direction_id
                        direction_confirm_count = 1

                    if direction_confirm_count >= 3:
                        prev_direction = direction_id
                        direction_confirm_count = 0
                        avoid_angle = -config.AI_AVOID_ANGLE if direction_id == 1 else config.AI_AVOID_ANGLE
                        
                        dir_name = "좌측" if direction_id == 1 else "우측"
                        print(f"🚨 [OD] 장애물 확정! {dir_name} 회피 지시 (각도: {avoid_angle:+.1f}°, 점수: {total_score:.2f})", flush=True)
                        handler.handle_static_object_avoidance(avoid_angle, True)
                else:
                    candidate_direction = direction_id
                    direction_confirm_count = 0
            else:
                # 장애물이 안 보이거나 0.3점 이하일 때 바로 끄지 않고 카운트 증가
                missing_frame_count += 1
                
                # 4프레임 연속으로 안 보일 때만 확실히 해제
                if missing_frame_count > 3:
                    g_OBJECT_EXIST.value = False
                    candidate_direction = 3
                    direction_confirm_count = 0
                    
                    if prev_direction != 3:
                        print(f"✅ [OD] {missing_frame_count}프레임 연속 장애물 없음 -> 회피 해제", flush=True)
                        handler.handle_static_object_avoidance(0.0, False)
                        prev_direction = 3

            fps_calc.update()

            annotated_frame = results[0].plot()
            cv2.putText(annotated_frame, f"OD FPS: {fps_calc.get_fps():.1f}", (10, 25), cv2.FONT_HERSHEY_SIMPLEX, 0.6, (0, 255, 0), 2)

            if out is not None:
                out.write(annotated_frame)

            if config.SHOW_DISPLAY:
                try:
                    cv2.imshow("VIP Object Detection", annotated_frame)
                    if cv2.waitKey(1) & 0xFF == ord("q"):
                        break
                except Exception:
                    pass

            time.sleep(0.002)

    except KeyboardInterrupt:
        print("\n👋 [od.py] 안전 종료.", flush=True)
    except Exception as e:
        print(f"⚠️ [od.py] 예외 발생: {e}", flush=True)
    finally:
        if out is not None:
            out.release()
            print("💾 [od.py] 비디오 파일 릴리즈 완료.", flush=True)
        try:
            del frame
            del raw_buf
        except Exception:
            pass
        gc.collect()
        try:
            shm.close()
        except Exception:
            pass
        if config.SHOW_DISPLAY:
            try:
                cv2.destroyAllWindows()
            except Exception:
                pass