#!/bin/bash

# 1. 기존 유령 공유 메모리 및 파이썬 프로세스 강제 정리
sudo rm -rf /dev/shm/*assist_video_shm*
sudo killall -9 python python3 2>/dev/null

# 2. GPIO 핀 점유 상태 강제 초기화 (GPIO busy 방지)
pinctrl set 12 no 2>/dev/null
pinctrl set 13 no 2>/dev/null

# 3. 카메라, 시리얼, 블루투스 하드웨어 권한 부여 및 설정
sudo chmod 666 /dev/video* 2>/dev/null
sudo chmod 666 /dev/ttyUSB* 2>/dev/null
sudo rfkill unblock bluetooth 2>/dev/null
sudo systemctl start bluetooth 2>/dev/null

# 하드웨어 초기화 안정화 대기
sleep 1

# 4. 프로젝트 디렉토리로 이동
cd /home/user15/work/project/VIP_WEARABLE/vip_wearable_rasi

# 5. 가상환경 파이썬으로 main.py 백그라운드 실행
exec /home/user15/work/project/VIP_WEARABLE/vip_wearable_rasi/env/bin/python main.py