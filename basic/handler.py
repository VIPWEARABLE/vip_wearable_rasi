import queue
import basic.g_val as g

tx_queue = None

def init_handler_queue(shared_queue):
    global tx_queue
    tx_queue = shared_queue

def handle_path_deviation(val):
    """ 내비게이션 경로 이탈 피드백 전송 (앱에서 온 각도 전용) """
    global tx_queue
    if tx_queue is not None:
        try:
            # 앱 데이터는 state=False (0x00) 플래그로 전송
            tx_queue.put_nowait((float(val), False))
        except queue.Full:
            pass

def handle_surface_changed(val, target_id, direction_id):
    """ 지형 안내 (기존과 동일하게 유지) """
    surfaces = {0: "차도", 1: "보도블록", 2: "횡단보도"}
    print(f"ℹ️ [지형 안내 - SEM] 전방에 [{surfaces.get(target_id, '지형')}] 진입합니다.")

def handle_static_object_avoidance(avoid_angle, is_avoiding):
    """ OD 장애물 회피 피드백 전송 (AI 전용) """
    global tx_queue
    
    # 프로세스 전역 락 업데이트 (main.py가 알 수 있도록)
    g.AI_AVOIDING.value = is_avoiding
    
    if tx_queue is not None:
        try:
            if is_avoiding:
                # AI 회피 모드는 state=True (0x01) 플래그로 전송
                tx_queue.put_nowait((float(avoid_angle), True))
                dir_str = "왼쪽" if avoid_angle < 0 else "오른쪽"
                print(f"🚨 [AI 회피] 전방 장애물! {dir_str}으로 회피하세요. (각도: {avoid_angle})")
            else:
                # 회피 종료 시 0.0을 쏘지 않고, 앱이 즉시 자기 각도를 전송하도록 방아쇠 활성화
                g.FORCE_APP_RESEND.value = True
                print(f"✅ [장애물 해제] 원래 앱 내비게이션 경로(직진)로 복귀합니다.")
        except queue.Full:
            pass