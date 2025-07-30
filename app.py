import os
from utils import calculate_leave
from dotenv import load_dotenv
from flask import Flask, render_template, request, redirect, session, url_for, flash
from dateutil.relativedelta import relativedelta
from flask import jsonify
from datetime import datetime, timedelta
from collections import defaultdict
import io
import pandas as pd
from flask import send_file
import requests
import pytz

load_dotenv()

app = Flask(__name__)
app.secret_key = os.getenv("SECRET_KEY")  # 로그인 세션용
print("SECRET_KEY from .env:", os.getenv("SECRET_KEY"))

# Supabase 정보 입력
SUPABASE_URL = os.getenv("SUPABASE_URL")
SUPABASE_KEY = os.getenv("SUPABASE_KEY")

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
                return redirect('/employee')
        else:
            return render_template('login.html', error="❌ 로그인 실패. 다시 확인해주세요.")
    return render_template('login.html')

@app.route('/logout', methods=['GET', 'POST']) # Allow both GET and POST for convenience, but POST is preferred
def logout():
    # Only remove the 'user' key from the session, leaving other session data (like flash messages) intact.
    session.pop('user', None) 
    flash('로그아웃되었습니다.', 'info') # Set the flash message
    return redirect('/login')

# ✅ 공용캘린더
@app.route('/calendar')
def calendar():
    if 'user' not in session:
        return redirect('/login')
    return render_template('calendar.html')

