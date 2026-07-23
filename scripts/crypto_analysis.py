"""
암호화폐 분석 — MVRV Z-Score 중심.

핵심 아이디어:
1. **MVRV Z-Score (BTC)**가 시장 사이클 레짐을 결정 — 모든 코인이 이 레짐을 따라간다고 봄
2. **RSI(14)**는 개별 코인의 과매도만 보정 (과매수 오버라이드는 H20 백테스트에서
   적중률 34~47%로 동전던지기보다 나빠 제거함 — scripts/signal_validation.run_coin_rsi_validation)
3. 시각적으로 50/200일 이동평균선과 BMSB도 표시(참고용)

행동 결정 우선순위:
  1) 개별 코인 RSI ≤ 25 AND 레짐이 deep_value/accumulation  →  매수
  2) 레짐 매핑 그대로
"""
import datetime
import pandas as pd
import ta

from scripts.onchain import REGIME_LABEL_KR

# "코인 정리 로드맵" 그룹 — rebalancing_page.py의 "코인 정리 로드맵" 카드와
# portfolio_page.py의 개별 코인 매도 신호가 같은 그룹 정의를 쓰도록 SSOT화(2026-07-22).
COIN_EXIT_GROUPS = {
    "G1": ["TRUMP-USD", "MASK-USD", "ZETA-USD", "SAND-USD", "ID-USD"],
    "G2": ["GAS-USD", "DOGE-USD", "ETC-USD", "ENS-USD"],
    "G3": ["BTC-USD", "ETH-USD", "SOL-USD"],
}

# G1(소형알트)·G2(중형알트) 개별손실 기반 청산 규칙의 경계값. G3(BTC·ETH·SOL)는
# 핵심 장기보유 자산이라 이 규칙 대상에서 제외(2026-07-22 사용자 확인) — MVRV
# 트리거로만 관리.
#
# -40%는 scripts/backtest.py::backtest_loss_cut()과 같은 방법론(골든크로스 진입
# → 손절선 히트 시 그 이후 가격 변화 관측)을 19개 코인 종목·10,940개 진입
# 케이스에 적용해서 나온 값(2026-07-22 백테스트): -20%~-40%는 손절이 실제로
# 유리했던 비율(better_to_cut)이 70~74%로 탄탄했지만, -60%를 넘어가면 42.9%로
# 동전던지기보다 나빠짐 — 이미 그만큼 빠진 뒤에는 손절이 통계적으로 안 도움된다는
# 뜻. 그래서 "조기 손절선"은 -40%로 두고, 그보다 훨씬 깊이 물린 기존 보유분은
# 즉시 매도 강제 대신 "손절선까지 회복하면 매도(그 전엔 대기)"로 처리.
ALT_STOPLOSS_RECOVERY_PCT = -40.0
ALT_STOPLOSS_DEADLINE = datetime.date(2027, 12, 31)


# 백테스트가 실제로 검증한 손절 구간의 얕은 쪽 경계 — -20% 미만(즉 손실이 이보다
# 얕은)은 애초에 검증 대상이 아니었으므로 이 규칙을 적용하면 안 됨. 독립 감사
# 에이전트가 발견(2026-07-22): 이 하한이 없어서 G1·G2 코인이 -1% 손실만 나도
# "손절선 이내 — 매도 권장"이 뜨는 버그가 있었음(오늘은 보유 코인이 전부 -40%보다
# 훨씬 깊이 물려 있어서 우연히 안 드러났을 뿐).
ALT_STOPLOSS_VALIDATED_FLOOR_PCT = -20.0


