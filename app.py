import os
from utils import calculate_leave
from dotenv import load_dotenv
from flask import Flask, render_template, request, redirect, session, url_for, flash, json
from dateutil.relativedelta import relativedelta
from flask import jsonify
from datetime import datetime, timedelta
from dateutil.parser import isoparse, parse
from collections import defaultdict
import io
import pandas as pd
from flask import send_file
import requests
import pytz
import re
import time
from supabase import create_client

load_dotenv()

app = Flask(__name__)
app.secret_key = os.getenv("SECRET_KEY")  # 로그인 세션용
print("SECRET_KEY from .env:", os.getenv("SECRET_KEY"))

# Supabase 정보 입력
SUPABASE_URL = os.getenv("SUPABASE_URL")
SUPABASE_KEY = os.getenv("SUPABASE_KEY")

supabase = create_client(SUPABASE_URL, SUPABASE_KEY)

@app.route('/')
def home():
    return redirect('/login')

@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        email = request.form['email']
        password = request.form['password']

        headers = {
            "apikey": SUPABASE_KEY,
            "Authorization": f"Bearer {SUPABASE_KEY}"
        }
        params = {
            "email": f"eq.{email}",
            "password": f"eq.{password}"
        }

        res = requests.get(f"{SUPABASE_URL}/rest/v1/users", headers=headers, params=params)

        if res.status_code == 200 and len(res.json()) > 0:
            user = res.json()[0]
            session['user'] = {
                'id': user['id'],
                'name': user['name'],
                'role': user['role']
            }

            if user['role'] == 'admin':
                return redirect('/admin')
            else:
                return redirect('/dashboard')
        else:
            return render_template('login.html', error="❌ 로그인 실패. 다시 확인해주세요.")
    return render_template('login.html')

@app.route('/logout', methods=['GET', 'POST']) # Allow both GET and POST for convenience, but POST is preferred
def logout():
    # Only remove the 'user' key from the session, leaving other session data (like flash messages) intact.
    session.pop('user', None) 
    flash('로그아웃되었습니다.', 'info') # Set the flash message
    return redirect('/login')

# ✅ 직원용 대시보드
@app.route('/dashboard')
def main_dashboard():
    if 'user' not in session or session['user']['role'] != 'employee':
        flash("직원 대시보드 접근 권한이 없습니다.", "danger")
        return redirect(url_for('login'))

    user_id = session['user']['id']

    headers = {
        "apikey": SUPABASE_KEY,
        "Authorization": f"Bearer {SUPABASE_KEY}"
    }

    # === [추가된 부분 시작] 출퇴근 기록 가져오기 (메인 대시보드 버튼용) ===
    kst_timezone = pytz.timezone('Asia/Seoul')
    today = datetime.now(kst_timezone).date()
    current_check_in_time = None
    current_check_out_time = None
    today_attendance_params = {
        "user_id": f"eq.{user_id}",
        "date": f"eq.{today.isoformat()}"
    }
    res_today_attendance = requests.get(f"{SUPABASE_URL}/rest/v1/attendances", headers=headers, params=today_attendance_params)
    if res_today_attendance.status_code == 200 and res_today_attendance.json():
        today_record = res_today_attendance.json()[0]
        if today_record.get('check_in_time'):
            current_check_in_time = datetime.strptime(today_record['check_in_time'], '%H:%M:%S').strftime('%I:%M %p')
        if today_record.get('check_out_time'):
            current_check_out_time = datetime.strptime(today_record['check_out_time'], '%H:%M:%S').strftime('%I:%M %p')
    # === [추가된 부분 끝] ===

    # 1. 오늘 날짜의 출근/퇴근 기록 가져오기 (출근/퇴근 버튼 표시용)
    kst_timezone = pytz.timezone('Asia/Seoul')
    today = datetime.now(kst_timezone).date()

    # --- 디버깅용 코드 시작 ---
    print(f"DEBUG: Server's KST today: {today.isoformat()}")
    # --- 디버깅용 코드 끝 ---

    current_check_in_time = None
    current_check_out_time = None

    today_attendance_params = {
        "user_id": f"eq.{user_id}",
        "date": f"eq.{today.isoformat()}"
    }
    
    # --- 디버깅용 코드 시작 ---
    print(f"DEBUG: Supabase query params for today's attendance: {today_attendance_params}")
    # --- 디버깅용 코드 끝 ---

    res_today_attendance = requests.get(f"{SUPABASE_URL}/rest/v1/attendances", headers=headers, params=today_attendance_params)

    # --- 디버깅용 코드 시작 ---
    print(f"DEBUG: Supabase response status for today's attendance: {res_today_attendance.status_code}")
    print(f"DEBUG: Supabase response JSON for today's attendance: {res_today_attendance.json()}")
    # --- 디버깅용 코드 끝 ---

    if res_today_attendance.status_code == 200 and res_today_attendance.json():
        today_record = res_today_attendance.json()[0]
        if today_record.get('check_in_time'):
            # time without time zone (HH:MM:SS) 형식으로 저장되었으므로 strptime 사용
            current_check_in_time = datetime.strptime(today_record['check_in_time'], '%H:%M:%S').strftime('%I:%M %p')
        if today_record.get('check_out_time'):
            current_check_out_time = datetime.strptime(today_record['check_out_time'], '%H:%M:%S').strftime('%I:%M %p')

    # ... (사용자 정보, 연차/월차, 휴가 목록 관련 기존 코드 유지) ...
    user_res = requests.get(
        f"{SUPABASE_URL}/rest/v1/users?id=eq.{user_id}&select=name,color_code,join_date,yearly_leave,monthly_leave",
        headers=headers
    )

    if user_res.status_code != 200 or not user_res.json(): # user_res.json()이 비어있는 경우도 확인
        flash("사용자 정보 조회 실패", "danger")
        return redirect(url_for('login')) # 사용자 정보 없으면 로그인 페이지로 리다이렉트

    user_info = user_res.json()[0]
    join_date_str = user_info.get("join_date")

    yearly_leave, monthly_leave = calculate_leave(join_date_str)

    params = {
        "user_id": f"eq.{user_id}",
        "order": "requested_at.desc"
    }

    res = requests.get(
        f"{SUPABASE_URL}/rest/v1/vacations",
        headers=headers,
        params=params
    )

    vacations = res.json() if res.status_code == 200 else []

    used_days = sum(v["used_days"] for v in vacations if v["status"] == "approved")
    remaining_total = yearly_leave + monthly_leave - used_days

    status_map = {
        "pending": "대기중",
        "approved": "승인됨",
        "rejected": "반려됨"
    }

    for v in vacations:
        v["status_kor"] = status_map.get(v["status"], "알 수 없음")
        v["name"] = session['user']['name']

    pending_count = sum(1 for v in vacations if v["status"] == "pending")
    approved_count = sum(1 for v in vacations if v["status"] == "approved")
    rejected_count = sum(1 for v in vacations if v["status"] == "rejected")


    # 7. MY 근태현황 데이터 가져오기 (check_in_time, check_out_time 사용)
    attendance_events = []
    try:
        # 지난 30일이 아닌, 모든 기록을 가져오는 것이 더 일반적입니다.
        # 만약 30일 이내 기록만 필요하다면 이 부분을 유지하세요.
        # thirty_days_ago = (datetime.now() - timedelta(days=30)).date()

        # 특정 user_id의 모든 출퇴근 기록을 가져옴
        all_attendance_params = {
            "user_id": f"eq.{user_id}",
            # "date": f"gte.{thirty_days_ago.isoformat()}", # 30일 제한을 없애려면 이 줄을 주석 처리
            "order": "date.desc" # 최신 날짜부터 보여주기 위해 내림차순 정렬
        }

        all_attendance_res = requests.get(
            f"{SUPABASE_URL}/rest/v1/attendances",
            headers=headers,
            params=all_attendance_params
        )

        if all_attendance_res.status_code == 200:
            raw_records = all_attendance_res.json()

            for record in raw_records:
                record_date_str = record.get('date') # Supabase에서 가져온 날짜 문자열
                check_in_time_raw = record.get('check_in_time')
                check_out_time_raw = record.get('check_out_time')

                check_in_display = 'N/A'
                check_out_display = 'N/A'
                work_duration = '-' # 기본값

                dt_in_combined = None
                dt_out_combined = None

                # 날짜와 출근 시간을 결합하여 datetime 객체 생성
                if check_in_time_raw and record_date_str:
                    try:
                        # record_date_str (YYYY-MM-DD) 와 check_in_time_raw (HH:MM:SS)를 조합
                        dt_in_combined = datetime.strptime(f"{record_date_str} {check_in_time_raw}", '%Y-%m-%d %H:%M:%S')
                        check_in_display = dt_in_combined.strftime('%I:%M %p') # HH:MM 형식으로 자르기
                    except ValueError:
                        print(f"출근 시간 또는 날짜 파싱 오류: 날짜={record_date_str}, 시간={check_in_time_raw}")

                # 날짜와 퇴근 시간을 결합하여 datetime 객체 생성
                if check_out_time_raw and record_date_str:
                    try:
                        dt_out_combined = datetime.strptime(f"{record_date_str} {check_out_time_raw}", '%Y-%m-%d %H:%M:%S')
                        check_out_display = dt_out_combined.strftime('%I:%M %p') # HH:MM 형식으로 자르기
                    except ValueError:
                        print(f"퇴근 시간 또는 날짜 파싱 오류: 날짜={record_date_str}, 시간={check_out_time_raw}")


                # 근무 시간 계산
                if dt_in_combined and dt_out_combined:
                    # 퇴근 시간이 출근 시간보다 빠를 경우 (예: 자정 넘어 근무)
                    # 현재 근태 시스템이 24시간을 넘기는 근무를 한 날짜에 허용하는지 확인 필요.
                    # 만약 자정을 넘어가더라도 하루에만 기록된다면 아래 로직을 사용합니다.
                    if dt_out_combined < dt_in_combined:
                        dt_out_combined += timedelta(days=1)


                    duration = dt_out_combined - dt_in_combined
                    total_seconds = int(duration.total_seconds())
                    hours = total_seconds // 3600
                    minutes = (total_seconds % 3600) // 60
                    
                    # 근무 시간이 음수이거나 비정상적일 경우 처리
                    if hours < 0: # 자정 넘어 근무 로직을 사용하지 않고 이런 경우 발생 시
                        work_duration = "오류"
                    else:
                        work_duration = f"{hours}시간 {minutes}분"
                elif check_in_time_raw and not check_out_time_raw:
                    work_duration = "근무 중" # 출근만 하고 퇴근하지 않은 경우
                # else: work_duration은 기본값 '-' 유지 (둘 다 없거나 퇴근만 있는 경우)


                attendance_events.append({
                    'date': record_date_str, # 날짜는 문자열 그대로 유지
                    'check_in': check_in_display,
                    'check_out': check_out_display,
                    'work_duration': work_duration # 계산된 근무 시간 추가
                })
        else:
            print(f"MY 근태현황 데이터 조회 실패: {all_attendance_res.status_code} - {all_attendance_res.text}")

    except Exception as e:
        print(f"MY 근태현황 데이터 처리 중 오류 발생: {e}")
        import traceback
        traceback.print_exc()

    # user 정보를 하나로 합치는 부분 추가
    # user_info는 Supabase에서 가져온 데이터
    # session['user']에는 이름, role, id가 있음
    full_user_info = {
        'name': session['user']['name'],
        'yearly_leave': yearly_leave,
        'monthly_leave': monthly_leave,
        'remaining_total': remaining_total,
        # 필요한 다른 정보도 추가할 수 있습니다.
    }

    return render_template(
        'main_dashboard.html',
        user=full_user_info, # 합쳐진 'full_user_info'를 'user' 변수로 전달합니다.
        vacations=vacations,
        yearly_leave=yearly_leave, # 'user' 변수에 포함되었으므로 삭제 가능 (선택 사항)
        monthly_leave=monthly_leave,
        remaining_total=remaining_total,
        pending_count=pending_count,
        approved_count=approved_count,
        rejected_count=rejected_count,
        current_check_in_time=current_check_in_time,
        current_check_out_time=current_check_out_time,
        attendance_events=attendance_events
    )

