# utils.py

from datetime import datetime
from dateutil.relativedelta import relativedelta

def calculate_leave(join_date_str: str) -> tuple:
    """
    입사일을 기반으로 연차/월차 자동 계산
    :param join_date_str: YYYY-MM-DD 형식의 문자열
    :return: (yearly_leave: float, monthly_leave: float)
    """
    try:
        today = datetime.today().date()
        join_date = datetime.strptime(join_date_str, "%Y-%m-%d").date()
        months = relativedelta(today, join_date).years * 12 + relativedelta(today, join_date).months

        yearly = 15 if months >= 12 else 0
        monthly = 0 if months >= 12 else min(months, 11)
        return yearly, monthly
    except Exception:
        return 0, 0