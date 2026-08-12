#!/bin/bash

# 1. 기존 유령 공유 메모리 및 파이썬 프로세스 강제 청소
sudo rm -rf /dev/shm/*assist_video_shm*
sudo killall -9 python python3 2>/dev/null

# 청소 후 안정화 대기
sleep 1

# 2. 프로젝트 디렉토리로 이동
cd /home/user15/work/project/VIP_WEARABLE/vip_wearable_rasi

# 3. 가상환경(env) 파이썬으로 main.py 실행
/home/user15/work/project/VIP_WEARABLE/vip_wearable_rasi/env/bin/python main.py