# 1) /admin → /admin/vacation 으로 리다이렉트
@app.route('/admin')
def admin_root():
    return redirect(url_for('admin_vacation'))

# 2) 휴가 관리 전용 페이지
@app.route('/admin/vacation')
def admin_vacation():
    if 'user' not in session or session['user']['role'] != 'admin':
        flash("관리자 대시보드 접근 권한이 없습니다.", "danger")
        return redirect(url_for('login'))

    headers = {
        "apikey": SUPABASE_KEY,
        "Authorization": f"Bearer {SUPABASE_KEY}"
    }

    # --- 직원 목록 가져오기 (통계용) ---
    users_res = requests.get(
        f"{SUPABASE_URL}/rest/v1/users?select=id,name,join_date,role",
        headers=headers
    )
    all_users     = users_res.json() if users_res.status_code == 200 else []
    employee_users = [u for u in all_users if u.get('role') != 'admin']

    # --- 휴가 신청 내역 조회 ---
    params = {
        "select": "id,start_date,end_date,type,status,user_id,users(name),deduct_from_type",
        "order": "start_date.desc"
    }
    res = requests.get(f"{SUPABASE_URL}/rest/v1/vacations", headers=headers, params=params)
    vacations = res.json() if res.status_code == 200 else []

    # 이름·표시형식 가공
    for v in vacations:
        v["name"] = v.get("users", {}).get("name", "알 수 없음")
        if v.get('type') == 'full_day':
            v['display_type'] = '종일'
        elif v.get('type') == 'half_day_am':
            v['display_type'] = '반차(오전)'
        elif v.get('type') == 'half_day_pm':
            v['display_type'] = '반차(오후)'
        elif v.get('type') == 'quarter_day_am':
            v['display_type'] = '반반차(오전)'
        elif v.get('type') == 'quarter_day_pm':
            v['display_type'] = '반반차(오후)'
        else:
            v['display_type'] = v.get('type', '알 수 없음')

    # --- 직원별 통계 계산 ---

    user_stats_dict = defaultdict(dict)
    # 승인된 휴가만
    all_approved_res = requests.get(
        f"{SUPABASE_URL}/rest/v1/vacations?status=eq.approved&select=user_id,used_days,deduct_from_type,type",
        headers=headers
    )
    all_approved = all_approved_res.json() if all_approved_res.status_code == 200 else []
    for u in employee_users:
        uid = u["id"]
        auto_y, auto_m = calculate_leave(u.get("join_date") or "")
        used_y = used_m = 0.0
        for vac in all_approved:
            if vac["user_id"] != uid: continue
            days = float(vac.get("used_days") or 0)
            src  = vac.get("deduct_from_type")
            if src == "yearly":
                used_y += days
            elif src == "monthly":
                used_m += days
            else:
                # 레거시 처리
                if vac.get("type","").startswith(("반차","반반차","종일")):
                    used_y += days
                elif vac.get("type")=="월차":
                    used_m += days
        user_stats_dict[uid] = {
            "name": u["name"],
            "auto_yearly": auto_y,
            "auto_monthly": auto_m,
            "used_yearly": round(used_y,2),
            "used_monthly": round(used_m,2),
            "remain_yearly": round(auto_y - used_y, 2),
            "remain_monthly": round(auto_m - used_m, 2)
        }
    user_stats = list(user_stats_dict.values())

    # --- 승인 대기/완료 건수 ---
    pending_count   = sum(1 for v in vacations if v["status"] == "pending")
    completed_count = sum(1 for v in vacations if v["status"] in ["approved","rejected"])

    return render_template(
        'admin_vacation.html',
        active           = 'vacation',
        user             = session['user'],
        vacations        = vacations,
        user_stats       = user_stats,
        pending_count    = pending_count,
        completed_count  = completed_count
    )

# 3) 근무 기록 전용 페이지
@app.route('/admin/attendance')
def admin_attendance():
    if 'user' not in session or session['user']['role'] != 'admin':
        flash("관리자 대시보드 접근 권한이 없습니다.", "danger")
        return redirect(url_for('login'))

    headers = {
        "apikey":        SUPABASE_KEY,
        "Authorization": f"Bearer {SUPABASE_KEY}"
    }

    # --- 직원 목록 (필터용) ---
    users_res = requests.get(
        f"{SUPABASE_URL}/rest/v1/users?select=id,name,role",
        headers=headers
    )
    all_users      = users_res.json() if users_res.status_code == 200 else []
    employee_users = [u for u in all_users if u.get('role') != 'admin']

    # --- 근무 기록 조회 (최근 30일) ---
    from datetime import datetime, timedelta
    import pytz
    kst = pytz.timezone('Asia/Seoul')
    thirty_days_ago = (datetime.now(kst) - timedelta(days=30)).date().isoformat()
    att_res = requests.get(
        f"{SUPABASE_URL}/rest/v1/attendances?date=gte.{thirty_days_ago}&order=date.desc,check_in_time.desc",
        headers=headers
    )
    raw = att_res.json() if att_res.status_code == 200 else []

    # 이름 매핑
    name_map = {u["id"]: u["name"] for u in all_users}

    all_attendance_records = []
    for r in raw:
        record_date = r.get("date")
        ci_raw      = r.get("check_in_time")
        co_raw      = r.get("check_out_time")

        # 디스플레이용 초기값
        check_in_display  = ci_raw  or "미기록"
        check_out_display = co_raw  or "미기록"
        #work_duration     = "-"     # 기본값

        dt_in  = None
        dt_out = None

        # 출근 시간 파싱
        if ci_raw and record_date:
            try:
                dt_in = datetime.strptime(f"{record_date} {ci_raw}", "%Y-%m-%d %H:%M:%S")
                check_in_display = dt_in.strftime("%I:%M %p")
            except ValueError:
                pass

        # 퇴근 시간 파싱
        if co_raw and record_date:
            try:
                dt_out = datetime.strptime(f"{record_date} {co_raw}", "%Y-%m-%d %H:%M:%S")
                check_out_display = dt_out.strftime("%I:%M %p")
            except ValueError:
                pass

        # 근무 시간 계산
        if dt_in and dt_out:
            if dt_out < dt_in:
                dt_out += timedelta(days=1)
            diff = dt_out - dt_in
            total_sec = int(diff.total_seconds())
            h = total_sec // 3600
            m = (total_sec % 3600) // 60
            work_duration = f"{h}시간 {m}분"
        elif dt_in and not dt_out:
            work_duration = "근무 중"

        all_attendance_records.append({
            "date":          record_date,
            "employee_name": name_map.get(r.get("user_id"), "알 수 없음"),
            "check_in":      check_in_display,
            "check_out":     check_out_display,
            "work_duration": work_duration,
            "user_id":       r.get("user_id")
        })

    return render_template(
        'admin_attendance.html',
        active                 = 'attendance',
        user                   = session['user'],
        all_attendance_records = all_attendance_records,
        all_users              = employee_users
    )