def coin_alt_stoploss_status(pnl_pct, today=None):
    """G1·G2 코인의 "손절 구간(-20%~-40%) 진입 시 매도 / 그보다 깊으면 -40% 회복
    또는 2027년 말 데드라인까지 대기" 규칙을 실제로 계산 가능하게 만든 함수
    (2026-07-22, 기존 coin_g1_exit_status에서 G2까지 확장 + 백테스트 기반 -40%로
    조정 + 하한 -20% 추가). 이 규칙은 원래 rebalancing_page.py의 "코인 정리
    로드맵" 카드에 문구로만 있었고 실제 손실%·날짜와 비교해 평가된 적이 없었음
    — 그 사이 portfolio_page.py는 이 규칙과 무관한 자체 "-40% 손실 → 매도검토"를
    써서, 같은 코인에 대해 리밸런싱 인사이트(MVRV 매집구간 → 매수 우호)와
    정반대 방향을 동시에 보여주는 사고로 이어졌음(사용자 실제 목격).

    Returns (status, reason):
      - "sell": 손실이 백테스트 검증 구간(-40%~-20%) 안에 있음 — 지금 매도가
        통계적으로 유리(70~74%). 또는 그보다 깊이 물렸다가 이 구간까지 회복.
        또는 2027년말 데드라인 도달.
      - "wait": -40%보다 깊이 물려서 검증 구간 밖 — 지금 매도는 통계적 이점 없음.
      - None: 손실이 -20%보다 얕음(검증 대상 아님) 또는 데이터 없음.
    """
    if pnl_pct is None or pnl_pct != pnl_pct:  # None 또는 NaN
        return None, ""
    if pnl_pct > ALT_STOPLOSS_VALIDATED_FLOOR_PCT:  # 아직 손절 검증 구간 진입 전
        return None, ""
    if today is None:
        today = datetime.date.today()
    if pnl_pct >= ALT_STOPLOSS_RECOVERY_PCT:
        return "sell", f"손실 {pnl_pct:.1f}%로 손절 검증 구간({ALT_STOPLOSS_RECOVERY_PCT:.0f}%~{ALT_STOPLOSS_VALIDATED_FLOOR_PCT:.0f}%) 안 — 매도 권장 시점"
    if today >= ALT_STOPLOSS_DEADLINE:
        return "sell", "2027년 말 데드라인 도달 — 조건 미충족, 로드맵 기준 전량 매도"
    return "wait", (
        f"손실 {pnl_pct:.1f}% — 손절선({ALT_STOPLOSS_RECOVERY_PCT:.0f}%)을 이미 넘어선 상태. "
        f"지금 추가로 매도해도 백테스트상 이점 없음(-60%대 손절 유리율 42.9%) — "
        f"{ALT_STOPLOSS_RECOVERY_PCT:.0f}% 회복 또는 2027년 말까지 대기"
    )

_REGIME_PHRASE_SUFFIX_KR = {
    "deep_value":   "(역사적 저평가)",
    "accumulation": "구간(저평가)",
    "bull":         " 경계",
    "top":          "구간(비중축소 권고)",
    "unknown":      "",
}
_REGIME_PHRASE_KR = {k: f"{REGIME_LABEL_KR[k]}{v}" for k, v in _REGIME_PHRASE_SUFFIX_KR.items()}


def compute_crypto_indicators(df: pd.DataFrame) -> pd.DataFrame:
    df = df.copy()
    df.rename(columns=lambda c: c.capitalize(), inplace=True)
    if "Close" not in df.columns:
        raise ValueError("Missing Close column")

    df["ma50"] = df["Close"].rolling(50).mean()
    df["ma200"] = df["Close"].rolling(200).mean()
    df["sma20w"] = df["Close"].rolling(140).mean()
    df["ema21w"] = df["Close"].ewm(span=147, adjust=False).mean()
    df["rsi14"] = ta.momentum.RSIIndicator(close=df["Close"], window=14).rsi()
    return df


def generate_crypto_signals(df: pd.DataFrame) -> pd.DataFrame:
    """시각화용 골든/데드 크로스 마킹은 유지(차트에 표시)."""
    df = df.copy()
    above = df["ma50"] > df["ma200"]
    prev_above = above.shift(1)
    df["state"] = "bear"
    df.loc[above, "state"] = "bull"
    df["signal"] = "hold"
    df.loc[above & (~prev_above.fillna(False)), "signal"] = "golden_cross"
    df.loc[(~above) & (prev_above.fillna(False)), "signal"] = "death_cross"
    return df


