"""scripts/check_alerts.py의 코인 손익 신호 — 카카오 알림 파이프라인.

2026-07-22 실사용 중 발견된 두 버그:
1. sig_row["close"](USD)와 row["buy_price"](KRW)를 환율 변환 없이 나눠서
   보유 코인 전부가 -100%에 가까운 손익으로 계산되던 버그.
2. "-40% 손실 → severity 2(매도 검토)"가 백테스트 검증도 없고 코인 정리
   로드맵과도 무관해서, MVRV 매집구간이라 다른 화면은 전부 "매수 우호"인데
   카카오 알림만 "🔴 매도 검토"를 보내던 사고.
이 테스트는 두 버그가 다시 생기면 바로 실패하도록 고정한다.
"""
import sys
from pathlib import Path

sys.path.append(str(Path(__file__).resolve().parent.parent))
sys.path.append(str(Path(__file__).resolve().parent.parent / "scripts"))

from scripts.check_alerts import severity_for_holding

USDKRW = 1380.0


def _row(buy_price):
    # G1/G2/G3 어디에도 안 속한 코인 — 이 테스트는 환율 변환 자체만 검증하는
    # 것이라, 손절 로드맵(G1·G2)의 "깊이 물리면 severity 0(대기)" 분기에
    # 걸리지 않는 티커를 씀.
    return {"buy_price": buy_price, "ticker": "ADA-USD"}


def test_currency_conversion_not_flat_minus_100():
    """USD 종가 * 환율로 변환해야 정상적인 손익이 나온다(변환 안 하면 -100%에 가까운 값)."""
    buy_price_krw = 25_631.0   # 실제 holdings.csv 예시(1개당 KRW)
    close_usd = 7.0            # 실제 coin_summary.csv 종가(USD)
    sig_row = {"close": close_usd}
    severity, reasons = severity_for_holding(
        _row(buy_price_krw), sig_row, mvrv_z=0.42, is_coin=True, bb=None, usdkrw=USDKRW,
    )
    # 변환하면 손익 -62% 근방 — -100%에 근접하지 않아야 한다
    assert reasons, "손실이 -20%를 넘으므로 사유가 있어야 함"
    assert "-100" not in reasons[0]


def test_g1_ticker_deep_loss_not_flagged_sell_when_roadmap_says_wait():
    """G1(TRUMP 등) 코인은 손절선(-40%)보다 훨씬 깊이 물려 있으면
    severity 0(알림 없음) — 검증 안 된 규칙으로 '매도 검토' 내면 안 됨."""
    row = {"buy_price": 12_629.0, "ticker": "TRUMP-USD"}
    sig_row = {"close": 1.6}  # 실제 데이터 기준 손실 -80%대
    severity, reasons = severity_for_holding(
        row, sig_row, mvrv_z=0.42, is_coin=True, bb=None, usdkrw=USDKRW,
    )
    assert severity == 0
    assert reasons == []


def test_g1_ticker_sells_when_recovered_to_threshold():
    """G1 코인이 손절선(-40%) 이내로 회복하면 severity 2로 매도 신호를 내야 한다."""
    row = {"buy_price": 100_000.0, "ticker": "TRUMP-USD"}
    # 손익 -35% (환율 반영 후, 손절선 -40%보다 나은 상태) 나오도록 close 역산
    close_usd = (100_000.0 * 0.65) / USDKRW
    sig_row = {"close": close_usd}
    severity, reasons = severity_for_holding(
        row, sig_row, mvrv_z=0.42, is_coin=True, bb=None, usdkrw=USDKRW,
    )
    assert severity == 2
    assert "회복" in reasons[0] or "매도" in reasons[0]


def test_g2_ticker_also_uses_roadmap_not_flagged_sell_when_deep():
    """G2(ETC 등)도 이제 같은 손절선 로드맵을 쓴다 — 깊이 물려 있으면 severity 0."""
    row = {"buy_price": 25_631.0, "ticker": "ETC-USD"}
    sig_row = {"close": 7.0}  # 실제 데이터 기준 손실 -60%대
    severity, reasons = severity_for_holding(
        row, sig_row, mvrv_z=0.42, is_coin=True, bb=None, usdkrw=USDKRW,
    )
    assert severity == 0
    assert reasons == []


def test_g3_alt_deep_loss_downgraded_to_caution_not_sell():
    """G3(BTC·ETH·SOL, 핵심 장기보유)는 손절선 로드맵 대상이 아니라서, 개별
    손실이 커도 severity 1(주의)이지 severity 2(매도 검토)를 내면 안 된다
    — MVRV가 매수 우호일 때 정반대 신호가 동시에 뜨는 사고를 막기 위함."""
    row = {"buy_price": 4_111_452.0, "ticker": "ETH-USD"}
    sig_row = {"close": 1_920.0}  # 실제 데이터 기준 손실 -35%대
    severity, reasons = severity_for_holding(
        row, sig_row, mvrv_z=0.42, is_coin=True, bb=None, usdkrw=USDKRW,
    )
    assert severity == 1
    assert "매도 검토" not in reasons[0]  # "매도 근거로 검증되지 않음"은 sell 지시가 아니라 허용


def test_btc_severity_uses_mvrv_only_not_pnl():
    row = {"buy_price": 133_952_455.0, "ticker": "BTC-USD"}
    sig_row = {"close": 65_972.0}
    severity, reasons = severity_for_holding(
        row, sig_row, mvrv_z=0.42, is_coin=True, is_etf=False, bb=None, usdkrw=USDKRW,
    )
    assert severity == 0  # accumulation 구간(0~1.5)이라 알림 없음
    assert reasons == []
