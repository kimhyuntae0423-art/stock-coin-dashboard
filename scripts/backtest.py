"""
신호 백테스트 엔진.

1. 골든크로스/데스크로스 적중률 — 신호 후 1M/3M/6M 수익률
2. RSI 임계값 신호 적중률 — RSI 70/80 과매수, RSI 30 과매도 후 가격 방향
3. 손절선 검증 — 골든크로스 진입 후 -8%/-20% 손절 vs 보유 중 어느 쪽이 나은가
"""

from pathlib import Path
import pandas as pd
import numpy as np

RESULTS_DIR = Path(__file__).resolve().parent.parent / "results"
BACKTEST_DIR = RESULTS_DIR / "backtest"


# ─────────────────────────────────────────────
# 공통 유틸
# ─────────────────────────────────────────────

def _load(path: Path) -> pd.DataFrame:
    df = pd.read_csv(path, parse_dates=["Date"])
    df = df.set_index("Date").sort_index()
    return df


def _derive_crosses(df: pd.DataFrame) -> pd.DataFrame:
    """
    저장된 CSV의 signal 컬럼은 bull 상태 전체가 golden_cross로 오기록된 구버전이 있음.
    state 컬럼 전환점에서 직접 골든/데스크로스를 재도출해 signal 컬럼을 덮어쓴다.
    """
    df = df.copy()
    if "state" not in df.columns:
        return df
    state = df["state"]
    prev  = state.shift(1)
    df["signal"] = "hold"
    df.loc[(state == "bull") & (prev == "bear"), "signal"] = "golden_cross"
    df.loc[(state == "bear") & (prev == "bull"), "signal"] = "death_cross"
    # 첫 행은 이전 상태 불명 → hold
    df.iloc[0, df.columns.get_loc("signal")] = "hold"
    return df


def _fwd_return(df: pd.DataFrame, date, days: int) -> float | None:
    future = df[df.index > date]["Close"]
    if len(future) < days:
        return None
    exit_price = float(future.iloc[days - 1])
    entry_price = float(df.loc[date, "Close"])
    return round((exit_price / entry_price - 1) * 100, 2)


# ─────────────────────────────────────────────
# 1. 골든크로스 / 데스크로스
# ─────────────────────────────────────────────

def backtest_crosses(df: pd.DataFrame, ticker: str) -> list[dict]:
    rows = []
    signals = df[df["signal"].isin(["golden_cross", "death_cross"])]

    for date, row in signals.iterrows():
        sig = row["signal"]
        entry = float(row["Close"])
        r22 = _fwd_return(df, date, 22)
        r66 = _fwd_return(df, date, 66)
        r132 = _fwd_return(df, date, 132)

        # 기대 방향: 골든=상승(+), 데스=하락(-)
        expected_sign = 1 if sig == "golden_cross" else -1
        rows.append({
            "ticker": ticker,
            "signal": sig,
            "date": date.strftime("%Y-%m-%d"),
            "entry_price": round(entry, 4),
            "fwd_1M": r22,
            "fwd_3M": r66,
            "fwd_6M": r132,
            # 적중 여부 (기대 방향과 실제 방향 일치)
            "hit_1M": bool(r22 is not None and r22 * expected_sign > 0),
            "hit_3M": bool(r66 is not None and r66 * expected_sign > 0),
            "hit_6M": bool(r132 is not None and r132 * expected_sign > 0),
        })
    return rows


# ─────────────────────────────────────────────
# 2. RSI 임계값 신호
# ─────────────────────────────────────────────

def _rsi_crossings(df: pd.DataFrame, level: float, direction: str) -> pd.Index:
    rsi = df["rsi14"].dropna()
    if direction == "above":
        mask = (rsi >= level) & (rsi.shift(1) < level)
    else:
        mask = (rsi <= level) & (rsi.shift(1) > level)
    return df.index[mask.reindex(df.index, fill_value=False)]


def backtest_rsi(df: pd.DataFrame, ticker: str) -> list[dict]:
    rows = []
    configs = [
        (70, "above", "RSI 70 돌파(과매수)", -1),   # 오른 뒤 조정 기대 → 하락이 적중
        (80, "above", "RSI 80 돌파(극단 과매수)", -1),
        (30, "below", "RSI 30 이탈(과매도)", +1),   # 빠진 뒤 반등 기대 → 상승이 적중
    ]
    for level, direction, label, expected_sign in configs:
        for date in _rsi_crossings(df, level, direction):
            if date not in df.index:
                continue
            rsi_val = df.loc[date, "rsi14"]
            r5  = _fwd_return(df, date, 5)
            r10 = _fwd_return(df, date, 10)
            r22 = _fwd_return(df, date, 22)
            rows.append({
                "ticker": ticker,
                "signal": label,
                "date": date.strftime("%Y-%m-%d"),
                "rsi": round(float(rsi_val), 1),
                "fwd_5d": r5,
                "fwd_10d": r10,
                "fwd_22d": r22,
                "hit_5d":  bool(r5  is not None and r5  * expected_sign > 0),
                "hit_10d": bool(r10 is not None and r10 * expected_sign > 0),
                "hit_22d": bool(r22 is not None and r22 * expected_sign > 0),
            })
    return rows