# ✅ 휴가 현황 캘린더
@app.route('/vacation_calendar')
def vacation_calendar():
    if 'user' not in session or session['user']['role'] != 'employee':
        flash("직원 대시보드 접근 권한이 없습니다.", "danger")
        return redirect(url_for('login'))
        
    user_id = session['user']['id']
    
    headers = {
        "apikey": SUPABASE_KEY,
        "Authorization": f"Bearer {SUPABASE_KEY}"
    }
    
    # 1. 로그인한 사용자 정보 가져오기 (사이드바에 필요)
    user_res = requests.get(
        f"{SUPABASE_URL}/rest/v1/users?id=eq.{user_id}&select=name,yearly_leave,monthly_leave",
        headers=headers
    )
    if user_res.status_code != 200 or not user_res.json():
        flash("사용자 정보 조회 실패", "danger")
        return redirect(url_for('login'))
    user_info = user_res.json()[0]
    
    # 2. 로그인한 사용자의 오늘 출퇴근 기록 가져오기 (사이드바에 필요)
    kst_timezone = pytz.timezone('Asia/Seoul')
    today = datetime.now(kst_timezone).date()
    current_check_in_time = None
    current_check_out_time = None
    today_attendance_params = {
        "user_id": f"eq.{user_id}",
        "date": f"eq.{today.isoformat()}"
    }
    res_today_attendance = requests.get(f"{SUPABASE_URL}/rest/v1/attendances", headers=headers, params=today_attendance_params)
    if res_today_attendance.status_code == 200 and res_today_attendance.json():
        today_record = res_today_attendance.json()[0]
        if today_record.get('check_in_time'):
            current_check_in_time = datetime.strptime(today_record['check_in_time'], '%H:%M:%S').strftime('%I:%M %p')
        if today_record.get('check_out_time'):
            current_check_out_time = datetime.strptime(today_record['check_out_time'], '%H:%M:%S').strftime('%I:%M %p')

    # 3. 모든 직원의 승인된 휴가 기록 가져오기 (달력에 필요)
    vacation_params = {
        "status": "eq.approved",
        "select": "*,users(name),vacation_types(type_code)"
    }
    vacations_res = requests.get(
        f"{SUPABASE_URL}/rest/v1/vacations",
        headers=headers,
        params=vacation_params
    )
    vacations_data = vacations_res.json() if vacations_res.status_code == 200 else []
    
    # 4. FullCalendar에 맞게 데이터 가공
    events = []
    for vacation in vacations_data:
        end_date = datetime.strptime(vacation['end_date'], '%Y-%m-%d').date()
        end_date_adjusted = end_date + timedelta(days=1)
        
        events.append({
            'title': f"{vacation['users']['name']} ({vacation['vacation_types']['type_code']})",
            'start': vacation['start_date'],
            'end': end_date_adjusted.isoformat(),
            'allDay': True,
            'type_code': vacation['vacation_types']['type_code']
        })
    
    return render_template(
        'vacation_calendar.html',
        # FullCalendar에 넘겨줄 부서 전체 휴가 데이터
        vacations=events, 
        # base.html (사이드바)에 넘겨줄 사용자 정보
        user=user_info,
        current_check_in_time=current_check_in_time,
        current_check_out_time=current_check_out_time
    )

# attendance 라우트 (출퇴근 기록 처리)
@app.route('/attendance', methods=['POST'])
def attendance():
    user = session.get('user')
    if not user:
        flash("로그인이 필요합니다.", "danger")
        return redirect(url_for('login'))

    user_id = user['id']
    employee_name = user.get('name') # 세션에서 직원 이름 가져오기
    record_type = request.form.get('type') # '출근' 또는 '퇴근'
    
    # KST (한국 표준시) 시간대를 명시적으로 지정하여 현재 시간과 날짜를 가져옵니다.
    kst_timezone = pytz.timezone('Asia/Seoul')
    now_kst = datetime.now(kst_timezone) # <-- 이 줄을 추가합니다.
    today_date_str = now_kst.strftime('%Y-%m-%d') # <-- now 대신 now_kst 사용
    current_time_str = now_kst.strftime('%H:%M:%S') # <-- now 대신 now_kst 사용

    headers = {
        "apikey": SUPABASE_KEY,
        "Authorization": f"Bearer {SUPABASE_KEY}",
        "Content-Type": "application/json"
    }

    try:
        # Supabase에 오늘 날짜의 기록을 조회할 때 KST 기준 날짜 사용
        existing_attendance_params = {
            "user_id": f"eq.{user_id}",
            "date": f"eq.{today_date_str}" # <-- KST 기준 날짜 사용
        }
        res_check_exist = requests.get(
            f"{SUPABASE_URL}/rest/v1/attendances",
            headers=headers,
            params=existing_attendance_params
        )
        existing_records = res_check_exist.json() if res_check_exist.status_code == 200 else []
        current_day_attendance = existing_records[0] if existing_records else None

        if record_type == '출근':
            if current_day_attendance and current_day_attendance.get('check_in_time'):
                # 오늘 날짜의 기록이 있고 이미 출근 시간이 있다면
                flash("이미 출근 처리되었습니다.", "info")
            else:
                if current_day_attendance:
                    # 오늘 날짜의 기록은 있지만 출근 시간이 없다면 (퇴근만 있거나, 혹은 Supabase 제약 조건에 의해 빈 레코드가 생성된 경우)
                    data_to_update = {
                        'check_in_time': current_time_str,
                        'employee_name': employee_name # <-- 여기에 직원 이름 추가
                        }
                    res = requests.patch(
                        f"{SUPABASE_URL}/rest/v1/attendances?id=eq.{current_day_attendance['id']}",
                        headers=headers,
                        json=data_to_update
                    )
                    if res.status_code == 200 or res.status_code == 204:
                        flash(f"출근 처리되었습니다: {now_kst.strftime('%I:%M %p')}", "success") # <-- now_kst 사용 및 AM/PM 포맷
                    else:
                        raise Exception(f"출근 기록 업데이트 실패: {res.status_code} - {res.text}")
                else:
                    # 오늘 날짜의 기록이 전혀 없다면 새로운 기록 생성
                    data_to_send = {
                        'user_id': user_id,
                        'date': today_date_str,
                        'check_in_time': current_time_str,
                        'check_out_time': None,
                        'employee_name': employee_name
                    }
                    res = requests.post(
                        f"{SUPABASE_URL}/rest/v1/attendances",
                        headers=headers,
                        json=data_to_send
                    )
                    if res.status_code == 201:
                        flash(f"출근 처리되었습니다: {now_kst.strftime('%I:%M %p')}", "success") # <-- now_kst 사용 및 AM/PM 포맷
                    else:
                        raise Exception(f"출근 기록 생성 실패: {res.status_code} - {res.text}")

        elif record_type == '퇴근':
            if not current_day_attendance or not current_day_attendance.get('check_in_time'):
                flash("출근 기록이 먼저 필요합니다.", "warning")
            elif current_day_attendance.get('check_out_time'):
                flash("이미 퇴근 처리되었습니다.", "info")
            else:
                if current_day_attendance:
                    data_to_update = {'check_out_time': current_time_str}
                    res = requests.patch(
                        f"{SUPABASE_URL}/rest/v1/attendances?id=eq.{current_day_attendance['id']}",
                        headers=headers,
                        json=data_to_update
                    )
                    if res.status_code == 200 or res.status_code == 204:
                        flash("오늘 하루도 수고하셨습니다.", "success")
                    else:
                        raise Exception(f"퇴근 기록 업데이트 실패: {res.status_code} - {res.text}")
                else:
                    flash("출근 기록이 없어 퇴근 처리가 불가능합니다.", "warning")

    except requests.exceptions.RequestException as e:
        print(f"Supabase 요청 오류: {e}")
        flash("네트워크 통신 중 오류가 발생했습니다.", "danger")
    except Exception as e:
        print(f"근태 처리 중 오류가 발생했습니다: {e}")
        import traceback
        traceback.print_exc()
        flash("근태 처리 중 알 수 없는 오류가 발생했습니다.", "danger")

    return redirect(url_for('main_dashboard'))

