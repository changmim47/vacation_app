from datetime import datetime
from dateutil.relativedelta import relativedelta
import pytz # pytz 임포트 추가

def calculate_leave(join_date_str: str) -> tuple:
    """
    입사일을 기반으로 연차/월차 자동 계산
    :param join_date_str: YYYY-MM-DD 형식의 문자열
    :return: (yearly_leave: float, monthly_leave: float)
    """
    try:
        # KST (한국 표준시) 시간대를 명시적으로 지정하여 오늘 날짜를 가져옵니다.
        kst_timezone = pytz.timezone('Asia/Seoul')
        today = datetime.now(kst_timezone).date() # <-- 이 줄을 변경합니다.
        
        join_date = datetime.strptime(join_date_str, "%Y-%m-%d").date()
        months = relativedelta(today, join_date).years * 12 + relativedelta(today, join_date).months

        yearly = 15 if months >= 12 else 0
        monthly = 0 if months >= 12 else min(months, 11)
        return yearly, monthly
    except Exception as e:
        print(f"Error in calculate_leave: {e}") # 오류 로깅 추가
        return 0, 0