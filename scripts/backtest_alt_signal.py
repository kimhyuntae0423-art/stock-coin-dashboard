"""알트코인 신호 백테스트 — RSI / 추세(골든·데드크로스) / 52주 고점 대비 낙폭 구간별 90일 수익률 측정.

Usage:
    python scripts/backtest_alt_signal.py
"""
import pandas as pd
import numpy as np
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
RESULTS = ROOT / "results"
TICKERS = ["ETC-USD", "ENS-USD", "BTC-USD"]


def load(ticker: str) -> pd.DataFrame:
    path = RESULTS / f"coin_{ticker}_signals.csv"
    df = pd.read_csv(path, parse_dates=["Date"])
    df = df.sort_values("Date").reset_index(drop=True)
    df["Close"] = pd.to_numeric(df["Close"], errors="coerce")
    df["rsi14"] = pd.to_numeric(df["rsi14"], errors="coerce")
    return df


def add_features(df: pd.DataFrame) -> pd.DataFrame:
    df = df.copy()
    # 미래 수익률 (90일, 180일)
    for days in [30, 90, 180]:
        df[f"fwd_{days}d"] = (df["Close"].shift(-days) / df["Close"] - 1) * 100

    # 52주 고점 대비 낙폭
    df["high_52w"] = df["Close"].rolling(252, min_periods=30).max()
    df["dd_from_high"] = (df["Close"] / df["high_52w"] - 1) * 100

    # 이동평균 기반 추세 (ma50/ma200이 없는 초기 행 제외)
    df["trend"] = df["state"].fillna("bear")
    return df


def stats(series: pd.Series) -> str:
    s = series.dropna()
    if len(s) < 10:
        return f"n={len(s)} (데이터 부족)"
    pos_rate = (s > 0).mean() * 100
    return f"평균 {s.mean():+.1f}%  중간값 {s.median():+.1f}%  승률 {pos_rate:.0f}%  n={len(s)}"


def run_backtest(ticker: str):
    df = load(ticker)
    df = add_features(df)

    print(f"\n{'='*60}")
    print(f"  {ticker}  ({df['Date'].min().date()} ~ {df['Date'].max().date()})")
    print(f"{'='*60}")

    # ── 1. RSI 구간별 90일 수익 ──────────────────────────────────
    print("\n[1] RSI 구간 → 90일 수익률")
    rsi_bins = [(0, 20), (20, 30), (30, 40), (40, 50), (50, 60), (60, 70), (70, 80), (80, 100)]
    for lo, hi in rsi_bins:
        mask = df["rsi14"].between(lo, hi)
        print(f"  RSI {lo:>3}-{hi:<3}: {stats(df.loc[mask, 'fwd_90d'])}")

    # ── 2. 추세(bull/bear) 별 90일 수익 ─────────────────────────
    print("\n[2] 추세 신호 → 90일 수익률")
    for state in ["bull", "bear"]:
        mask = df["trend"] == state
        print(f"  {state:5}: {stats(df.loc[mask, 'fwd_90d'])}")

    # ── 3. 52주 고점 대비 낙폭 구간 → 90일 수익 ─────────────────
    print("\n[3] 52주 고점 대비 낙폭 구간 → 90일 수익률")
    dd_bins = [
        (-100, -80), (-80, -60), (-60, -40),
        (-40, -20), (-20, 0), (0, 20),
    ]
    for lo, hi in dd_bins:
        mask = df["dd_from_high"].between(lo, hi)
        print(f"  {lo:>4}%~{hi:>3}%: {stats(df.loc[mask, 'fwd_90d'])}")

    # ── 4. RSI + 추세 조합 (핵심 신호 후보) ─────────────────────
    print("\n[4] RSI + 추세 조합 → 90일 수익률 (핵심 신호 후보)")
    combos = [
        ("RSI<30 + bull", df["rsi14"] < 30, df["trend"] == "bull"),
        ("RSI<30 + bear", df["rsi14"] < 30, df["trend"] == "bear"),
        ("RSI 30-50 + bull", df["rsi14"].between(30, 50), df["trend"] == "bull"),
        ("RSI 30-50 + bear", df["rsi14"].between(30, 50), df["trend"] == "bear"),
        ("RSI>70 + bull", df["rsi14"] > 70, df["trend"] == "bull"),
        ("RSI>70 + bear", df["rsi14"] > 70, df["trend"] == "bear"),
    ]
    for label, cond1, cond2 in combos:
        mask = cond1 & cond2
        print(f"  {label:<22}: {stats(df.loc[mask, 'fwd_90d'])}")

    print()


def summarize():
    """종합: 신호 기준 추천값 도출."""
    print("\n" + "="*60)
    print("  종합 요약 — 신호 설계 참고")
    print("="*60)
    print("""
▶ 위 결과에서 아래 기준으로 신호 임계값을 정합니다:
  - 90일 승률 70% 이상 + 평균 수익 +20% 이상 → 🟢 보유 양호
  - 90일 승률 50% 미만 + 평균 수익 음수       → 🔴 매도 검토
  - 그 외                                      → 🟠 주의 / 🔵 보유
""")


if __name__ == "__main__":
    for t in TICKERS:
        try:
            run_backtest(t)
        except FileNotFoundError:
            print(f"\n{t}: 파일 없음 — 스킵")
    summarize()
