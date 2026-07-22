"""총수익률·연환산수익률 계산 (SSOT).

why_market_page.py와 backtest_page.py가 각자 동일한 CAGR 공식을 중복 구현하고
있던 것을 여기로 통일 — 2026-07-21.
"""


def compute_returns(f_, l_, days):
    """시작가(f_)·종가(l_)·보유일수(days)로 총수익률·연환산수익률(%)을 계산한다.

    시작가가 0 이하이거나 종가가 음수면(데이터 이상치) None을 반환한다 —
    안 그러면 복소수(l_/f_ 음수 밑 + 비정수 지수)나 ZeroDivisionError로
    호출부가 죽는다.
    """
    if f_ is None or l_ is None or f_ <= 0 or l_ < 0 or days <= 0:
        return None
    ratio = l_ / f_
    return {
        "total_ret": round((ratio - 1) * 100, 1),
        "ann_ret":   round((ratio ** (365.0 / days) - 1) * 100, 1),
    }
