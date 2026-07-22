"""coin_g1_exit_status()의 '-60% 이내 회복 / 2027년 말 데드라인' 로드맵 규칙.

2026-07-22: portfolio_page.py가 이 규칙과 무관한 자체 "-40% 손실 → 매도검토"를
써서 리밸런싱 인사이트(MVRV 매집구간 → 매수 우호)와 반대 방향을 동시에
보여준 사고가 있었음 — 이 테스트는 실제 로드맵 규칙의 경계 동작을 고정한다.
"""
import sys
import datetime
from pathlib import Path

sys.path.append(str(Path(__file__).resolve().parent.parent))
from scripts.crypto_analysis import coin_g1_exit_status, G1_LOSS_RECOVERY_PCT, G1_DEADLINE


def test_none_pnl_returns_no_status():
    assert coin_g1_exit_status(None) == (None, "")


def test_nan_pnl_returns_no_status():
    assert coin_g1_exit_status(float("nan")) == (None, "")


def test_deep_loss_before_deadline_waits():
    status, reason = coin_g1_exit_status(-80.0, today=datetime.date(2026, 7, 22))
    assert status == "wait"
    assert "80.0" in reason


def test_recovered_to_threshold_sells():
    status, _ = coin_g1_exit_status(G1_LOSS_RECOVERY_PCT, today=datetime.date(2026, 7, 22))
    assert status == "sell"


def test_recovered_past_threshold_sells():
    status, _ = coin_g1_exit_status(-40.0, today=datetime.date(2026, 7, 22))
    assert status == "sell"


def test_still_deep_loss_but_past_deadline_sells():
    status, reason = coin_g1_exit_status(-80.0, today=G1_DEADLINE)
    assert status == "sell"
    assert "데드라인" in reason


def test_deep_loss_day_before_deadline_still_waits():
    day_before = G1_DEADLINE - datetime.timedelta(days=1)
    status, _ = coin_g1_exit_status(-80.0, today=day_before)
    assert status == "wait"
