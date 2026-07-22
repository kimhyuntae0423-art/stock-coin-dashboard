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
