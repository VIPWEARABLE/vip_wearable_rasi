# od.py 전체 수정본
import basic.config as config
import basic.handler as handler
from multiprocessing import shared_memory
import time
import cv2
import numpy as np
import torch
from ultralytics import YOLO
from utils import FPSCalculator, calculate_avoidance_direction

def run_object_detection(g_FRAME_OK, g_OD_PROCESSING, g_OBJECT_EXIST, g_ANGLE_OK, shared_queue):
    # 🚨 [가장 중요한 핵심 해결] 자식 프로세스인 od.py 내부의 handler에도 큐를 인식시켜 줍니다!
    handler.init_handler_queue(shared_queue)

    torch.set_num_threads(1)
    print("🔍 [od.py] 정적 객체 3방향 회피 AI 엔진 가동 (모듈화 완료)...")

    try:
        shm = shared_memory.SharedMemory(name=config.VIDEO_SHM_NAME)
        raw_buf = shm.buf
    except FileNotFoundError:
        print("❌ 공유 메모리를 찾을 수 없습니다. main.py 상태를 확인하세요.")
        return

    STATIC_CLASSES = [0, 1, 2]  # 0: 볼라드, 1: 사람, 2: 킥보드
    YOLO_OD_PATH = "/home/user15/work/project/VIP_WEARABLE/vip_wearable_rasi/models/Quantization_models/yolo26n.onnx"

    model = YOLO(YOLO_OD_PATH, task="detect")
    fps_calc = FPSCalculator(interval=1.0)

    prev_direction = 3

    try:
        while True:
            if not g_FRAME_OK.value or not g_OD_PROCESSING.value:
                time.sleep(0.001)
                continue

            frame = np.frombuffer(raw_buf, dtype=np.uint8)[: config.FRAME_SIZE].reshape((config.HEIGHT, config.WIDTH, config.CHANNELS))
            g_OD_PROCESSING.value = False

            # ========================================================
            # [추가] Phase 1 제자리 회전 중일 땐 장애물 회피를 차단(Mute)
            # ========================================================
            import basic.g_val as g
            if g.IS_ROTATING.value:
                # 회전 중이므로 장애물 경고를 울리지 않고, AI 상태를 초기화
                if prev_direction != 3:
                    handler.handle_static_object_avoidance(0.0, False)
                    prev_direction = 3
                # 연산을 스킵하여 자원을 아낌
                g_OD_PROCESSING.value = True # 다음 프레임을 위해 플래그 원상복구
                time.sleep(0.005)
                continue
            # ========================================================

            # 기존 모델 추론 (Phase 2 직진 중일 때만 여기까지 도달함)
            results = model(frame, imgsz=[256, 320], classes=STATIC_CLASSES, verbose=False, conf=0.60, max_det=5)

            
            if results[0].boxes is not None and len(results[0].boxes) > 0:
                g_OBJECT_EXIST.value = True

                direction_id, total_score = calculate_avoidance_direction(
                    results[0].boxes, config.WIDTH, config.HEIGHT
                )

                if total_score > 0.3:
                    if direction_id != prev_direction:
                        # 하이퍼파라미터에서 회피 각도 불러옴 (-30.0 or 30.0)
                        avoid_angle = -config.AI_AVOID_ANGLE if direction_id == 1 else config.AI_AVOID_ANGLE
                        
                        # 두 번째 인자를 True(회피 중)로 넘겨서 호출
                        handler.handle_static_object_avoidance(avoid_angle, True)
                        prev_direction = direction_id
                else:
                    if prev_direction != 3:
                        # 회피 종료(False)
                        handler.handle_static_object_avoidance(0.0, False)
                        prev_direction = 3
            else:
                g_OBJECT_EXIST.value = False

                if prev_direction != 3:
                    # 회피 종료(False)
                    handler.handle_static_object_avoidance(0.0, False)
                    prev_direction = 3 

            if config.SHOW_DISPLAY:
                annotated_frame = results[0].plot()
                fps_calc.update()
                cv2.putText(annotated_frame, f"FPS: {fps_calc.get_fps():.1f}", (10, 30), cv2.FONT_HERSHEY_SIMPLEX, 0.6, (0, 255, 0), 2, cv2.LINE_AA)
                if cv2.waitKey(1) & 0xFF == ord("q"):
                    break
            else:
                fps_calc.update()

            time.sleep(0.002)

    except KeyboardInterrupt:
        print("\n👋 od.py 안전 종료.")
    finally:
        try:
            del frame
            del raw_buf
        except Exception:
            pass
            
        import gc
        gc.collect()
        
        try:
            shm.close()
        except BufferError:
            pass
            
        if config.SHOW_DISPLAY:
            try:
                cv2.destroyAllWindows()
            except Exception:
                pass