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

    return df


if __name__ == "__main__":
    print("This module provides compute_indicators(df)")