# attendance 라우트 (출퇴근 기록 처리)
@app.route('/attendance', methods=['POST'])
def attendance():
    user = session.get('user')
    if not user:
        flash("로그인이 필요합니다.", "danger")
        return redirect(url_for('login'))

    user_id = user['id']
    record_type = request.form.get('type') # '출근' 또는 '퇴근'
    now = datetime.now()
    today_date_str = now.strftime('%Y-%m-%d')
    current_time_str = now.strftime('%H:%M:%S')

    headers = {
        "apikey": SUPABASE_KEY,
        "Authorization": f"Bearer {SUPABASE_KEY}",
        "Content-Type": "application/json"
    }

    try:
        existing_attendance_params = {
            "user_id": f"eq.{user_id}",
            "date": f"eq.{today_date_str}"
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
                flash("이미 출근 처리되었습니다.", "info")
            else:
                if current_day_attendance:
                    data_to_update = {'check_in_time': current_time_str}
                    res = requests.patch(
                        f"{SUPABASE_URL}/rest/v1/attendances?id=eq.{current_day_attendance['id']}",
                        headers=headers,
                        json=data_to_update
                    )
                    # ⭐ 출근 업데이트 성공 조건에 204 추가 ⭐
                    if res.status_code == 200 or res.status_code == 204:
                        flash(f"출근 처리되었습니다: {now.strftime('%H:%M')}", "success")
                    else:
                        raise Exception(f"출근 기록 업데이트 실패: {res.status_code} - {res.text}")
                else:
                    data_to_send = {
                        'user_id': user_id,
                        'date': today_date_str,
                        'check_in_time': current_time_str,
                        'check_out_time': None
                    }
                    res = requests.post(
                        f"{SUPABASE_URL}/rest/v1/attendances",
                        headers=headers,
                        json=data_to_send
                    )
                    if res.status_code == 201:
                        flash(f"출근 처리되었습니다: {now.strftime('%H:%M')}", "success")
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
                    # ⭐ 퇴근 업데이트 성공 조건에 204 추가 ⭐
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
        print(f"근태 처리 중 오류가 발생했습니다: {e}") # "danger" 문자열은 print 인수로 부적절하여 제거
        import traceback
        traceback.print_exc()
        flash("근태 처리 중 알 수 없는 오류가 발생했습니다.", "danger") # 사용자에게 표시될 메시지

    return redirect(url_for('employee_dashboard'))


# ✅ 직원용 대시보드
@app.route('/employee')
def employee_dashboard():
    if 'user' not in session or session['user']['role'] != 'employee':
        flash("직원 대시보드 접근 권한이 없습니다.", "danger")
        return redirect(url_for('login'))

    user_id = session['user']['id']

    headers = {
        "apikey": SUPABASE_KEY,
        "Authorization": f"Bearer {SUPABASE_KEY}"
    }

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

    return render_template(
        'employee_dashboard.html',
        user=session['user'],
        vacations=vacations,
        yearly_leave=yearly_leave,
        monthly_leave=monthly_leave,
        remaining_total=remaining_total,
        pending_count=pending_count,
        approved_count=approved_count,
        rejected_count=rejected_count,
        current_check_in_time=current_check_in_time,
        current_check_out_time=current_check_out_time,
        attendance_events=attendance_events # 이 리스트를 템플릿으로 전달
    )

# ✅ 관리자용 대시보드
@app.route('/admin')
def admin_dashboard():
    if 'user' not in session or session['user']['role'] != 'admin':
        flash("관리자 대시보드 접근 권한이 없습니다.", "danger") # 플래시 메시지 추가
        return redirect(url_for('login')) # url_for 사용

    user = session['user'] # 현재 로그인한 관리자 정보

    headers = {
        "apikey": SUPABASE_KEY,
        "Authorization": f"Bearer {SUPABASE_KEY}",
        "Content-Type": "application/json" # Content-Type 헤더 추가 (POST/PATCH에 필요하지만 GET에도 일관성 유지)
    }

    # 1. 모든 사용자 정보 가져오기 (이름 매핑용)
    users_res = requests.get(
        f"{SUPABASE_URL}/rest/v1/users?select=id,name,join_date,role", # role도 함께 가져옴
        headers=headers
    )
    all_users = users_res.json() if users_res.status_code == 200 else []
    user_names = {u['id']: u['name'] for u in all_users} # user_id: name 딕셔너리 생성


    # ✅ 휴가 신청 내역 조회 (deduct_from_type 컬럼도 함께 가져옴)
    params = {
        "select": "id,start_date,end_date,type,status,user_id,users(name),deduct_from_type",
        "order": "start_date.desc"
    }

    res = requests.get(f"{SUPABASE_URL}/rest/v1/vacations", headers=headers, params=params)
    vacations = res.json() if res.status_code == 200 else []

    for v in vacations:
        v["name"] = v["users"]["name"] if "users" in v else "Unknown"

    # ✅ 직원별 휴가 통계 계산
    user_res = requests.get(f"{SUPABASE_URL}/rest/v1/users?select=id,name,join_date, role", headers=headers)
    users = user_res.json() if user_res.status_code == 200 else []

    user_stats = defaultdict(dict)
    today = datetime.today().date()

    for u in users:
        if u.get("role") == "admin":
            continue  # ✅ 관리자 제외

        uid = u["id"]
        name = u["name"]
        join_date_str = u.get("join_date")

        if not join_date_str:
            continue  # join_date 없는 경우 건너뜀

        auto_yearly, auto_monthly = calculate_leave(join_date_str)

        # deduct_from_type 컬럼도 함께 가져옴
        vac_res = requests.get(
        f"{SUPABASE_URL}/rest/v1/vacations?user_id=eq.{uid}&status=eq.approved&select=type,used_days,deduct_from_type",
        headers=headers
        )
        vacs = vac_res.json() if vac_res.status_code == 200 else []

        # ✅ 사용된 연차/월차 계산 (deduct_from_type에 따라 분기)
        used_yearly = 0.0
        used_monthly = 0.0

        for v in vacs:
            try:
                used_days_val = float(v.get("used_days", 0))
            except (ValueError, TypeError):
                used_days_val = 0.0 # 유효하지 않은 값 처리

            # 휴가 타입과 deduct_from_type에 따라 사용 일수 합산
            if v.get("type") == "연차":
                used_yearly += used_days_val
            elif v.get("type") == "월차":
                used_monthly += used_days_val
            elif v.get("type") in ["반차-오전", "반차-오후", "반반차-오전", "반반차-오후"]:
                # deduct_from_type에 따라 연차 또는 월차에 합산
                if v.get("deduct_from_type") == "yearly":
                    used_yearly += used_days_val
                elif v.get("deduct_from_type") == "monthly":
                    used_monthly += used_days_val
                else:
                    # deduct_from_type이 없는 기존 데이터나 잘못된 데이터 처리 (정책 결정 필요)
                    # 예를 들어, 기본적으로 연차에서 차감되었다고 가정하거나, 로그를 남길 수 있습니다.
                    used_yearly += used_days_val # 기본값으로 연차에 합산
            
        used_yearly = round(used_yearly, 2)
        used_monthly = round(used_monthly, 2)

        user_stats[uid] = {
            "name": name,
            "auto_yearly": auto_yearly,
            "auto_monthly": auto_monthly,
            "used_yearly": used_yearly,
            "used_monthly": used_monthly,
            "remain_yearly": max(auto_yearly - used_yearly, 0),
            "remain_monthly": max(auto_monthly - used_monthly, 0)
        }

    # ✅ 결재할 휴가 / 완료된 휴가 건수 계산
    pending_count = sum(1 for v in vacations if v['status'] == 'pending')
    completed_count = sum(1 for v in vacations if v['status'] in ['approved', 'rejected'])

    # ⭐ 4. 전체 직원 근무 기록 조회 및 계산 로직 (새로 추가) ⭐
    all_attendance_records = []
    try:
        # 모든 직원의 근태 기록을 가져옵니다.
        # 필요시 날짜 범위 제한 (예: 최근 30일)
        thirty_days_ago = (datetime.now() - timedelta(days=30)).date()
        all_attendance_params = {
            "date": f"gte.{thirty_days_ago.isoformat()}", # 최근 30일 기록
            "order": "date.desc,check_in_time.desc" # 날짜 역순, 같은 날은 출근시간 역순 정렬
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
                
                # 직원 이름 추가
                record_user_id = record.get('user_id')
                employee_name = user_names.get(record_user_id, "알 수 없는 직원")

                check_in_display = 'N/A'
                check_out_display = 'N/A'
                work_duration = '-'

                dt_in_combined = None
                dt_out_combined = None

                # 출근 시간 파싱
                if check_in_time_raw and record_date_str:
                    try:
                        dt_in_combined = datetime.strptime(f"{record_date_str} {check_in_time_raw}", '%Y-%m-%d %H:%M:%S')
                        check_in_display = check_in_time_raw[:5] # HH:MM
                    except ValueError:
                        print(f"관리자 근태: 출근 시간 또는 날짜 파싱 오류: 날짜={record_date_str}, 시간={check_in_time_raw}")

                # 퇴근 시간 파싱
                if check_out_time_raw and record_date_str:
                    try:
                        dt_out_combined = datetime.strptime(f"{record_date_str} {check_out_time_raw}", '%Y-%m-%d %H:%M:%S')
                        check_out_display = check_out_time_raw[:5] # HH:MM
                    except ValueError:
                        print(f"관리자 근태: 퇴근 시간 또는 날짜 파싱 오류: 날짜={record_date_str}, 시간={check_out_time_raw}")

                # 근무 시간 계산
                if dt_in_combined and dt_out_combined:
                    # 퇴근 시간이 출근 시간보다 빠를 경우 (예: 자정 넘어 근무)
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

                all_attendance_records.append({
                    'employee_name': employee_name,
                    'date': record_date_str,
                    'check_in': check_in_display,
                    'check_out': check_out_display,
                    'work_duration': work_duration,
                    'user_id': record_user_id
                })
        else:
            print(f"관리자 근태 기록 조회 실패: {all_attendance_res.status_code} - {all_attendance_res.text}")

    except Exception as e:
        print(f"관리자 근태 기록 처리 중 오류 발생: {e}")
        import traceback
        traceback.print_exc()

    # ✅ 최종 템플릿 렌더링
    return render_template(
        "admin_dashboard.html",
        user=session['user'],
        vacations=vacations,
        user_stats=user_stats.values(),
        pending_count=pending_count,
        completed_count=completed_count,
        all_attendance_records=all_attendance_records,
        all_users=all_users
    )

@app.route("/monthly-stats")
def monthly_stats():
    if 'user' not in session or session['user']['role'] != 'admin':
        return redirect('/login')

    headers = {
        "apikey": SUPABASE_KEY,
        "Authorization": f"Bearer {SUPABASE_KEY}"
    }

    # 승인된 휴가 전체 조회 (user 이름 포함)
    res = requests.get(
        f"{SUPABASE_URL}/rest/v1/vacations?status=eq.approved&select=id,start_date,end_date,used_days,type,user_id,users(name)",
        headers=headers
    )
    vacations = res.json() if res.status_code == 200 else []

    from collections import defaultdict
    from dateutil.parser import parse

    # 👉 월별 휴가 사용 일수 집계 {유저명: {yyyy-mm: 총 사용일수}}
    monthly_stats = defaultdict(lambda: defaultdict(float))

    for v in vacations:
        user = v.get("users", {}).get("name", "Unknown")

        try:
            start_date = parse(v["start_date"])
            used_days = float(v.get("used_days", 0))
        except Exception:
            continue  # 파싱 오류 시 건너뜀

        # 시작월을 기준으로 집계
        month_key = start_date.strftime("%Y-%m")
        monthly_stats[user][month_key] += used_days

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

    from collections import defaultdict
    from dateutil.parser import parse
    import io
    import pandas as pd

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

        remain_yearly = max(total_yearly - used_yearly, 0)
        remain_monthly = max(total_monthly - used_monthly, 0)

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
    # 관리자 권한 확인 (필요하다면)
    if 'user' not in session or session['user']['role'] != 'admin':
        flash("엑셀 다운로드 권한이 없습니다.", "danger")
        return redirect(url_for('login'))

    headers = {
        "apikey": SUPABASE_KEY,
        "Authorization": f"Bearer {SUPABASE_KEY}"
    }

    # 필터링할 user_id를 쿼리 파라미터에서 가져옵니다.
    # HTML에서 `downloadAttendanceBtn.href`를 업데이트하므로, 여기에 반영됩니다.
    filter_user_id = request.args.get('user_id')

    # 모든 사용자 정보를 가져와 이름 매핑용으로 사용
    users_res = requests.get(
        f"{SUPABASE_URL}/rest/v1/users?select=id,name",
        headers=headers
    )
    user_names = {u['id']: u['name'] for u in users_res.json()} if users_res.status_code == 200 else {}

    # Supabase에서 근태 기록 가져오기
    # 필터링된 user_id가 있다면 해당 유저의 기록만 가져오고, 'all'이면 모든 기록을 가져옵니다.
    attendance_params = {
        "order": "date.desc,check_in_time.desc"
    }
    if filter_user_id and filter_user_id != 'all':
        attendance_params["user_id"] = f"eq.{filter_user_id}"
    
    # 모든 기간의 기록을 다운로드하는 것이 일반적이지만, 필요하면 날짜 범위 제한을 추가할 수 있습니다.
    # thirty_days_ago = (datetime.now() - timedelta(days=30)).date()
    # attendance_params["date"] = f"gte.{thirty_days_ago.isoformat()}"

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
                    print(f"Excel 다운로드: 출근 시간 또는 날짜 파싱 오류: 날짜={record_date_str}, 시간={check_in_time_raw}")

            if check_out_time_raw and record_date_str:
                try:
                    dt_out_combined = datetime.strptime(f"{record_date_str} {check_out_time_raw}", '%Y-%m-%d %H:%M:%S')
                    check_out_display = check_out_time_raw[:5]
                except ValueError:
                    print(f"Excel 다운로드: 퇴근 시간 또는 날짜 파싱 오류: 날짜={record_date_str}, 시간={check_out_time_raw}")

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

    # Pandas DataFrame 생성
    df = pd.DataFrame(records_for_excel)

    # Excel 파일 생성 (메모리 내에서)
    output = io.BytesIO()
    writer = pd.ExcelWriter(output, engine='xlsxwriter')
    df.to_excel(writer, index=False, sheet_name='근무기록')
    writer.close() # writer.save() 대신 writer.close() 사용 (pandas 1.x 이상)
    output.seek(0) # 파일 포인터를 처음으로 이동

    # 파일 전송
    filename = f"근무기록_{datetime.now().strftime('%Y%m%d_%H%M%S')}.xlsx"
    return send_file(output, 
                     mimetype='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
                     as_attachment=True, 
                     download_name=filename)


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

    return render_template("manage_users.html", users=users)

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

# ✅ 휴가 신청 처리
from datetime import datetime, timedelta

@app.route('/request-vacation', methods=['POST'])
def request_vacation():
    if 'user' not in session:
        flash("⛔ 사용자 정보를 불러오지 못했습니다. 다시 로그인해 주세요.", "danger")
        return redirect('/login')

    user_id = session['user']['id']
    start_date_str = request.form['start_date']
    end_date_str = request.form['end_date']

    # New: 폼에서 'base_leave_type'과 'leave_granularity_type' 값을 가져옵니다.
    base_leave_type_str = request.form['base_leave_type'] # 예: 'yearly', 'monthly'
    leave_granularity_type = request.form['leave_granularity_type'] # 예: 'full_day', 'half_day_am'

    print(f"DEBUG: base_leave_type: {base_leave_type_str}, granularity_type: {leave_granularity_type}")

    try:
        start_date = datetime.strptime(start_date_str, "%Y-%m-%d").date()
        end_date = datetime.strptime(end_date_str, "%Y-%m-%d").date()
    except ValueError:
        flash("❌ 날짜 형식이 잘못되었습니다.", "danger")
        return redirect('/employee')

    if start_date > end_date:
        flash("❌ 시작일은 종료일보다 빠를 수 없습니다.", "warning")
        return redirect('/employee')

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
            return redirect('/employee')

    # 사용 일수 계산 및 Supabase에 저장할 'type'과 'deduct_from_type' 결정
    used_days = 0.0
    type_to_save_in_supabase = "" # Supabase 'type' 컬럼에 저장될 값 (예: "종일", "반차-오전")
    deduct_from_type_to_save = "" # Supabase 'deduct_from_type' 컬럼에 저장될 값 (예: "yearly", "monthly")

    # base_leave_type에 따라 deduct_from_type_to_save를 설정
    if base_leave_type_str == 'yearly':
        deduct_from_type_to_save = "yearly"
    elif base_leave_type_str == 'monthly':
        deduct_from_type_to_save = "monthly"
    else:
        flash("❌ 유효한 휴가 유형(연차/월차)을 선택해 주세요.", "danger")
        return redirect('/employee')

    # leave_granularity_type에 따라 used_days와 type_to_save_in_supabase를 설정
    if leave_granularity_type == 'full_day':
        used_days = (end_date - start_date).days + 1
        type_to_save_in_supabase = "종일" # 또는 "연차" / "월차"로 저장해도 됩니다.
        if used_days <= 0:
            flash("❌ 종일 휴가는 최소 하루 이상이어야 합니다.", "danger")
            return redirect('/employee')
    elif leave_granularity_type == 'half_day_am':
        used_days = 0.5
        type_to_save_in_supabase = "반차-오전"
        if start_date != end_date:
            flash("❌ 반차는 하루만 선택할 수 있습니다.", "danger")
            return redirect('/employee')
    elif leave_granularity_type == 'half_day_pm':
        used_days = 0.5
        type_to_save_in_supabase = "반차-오후"
        if start_date != end_date:
            flash("❌ 반차는 하루만 선택할 수 있습니다.", "danger")
            return redirect('/employee')
    elif leave_granularity_type == 'quarter_day_am':
        used_days = 0.25
        type_to_save_in_supabase = "반반차-오전"
        if start_date != end_date:
            flash("❌ 반반차는 하루만 선택할 수 있습니다.", "danger")
            return redirect('/employee')
    elif leave_granularity_type == 'quarter_day_pm':
        used_days = 0.25
        type_to_save_in_supabase = "반반차-오후"
        if start_date != end_date:
            flash("❌ 반반차는 하루만 선택할 수 있습니다.", "danger")
            return redirect('/employee')
    else:
        flash("❌ 유효한 휴가 종류(종일/반차/반반차)를 선택해 주세요.", "danger")
        return redirect('/employee')

    # 사용자 정보 및 총 잔여 휴가 계산 (기존과 동일)
    res_user = requests.get(f"{SUPABASE_URL}/rest/v1/users?id=eq.{user_id}", headers=headers)
    if res_user.status_code != 200 or not res_user.json():
        flash("❌ 사용자 정보를 불러올 수 없습니다.", "danger")
        return redirect('/employee')

    user = res_user.json()[0]
    auto_yearly_leave, auto_monthly_leave = calculate_leave(user.get("join_date"))

    # 현재 사용된 휴가 계산 (Supabase 기록에서 deduct_from_type을 활용)
    # 기존 데이터와의 호환성을 위해 v.get("deduct_from_type")을 사용합니다.
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
        
        # 'deduct_from_type' 컬럼의 값을 기준으로 차감합니다.
        # 기존 데이터에 'deduct_from_type'이 없는 경우를 위한 폴백 로직이 필요합니다.
        deduction_source = v.get("deduct_from_type") 

        if deduction_source == "yearly":
            current_used_yearly += val
        elif deduction_source == "monthly":
            current_used_monthly += val
        else:
            # 이 부분은 'deduct_from_type'이 없는 (레거시) 데이터 처리 방식입니다.
            # 당신의 과거 데이터가 어떻게 휴가 유형을 저장했는지에 따라 이 로직을 조정해야 합니다.
            # 예: 만약 'type'이 "연차"이거나 "반차", "반반차"였다면 연차로 간주
            if v.get("type") == "연차" or v.get("type", "").startswith(("반차", "반반차")): 
                current_used_yearly += val
            elif v.get("type") == "월차":
                current_used_monthly += val

    remaining_monthly = max(auto_monthly_leave - current_used_monthly, 0)
    remaining_yearly = max(auto_yearly_leave - current_used_yearly, 0)

    # 잔여 휴가 확인
    sufficient_leave = True
    if deduct_from_type_to_save == "monthly" and remaining_monthly < used_days:
        flash(f"❌ 월차가 부족합니다. 현재 잔여: {remaining_monthly}일", "warning")
        sufficient_leave = False
    elif deduct_from_type_to_save == "yearly" and remaining_yearly < used_days:
        flash(f"❌ 연차가 부족합니다. 현재 잔여: {remaining_yearly}일", "warning")
        sufficient_leave = False

    if not sufficient_leave:
        return redirect('/employee')

    # Supabase에 휴가 신청 데이터 저장
    headers["Content-Type"] = "application/json"
    data = {
        "user_id": user_id,
        "type": type_to_save_in_supabase, # 이제는 세부 종류 (예: "종일", "반차-오전")가 저장됩니다.
        "start_date": start_date_str,
        "end_date": end_date_str,
        "used_days": used_days,
        "status": "pending",
        "deduct_from_type": deduct_from_type_to_save # "yearly" 또는 "monthly"가 명확히 저장됩니다.
    }

    res_post = requests.post(f"{SUPABASE_URL}/rest/v1/vacations", headers=headers, json=data)
    if res_post.status_code == 201:
        flash("✅ 휴가 신청이 완료되었습니다.", "success")
        return redirect('/employee')
    else:
        flash("❌ 신청 실패: 관리자에게 문의해 주세요.", "danger")
        print(f"Supabase Post Error: {res_post.status_code}, {res_post.text}")
        return redirect('/employee')

# ✅ 캘린더용 이벤트 데이터 JSON API
@app.route('/vacation-events')
def vacation_events():
    if 'user' not in session:
        return redirect('/login')

    headers = {
        "apikey": SUPABASE_KEY,
        "Authorization": f"Bearer {SUPABASE_KEY}"
    }

    # 🔹 사용자 이름 포함, 승인된 휴가만 가져오기
    params = {
        "select": "start_date,end_date,type,users(name)",
        "status": "eq.approved"
    }

    res = requests.get(f"{SUPABASE_URL}/rest/v1/vacations", headers=headers, params=params)
    vacations = res.json() if res.status_code == 200 else []

    # 🔹 휴가 타입에 따라 className 지정
    type_to_class = {
        "연차": "vacation-annual",
        "월차": "vacation-monthly",
        "반차-오전": "vacation-half-am",
        "반차-오후": "vacation-half-pm",
        "반반차-오전": "vacation-quarter-am",
        "반반차-오후": "vacation-quarter-pm"
    }

    events = []
    for v in vacations:
        name = v['users']['name'] if "users" in v and v['users'] else "Unknown"
        class_name = type_to_class.get(v['type'], "vacation-default")

        events.append({
            "title": f"[{v['type']}] {name}",
            "start": v['start_date'],
            "end": (datetime.strptime(v['end_date'], "%Y-%m-%d") + timedelta(days=1)).strftime("%Y-%m-%d"),
            "className": class_name
        })

    return jsonify(events)

# ✅ 앱 실행
if __name__ == '__main__':
    app.run(debug=True)