# MY 근태현황 페이지
@app.route('/my-attendance')
def my_attendance():
    if 'user' not in session or session['user']['role'] != 'employee':
        flash("직원 대시보드 접근 권한이 없습니다.", "danger")
        return redirect(url_for('login'))

    user_id = session['user']['id']

    headers = {
        "apikey": SUPABASE_KEY,
        "Authorization": f"Bearer {SUPABASE_KEY}"
    }

        # === [추가된 부분 시작] 출퇴근 기록 가져오기 (사이드바 버튼용) ===
    kst_timezone = pytz.timezone('Asia/Seoul')
    today = datetime.now(kst_timezone).date()
    current_check_in_time = None
    current_check_out_time = None
    today_attendance_params = {
        "user_id": f"eq.{user_id}",
        "date": f"eq.{today.isoformat()}"
    }
    res_today_attendance = requests.get(f"{SUPABASE_URL}/rest/v1/attendances", headers=headers, params=today_attendance_params)
    if res_today_attendance.status_code == 200 and res_today_attendance.json():
        today_record = res_today_attendance.json()[0]
        if today_record.get('check_in_time'):
            current_check_in_time = datetime.strptime(today_record['check_in_time'], '%H:%M:%S').strftime('%I:%M %p')
        if today_record.get('check_out_time'):
            current_check_out_time = datetime.strptime(today_record['check_out_time'], '%H:%M:%S').strftime('%I:%M %p')
    # === [추가된 부분 끝] ===

    # base.html에 필요한 사용자 정보 전달
    user_res = requests.get(
        f"{SUPABASE_URL}/rest/v1/users?id=eq.{user_id}&select=name,yearly_leave,monthly_leave",
        headers=headers
    )
    if user_res.status_code != 200 or not user_res.json():
        flash("사용자 정보 조회 실패", "danger")
        return redirect(url_for('login'))
    
    user_info = user_res.json()[0]
    
    # 7. MY 근태현황 데이터 가져오기
    attendance_events = []
    try:
        all_attendance_params = {
            "user_id": f"eq.{user_id}",
            "order": "date.desc"
        }
        all_attendance_res = requests.get(
            f"{SUPABASE_URL}/rest/v1/attendances",
            headers=headers,
            params=all_attendance_params
        )

        if all_attendance_res.status_code == 200:
            raw_records = all_attendance_res.json()
            for record in raw_records:
                record_date_str = record.get('date')
                check_in_time_raw = record.get('check_in_time')
                check_out_time_raw = record.get('check_out_time')
                check_in_display = 'N/A'
                check_out_display = 'N/A'
                work_duration = '-'

                dt_in_combined = None
                dt_out_combined = None

                if check_in_time_raw and record_date_str:
                    try:
                        dt_in_combined = datetime.strptime(f"{record_date_str} {check_in_time_raw}", '%Y-%m-%d %H:%M:%S')
                        check_in_display = dt_in_combined.strftime('%I:%M %p')
                    except ValueError:
                        pass
                
                if check_out_time_raw and record_date_str:
                    try:
                        dt_out_combined = datetime.strptime(f"{record_date_str} {check_out_time_raw}", '%Y-%m-%d %H:%M:%S')
                        check_out_display = dt_out_combined.strftime('%I:%M %p')
                    except ValueError:
                        pass
                
                if dt_in_combined and dt_out_combined:
                    if dt_out_combined < dt_in_combined:
                        dt_out_combined += timedelta(days=1)
                    duration = dt_out_combined - dt_in_combined
                    total_seconds = int(duration.total_seconds())
                    hours = total_seconds // 3600
                    minutes = (total_seconds % 3600) // 60
                    if hours < 0:
                        work_duration = "오류"
                    else:
                        work_duration = f"{hours}시간 {minutes}분"
                elif check_in_time_raw and not check_out_time_raw:
                    work_duration = "근무 중"

                attendance_events.append({
                    'date': record_date_str,
                    'check_in': check_in_display,
                    'check_out': check_out_display,
                    'work_duration': work_duration
                })
    except Exception as e:
        print(f"MY 근태현황 데이터 처리 중 오류 발생: {e}")
        import traceback
        traceback.print_exc()

    return render_template(
        'my_attendance.html',
        user=user_info,
        attendance_events=attendance_events,
        # === [추가된 부분] ===
        current_check_in_time=current_check_in_time,
        current_check_out_time=current_check_out_time
        # === [추가된 부분 끝] ===
    )

@app.route("/monthly-stats")
def monthly_stats():
    if 'user' not in session or session['user']['role'] != 'admin':
        return redirect('/login')

    headers = {
        "apikey": SUPABASE_KEY,
        "Authorization": f"Bearer {SUPABASE_KEY}"
    }

    # 승인된 휴가 전체 조회
    res = requests.get(
        f"{SUPABASE_URL}/rest/v1/vacations?status=eq.approved&select=id,start_date,end_date,used_days,type,user_id,users(name)",
        headers=headers
    )
    vacations = res.json() if res.status_code == 200 else []

    # 👉 월별 휴가 사용 일수 집계 {유저명: {yyyy-mm: 일수}}
    monthly_stats = defaultdict(lambda: defaultdict(float))

    for v in vacations:
        user = v.get("users", {}).get("name", "Unknown")

        try:
            start_date = parse(v["start_date"])
            used_days = float(v.get("used_days", 0))
        except Exception:
            continue

        month_key = start_date.strftime("%Y-%m")
        monthly_stats[user][month_key] += used_days

    # 🔥 현재 월 강제로 포함시키기
    current_month_key = datetime.now().strftime("%Y-%m")

    for user in monthly_stats:
        monthly_stats[user].setdefault(current_month_key, 0.0)

    return render_template("monthly_stats.html", user=session['user'], stats=monthly_stats)


@app.route('/download-stats')
def download_stats():
    if 'user' not in session or session['user']['role'] != 'admin':
        return redirect('/login')

    stats_type = request.args.get('type', 'total')  # 기본은 'total'
    headers = {
        "apikey": SUPABASE_KEY,
        "Authorization": f"Bearer {SUPABASE_KEY}"
    }

    # 📌 1. 월별 통계 다운로드
    if stats_type == 'monthly':
        vac_res = requests.get(
            f"{SUPABASE_URL}/rest/v1/vacations?status=eq.approved&select=id,start_date,used_days,type,user_id,users(name)",
            headers=headers
        )
        vacations = vac_res.json() if vac_res.status_code == 200 else []

        monthly_stats = defaultdict(lambda: defaultdict(float))  # {user: {YYYY-MM: used_days}}

        for v in vacations:
            if not v.get("start_date") or not v.get("used_days"):
                continue

            user = v["users"]["name"] if "users" in v and v["users"] else "Unknown"
            start_date = parse(v["start_date"])
            month_key = start_date.strftime("%Y-%m")

            try:
                used_days = float(v["used_days"])
            except (ValueError, TypeError):
                used_days = 0

            monthly_stats[user][month_key] += used_days

        all_months = sorted({m for stats in monthly_stats.values() for m in stats})

        data = []
        for user, stats in monthly_stats.items():
            row = {"상담원": user}
            for month in all_months:
                row[month] = stats.get(month, 0)
            data.append(row)

        df = pd.DataFrame(data)
        output = io.BytesIO()
        with pd.ExcelWriter(output, engine='xlsxwriter') as writer:
            df.to_excel(writer, sheet_name="월별 휴가 통계", index=False)
        output.seek(0)

        return send_file(
            output,
            mimetype="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            as_attachment=True,
            download_name="월별_휴가_통계.xlsx"
        )

# 📌 2. 전체 통계 다운로드
    res = requests.get(f"{SUPABASE_URL}/rest/v1/users?select=id,name,join_date,role", headers=headers)
    users = res.json() if res.status_code == 200 else []

    today = datetime.today().date()
    rows = []

    for u in users:
        if u.get("role") == "admin":
            continue

        uid = u["id"]
        name = u["name"]
        
        # join_date가 없는 경우 건너뛰거나 기본값 설정
        join_date_str = u.get("join_date")
        if not join_date_str:
            continue

        total_yearly, total_monthly = calculate_leave(join_date_str)

        # deduct_from_type 컬럼도 함께 가져옴
        vac_res = requests.get(
            f"{SUPABASE_URL}/rest/v1/vacations?user_id=eq.{uid}&status=eq.approved&select=type,used_days,deduct_from_type",
            headers=headers
        )
        vacs = vac_res.json() if vac_res.status_code == 200 else []

        # ✅ 사용된 연차/월차 초기화
        used_yearly = 0.0
        used_monthly = 0.0

        # 휴가 타입과 deduct_from_type에 따라 사용 일수 합산
        for v in vacs:
            try:
                used_days_val = float(v.get("used_days", 0))
            except (ValueError, TypeError):
                used_days_val = 0.0
    
            deduction_source = v.get("deduct_from_type") # Supabase에서 가져온 deduct_from_type

            if deduction_source == "yearly":
                used_yearly += used_days_val
            elif deduction_source == "monthly":
                used_monthly += used_days_val
            else:
            # deduct_from_type이 없는 (오래된) 데이터 처리.
            # request_vacation의 폴백 로직과 일관성 유지 필요.
            # 예: 과거 데이터가 'type' 필드에 '연차' 또는 '반차'로만 있었다면 연차로 간주.
                if v.get("type") == "연차" or v.get("type", "").startswith(("반차", "반반차")): 
                    used_yearly += used_days_val
                elif v.get("type") == "월차":
                    used_monthly += used_days_val 
            
        used_yearly = round(used_yearly, 2)
        used_monthly = round(used_monthly, 2)

        remain_yearly = total_yearly - used_yearly
        remain_monthly = total_monthly - used_monthly

        rows.append({
            "직원명": name,
            "총 연차": total_yearly,
            "총 월차": total_monthly,
            "사용 연차": used_yearly,
            "사용 월차": used_monthly,
            "잔여 연차": remain_yearly,
            "잔여 월차": remain_monthly
        })

    df = pd.DataFrame(rows)
    output = io.BytesIO()
    with pd.ExcelWriter(output, engine='xlsxwriter') as writer:
        df.to_excel(writer, sheet_name="휴가 통계", index=False)
    output.seek(0)

    return send_file(
        output,
        mimetype="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        as_attachment=True,
        download_name="휴가_통계.xlsx"
    )

@app.route('/download-used-vacations')
def download_used_vacations():
    if 'user' not in session or session['user']['role'] != 'admin':
        return redirect('/login')

    headers = {
        "apikey": SUPABASE_KEY,
        "Authorization": f"Bearer {SUPABASE_KEY}"
    }

    url = f"{SUPABASE_URL}/rest/v1/vacations?select=id,type,used_days,status,start_date,end_date,requested_at,users(name)&order=requested_at.desc"
    res = requests.get(url, headers=headers)

    if res.status_code != 200:
        return "데이터를 불러오는 데 실패했습니다.", 500

    raw = res.json()

    data = [
        {
            "직원명": v["users"]["name"],
            "휴가유형": v.get("type", "기타"),
            "사용일수": v.get("used_days", 0),
            "신청일자": v.get("requested_at", '')[:10],
            "시작일자": v.get("start_date", '')[:10],
            "종료일자": v.get("end_date", '')[:10],
            "상태": v.get("status", "unknown")
        }
        for v in raw if v.get("status") == "approved"
    ]

    df = pd.DataFrame(data)
    output = io.BytesIO()
    with pd.ExcelWriter(output, engine='xlsxwriter') as writer:
        df.to_excel(writer, index=False, sheet_name='휴가 소진 내역')
    output.seek(0)

    return send_file(
        output,
        as_attachment=True,
        download_name="휴가_소진_내역.xlsx",
        mimetype="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
    )

