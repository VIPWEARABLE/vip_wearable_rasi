import time
import sys
import cv2
import numpy as np
import torch
import subprocess
from multiprocessing import Process, shared_memory, freeze_support, Queue
from basic import ble_core
import basic.config as config
import basic.g_val as g
from utils import process_navigation_vibration

from od import run_object_detection
from sem import run_segmentation
from basic.ble_core import reset_hardware_to_sleep, run_ble_server_process
import basic.handler as handler
import os
os.environ["OPENCV_UI_BACKEND"] = "headless" # ⭕ 이 줄로 변경

def main():
    print("[main.py] 보행 보조 시스템 중앙 컨트롤러 가동...")
    torch.set_num_threads(1) 
    
    try:
        temp_shm = shared_memory.SharedMemory(name=config.VIDEO_SHM_NAME)
        temp_shm.close()
        temp_shm.unlink()
        print("[main.py] 이전 공유 메모리 찌꺼기 강제 초기화 완료.")
    except Exception:
        pass
    
    # 1. 공유 메모리 할당 (기존과 동일)
    try:
        shm = shared_memory.SharedMemory(name=config.VIDEO_SHM_NAME, create=True, size=config.FRAME_SIZE)
    except FileExistsError:
        shm = shared_memory.SharedMemory(name=config.VIDEO_SHM_NAME)
    
    shm_array = np.ndarray((config.HEIGHT, config.WIDTH, config.CHANNELS), dtype=np.uint8, buffer=shm.buf)

    print("[main.py] 자식 AI 엔진 및 통신 서버 병렬 프로세스 생성 중...")
    shared_queue = Queue()
    
    ble_core.init_ai_queue(shared_queue)
    handler.init_handler_queue(shared_queue)
    
    # 2. 서브 프로세스 생성 및 시작
    ble_process = Process(target=run_ble_server_process, args=(shared_queue,), daemon=True)
    od_process = Process(target=run_object_detection, args=(g.FRAME_OK, g.OD_PROCESSING, g.OBJECT_EXIST, g.ANGLE_OK, shared_queue), daemon=True)
    sem_process = Process(target=run_segmentation, args=(g.FRAME_OK, g.SEM_PROCESSING, g.ANGLE_OK, shared_queue), daemon=True)
    
    ble_process.start()
    od_process.start()
    sem_process.start()
    print("[main.py] AI 프로세스 및 BLE 서버 정상 가동 완료.")

    # 3. 카메라 설정
    camera_index = 0
    cap = cv2.VideoCapture(camera_index + config.CAMERA_BACKEND)
    cap.set(cv2.CAP_PROP_BUFFERSIZE, config.CAMERA_BUFFER_SIZE)

    if not cap.isOpened():
        print(f"[main.py] 에러: 웹캠을 열 수 없습니다. 시스템을 종료합니다.")
        od_process.terminate()
        sem_process.terminate()
        ble_process.terminate()
        reset_hardware_to_sleep()
        shm.close()
        shm.unlink()
        sys.exit(1)
        
    print("[main.py] 웹캠 연결 완료. BLE 연결을 대기합니다... (AI 연산 휴면 상태)")
    print("-" * 60)
    is_first_frame = True 

    try:
        while True:
            # [핵심 1] 카메라는 항상 읽어줍니다. 읽지 않으면 버퍼에 과거 영상이 쌓여버립니다.
            ret, frame = cap.read()
            if not ret:
                camera_fail_count += 1
                if camera_fail_count > 30: # 30프레임 연속 실패 시
                    print("[main.py] 🚨 치명적 에러: 카메라 연결이 끊어졌습니다. 시스템을 종료합니다.")
                    break # while 루프를 탈출하여 finally 블록으로 안전하게 이동
                time.sleep(0.01)
                continue

            # BLE가 연결되지 않았다면(대기 상태), AI로 이미지를 넘기지 않고 다시 위로 돌아갑니다.
            if not g.BLE_CONNECTED.value:
                time.sleep(0.03) # 프레임 스킵을 위해 짧게 대기 (CPU/발열 절약)
                is_first_frame = True # 나중에 연결되었을 때 즉시 영상을 쏘기 위해 초기화
                continue

            # ------------- 이 아래부터는 BLE가 연결된(활성화) 상태에서만 실행됩니다 -------------
            
            # 조향 핸들러 호출
            angle = g.ANGLE_VALUE.value  
            if angle != 999.0:  
                process_navigation_vibration(angle)

            # AI 프로세스들이 이전 프레임 연산을 마쳤을 때만 새로운 프레임 주입
            if is_first_frame or (not g.SEM_PROCESSING.value and not g.OD_PROCESSING.value):
                g.FRAME_OK.value = False

                resized_frame = cv2.resize(frame, (config.WIDTH, config.HEIGHT))
                shm_array[:] = resized_frame[:]

                g.FRAME_OK.value = True

                # AI 프로세스에게 영상이 준비되었음을 알림 (추론 시작)
                g.OD_PROCESSING.value = True
                g.SEM_PROCESSING.value = True
                is_first_frame = False
            else:
                time.sleep(0.001)   
                        
    except KeyboardInterrupt:
        print("\n[main.py] 시스템 안전 종료 신호(Ctrl+C)를 수신했습니다.")
    finally:
        # [핵심 3] 시스템 셧다운 시 모든 하드웨어와 자원을 꼼꼼하게 해제합니다.
        print("[main.py] 자원 정리를 시작합니다...")
        cap.release()
        
        # 프로세스가 살아있다면 안전하게 강제 종료 후 메모리 반환 대기(join)
        for p in [od_process, sem_process, ble_process]:
            if p.is_alive():
                p.terminate()
                p.join(timeout=1.0) 

        reset_hardware_to_sleep()
        shm.close()
        try:
            shm.unlink()
        except Exception:
            pass
        subprocess.run(["sudo", "btmgmt", "--index", "0", "clr-adv"], capture_output=True)
        print("[main.py] 모든 자원과 하드웨어 스트림을 안전하게 소거했습니다. 종료합니다.")

if __name__ == "__main__":
    freeze_support()
    main()