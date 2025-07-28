import os
from utils import calculate_leave
from dotenv import load_dotenv
from flask import Flask, render_template, request, redirect, session
from dateutil.relativedelta import relativedelta
from flask import jsonify
from datetime import datetime, timedelta
from collections import defaultdict
import io
import pandas as pd
from flask import send_file
import requests
from flask import request, session, redirect, flash

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

@app.route('/logout')
def logout():
    session.clear()
    return redirect('/login')

# ✅ 공용캘린더
@app.route('/calendar')
def calendar():
    if 'user' not in session:
        return redirect('/login')
    return render_template('calendar.html')

# ✅ 직원용 대시보드
@app.route('/employee')
def employee_dashboard():
    if 'user' not in session or session['user']['role'] != 'employee':
        return redirect('/login')

    user_id = session['user']['id']

    headers = {
        "apikey": SUPABASE_KEY,
        "Authorization": f"Bearer {SUPABASE_KEY}"
    }

    # ✅ 사용자 정보 가져오기
    user_res = requests.get(
        f"{SUPABASE_URL}/rest/v1/users?id=eq.{user_id}&select=name,color_code,join_date,yearly_leave,monthly_leave",
        headers=headers
    )

    if user_res.status_code != 200 or len(user_res.json()) == 0:
        return "❌ 사용자 정보 조회 실패"

    user_info = user_res.json()[0]
    join_date_str = user_info.get("join_date")
    yearly_leave = float(user_info.get("yearly_leave", 0))
    monthly_leave = float(user_info.get("monthly_leave", 0))

    # ✅ 연차/월차 자동 계산
    today = datetime.today().date()
    yearly_leave, monthly_leave = calculate_leave(join_date_str)

    # ✅ 휴가 목록 가져오기
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

    # ✅ 사용한 일수 및 상태 한글 매핑
    used_days = sum(v["used_days"] for v in vacations if v["status"] == "approved")
    remaining_total = yearly_leave + monthly_leave - used_days

    status_map = {
        "pending": "대기중",
        "approved": "승인됨",
        "rejected": "반려됨"
    }

    for v in vacations:
        v["status_kor"] = status_map.get(v["status"], "알 수 없음")
        v["name"] = session['user']['name']  # 직원 이름 추가

    # ✅ 상태별 건수 계산
    all_count = len(vacations)
    pending_count = sum(1 for v in vacations if v["status"] == "pending")
    approved_count = sum(1 for v in vacations if v["status"] == "approved")
    rejected_count = sum(1 for v in vacations if v["status"] == "rejected")

    # ✅ 템플릿 렌더링
    return render_template(
        'employee_dashboard.html',
        user=session['user'],
        vacations=vacations,
        yearly_leave=yearly_leave,
        monthly_leave=monthly_leave,
        remaining_total=remaining_total,
        all_count=all_count,
        pending_count=pending_count,
        approved_count=approved_count,
        rejected_count=rejected_count
    )

