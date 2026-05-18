import pandas as pd
import ta


def compute_indicators(df: pd.DataFrame) -> pd.DataFrame:
    df = df.copy()
    df.rename(columns=lambda c: c.capitalize(), inplace=True)
    # Ensure required columns
    for col in ["Close", "High", "Low", "Volume"]:
        if col not in df.columns:
            raise ValueError(f"Missing column {col}")

    df["ma20"] = df["Close"].rolling(20).mean()
    df["ma50"] = df["Close"].rolling(50).mean()
    df["ma200"] = df["Close"].rolling(200).mean()
    df["momentum20"] = df["Close"].pct_change(20)

    rsi = ta.momentum.RSIIndicator(close=df["Close"], window=14)
    df["rsi14"] = rsi.rsi()

    # MACD (12/26/9) — 추세 + 모멘텀 확인용
    macd = ta.trend.MACD(close=df["Close"], window_slow=26, window_fast=12, window_sign=9)
    df["macd"] = macd.macd()
    df["macd_signal"] = macd.macd_signal()
    df["macd_hist"] = macd.macd_diff()

    # 볼린저밴드 (20, 2σ) — 변동성 / 평균회귀 신호
    bb = ta.volatility.BollingerBands(close=df["Close"], window=20, window_dev=2)
    df["bb_upper"] = bb.bollinger_hband()
    df["bb_middle"] = bb.bollinger_mavg()
    df["bb_lower"] = bb.bollinger_lband()
    df["bb_pct"] = bb.bollinger_pband()    # 0~1, 1=상단터치, 0=하단터치

    # OBV — 거래량 누적 (수급 흐름)
    obv = ta.volume.OnBalanceVolumeIndicator(close=df["Close"], volume=df["Volume"])
    df["obv"] = obv.on_balance_volume()

    return df


if __name__ == "__main__":
    print("This module provides compute_indicators(df)")
