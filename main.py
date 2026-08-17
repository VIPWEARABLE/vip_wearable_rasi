# main.py

import os
import subprocess
import sys
import time
from multiprocessing import Process, freeze_support, shared_memory

import cv2
import numpy as np
import torch

import basic.config as config
import basic.g_val as g
import basic.handler as handler
from basic.ble_core import reset_hardware_to_sleep, run_ble_server_process
from basic.hardware_controller import HardwareController
from ai.od import run_object_detection
from ai.sem import run_segmentation
from ai.utils import process_navigation_vibration

def main():
    print("[main.py] 보행 보조 시스템 중앙 컨트롤러 가동...")
    torch.set_num_threads(1) 
    
    # 0. 하드웨어 컨트롤러 초기화 (IMU + 모터)
    hw = HardwareController(port=config.UART_PORT, baudrate=config.BAUDRATE)    

    try:
        temp_shm = shared_memory.SharedMemory(name=config.VIDEO_SHM_NAME)
        temp_shm.close()
        temp_shm.unlink()
    except Exception:
        pass
    
    try:
        shm = shared_memory.SharedMemory(name=config.VIDEO_SHM_NAME, create=True, size=config.FRAME_SIZE)
    except FileExistsError:
        shm = shared_memory.SharedMemory(name=config.VIDEO_SHM_NAME)
    
    shm_array = np.ndarray((config.HEIGHT, config.WIDTH, config.CHANNELS), dtype=np.uint8, buffer=shm.buf)
    
    # 1. 서브 프로세스 실행
    ble_process = Process(target=run_ble_server_process, daemon=True)
    od_process = Process(target=run_object_detection, args=(g.FRAME_OK, g.OD_PROCESSING, g.OBJECT_EXIST, g.ANGLE_OK), daemon=True)
    sem_process = Process(target=run_segmentation, args=(g.FRAME_OK, g.SEM_PROCESSING, g.ANGLE_OK), daemon=True)

    ble_process.start()
    od_process.start()
    sem_process.start()

    camera_index = 0
    cap = cv2.VideoCapture(camera_index, config.CAMERA_BACKEND)
    cap.set(cv2.CAP_PROP_BUFFERSIZE, config.CAMERA_BUFFER_SIZE)

    if not cap.isOpened():
        print(f"[main.py] 카메라(/dev/video{camera_index}) 에러. 종료합니다.")
        sys.exit(1)
        
    print("[main.py] 시스템 준비 완료. 블루투스 연결을 대기합니다...")
    is_first_frame = True 
    camera_fail_count = 0

    try:
        while True:
            # 1. IMU 및 낙상 감지
            is_connected = g.BLE_CONNECTED.value
            hw.update_imu(is_connected=is_connected)
            
            if is_connected and hw.check_fall_detection():
                print("[main.py] 🚨 낙상 발생 감지! 양쪽 모터 최대 진동!")
                hw._set_raw_pwm(999, 999)
                time.sleep(1.0)
                continue

            # 2. 카메라 프레임 수신
            ret, frame = cap.read()
            if not ret:
                camera_fail_count += 1
                if camera_fail_count > 30:
                    break
                time.sleep(0.01)
                continue
            camera_fail_count = 0

            # 3. 연결 안됨 OR 목적지 설정 안됨 -> 모터 정지 & AI 휴면
            if not is_connected or not g.ANGLE_OK.value:
                hw.update_haptic(0.0, False)
                time.sleep(0.03)
                is_first_frame = True
                continue

            # 4. 목적지가 설정된 내비게이션 상태 -> 햅틱 제어
            app_angle = g.ANGLE_VALUE.value  
            
            if app_angle != 999.0:  
                process_navigation_vibration(app_angle)
                
                is_avoidance = bool(g.AI_AVOIDING.value)
                ai_angle = g.AI_AVOID_ANGLE_VALUE.value

                # 1. 앱 경로 오차가 15도를 초과하는 경우 -> 회전 우선!
                if abs(app_angle) > 15.0:
                    hw.update_haptic(angle_error=app_angle, is_avoidance=False)

                # 2. +-15도 이내로 정렬된 경우 (직진 상태) -> 장애물 회피 우선!
                else:
                    if is_avoidance:
                        # 직진 중 전방 장애물 감지 -> AI 회피 진동 (징-징-징)
                        hw.update_haptic(angle_error=ai_angle, is_avoidance=True)
                    else:
                        # 직진 중 장애물 없음 -> 모터 정지 (안정적인 직진)
                        hw.update_haptic(angle_error=0.0, is_avoidance=False)
            else:
                hw.update_haptic(0.0, False)

            # ========================================================
            # 5. [핵심 누락 복구] AI 프로세스로 프레임 전달 및 추론 깨우기
            # ========================================================
            if is_first_frame or (not g.SEM_PROCESSING.value and not g.OD_PROCESSING.value):
                g.FRAME_OK.value = False
                resized_frame = cv2.resize(frame, (config.WIDTH, config.HEIGHT))
                shm_array[:] = resized_frame[:]
                g.FRAME_OK.value = True

                # AI 프로세스 실행 플래그 ON
                g.OD_PROCESSING.value = True
                g.SEM_PROCESSING.value = True
                is_first_frame = False
            else:
                time.sleep(0.001)
                        
    except KeyboardInterrupt:
        print("\n[main.py] 종료 신호 수신.")
    finally:
        print("\n[main.py] 시스템 정리 중... 프로세스 정상 종료 대기")
        hw.close()
        cap.release()
        
        # 1. 목적지/프로세스 플래그를 꺼서 서브프로세스 루프 자연 탈출 유도
        g.ANGLE_OK.value = False
        reset_hardware_to_sleep()

        # 2. 서브프로세스들이 out.release()를 마칠 수 있도록 잠시 대기 후 종료
        for p in [od_process, sem_process, ble_process]:
            if p.is_alive():
                p.terminate() # SIGTERM 전송
                p.join(timeout=1.0) # 최대 1초 정상 정리 대기

        shm.close()
        try:
            shm.unlink()
        except Exception:
            pass
        print("[main.py] 전체 시스템 안전 종료 완료.")

if __name__ == "__main__":
    freeze_support()
    main()