def latest_crypto_signal(df: pd.DataFrame, regime: str = "unknown") -> dict:
    """
    BTC MVRV 레짐(regime)을 외부에서 주입받아 추천 행동을 결정.
    regime ∈ {deep_value, accumulation, bull, top, unknown} — onchain.classify_regime()
    (백테스트 검증 구간 0/1.5/2.5, coin_mvrv_zones.csv)과 동일 기준.
    """
    if df.empty:
        return {"action": "no_data"}

    last = df.iloc[-1]
    rsi = float(last.get("rsi14", float("nan")))
    is_oversold_extreme = rsi == rsi and rsi <= 25

    base_action = {
        "deep_value": "매수",
        "accumulation": "매수",
        "bull": "보유",
        "top": "매도",
        "unknown": "보유",
    }.get(regime, "보유")

    # 우선순위: 개별 코인의 극단 과매도만 레짐을 오버라이드 (과매수 오버라이드는 역방향 검증되어 제거)
    if is_oversold_extreme and regime in ("deep_value", "accumulation"):
        action = "매수"
    else:
        action = base_action

    return {
        "date": last.name.strftime("%Y-%m-%d"),
        "close": float(last["Close"]),
        "rsi14": None if rsi != rsi else round(rsi, 2),
        "regime": regime,
        "action": action,
    }


def coin_holdings_action_text(action: str, rsi, regime: str) -> str:
    """"보유 현황" 표의 코인 액션 문구. rebalancing_page.py 전용으로 인라인
    정의돼 있던 것을 여기로 옮김(2026-07-22) — coin_rebalance_insight()와
    같은 REGIME_LABEL_KR을 쓰는데도 둘이 따로 떨어져 있으면 다음에 한쪽만
    고치고 잊어버릴 위험이 있어서, 테스트가 두 함수를 같이 임포트해서
    "같은 코인이면 방향이 절대 안 갈린다"를 강제할 수 있도록 한 파일에 둠."""
    phrase = _REGIME_PHRASE_KR.get(regime, str(regime) if regime else "데이터 부족")
    has_rsi = rsi is not None and pd.notna(rsi)
    oversold = has_rsi and rsi <= 25
    rsi_txt = f"RSI {rsi:.0f}" if has_rsi else "RSI 없음"
    if str(action) == "매수":
        if oversold:
            return f"💎 매수 우호 ({phrase} + {rsi_txt} 과매도로 반등여지 확인, H20 검증)"
        return f"💎 매수 우호 ({phrase})"
    if str(action) == "매도":
        return f"🔴 비중 축소 검토 ({phrase} — MVRV 기준 과열)"
    return f"✅ 유지 ({phrase}, {rsi_txt})"


def coin_rebalance_insight(raw_need: float, regime: str, rsi: float, diff_pp: float) -> str:
    """"배분 현황" 리밸런싱 인사이트의 코인 문구. coin_holdings_action_text()와
    짝을 이룸 — regime이 deep_value/accumulation이면 항상 매수 쪽, top이면
    항상 매도 쪽 톤이어야 한다는 게 두 함수가 절대 어겨선 안 되는 불변조건.
    (2026-07-22, tests/test_coin_regime_consistency.py가 이 불변조건을 검증)."""
    regime_kr = REGIME_LABEL_KR.get(regime, "")
    rsi_str = f"RSI {rsi:.0f}"
    b = f"비중 {diff_pp:+.1f}%p 부족"
    o = f"비중 {abs(diff_pp):.1f}%p 초과"
    z = f"비중 달성(차이 {diff_pp:+.1f}%p), 추가금액 없음"
    if raw_need < -5000:
        if regime in ("deep_value", "accumulation"):
            return f"🟡 {regime_kr} 구간({rsi_str}) — 저평가, {o}지만 매도 보류 권장"
        elif regime == "top":
            return f"🔴 {regime_kr} 구간({rsi_str}) — {o}, 익절 매도 고려"
        elif regime == "bull":
            return f"🟢 {regime_kr} 구간({rsi_str}) — {o}, 천천히 축소"
        elif rsi <= 25:
            return f"🟡 과매도({rsi_str}, 51~54%) — {o}지만 저점 매도 위험, 보류"
        else:
            return f"🔵 {regime_kr}({rsi_str}) — {o}, 점진 축소"
    elif raw_need > 5000:
        if regime in ("deep_value", "accumulation") and rsi <= 25:
            return f"🎯 {regime_kr}+과매도({rsi_str}, 51~54%) — 최적 진입 조건. {b} → 적극 매수"
        elif regime in ("deep_value", "accumulation"):
            return f"🟢 {regime_kr} 구간({rsi_str}) — {b} → 분할 매수"
        elif regime == "top":
            return f"🔴 {regime_kr} 구간({rsi_str}) — {b}지만 고점 위험, 보류"
        elif regime == "bull" and rsi <= 25:
            return f"🎯 과매도({rsi_str}, 51~54%) — {b}, 반등 확률 높음 → 매수"
        elif regime == "bull":
            return f"⚠️ {regime_kr} 구간({rsi_str}) — {b}, 소량 분할만"
        elif rsi <= 25:
            return f"🎯 과매도({rsi_str}, 51~54%) — {b}, 반등 확률 높음 → 매수"
        else:
            return f"🔵 {regime_kr}({rsi_str}) — {b} → 매수"
    else:
        if regime in ("deep_value", "accumulation"):
            return f"🟢 {regime_kr} 구간({rsi_str}) — 매수 신호 우호적이나 {z}"
        elif regime == "top":
            return f"🔴 {regime_kr} 구간({rsi_str}) — {z}, 매도 검토"
        elif regime:
            return f"🔵 {regime_kr}({rsi_str}) — {z}"
        return ""


