"""
암호화폐 분석 — MVRV Z-Score 중심.

핵심 아이디어:
1. **MVRV Z-Score (BTC)**가 시장 사이클 레짐을 결정 — 모든 코인이 이 레짐을 따라간다고 봄
2. **RSI(14)**는 개별 코인의 과매수/과매도를 보정
3. 시각적으로 50/200일 이동평균선과 BMSB도 표시(참고용)

행동 결정 우선순위:
  1) 개별 코인 RSI ≥ 80  →  매도 (극단 과열)
  2) 개별 코인 RSI ≤ 25 AND 레짐이 deep_value/accumulation  →  매수
  3) 레짐 매핑 그대로
"""
import pandas as pd
import ta


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
    regime ∈ {deep_value, accumulation, bull, late_bull, top, unknown}
    """
    if df.empty:
        return {"action": "no_data"}

    last = df.iloc[-1]
    rsi = float(last.get("rsi14", float("nan")))
    is_overbought_extreme = rsi == rsi and rsi >= 80
    is_oversold_extreme = rsi == rsi and rsi <= 25

    base_action = {
        "deep_value": "매수",
        "accumulation": "매수",
        "bull": "보유",
        "late_bull": "매도",
        "top": "매도",
        "unknown": "보유",
    }.get(regime, "보유")

    # 우선순위: 개별 코인의 RSI 극단치가 레짐을 오버라이드
    if is_overbought_extreme:
        action = "매도"
    elif is_oversold_extreme and regime in ("deep_value", "accumulation"):
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
