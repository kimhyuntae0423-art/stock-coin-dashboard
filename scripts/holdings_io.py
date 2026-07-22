"""보유 내역 편집기의 매수일(buy_date) 파싱/저장 (SSOT).

portfolio_page.py와 rebalancing_page.py가 각자 독립 구현하다가 둘 다 같은
버그(매수일 컬럼 누락 → 저장 시 전체 삭제)를 만들었던 부분 — 2026-07-21.
"""
import pandas as pd


def parse_buy_dates(series: pd.Series) -> pd.Series:
    """CSV의 문자열(빈 값 포함) buy_date를 data_editor용 date 객체로 변환."""
    return pd.to_datetime(series, errors="coerce").dt.date


def format_buy_dates(series: pd.Series) -> pd.Series:
    """data_editor에서 편집된 date/NaT를 저장용 "YYYY-MM-DD" 문자열로 변환."""
    return series.apply(lambda d: d.strftime("%Y-%m-%d") if pd.notna(d) else "")