@app.route('/update-status', methods=['POST'])
def update_status():
    if 'user' not in session or session['user']['role'] != 'admin':
        return redirect('/login')

    vacation_id = request.form['vacation_id']
    new_status = request.form['status']

    headers = {
        "apikey": SUPABASE_KEY,
        "Authorization": f"Bearer {SUPABASE_KEY}",
        "Content-Type": "application/json"
    }

    res = requests.patch(
        f"{SUPABASE_URL}/rest/v1/vacations?id=eq.{vacation_id}",
        headers=headers,
        json={"status": new_status}
    )

    if res.status_code == 204:
        if new_status == 'approved':
            flash("✅ 휴가가 승인되었습니다.", "success")
        elif new_status == 'rejected':
            flash("❌ 휴가가 반려되었습니다.", "warning")
    else:
        flash("⚠️ 상태 변경 중 오류가 발생했습니다.", "danger")

    return redirect('/admin')

# ⭐ 새로운 라우트: 근무 기록 엑셀 다운로드 ⭐
@app.route('/download-attendance-stats')
def download_attendance_stats():
    # 관리자 권한 확인
    if 'user' not in session or session['user']['role'] != 'admin':
        flash("엑셀 다운로드 권한이 없습니다.", "danger")
        return redirect(url_for('login'))

    headers = {
        "apikey": SUPABASE_KEY,
        "Authorization": f"Bearer {SUPABASE_KEY}"
    }

    # 필터 파라미터
    filter_user_id = request.args.get('user_id')          # 'all' | <uuid>
    date_from      = request.args.get('date_from')         # 'YYYY-MM-DD' | None
    date_to        = request.args.get('date_to')           # 'YYYY-MM-DD' | None

    # 이름 매핑
    users_res = requests.get(
        f"{SUPABASE_URL}/rest/v1/users?select=id,name",
        headers=headers
    )
    user_names = {u['id']: u['name'] for u in users_res.json()} if users_res.status_code == 200 else {}

    # Supabase 쿼리 파라미터 구성
    attendance_params = {
        "order": "date.desc,check_in_time.desc"
    }
    if filter_user_id and filter_user_id != 'all':
        attendance_params["user_id"] = f"eq.{filter_user_id}"

    # 날짜 범위 필터 적용
    # - 둘 다 있으면 and=(date.gte.X,date.lte.Y)
    # - 하나만 있으면 date=gte.X 또는 date=lte.Y
    if date_from and date_to:
        attendance_params["and"] = f"(date.gte.{date_from},date.lte.{date_to})"
    elif date_from:
        attendance_params["date"] = f"gte.{date_from}"
    elif date_to:
        attendance_params["date"] = f"lte.{date_to}"
    # (없으면 전체 기간)

    # 근태 기록 조회
    all_attendance_res = requests.get(
        f"{SUPABASE_URL}/rest/v1/attendances",
        headers=headers,
        params=attendance_params
    )

    records_for_excel = []
    if all_attendance_res.status_code == 200:
        raw_records = all_attendance_res.json()

        for record in raw_records:
            record_date_str = record.get('date')
            check_in_time_raw = record.get('check_in_time')
            check_out_time_raw = record.get('check_out_time')
            record_user_id = record.get('user_id')

            employee_name = user_names.get(record_user_id, "알 수 없는 직원")
            check_in_display = 'N/A'
            check_out_display = 'N/A'
            work_duration = '-'

            dt_in_combined = None
            dt_out_combined = None

            if check_in_time_raw and record_date_str:
                try:
                    dt_in_combined = datetime.strptime(f"{record_date_str} {check_in_time_raw}", '%Y-%m-%d %H:%M:%S')
                    check_in_display = check_in_time_raw[:5]
                except ValueError:
                    print(f"Excel 다운로드: 출근 시간/날짜 파싱 오류: 날짜={record_date_str}, 시간={check_in_time_raw}")

            if check_out_time_raw and record_date_str:
                try:
                    dt_out_combined = datetime.strptime(f"{record_date_str} {check_out_time_raw}", '%Y-%m-%d %H:%M:%S')
                    check_out_display = check_out_time_raw[:5]
                except ValueError:
                    print(f"Excel 다운로드: 퇴근 시간/날짜 파싱 오류: 날짜={record_date_str}, 시간={check_out_time_raw}")

            if dt_in_combined and dt_out_combined:
                if dt_out_combined < dt_in_combined:
                    dt_out_combined += timedelta(days=1)

                duration = dt_out_combined - dt_in_combined
                total_seconds = int(duration.total_seconds())
                hours = total_seconds // 3600
                minutes = (total_seconds % 3600) // 60

                if hours < 0:
                    work_duration = "오류"
                else:
                    work_duration = f"{hours}시간 {minutes}분"
            elif check_in_time_raw and not check_out_time_raw:
                work_duration = "근무 중"

            records_for_excel.append({
                '날짜': record_date_str,
                '이름': employee_name,
                '출근시간': check_in_display,
                '퇴근시간': check_out_display,
                '근무시간': work_duration
            })

    # DataFrame → Excel
    df = pd.DataFrame(records_for_excel)
    output = io.BytesIO()
    with pd.ExcelWriter(output, engine='xlsxwriter') as writer:
        df.to_excel(writer, index=False, sheet_name='근무기록')
    output.seek(0)

    # 파일명에 유저/기간 반영(선택)
    user_part = ''
    if filter_user_id and filter_user_id != 'all':
        user_part = f"_{user_names.get(filter_user_id, '직원')}"
    range_part = ''
    if date_from or date_to:
        range_part = f"_{date_from or ''}~{date_to or ''}"

    filename = f"근무기록{user_part}{range_part}_{datetime.now().strftime('%Y%m%d_%H%M%S')}.xlsx"

    return send_file(
        output,
        mimetype='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
        as_attachment=True,
        download_name=filename
    )



# ✅ 직원관리용 페이지라우트
@app.route('/manage-users')
def manage_users():
    if 'user' not in session or session['user']['role'] != 'admin':
        return redirect('/login')

    headers = {
        "apikey": SUPABASE_KEY,
        "Authorization": f"Bearer {SUPABASE_KEY}"
    }

    res = requests.get(f"{SUPABASE_URL}/rest/v1/users?select=id,name,email,join_date,role", headers=headers)
    users = res.json() if res.status_code == 200 else []

    return render_template(
        "manage_users.html", 
        users=users,
        user=session['user'],
         active='manage-users')

# ✅ 직원관리용 페이지라우트-직원등록
@app.route('/add-user', methods=['POST'])
def add_user():
    if 'user' not in session or session['user']['role'] != 'admin':
        return redirect('/login')

    name = request.form['name']
    email = request.form['email']
    password = request.form['password']
    join_date = request.form['join_date']

    headers = {
        "apikey": SUPABASE_KEY,
        "Authorization": f"Bearer {SUPABASE_KEY}",
        "Content-Type": "application/json"
    }

    user_data = {
        "name": name,
        "email": email,
        "password": password,
        "join_date": join_date,
        "role": "employee",
        "yearly_leave": 0,
        "monthly_leave": 0
    }

    res = requests.post(f"{SUPABASE_URL}/rest/v1/users", headers=headers, json=user_data)
    return redirect('/manage-users') if res.status_code == 201 else f"❌ 등록 실패: {res.text}"

# ✅ 직원관리용 페이지라우트-직원삭제
@app.route('/delete-user/<user_id>', methods=['POST'])
def delete_user(user_id):
    if 'user' not in session or session['user']['role'] != 'admin':
        return redirect('/login')

    headers = {
        "apikey": SUPABASE_KEY,
        "Authorization": f"Bearer {SUPABASE_KEY}"
    }

    res = requests.delete(f"{SUPABASE_URL}/rest/v1/users?id=eq.{user_id}", headers=headers)
    return redirect('/manage-users') if res.status_code == 204 else f"❌ 삭제 실패: {res.text}"

# ✅ 직원관리용 페이지라우트-입사일수정라우트
@app.route('/update-join-date', methods=['POST'])
def update_join_date():
    if 'user' not in session or session['user']['role'] != 'admin':
        return redirect('/login')

    user_id = request.form.get('id')
    join_date = request.form.get('join_date')

    if not user_id or not join_date:
        return "❌ 입력값 오류", 400

    headers = {
        "apikey": SUPABASE_KEY,
        "Authorization": f"Bearer {SUPABASE_KEY}",
        "Content-Type": "application/json"
    }

    payload = {
        "join_date": join_date
    }

    res = requests.patch(
        f"{SUPABASE_URL}/rest/v1/users?id=eq.{user_id}",
        headers=headers,
        json=payload
    )

    if res.status_code == 204:
        return redirect('/manage-users')
    else:
        return f"❌ 수정 실패: {res.text}", 500

@app.route('/used-vacations')
def used_vacations_page():
    if 'user' not in session or session['user']['role'] != 'admin':
        return redirect('/login')

    headers = {
        "apikey": SUPABASE_KEY,
        "Authorization": f"Bearer {SUPABASE_KEY}"
    }

    url = f"{SUPABASE_URL}/rest/v1/vacations?select=id,type,used_days,status,start_date,end_date,requested_at,users(name)&order=requested_at.desc"
    res = requests.get(url, headers=headers)

    if res.status_code != 200:
        return "데이터를 불러오는 데 실패했습니다.", 500

    raw = res.json()

    used_vacations = [
        {
            "name": v["users"]["name"],
            "type": v.get("type", "기타"),
            "used_days": v.get("used_days", 0),
            "requested_at": v.get("requested_at", '')[:10],
            "start_date": v.get("start_date", '')[:10],
            "end_date": v.get("end_date", '')[:10],
            "status": v.get("status", "unknown")
        }
        for v in raw if v.get("status") == "approved"
    ]

    return render_template('used_vacations.html', used_vacations=used_vacations)


