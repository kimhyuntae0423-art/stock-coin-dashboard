"""
시계열 기반 팩터 계산 — 일별 OHLCV에서 추출.

- 12-1 모멘텀(Jegadeesh-Titman): 13개월 전 → 1개월 전 가격 수익률.
  최근 1개월을 제외하여 단기 평균회귀 노이즈를 제거.
  미국 시장 50년 백테스트에서 단순 12M 수익률 대비 일관된 우위.

- 52주 고가 근접도(George-Hwang 2004): 현재가 / 최근 252거래일 최고가.
  1에 가까울수록 신고가 근접 → 강세 지속 확률 ↑.

두 팩터 모두 fundamentals 데이터에 의존하지 않아 모든 종목에 적용 가능.
"""
from __future__ import annotations
from pathlib import Path
import numpy as np
import pandas as pd

RESULTS = Path(__file__).resolve().parent.parent / "results"

# 거래일 기준 (한 달 ≈ 21일, 1년 ≈ 252일)
_TRADING_DAYS_1M = 21
_TRADING_DAYS_12M = 252
_TRADING_DAYS_13M = 273  # 21 * 13


def _load_signals(ticker: str) -> pd.DataFrame | None:
    f = RESULTS / f"{ticker}_signals.csv"
    if not f.exists() or f.stat().st_size < 100:
        return None
    df = pd.read_csv(f)
    if "Close" not in df.columns or "High" not in df.columns:
        return None
    df = df.dropna(subset=["Close"]).reset_index(drop=True)
    return df


def momentum_12_1(ticker: str) -> float | None:
    """12-1 모멘텀: 1개월 전 종가 / 13개월 전 종가 - 1 (단위: %)."""
    df = _load_signals(ticker)
    if df is None or len(df) < _TRADING_DAYS_13M + 1:
        return None
    close = df["Close"].astype(float)
    end_idx = len(close) - 1 - _TRADING_DAYS_1M
    start_idx = len(close) - 1 - _TRADING_DAYS_13M
    if start_idx < 0 or end_idx < 0:
        return None
    end_px = close.iloc[end_idx]
    start_px = close.iloc[start_idx]
    if start_px <= 0:
        return None
    return float((end_px / start_px - 1.0) * 100.0)


def high_52w_ratio(ticker: str) -> float | None:
    """52주 고가 근접도: 현재 종가 / 최근 252거래일 최고가 (0~1)."""
    df = _load_signals(ticker)
    if df is None or len(df) < 30:
        return None
    last_close = float(df["Close"].iloc[-1])
    window = df["High"].astype(float).iloc[-_TRADING_DAYS_12M:]
    high_52w = float(window.max())
    if high_52w <= 0:
        return None
    return last_close / high_52w


def annualized_vol(ticker: str, window: int = 63) -> float | None:
    """연환산 변동성: 최근 `window`거래일 일별 로그수익률 표준편차 × √252.

    63일 ≈ 3개월. 너무 짧으면 노이즈, 너무 길면 최근 위험 반영 부족.
    Risk Parity / Inverse Vol weighting에 표준 사용.
    """
    df = _load_signals(ticker)
    if df is None or len(df) < window + 1:
        return None
    close = pd.to_numeric(df["Close"], errors="coerce").dropna()
    if len(close) < window + 1:
        return None
    log_ret = (close / close.shift(1)).apply(lambda x: None if x is None or x <= 0 else x)
    log_ret = pd.Series([float(np.log(v)) for v in log_ret.tail(window) if v is not None and v > 0])
    if len(log_ret) < 2:
        return None
    sd = float(log_ret.std(ddof=1))
    return sd * (252 ** 0.5)


def enrich_price_factors(stocks_df: pd.DataFrame) -> pd.DataFrame:
    """ticker 컬럼이 있는 DataFrame에 mom_12_1, high52_ratio, ann_vol 컬럼 추가."""
    out = stocks_df.copy()
    out["mom_12_1"] = out["ticker"].apply(momentum_12_1)
    out["high52_ratio"] = out["ticker"].apply(high_52w_ratio)
    out["ann_vol"] = out["ticker"].apply(annualized_vol)
    return out
