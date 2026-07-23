"""coin_alt_stoploss_status()의 '손절선(-40%) 이내 회복 / 2027년 말 데드라인' 규칙.

2026-07-22: portfolio_page.py가 이 규칙과 무관한 자체 "-40% 손실 → 매도검토"를
써서 리밸런싱 인사이트(MVRV 매집구간 → 매수 우호)와 반대 방향을 동시에
보여준 사고가 있었음 — 이 테스트는 실제 로드맵 규칙의 경계 동작을 고정한다.

-40%는 scripts/backtest.py::backtest_loss_cut()과 같은 방법론을 19개 코인
종목·10,940개 진입 케이스에 적용한 백테스트 근거(better_to_cut 70.2%)로
정함(기존 -60%는 임의값이었음, G1만 적용하던 것도 G2까지 확장).
"""
import sys
import datetime
from pathlib import Path

sys.path.append(str(Path(__file__).resolve().parent.parent))
from scripts.crypto_analysis import (
    coin_alt_stoploss_status, ALT_STOPLOSS_RECOVERY_PCT, ALT_STOPLOSS_DEADLINE,
)


def test_none_pnl_returns_no_status():
    assert coin_alt_stoploss_status(None) == (None, "")


def test_nan_pnl_returns_no_status():
    assert coin_alt_stoploss_status(float("nan")) == (None, "")


def test_deep_loss_before_deadline_waits():
    status, reason = coin_alt_stoploss_status(-80.0, today=datetime.date(2026, 7, 22))
    assert status == "wait"
    assert "80.0" in reason


def test_recovered_to_threshold_sells():
    status, _ = coin_alt_stoploss_status(ALT_STOPLOSS_RECOVERY_PCT, today=datetime.date(2026, 7, 22))
    assert status == "sell"


def test_recovered_past_threshold_sells():
    status, _ = coin_alt_stoploss_status(-20.0, today=datetime.date(2026, 7, 22))
    assert status == "sell"


def test_mild_loss_still_worse_than_threshold_waits():
    # -45%는 -40%(손절선)보다 더 나쁜 손실이므로 아직 회복 전 — 대기
    status, _ = coin_alt_stoploss_status(-45.0, today=datetime.date(2026, 7, 22))
    assert status == "wait"


def test_still_deep_loss_but_past_deadline_sells():
    status, reason = coin_alt_stoploss_status(-80.0, today=ALT_STOPLOSS_DEADLINE)
    assert status == "sell"
    assert "데드라인" in reason


def test_deep_loss_day_before_deadline_still_waits():
    day_before = ALT_STOPLOSS_DEADLINE - datetime.timedelta(days=1)
    status, _ = coin_alt_stoploss_status(-80.0, today=day_before)
    assert status == "wait"