def _g1g2_stoploss_override(ticker: str, pnl_pct) -> str | None:
    """G1·G2(출구 전략 대상 알트) 개별손실 손절 로드맵이 MVRV보다 우선(사용자
    확인)이라는 규칙을 호출부마다 따로 넣다가 두 곳(rebalancing_page.py의
    "보유 현황" 표와 "배분 현황" 인사이트)에서 깜빡해서, 이미 손절선 훨씬
    아래로 물려 로드맵상 "대기"인 코인에도 여전히 "매수 우호"가 뜨던 사고가
    반복됨(2026-07-22, 회의적 재검증에서 발견 — portfolio_page.py는 이미
    반영 중이라 같은 코인에 대해 페이지마다 반대로 말하고 있었음). 아래 두
    래퍼 함수(coin_holdings_action_with_stoploss/coin_rebalance_insight_
    with_stoploss)로 이 체크를 강제해서 새 호출부가 또 잊는 걸 원천 차단.

    Returns 로드맵 문구(str) 또는 None(로드맵 대상 아님 — 호출부가 원래
    함수로 폴백해야 함)."""
    if pnl_pct is None or pnl_pct != pnl_pct or pnl_pct >= 0:
        return None
    if ticker not in COIN_EXIT_GROUPS["G1"] and ticker not in COIN_EXIT_GROUPS["G2"]:
        return None
    status, reason = coin_alt_stoploss_status(pnl_pct)
    if status == "sell":
        return f"🔴 전량 매도 권장 (로드맵) — {reason}"
    if status == "wait":
        return f"🟡 대기 (로드맵 기준) — {reason}"
    return None


def coin_holdings_action_with_stoploss(action: str, rsi, regime: str, pnl_pct, ticker: str) -> str:
    """coin_holdings_action_text()에 G1·G2 손절 로드맵 우선순위를 강제 적용한 버전.
    "보유 현황" 표 등 개별 보유분의 pnl_pct·ticker를 알 수 있는 곳에서는 이걸 쓸 것."""
    return _g1g2_stoploss_override(ticker, pnl_pct) or coin_holdings_action_text(action, rsi, regime)


def coin_rebalance_insight_with_stoploss(
    raw_need: float, regime: str, rsi: float, diff_pp: float, pnl_pct, ticker: str
) -> str:
    """coin_rebalance_insight()에 G1·G2 손절 로드맵 우선순위를 강제 적용한 버전.
    "배분 현황" 인사이트 등 개별 보유분의 pnl_pct·ticker를 알 수 있는 곳에서는 이걸 쓸 것."""
    return (_g1g2_stoploss_override(ticker, pnl_pct)
            or coin_rebalance_insight(raw_need, regime, rsi, diff_pp))
