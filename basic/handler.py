import basic.g_val as g

def handle_surface_changed(val, target_id, direction_id):
    surfaces = {0: "차도", 1: "보도블록", 2: "횡단보도"}
    print(f"ℹ️ [지형 안내 - SEM] 전방에 [{surfaces.get(target_id, '지형')}] 진입합니다.")

def handle_static_object_avoidance(avoid_angle, is_avoiding):
    """ OD 장애물 회피 시 큐 대신 전역 변수(Value)로 즉시 덮어씌움 """
    g.AI_AVOIDING.value = is_avoiding
    g.AI_AVOID_ANGLE_VALUE.value = float(avoid_angle) # AI 회피 각도 기록
    
    if is_avoiding:
        dir_str = "왼쪽" if avoid_angle < 0 else "오른쪽"
        print(f"🚨 [AI 회피] 전방 장애물! {dir_str}으로 회피하세요. (각도: {avoid_angle})")
    else:
        g.FORCE_APP_RESEND.value = True
        print(f"✅ [장애물 해제] 원래 앱 내비게이션 경로(직진)로 복귀합니다.")