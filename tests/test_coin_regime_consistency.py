"""'보유 현황' 액션 문구와 '배분 현황' 리밸런싱 인사이트 문구가 같은 코인에
대해 절대 반대 방향(매수 vs 매도)을 말하지 않는다는 불변조건.

2026-07-22: 사용자가 실제로 "보유현황=매도검토, 리밸런싱=매수우호"가 동시에
뜨는 걸 목격 — 원인은 리밸런싱 인사이트 쪽이 존재하지 않는 regime 값
(distribution/markup/markdown)을 조건으로 걸고 있어서, 실제 regime "top"
(과열)을 못 알아보고 기본(fallback) "매수" 문구로 새던 버그였음. 이 테스트는
그 버그가 다시 생기면 바로 실패하도록 두 함수의 출력을 전 조합에 대해
직접 비교한다.
"""
import sys
from pathlib import Path

sys.path.append(str(Path(__file__).resolve().parent.parent))

import pandas as pd
import pytest

from scripts.crypto_analysis import (
    latest_crypto_signal, coin_holdings_action_text, coin_rebalance_insight,
    coin_holdings_action_with_stoploss, coin_rebalance_insight_with_stoploss,
    COIN_EXIT_GROUPS,
)

REGIMES = ["deep_value", "accumulation", "bull", "top", "unknown"]
RSIS = [10.0, 25.0, 50.0, 80.0]
# (raw_need, diff_pp): 비중 초과(매도 판단 구간) / 비중 부족(매수 판단 구간) / 비중 달성
RAW_CASES = [(-10000, 5.0), (10000, -5.0), (0, 0.0)]


def _is_sell_leaning(text: str) -> bool:
    # "과매도"(oversold)는 "매도"를 부분문자열로 포함하지만 뜻은 반대(매수 우호)라 제외.
    stripped = text.replace("과매도", "")
    return "축소" in stripped or ("매도" in stripped and "보류" not in stripped)


def _is_buy_leaning(text: str) -> bool:
    return "매수" in text and "보류" not in text and "위험" not in text


@pytest.mark.parametrize("regime", REGIMES)
@pytest.mark.parametrize("rsi", RSIS)
@pytest.mark.parametrize("raw_need,diff_pp", RAW_CASES)
def test_holdings_and_rebalance_never_point_opposite_ways(regime, rsi, raw_need, diff_pp):
    sig_df = pd.DataFrame({"rsi14": [rsi], "Close": [100.0]},
                           index=[pd.Timestamp("2026-07-22")])
    action = latest_crypto_signal(sig_df, regime=regime)["action"]

    holdings_text  = coin_holdings_action_text(action, rsi, regime)
    rebalance_text = coin_rebalance_insight(raw_need, regime, rsi, diff_pp)

    holdings_sell, holdings_buy   = _is_sell_leaning(holdings_text), _is_buy_leaning(holdings_text)
    rebalance_sell, rebalance_buy = _is_sell_leaning(rebalance_text), _is_buy_leaning(rebalance_text)

    assert not (holdings_sell and rebalance_buy), (
        f"보유현황=매도인데 리밸런싱=매수로 반대 방향: regime={regime} rsi={rsi} "
        f"raw_need={raw_need}\n  보유현황: {holdings_text}\n  리밸런싱: {rebalance_text}"
    )
    assert not (holdings_buy and rebalance_sell), (
        f"보유현황=매수인데 리밸런싱=매도로 반대 방향: regime={regime} rsi={rsi} "
        f"raw_need={raw_need}\n  보유현황: {holdings_text}\n  리밸런싱: {rebalance_text}"
    )


def test_top_regime_always_sell_leaning_in_holdings():
    """top(과열) regime은 latest_crypto_signal()에서 action='매도'만 나와야 한다
    (base_action 매핑, RSI 오버라이드는 deep_value/accumulation에만 적용)."""
    for rsi in RSIS:
        sig_df = pd.DataFrame({"rsi14": [rsi], "Close": [100.0]},
                               index=[pd.Timestamp("2026-07-22")])
        assert latest_crypto_signal(sig_df, regime="top")["action"] == "매도"