# 휴가 신청 폼 페이지를 보여주는 엔드포인트
@app.route('/vacation/request')
def vacation_request():
    if 'user' not in session or session['user']['role'] != 'employee':
        flash("직원 대시보드 접근 권한이 없습니다.", "danger")
        return redirect(url_for('login'))

    user_id = session['user']['id']

    headers = {
        "apikey": SUPABASE_KEY,
        "Authorization": f"Bearer {SUPABASE_KEY}"
    }

    # === [추가된 부분 시작] 출퇴근 기록 가져오기 (사이드바 버튼용) ===
    kst_timezone = pytz.timezone('Asia/Seoul')
    today = datetime.now(kst_timezone).date()
    current_check_in_time = None
    current_check_out_time = None
    today_attendance_params = {
        "user_id": f"eq.{user_id}",
        "date": f"eq.{today.isoformat()}"
    }
    res_today_attendance = requests.get(f"{SUPABASE_URL}/rest/v1/attendances", headers=headers, params=today_attendance_params)
    if res_today_attendance.status_code == 200 and res_today_attendance.json():
        today_record = res_today_attendance.json()[0]
        if today_record.get('check_in_time'):
            current_check_in_time = datetime.strptime(today_record['check_in_time'], '%H:%M:%S').strftime('%I:%M %p')
        if today_record.get('check_out_time'):
            current_check_out_time = datetime.strptime(today_record['check_out_time'], '%H:%M:%S').strftime('%I:%M %p')
    # === [추가된 부분 끝] ===

    # base.html에 필요한 사용자 정보 전달
    user_res = requests.get(
        f"{SUPABASE_URL}/rest/v1/users?id=eq.{user_id}&select=name,yearly_leave,monthly_leave",
        headers=headers
    )
    if user_res.status_code != 200 or not user_res.json():
        flash("사용자 정보 조회 실패", "danger")
        return redirect(url_for('login'))
    
    user_info = user_res.json()[0]

    return render_template(
        'vacation_request.html', 
        user=user_info,
        # === [추가된 부분] ===
        current_check_in_time=current_check_in_time,
        current_check_out_time=current_check_out_time
        # === [추가된 부분 끝] ===
        )

# ✅ 휴가 신청 처리
@app.route('/request-vacation', methods=['POST'])
def request_vacation():
    # user = None  # 이 줄을 제거합니다.
    
    user = session.get('user') # 세션에서 사용자 정보를 가져옵니다.
    
    # 1. user 객체가 None인지 확인하고, None이면 바로 로그인 페이지로 리다이렉트
    if user is None: # 명시적으로 'is None'을 사용합니다.
        flash("⛔ 사용자 정보를 불러오지 못했습니다. 다시 로그인해 주세요.", "danger")
        return redirect(url_for('login')) # '/login' -> url_for('login')으로 변경

    # 2. user 객체가 딕셔너리 타입인지 확인 (세션 데이터의 유효성 검사)
    if not isinstance(user, dict):
        print(f"ERROR: User object in session is not a dictionary: {user}, type: {type(user)}")
        flash("세션 사용자 정보가 올바르지 않습니다. 다시 로그인해주세요.", "danger")
        return redirect(url_for('login')) # '/login' -> url_for('login')으로 변경

    # 3. user_id와 employee_name을 안전하게 가져옵니다.
    # .get() 메서드를 사용하여 키가 없어도 오류가 아닌 None을 반환하도록 합니다.
    user_id = user.get('id')
    employee_name = user.get('name')

    # 4. user_id 또는 employee_name이 None인지 다시 확인하고, 불완전하면 리다이렉트
    if user_id is None or employee_name is None:
        print(f"ERROR: Missing user_id ({user_id}) or employee_name ({employee_name}) in session user data: {user}")
        flash("사용자 정보가 불완전합니다. 다시 로그인해주세요.", "danger")
        return redirect(url_for('login')) # '/login' -> url_for('login')으로 변경

    start_date_str = request.form.get('start_date')
    end_date_str = request.form.get('end_date')
    leave_type = request.form.get('type') # full_day, half_day_am 등
    deduct_from_type = request.form.get('deduct_from_type') # yearly, monthly

    print(f"DEBUG: base_leave_type: {deduct_from_type}, granularity_type: {leave_type}")

    try:
        start_date = datetime.strptime(start_date_str, '%Y-%m-%d').date()
        end_date = datetime.strptime(end_date_str, '%Y-%m-%d').date()
    except ValueError:
        flash("❌ 날짜 형식이 잘못되었습니다.", "danger")
        return redirect(url_for('main_dashboard')) # '/dashboard' -> url_for('main_dashboard')으로 변경

    if start_date > end_date:
        flash("❌ 시작일은 종료일보다 빠를 수 없습니다.", "warning")
        return redirect(url_for('main_dashboard')) # '/dashboard' -> url_for('main_dashboard')으로 변경

    headers = {
        "apikey": SUPABASE_KEY,
        "Authorization": f"Bearer {SUPABASE_KEY}"
    }

    # 중복 휴가 검사 (기존 로직과 동일)
    vac_check = requests.get(
        f"{SUPABASE_URL}/rest/v1/vacations?user_id=eq.{user_id}&or=(status.eq.approved,status.eq.pending)",
        headers=headers
    )
    existing = vac_check.json() if vac_check.status_code == 200 else []

    for vac in existing:
        exist_start = datetime.strptime(vac["start_date"], "%Y-%m-%d").date()
        exist_end = datetime.strptime(vac["end_date"], "%Y-%m-%d").date()
        if start_date <= exist_end and end_date >= exist_start:
            flash(f"⚠️ 해당 기간({vac['start_date']}~{vac['end_date']})에 이미 신청된 휴가가 있습니다.", "warning")
            return redirect(url_for('main_dashboard')) # '/dashboard' -> url_for('main_dashboard')으로 변경

    # 사용 일수 계산
    used_days = 0.0
    type_to_save_in_supabase = ""
    deduct_from_type_to_save = ""

    if deduct_from_type == 'yearly':
        deduct_from_type_to_save = "yearly"
    elif deduct_from_type == 'monthly':
        deduct_from_type_to_save = "monthly"
    else:
        flash("❌ 유효한 휴가 유형(연차/월차)을 선택해 주세요.", "danger")
        return redirect(url_for('main_dashboard')) # '/dashboard' -> url_for('main_dashboard')으로 변경

    if leave_type == 'full_day':
        used_days = (end_date - start_date).days + 1
        type_to_save_in_supabase = "종일"
        if used_days <= 0:
            flash("❌ 종일 휴가는 최소 하루 이상이어야 합니다.", "danger")
            return redirect(url_for('main_dashboard')) # '/dashboard' -> url_for('main_dashboard')으로 변경
    elif leave_type == 'half_day_am':
        used_days = 0.5
        type_to_save_in_supabase = "반차-오전"
        if start_date != end_date:
            flash("❌ 반차는 하루만 선택할 수 있습니다.", "danger")
            return redirect(url_for('main_dashboard')) # '/dashboard' -> url_for('main_dashboard')으로 변경
    elif leave_type == 'half_day_pm':
        used_days = 0.5
        type_to_save_in_supabase = "반차-오후"
        if start_date != end_date:
            flash("❌ 반차는 하루만 선택할 수 있습니다.", "danger")
            return redirect(url_for('main_dashboard')) # '/dashboard' -> url_for('main_dashboard')으로 변경
    elif leave_type == 'quarter_day_am':
        used_days = 0.25
        type_to_save_in_supabase = "반반차-오전"
        if start_date != end_date:
            flash("❌ 반반차는 하루만 선택할 수 있습니다.", "danger")
            return redirect(url_for('main_dashboard')) # '/dashboard' -> url_for('main_dashboard')으로 변경
    elif leave_type == 'quarter_day_pm':
        used_days = 0.25
        type_to_save_in_supabase = "반반차-오후"
        if start_date != end_date:
            flash("❌ 반반차는 하루만 선택할 수 있습니다.", "danger")
            return redirect(url_for('main_dashboard')) # '/dashboard' -> url_for('main_dashboard')으로 변경
    else:
        flash("❌ 유효한 휴가 종류(종일/반차/반반차)를 선택해 주세요.", "danger")
        return redirect(url_for('main_dashboard')) # '/dashboard' -> url_for('main_dashboard')으로 변경

    # 사용자 정보 및 총 잔여 휴가 계산 (기존과 동일)
    res_user = requests.get(f"{SUPABASE_URL}/rest/v1/users?id=eq.{user_id}", headers=headers)
    if res_user.status_code != 200 or not res_user.json():
        flash("❌ 사용자 정보를 불러올 수 없습니다.", "danger")
        return redirect(url_for('main_dashboard')) # '/dashboard' -> url_for('main_dashboard')으로 변경

    user_data_from_db = res_user.json()[0]
    auto_yearly_leave, auto_monthly_leave = calculate_leave(user_data_from_db.get("join_date"))

    res_vac = requests.get(
        f"{SUPABASE_URL}/rest/v1/vacations?user_id=eq.{user_id}&status=eq.approved",
        headers=headers
    )
    used_vac_records = res_vac.json() if res_vac.status_code == 200 else []
    
    current_used_monthly = 0.0
    current_used_yearly = 0.0

    for v in used_vac_records:
        try:
            val = float(v.get("used_days", 0))
        except (ValueError, TypeError):
            val = 0.0
        
        deduction_source = v.get("deduct_from_type") 

        if deduction_source == "yearly":
            current_used_yearly += val
        elif deduction_source == "monthly":
            current_used_monthly += val
        else:
            if v.get("type") == "연차" or v.get("type", "").startswith(("반차", "반반차")): 
                current_used_yearly += val
            elif v.get("type") == "월차":
                current_used_monthly += val

    remaining_monthly = max(auto_monthly_leave - current_used_monthly, 0)
    remaining_yearly = max(auto_yearly_leave - current_used_yearly, 0)

    # 잔여 휴가 확인
    # 부족해도 신청 가능 — 음수로 떨어질 수 있음
    if deduct_from_type_to_save == "monthly" and remaining_monthly < used_days:
        flash(f"⚠ 월차가 부족하지만 신청은 가능합니다. 현재 잔여: {remaining_monthly}일 → 신청 후 {remaining_monthly - used_days}일", "warning")

    elif deduct_from_type_to_save == "yearly" and remaining_yearly < used_days:
        flash(f"⚠ 연차가 부족하지만 신청은 가능합니다. 현재 잔여: {remaining_yearly}일 → 신청 후 {remaining_yearly - used_days}일", "warning")

    # ❌ 신청 차단 로직 삭제
    # if not sufficient_leave:
    #     return redirect(url_for('main_dashboard'))

    # Supabase에 휴가 신청 데이터 저장
    headers["Content-Type"] = "application/json"
    data = {
        "user_id": user_id,
        'employee_name': employee_name,
        "type": type_to_save_in_supabase,
        "start_date": start_date_str,
        "end_date": end_date_str,
        "used_days": used_days,
        "status": "pending",
        "deduct_from_type": deduct_from_type_to_save
    }

    res_post = requests.post(f"{SUPABASE_URL}/rest/v1/vacations", headers=headers, json=data)
    if res_post.status_code == 201:
        flash("✅ 휴가 신청이 완료되었습니다.", "success")
        return redirect(url_for('main_dashboard')) # '/dashboard' -> url_for('main_dashboard')으로 변경
    else:
        flash("❌ 신청 실패: 관리자에게 문의해 주세요.", "danger")
        print(f"Supabase Post Error: {res_post.status_code}, {res_post.text}")
        return redirect(url_for('main_dashboard')) # '/dashboard' -> url_for('main_dashboard')으로 변경