# ─────────────────────────────────────────────
# 3. 손절선 검증
# ─────────────────────────────────────────────

def backtest_loss_cut(df: pd.DataFrame, ticker: str, cuts=(-8, -20)) -> list[dict]:
    """
    골든크로스에서 진입 → 데스크로스(또는 데이터 끝)에서 청산.
    -8% / -20% 손절선이 실제로 추가 손실을 막았는지 검증.

    post_cut_return > 0  → 손절 후 가격 회복  → 손절이 불필요했음 (조기 청산 손해)
    post_cut_return < 0  → 손절 후 가격 추가 하락 → 손절이 옳았음 (추가 손실 방지)
    better_to_cut = True → 손절했을 때 최종 수익률이 더 좋음
    """
    rows = []
    golden_dates = df[df["signal"] == "golden_cross"].index
    death_dates  = df[df["signal"] == "death_cross"].index

    for entry_date in golden_dates:
        entry_price = float(df.loc[entry_date, "Close"])

        # 다음 데스크로스가 청산 시점
        later_deaths = death_dates[death_dates > entry_date]
        exit_date = later_deaths[0] if len(later_deaths) > 0 else df.index[-1]
        exit_price = float(df.loc[exit_date, "Close"])
        hold_return = round((exit_price / entry_price - 1) * 100, 2)
        hold_days = (exit_date - entry_date).days

        holding = df[(df.index > entry_date) & (df.index <= exit_date)]["Close"]

        row = {
            "ticker": ticker,
            "entry_date": entry_date.strftime("%Y-%m-%d"),
            "exit_date": exit_date.strftime("%Y-%m-%d"),
            "hold_days": hold_days,
            "hold_return_pct": hold_return,
        }

        for cut in cuts:
            cut_price = entry_price * (1 + cut / 100)
            hit_date = None
            for d, p in holding.items():
                if float(p) <= cut_price:
                    hit_date = d
                    break

            key = f"cut_{abs(cut)}pct"
            if hit_date is not None:
                # 손절 후 청산일까지 가격 변화
                after = df[(df.index > hit_date) & (df.index <= exit_date)]["Close"]
                if not after.empty:
                    post_cut = round((float(after.iloc[-1]) / cut_price - 1) * 100, 2)
                else:
                    post_cut = 0.0
                # 손절 시 총 수익률 = cut% (고정)
                # 보유 시 총 수익률 = hold_return
                better = cut > hold_return  # 손절 수익률 > 보유 수익률
                row.update({
                    f"{key}_hit": True,
                    f"{key}_hit_date": hit_date.strftime("%Y-%m-%d"),
                    f"{key}_post_cut_return": post_cut,
                    f"{key}_better_to_cut": better,
                })
            else:
                row.update({
                    f"{key}_hit": False,
                    f"{key}_hit_date": None,
                    f"{key}_post_cut_return": None,
                    f"{key}_better_to_cut": None,
                })

        rows.append(row)
    return rows


# ─────────────────────────────────────────────
# 전체 실행
# ─────────────────────────────────────────────

def run_all():
    BACKTEST_DIR.mkdir(exist_ok=True)

    stock_files = [f for f in RESULTS_DIR.glob("*_signals.csv")
                   if not f.name.startswith("coin_")]
    coin_files  = list(RESULTS_DIR.glob("coin_*_signals.csv"))

    all_crosses   = []
    all_rsi       = []
    all_loss_cut  = []

    def _ticker_from(path: Path, is_coin: bool) -> str:
        name = path.stem  # e.g. "005930.KS_signals" or "coin_BTC-USD_signals"
        name = name.replace("_signals", "")
        if is_coin:
            name = name.replace("coin_", "")
        return name

    for files, is_coin in [(stock_files, False), (coin_files, True)]:
        for f in files:
            ticker = _ticker_from(f, is_coin)
            try:
                df = _load(f)
                df = _derive_crosses(df)   # state 컬럼에서 정확한 크로스 재도출
                if "signal" not in df.columns:
                    continue
                all_crosses.extend(backtest_crosses(df, ticker))
                if "rsi14" in df.columns:
                    all_rsi.extend(backtest_rsi(df, ticker))
                all_loss_cut.extend(backtest_loss_cut(df, ticker))
            except Exception as e:
                print(f"[SKIP] {ticker}: {e}")

    pd.DataFrame(all_crosses).to_csv(BACKTEST_DIR / "cross_signals.csv",    index=False)
    pd.DataFrame(all_rsi).to_csv(   BACKTEST_DIR / "rsi_signals.csv",       index=False)
    pd.DataFrame(all_loss_cut).to_csv(BACKTEST_DIR / "loss_cut.csv",        index=False)
    print(f"백테스트 완료 → {BACKTEST_DIR}")


if __name__ == "__main__":
    run_all()
