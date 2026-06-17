import pandas as pd
from pathlib import Path

RESULTS = Path("results")
for ticker in ["ETC-USD", "ENS-USD"]:
    df = pd.read_csv(RESULTS / f"coin_{ticker}_signals.csv", parse_dates=["Date"])
    df = df.sort_values("Date")
    df["high_52w"] = df["Close"].rolling(252, min_periods=30).max()
    last = df.iloc[-1]
    dd = (last["Close"] / last["high_52w"] - 1) * 100
    print(f"{ticker}: 현재 ${last['Close']:.2f}  52주고점 ${last['high_52w']:.2f}  낙폭 {dd:.1f}%  RSI {last['rsi14']:.1f}  추세 {last['state']}")