@app.route('/vacation-events')
def get_vacation_events():
    """
    FullCalendar에 표시할 모든 직원의 승인된 휴가 이벤트를 가져옵니다.
    Supabase에서 'status'가 'approved'인 휴가 기록만 필터링합니다.
    """
    headers = {
        "apikey": SUPABASE_KEY,
        "Authorization": f"Bearer {SUPABASE_KEY}"
    }

    # ✅ 수정: 승인된 휴가 기록만 가져오도록 status 필터 추가
    # ✅ 수정: vacation_types 조인 제거 및 기존 로직 재활용
    params = {
        "status": "eq.approved",
        "select": "user_id,type,deduct_from_type,status,start_date,end_date,users(name),employee_name"
    }

    try:
        res = requests.get(
            f"{SUPABASE_URL}/rest/v1/vacations",
            headers=headers,
            params=params
        )
        res.raise_for_status()  # HTTP 오류 발생 시 예외 발생
        vacations = res.json()
    except requests.exceptions.RequestException as e:
        print(f"Error fetching vacation events: {e}")
        return jsonify({'error': 'Failed to fetch vacation events'}), 500

    events = []
    for v in vacations:
        event_class_names = []
        
        employee_name = v.get('users', {}).get('name') or v.get('employee_name', '알 수 없음')

        # 캘린더 제목과 클래스 결정을 위한 변수
        display_type = '휴가'
        vacation_type = v.get('type')
        
        # 반차, 반반차를 먼저 판단
        if vacation_type in ['반차-오전', '반차-오후']:
            event_class_names.append('vacation-type-half-day')
            display_type = '반차'
        elif vacation_type in ['반반차-오전', '반반차-오후']:
            event_class_names.append('vacation-type-quarter-day')
            display_type = '반반차'
        else:
            # 종일 휴가를 판단
            deduct_type = v.get('deduct_from_type')
            if deduct_type == 'yearly':
                event_class_names.append('vacation-type-full-day')
                display_type = '연차'
            elif deduct_type == 'monthly':
                event_class_names.append('vacation-type-full-day')
                display_type = '월차'
            else:
                event_class_names.append('vacation-type-other')
                display_type = '기타'

        # 휴가 상태에 따른 클래스 추가 (승인/대기/반려)
        event_status = v.get('status')
        if event_status:
            event_class_names.append(f"vacation-status-{event_status}")

        # FullCalendar의 'end' 날짜는 종료일 다음 날로 설정
        end_date_inclusive = (datetime.strptime(v['end_date'], "%Y-%m-%d") + timedelta(days=1)).strftime("%Y-%m-%d")

        events.append({
            'title': f"{employee_name} ({display_type})",
            'start': v['start_date'],
            'end': end_date_inclusive,
            'classNames': event_class_names,
            'allDay': True
        })
        
    return jsonify(events)


@app.route('/my-vacations-history')
def my_vacations_history():
    """
    현재 로그인된 사용자의 휴가 신청 내역을 가져옵니다.
    """
    if 'user' not in session:
        return jsonify({'error': 'Unauthorized'}), 401

    user_id = session['user']['id']
    headers = {
        "apikey": SUPABASE_KEY,
        "Authorization": f"Bearer {SUPABASE_KEY}"
    }
    
    # ✅ 수정: vacation_types 조인 제거 및 기존 로직 재활용
    params = {
        "user_id": f"eq.{user_id}",
        "select": "user_id,type,deduct_from_type,status,start_date,end_date,requested_at,used_days"
    }

    try:
        res = requests.get(
            f"{SUPABASE_URL}/rest/v1/vacations",
            headers=headers,
            params=params
        )
        res.raise_for_status()
        vacations = res.json()
    except requests.exceptions.RequestException as e:
        print(f"Error fetching my vacation history: {e}")
        return jsonify({'error': 'Failed to fetch vacation history'}), 500
    
    # 'type_kor' 필드를 추가하여 한국어 표기를 프론트엔드로 전달
    for v in vacations:
        v['type_kor'] = v['type'] # 기본값으로 type 필드를 사용
        if v['type'] == 'full_day':
            v['type_kor'] = '종일'
        elif v['type'] == 'half_day_am':
            v['type_kor'] = '반차(오전)'
        elif v['type'] == 'half_day_pm':
            v['type_kor'] = '반차(오후)'
        elif v['type'] == 'quarter_day_am':
            v['type_kor'] = '반반차(오전)'
        elif v['type'] == 'quarter_day_pm':
            v['type_kor'] = '반반차(오후)'
    
    return jsonify(vacations)

# =========================================================
# ✅ [오류 해결을 위한 함수]
# =========================================================

def parse_iso_datetime(iso_string: str) -> datetime:
    """
    Parses an ISO 8601 string into a datetime object.
    It robustly handles various non-standard formats using datetime.strptime().
    - Corrects non-standard timezone offsets ('+HHMM') to '+HH:MM'.
    - Corrects 'Z' to '+00:00'.
    - Normalizes fractional seconds to exactly 6 digits (microseconds).
    """
    
    processed_string = iso_string

    # Step 1: Handle non-standard timezone offsets
    # e.g., '+0000' -> '+00:00'
    tz_match = re.fullmatch(r'(.+)([+-]\d{4})$', processed_string)
    if tz_match:
        naive_part, tz_offset = tz_match.groups()
        processed_string = f"{naive_part}{tz_offset[:3]}:{tz_offset[3:]}"
    
    # e.g., 'Z' -> '+00:00'
    elif processed_string.endswith('Z'):
        processed_string = processed_string[:-1] + '+00:00'

    # Step 2: Normalize fractional seconds to 6 digits (microseconds)
    # This is the key fix for the a ValueError with > 6 fractional digits.
    match = re.search(r'\.(\d+)', processed_string)
    if match:
        fractional_seconds = match.group(1)
        # Truncate to 6 digits if longer, then pad with '0' if shorter.
        # This ensures it's always exactly 6 digits.
        padded_seconds = fractional_seconds[:6].ljust(6, '0')
        # Replace the original fractional seconds with the padded one
        processed_string = processed_string.replace(f".{fractional_seconds}", f".{padded_seconds}")
    
    # Step 3: Final parsing using datetime.strptime()
    try:
        # Format with fractional seconds
        if '.' in processed_string:
            return datetime.strptime(processed_string, '%Y-%m-%dT%H:%M:%S.%f%z')
        # Format without fractional seconds
        else:
            # Timezone offset follows seconds directly
            return datetime.strptime(processed_string, '%Y-%m-%dT%H:%M:%S%z')
    except ValueError as e:
        # Raise an error if parsing ultimately fails
        raise ValueError(f"Invalid isoformat string: '{iso_string}' after correction attempts. Final string: '{processed_string}'")

# =========================================================
# ✅ [새로 추가된 부분] 공지사항 관련 라우트
# =========================================================

# 공지사항 페이지 (직원/관리자 모두 접근 가능)
@app.route('/notices')
def notices_page():
    """
    공지사항 목록 페이지를 렌더링합니다.
    로그인한 사용자만 접근 가능합니다.
    """
    if 'user' not in session:
        flash("로그인이 필요합니다.", "info")
        return redirect(url_for('login'))
        
    return render_template('notices.html', user=session['user'])