# ✅ 관리자용 대시보드
@app.route('/admin')
def admin_dashboard():
    if 'user' not in session or session['user']['role'] != 'admin':
        return redirect('/login')

    headers = {
        "apikey": SUPABASE_KEY,
        "Authorization": f"Bearer {SUPABASE_KEY}"
    }

    # ✅ 휴가 신청 내역 조회
    params = {
        "select": "id,start_date,end_date,type,status,user_id,users(name)",
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

        vac_res = requests.get(
        f"{SUPABASE_URL}/rest/v1/vacations?user_id=eq.{uid}&status=eq.approved",
        headers=headers
        )
        vacs = vac_res.json() if vac_res.status_code == 200 else []

        # ✅ 반차, 반반차 포함하여 연차 사용일 계산
        used_yearly = round(
        sum(float(v["used_days"]) for v in vacs 
        if v["type"] and v["type"].startswith(("연차", "반차", "반반차"))
        ),
        2
        )
        used_monthly = round(
        sum(float(v["used_days"]) for v in vacs 
        if v["type"] and v["type"].startswith("월차")
        ),
        2
        )

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

    # ✅ 최종 템플릿 렌더링
    return render_template(
        "admin_dashboard.html",
        user=session['user'],
        vacations=vacations,
        user_stats=user_stats.values(),
        pending_count=pending_count,
        completed_count=completed_count
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
        total_yearly, total_monthly = calculate_leave(u["join_date"])

        vac_res = requests.get(
            f"{SUPABASE_URL}/rest/v1/vacations?user_id=eq.{uid}&status=eq.approved",
            headers=headers
        )
        vacs = vac_res.json() if vac_res.status_code == 200 else []

        # ✅ 반차/반반차 포함 연차 계산
        used_yearly = round(
            sum(float(v["used_days"]) for v in vacs
                if v.get("type", "").startswith("연차")
                or v.get("type", "").startswith("반차")
                or v.get("type", "").startswith("반반차")),
            2
        )

        # ✅ 월차 계산
        used_monthly = round(
            sum(float(v["used_days"]) for v in vacs
                if v.get("type") == "월차"),
            2
        )

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
    vacation_type = request.form['type']
    start_date_str = request.form['start_date']
    end_date_str = request.form['end_date']

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

    # ✅ 중복 휴가 검사
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

    # ✅ 사용 일수 계산
    if vacation_type in ['연차', '월차']:
        used_days = (end_date - start_date).days + 1
    elif vacation_type in ['반차-오전', '반차-오후']:
        used_days = 0.5
        if start_date != end_date:
            flash("❌ 반차는 하루만 선택할 수 있습니다.", "danger")
            return redirect('/employee')
    elif vacation_type in ['반반차-오전', '반반차-오후']:
        used_days = 0.25
        if start_date != end_date:
            flash("❌ 반반차는 하루만 선택할 수 있습니다.", "danger")
            return redirect('/employee')
    else:
        flash("❌ 휴가 종류를 선택해 주세요.", "danger")
        return redirect('/employee')

    # ✅ 사용자 정보 확인
    res_user = requests.get(f"{SUPABASE_URL}/rest/v1/users?id=eq.{user_id}", headers=headers)
    if res_user.status_code != 200 or not res_user.json():
        flash("❌ 사용자 정보를 불러올 수 없습니다.", "danger")
        return redirect('/employee')

    user = res_user.json()[0]
    auto_yearly_leave, auto_monthly_leave = calculate_leave(user.get("join_date"))

    # ✅ 사용된 휴가 계산
    res_vac = requests.get(
        f"{SUPABASE_URL}/rest/v1/vacations?user_id=eq.{user_id}&status=eq.approved",
        headers=headers
    )
    used_vac = res_vac.json() if res_vac.status_code == 200 else []
    used_monthly = sum(float(v["used_days"]) for v in used_vac if v["type"] == "월차")
    used_yearly = sum(float(v["used_days"]) for v in used_vac if v["type"] == "연차")

    remaining_monthly = max(auto_monthly_leave - used_monthly, 0)
    remaining_yearly = max(auto_yearly_leave - used_yearly, 0)

    if vacation_type == "월차" and remaining_monthly < used_days:
        flash(f"❌ 월차가 부족합니다. 현재 잔여: {remaining_monthly}일", "warning")
        return redirect('/employee')
    elif vacation_type == "연차" and remaining_yearly < used_days:
        flash(f"❌ 연차가 부족합니다. 현재 잔여: {remaining_yearly}일", "warning")
        return redirect('/employee')

    # ✅ 신청 저장
    headers["Content-Type"] = "application/json"
    data = {
        "user_id": user_id,
        "type": vacation_type,
        "start_date": start_date_str,
        "end_date": end_date_str,
        "used_days": used_days,
        "status": "pending"
    }

    res_post = requests.post(f"{SUPABASE_URL}/rest/v1/vacations", headers=headers, json=data)
    if res_post.status_code == 201:
        flash("✅ 휴가 신청이 완료되었습니다.", "success")  # ✅ 성공 메시지
        return redirect('/employee')
    else:
        flash("❌ 신청 실패: 관리자에게 문의해 주세요.", "danger")  # ✅ 실패 메시지
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