import sys
from pathlib import Path

sys.path.append(str(Path(__file__).resolve().parent.parent))
from scripts.returns import compute_returns


def test_basic_calculation():
    # 100 -> 200, 365일: 총수익률 100%, 연환산도 100%(딱 1년이므로 동일)
    r = compute_returns(100.0, 200.0, 365)
    assert r["total_ret"] == 100.0
    assert r["ann_ret"] == 100.0


def test_annualization_shrinks_short_period_gain():
    # 100 -> 140, 90일 보유 -> 총수익률 40%, 연환산은 이보다 훨씬 큼(복리 효과)
    r = compute_returns(100.0, 140.0, 90)
    assert r["total_ret"] == 40.0
    assert r["ann_ret"] > r["total_ret"]


def test_loss_case():
    r = compute_returns(100.0, 50.0, 365)
    assert r["total_ret"] == -50.0
    assert r["ann_ret"] == -50.0


def test_zero_start_price_returns_none_not_crash():
    # f_=0이면 ZeroDivisionError 대신 None을 반환해야 한다 (2026-07-21 리뷰에서 발견된 크래시)
    assert compute_returns(0.0, 100.0, 365) is None


def test_negative_start_price_returns_none():
    assert compute_returns(-10.0, 100.0, 365) is None


def test_negative_end_price_returns_none_not_complex():
    # l_<0이면 (l_/f_)가 음수가 되어 비정수 지수에서 복소수가 나오고
    # round()가 TypeError를 던진다 (2026-07-21 리뷰에서 발견된 크래시) — 가드로 차단.
    assert compute_returns(100.0, -10.0, 365) is None


def test_zero_days_returns_none():
    assert compute_returns(100.0, 110.0, 0) is None


def test_none_inputs_return_none():
    assert compute_returns(None, 100.0, 365) is None
    assert compute_returns(100.0, None, 365) is None