@app.route('/api/notices', methods=['GET'])
def get_notices_api():
    if 'user' not in session:
        return jsonify({'error': 'Unauthorized'}), 401

    headers = {
        "apikey":        SUPABASE_KEY,
        "Authorization": f"Bearer {SUPABASE_KEY}"
    }
    params = {
        "select": "id,title,content,created_at,attachments",
        "order":  "created_at.desc"
    }

    try:
        res = requests.get(
            f"{SUPABASE_URL}/rest/v1/notices",
            headers=headers,
            params=params
        )
        res.raise_for_status()
        notices = res.json()
        
        # 날짜 파싱 & 포맷, attachments 분할
        for notice in notices:
            # 1) created_at 처리
            created = notice.get('created_at')
            if created:
                try:
                    dt = isoparse(created)
                    notice['created_at'] = dt
                except (ValueError, TypeError):
                    notice['created_at'] = '날짜 정보 없음'
            # 2) attachments 처리
            atts = notice.get('attachments')
            notice['attachments'] = [a.strip() for a in atts.split(',')] if atts else []

        return jsonify(notices)

    except requests.exceptions.RequestException as e:
        print(f"Error fetching notices: {e}")
        return jsonify({'error': 'Failed to fetch notices'}), 500

# 공지사항 생성 라우트 (관리자만 접근 가능)
@app.route('/admin/notices/create', methods=['GET', 'POST'])
def create_notice():
    """
    공지사항 작성 페이지 및 파일 업로드 처리
    - Supabase Storage (notice-files 버킷)에 파일 업로드
    - DB에는 업로드된 파일의 Public URL 저장
    """
    if 'user' not in session or session['user']['role'] != 'admin':
        flash("공지사항 생성 권한이 없습니다.", "danger")
        return redirect(url_for('login'))

    if request.method == 'POST':
        title = request.form.get('title', '').strip()
        content = request.form.get('content', '').strip()
        attachments = request.files.getlist('attachments')

        uploaded_urls = []
        bucket = supabase.storage.from_("notice-files")

        # ========== 1) 첨부파일 업로드 ==========
        for f in attachments:
            if not f or not f.filename:
                continue

            # 파일 안전한 이름 생성 (타임스탬프_원본파일)
            timestamp = int(time.time())
            safe_name = f"{timestamp}_{f.filename}"

            try:
                # Storage 업로드
                bucket.upload(
                    path=f"notices/{safe_name}",
                    file=f.read(),
                    file_options={"content-type": f.mimetype}
                )

                # Public URL 생성
                public_url = bucket.get_public_url(f"notices/{safe_name}")
                uploaded_urls.append(public_url)

            except Exception as e:
                print(f"[ERROR] 파일 업로드 실패: {e}")
                flash(f"❌ '{f.filename}' 업로드 실패", "danger")

        # URL 콤마로 합치기
        attachments_str = ",".join(uploaded_urls) if uploaded_urls else None

        # ========== 2) 공지사항 DB 저장 ==========
        headers = {
            "apikey": SUPABASE_KEY,
            "Authorization": f"Bearer {SUPABASE_KEY}",
            "Content-Type": "application/json",
            "Prefer": "return=representation"
        }

        data = {
            "title": title,
            "content": content,
            "attachments": attachments_str,
            "user_id": session['user']['id']
        }

        try:
            res = requests.post(
                f"{SUPABASE_URL}/rest/v1/notices",
                headers=headers,
                data=json.dumps(data)
            )
            res.raise_for_status()

            flash("📢 공지사항이 성공적으로 등록되었습니다.", "success")
            return redirect(url_for('manage_notices'))

        except Exception as e:
            print(f"[ERROR] 공지사항 DB 저장 실패: {e}")
            flash("❌ 공지사항 저장 중 오류가 발생했습니다.", "danger")
            return redirect(url_for('create_notice'))

    # ===== GET (폼 렌더링) =====
    return render_template(
        'create_notice.html',
        user=session['user'],
        active='create-notice'
    )
# ✅ 공지사항 상세 정보 JSON 반환 API
@app.route('/api/notices/<int:notice_id>')
def get_notice_detail_api(notice_id):
    if 'user' not in session:
        return jsonify({'error': 'Unauthorized'}), 401

    headers = {
        "apikey": SUPABASE_KEY,
        "Authorization": f"Bearer {SUPABASE_KEY}"
    }

    try:
        res = requests.get(
            f"{SUPABASE_URL}/rest/v1/notices",
            headers=headers,
            params={
                "id": f"eq.{notice_id}",
                "select": "id,title,content,created_at,attachments"
            }
        )
        res.raise_for_status()
        data = res.json()

        if not data:
            return jsonify({'error': '공지사항을 찾을 수 없습니다.'}), 404

        notice = data[0]

        # 날짜 포맷 정리
        if 'created_at' in notice:
            try:
                dt_object = datetime.fromisoformat(notice['created_at'].replace('Z', '+00:00'))
                notice['created_at'] = dt_object.strftime('%Y-%m-%d %H:%M:%S')
            except Exception:
                notice['created_at'] = '날짜 정보 없음'

        # 첨부파일 리스트 처리
        if notice.get('attachments'):
            notice['attachments'] = [a.strip() for a in notice['attachments'].split(',')]
        else:
            notice['attachments'] = []

        return jsonify(notice)

    except requests.exceptions.RequestException as e:
        print(f"[ERROR] 공지 상세 조회 실패: {e}")
        return jsonify({'error': '공지사항 상세 정보를 가져오지 못했습니다.'}), 500
    
@app.route('/manage-notices')
def manage_notices():
    # 1) notices + 작성자 이름(users.name) 조회
    resp = supabase\
        .table('notices')\
        .select('id, title, content, attachments, created_at, users(name)')\
        .order('created_at', desc=True)\
        .execute()
    notices = resp.data or []

    for notice in notices:
        # 2) created_at → 날짜 문자열 "YYYY-MM-DD" 로 변경
        if notice.get('created_at'):
            try:
                dt = isoparse(notice['created_at'])
                notice['created_at'] = dt.date().isoformat()
            except Exception:
                notice['created_at'] = '날짜 정보 없음'
        # 3) attachments 분리
        atts = notice.get('attachments')
        notice['attachments'] = [s.strip() for s in atts.split(',')] if atts else []
        # 4) users(name) → author.name
        user_info = notice.get('users') or {}
        notice['author'] = {'name': user_info.get('name', '관리자')}

    return render_template(
        'manage_notices.html',
        notices=notices,
        active='manage-notices',
        user=session.get('user')
    )


@app.route('/notices/<string:notice_id>/delete', methods=['POST'])
def delete_notice(notice_id):

    try:
        # -------------------------------
        # 1) DB에서 첨부파일 목록 조회
        # -------------------------------
        notice_resp = supabase.table('notices') \
            .select("attachments") \
            .eq("id", notice_id) \
            .single() \
            .execute()

        notice = notice_resp.data
        attachments = notice.get("attachments") if notice else None

        # -------------------------------
        # 2) Storage 실제 파일 목록 조회
        # -------------------------------
        bucket = supabase.storage.from_("notice-files")
        stored_files = bucket.list("notices")   # notices 폴더 목록
        stored_names = {f["name"] for f in stored_files}

        # -------------------------------
        # 3) 삭제 대상 파일 구성
        # -------------------------------
        real_delete = []

        if attachments:
            raw_files = [f.strip() for f in attachments.split(",") if f.strip()]

            for item in raw_files:

                # URL이라면 파일명만 가져오기
                if item.startswith("http"):
                    filename = item.split("/")[-1].split("?")[0]
                else:
                    filename = item.strip()

                # Storage 안에 실제 파일이 존재할 때만 삭제 대상 추가
                if filename in stored_names:
                    real_delete.append(f"notices/{filename}")

        # -------------------------------
        # 4) Storage 파일 삭제 실행
        # -------------------------------
        if real_delete:
            bucket.remove(real_delete)

        # -------------------------------
        # 5) DB에서 공지사항 삭제
        # -------------------------------
        supabase.table("notices").delete().eq("id", notice_id).execute()

        flash("✅ 공지사항 및 첨부파일이 삭제되었습니다.", "success")

    except Exception as e:
        print("[DELETE ERROR]", e)
        flash("❌ 삭제 중 오류가 발생했습니다.", "danger")

    return redirect(url_for('manage_notices'))

@app.route('/notices/<string:notice_id>/edit', methods=['GET', 'POST'])
def edit_notice(notice_id):
    if request.method == 'POST':
        title   = request.form['title']
        content = request.form['content']
        resp = supabase\
            .table('notices')\
            .update({
                'title': title,
                'content': content,
                'updated_at': datetime.utcnow().isoformat()
            })\
            .eq('id', notice_id)\
            .execute()

        status = getattr(resp, 'status_code', None)
        if status == 200:
            flash('✅ 공지사항이 수정되었습니다.', 'success')
        else:
            flash(f'❌ 수정 중 오류가 발생했습니다. (status {status})', 'danger')
        return redirect(url_for('manage_notices'))

    # GET: 기존 데이터 + 작성자 조회
    resp = supabase\
        .table('notices')\
        .select('id, title, content, attachments, created_at, users(name)')\
        .eq('id', notice_id)\
        .single()\
        .execute()
    notice = resp.data or {}

    # created_at → 날짜 문자열
    if notice.get('created_at'):
        try:
            dt = isoparse(notice['created_at'])
            notice['created_at'] = dt.date().isoformat()
        except Exception:
            notice['created_at'] = '날짜 정보 없음'
    # attachments 분리
    atts = notice.get('attachments')
    notice['attachments'] = [s.strip() for s in atts.split(',')] if atts else []
    # users(name) → author.name
    user_info = notice.get('users') or {}
    notice['author'] = {'name': user_info.get('name', '알 수 없음')}

    return render_template(
        'edit_notice.html',
        notice=notice,
        active='manage-notices',
        user=session.get('user')
    )

# ✅ 앱 실행
if __name__ == '__main__':
    app.run(debug=True)