# ── G1·G2 손절 로드맵이 MVRV 신호를 실제로 오버라이드하는지 ─────────────────
# 2026-07-22: rebalancing_page.py의 "보유 현황" 표와 "배분 현황" 인사이트가
# 각자 따로 G1·G2 로드맵 체크를 inline으로 넣다가 두 곳 다 깜빡해서, 이미
# 손절선 훨씬 아래로 물린 코인(예: MVRV 매집구간 + RSI 낮음)에도 여전히
# "매수 우호"가 뜨던 사고가 있었음(portfolio_page.py는 이미 반영 중이라 같은
# 코인에 대해 페이지마다 반대로 말하고 있었음). coin_holdings_action_with_
# stoploss()/coin_rebalance_insight_with_stoploss()로 이 체크를 함수 안에
# 강제해서, 새 호출부가 또 잊어도 자동으로 로드맵이 적용되게 함 — 이 테스트는
# 그 강제 적용이 실제로 동작하는지, 그리고 두 래퍼 함수가 서로 반대 방향을
# 말하지 않는지 고정한다.
G1G2_TICKERS = COIN_EXIT_GROUPS["G1"] + COIN_EXIT_GROUPS["G2"]


@pytest.mark.parametrize("ticker", G1G2_TICKERS)
def test_g1g2_deep_loss_overrides_bullish_regime_to_wait(ticker):
    # MVRV 매집구간(강한 매수 신호)이어도, 개별손실이 손절선(-40%)보다 훨씬
    # 깊으면 두 화면 다 "대기"로 눌러야 한다 — "매수 우호"가 남아있으면 실패.
    holdings_text  = coin_holdings_action_with_stoploss("매수", 20.0, "accumulation", -80.0, ticker)
    rebalance_text = coin_rebalance_insight_with_stoploss(10000, "accumulation", 20.0, -5.0, -80.0, ticker)
    assert "대기" in holdings_text and "매수" not in holdings_text.split("(")[0]
    assert "대기" in rebalance_text and "매수" not in rebalance_text.split("(")[0]


@pytest.mark.parametrize("ticker", G1G2_TICKERS)
def test_g1g2_recovered_into_validated_zone_sells_on_both(ticker):
    # 손절 검증 구간(-40%~-20%) 안으로 회복하면 두 화면 다 "매도 권장"으로
    # 일치해야 한다.
    holdings_text  = coin_holdings_action_with_stoploss("매수", 50.0, "accumulation", -30.0, ticker)
    rebalance_text = coin_rebalance_insight_with_stoploss(10000, "accumulation", 50.0, -5.0, -30.0, ticker)
    assert "매도" in holdings_text
    assert "매도" in rebalance_text


def test_g3_ticker_not_covered_by_stoploss_falls_back_to_regime():
    # G3(BTC 등)는 손절 로드맵 대상이 아니므로, 개별손실이 깊어도 원래 함수
    # (MVRV 기준)로 그대로 폴백해야 한다 — 사용자가 명시적으로 G3 제외를 확인.
    holdings_text = coin_holdings_action_with_stoploss("매수", 60.0, "accumulation", -80.0, "BTC-USD")
    assert holdings_text == coin_holdings_action_text("매수", 60.0, "accumulation")
    assert "대기" not in holdings_text


def test_mild_gain_not_covered_by_stoploss_falls_back_to_regime():
    # 이익 상태(pnl>=0)면 손절 로드맵 자체가 해당 없음 — 원래 함수로 폴백.
    holdings_text = coin_holdings_action_with_stoploss("매수", 40.0, "accumulation", 10.0, "TRUMP-USD")
    assert holdings_text == coin_holdings_action_text("매수", 40.0, "accumulation")
