"""
코어 ETF 로테이션 전략 백테스트.

run()           : US ETF 5년 백테스트 (금리 급등 보정 포함)
run_ai_compare(): 466950.KS vs 469170.KS AI 슬롯 비교 (2023.10~)
"""
from __future__ import annotations
from pathlib import Path

import numpy as np
import pandas as pd

from scripts.etf_rotation import CORE_ROLES, _phase_blend, get_phase, PHASE_LABELS

_RES      = Path(__file__).resolve().parents[1] / "results"
_GUIDE_US = [r["us"] for r in CORE_ROLES if r["guide"]]  # VOO SCHD SOXX TLT GLD


def _load_close(ticker: str) -> pd.Series:
    p = _RES / f"{ticker}_signals.csv"
    if not p.exists():
        return pd.Series(name=ticker, dtype=float)
    df = pd.read_csv(p, index_col=0, parse_dates=True).sort_index()
    col = "Close" if "Close" in df.columns else "close"
    return df[col].rename(ticker) if col in df.columns else pd.Series(name=ticker, dtype=float)


def _weights(vix: float, tlt_1m: float = 0, ai_ticker: str = "SOXX") -> dict[str, float]:
    """
    5 guide ETF 비중 계산. ai_ticker로 SOXX 슬롯 교체 가능.
    금리 급등 보정(tlt_1m) 포함.
    """
    blend    = _phase_blend(vix)
    rate_sev = min(max((-tlt_1m - 3) / 7, 0.0), 1.0) if tlt_1m < -3 else 0.0

    guide_roles = [r for r in CORE_ROLES if r["guide"]]
    raw = {}
    for r in guide_roles:
        w = sum(pw * r["weights"].get(p, 0) for p, pw in blend.items())
        if rate_sev > 0:
            if r["us"] == "TLT":
                w *= (1 - 0.40 * rate_sev)
            elif r["us"] == "GLD":
                w *= (1 + 0.50 * rate_sev)
        # AI 슬롯 교체 (SOXX → ai_ticker)
        key = ai_ticker if r["us"] == "SOXX" else r["us"]
        raw[key] = w

    total = sum(raw.values())
    return {t: w / total for t, w in raw.items()}


def _run_core(prices: pd.DataFrame, vix: pd.Series, label: str,
              ai_ticker: str = "SOXX") -> pd.Series:
    """포트폴리오 equity curve 반환."""
    etf_cols = [ai_ticker if t == "SOXX" else t for t in _GUIDE_US]
    # TLT 1개월 수익률 (rolling 22일)
    tlt_col = "TLT" if "TLT" in prices.columns else None
    tlt_ret = prices[tlt_col].pct_change(22) * 100 if tlt_col else pd.Series(0, index=prices.index)

    rebal_dates = set(prices.resample("ME").last().index)
    initial     = 1_000_000.0
    holdings: dict[str, float] = {}
    cur_w: dict[str, float]    = {}
    vals = []

    for date, row in prices.iterrows():
        # 해당 날짜 ETF 모두 있는지 확인
        if any(pd.isna(row.get(c)) for c in etf_cols):
            vals.append(np.nan)
            continue

        vix_val = float(vix.loc[date]) if date in vix.index and not pd.isna(vix.loc[date]) else 18.0
        tlt_1m  = float(tlt_ret.loc[date]) if date in tlt_ret.index and not pd.isna(tlt_ret.loc[date]) else 0.0

        if not holdings or date in rebal_dates:
            new_w = _weights(vix_val, tlt_1m, ai_ticker)
            if not holdings:
                holdings = {t: initial * w / row[t] for t, w in new_w.items()}
            else:
                pv = sum(holdings[t] * row[t] for t in etf_cols)
                holdings = {t: pv * w / row[t] for t, w in new_w.items()}
            cur_w = new_w

        vals.append(sum(holdings[t] * row[t] for t in etf_cols))

    return pd.Series(vals, index=prices.index, name=label).dropna()


def _metrics(s: pd.Series, name: str) -> dict:
    rets   = s.pct_change().dropna()
    n_yrs  = len(s) / 252
    cagr   = (s.iloc[-1] / s.iloc[0]) ** (1 / max(n_yrs, 0.01)) - 1
    sharpe = rets.mean() / rets.std() * np.sqrt(252) if rets.std() > 0 else 0
    mdd    = ((s - s.cummax()) / s.cummax()).min()
    win_m  = (s.resample("ME").last().pct_change().dropna() > 0).mean()
    return {
        "전략":        name,
        "총수익률(%)": round((s.iloc[-1] / s.iloc[0] - 1) * 100, 1),
        "CAGR(%)":    round(cagr * 100, 1),
        "샤프비율":    round(sharpe, 2),
        "최대낙폭(%)": round(mdd * 100, 1),
        "월승률(%)":   round(win_m * 100, 1),
    }


# ── ① US ETF 5년 백테스트 (금리 보정 포함) ──────────────────────────────────
def run(out_dir: Path | None = None) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    out_dir = out_dir or _RES

    prices = pd.concat([_load_close(t) for t in _GUIDE_US], axis=1).dropna()
    vix    = _load_close("^VIX").reindex(prices.index).ffill().bfill()
    if prices.empty:
        return pd.DataFrame(), pd.DataFrame(), pd.DataFrame()

    strat = _run_core(prices, vix, "로테이션(금리보정)")
    bench = (1_000_000 * prices["VOO"] / prices["VOO"].iloc[0]).rename("VOO B&H")

    eq = pd.concat([strat, bench], axis=1).dropna()

    metrics_df = pd.DataFrame([
        _metrics(eq["로테이션(금리보정)"], "로테이션(금리보정)"),
        _metrics(eq["VOO B&H"],          "VOO B&H"),
    ])

    # 국면별 월성과
    eq["phase"] = eq.index.map(
        lambda d: get_phase(float(vix.loc[d]) if d in vix.index else 18.0)
    )
    monthly = eq.resample("ME").last()
    monthly["s_ret"] = monthly["로테이션(금리보정)"].pct_change()
    monthly["b_ret"] = monthly["VOO B&H"].pct_change()

    phase_rows = []
    for ph, grp in monthly.dropna(subset=["s_ret"]).groupby("phase"):
        phase_rows.append({
            "국면":           PHASE_LABELS.get(ph, ph),
            "기간(개월)":     len(grp),
            "전략 월평균(%)": round(grp["s_ret"].mean() * 100, 2),
            "VOO 월평균(%)":  round(grp["b_ret"].mean() * 100, 2),
            "전략 승률(%)":   round((grp["s_ret"] > 0).mean() * 100, 1),
        })
    phase_df = pd.DataFrame(phase_rows)

    eq.to_csv(out_dir / "rotation_backtest_equity.csv")
    metrics_df.to_csv(out_dir / "rotation_backtest_metrics.csv", index=False)
    phase_df.to_csv(out_dir / "rotation_backtest_phase.csv",   index=False)

    return eq, metrics_df, phase_df


# ── ② AI 슬롯 비교 (2023.10~ SOXX vs 466950 vs 469170) ────────────────────
def run_ai_compare(out_dir: Path | None = None) -> pd.DataFrame:
    out_dir = out_dir or _RES

    # 공통 날짜: 466950 / 469170 모두 있는 구간
    base_tickers = [t for t in _GUIDE_US if t != "SOXX"]  # VOO SCHD TLT GLD
    ai_options   = {"SOXX": "SOXX", "466950.KS": "466950.KS", "469170.KS": "469170.KS"}

    all_series = {t: _load_close(t) for t in base_tickers + list(ai_options.values()) + ["^VIX"]}
    vix = all_series["^VIX"]

    results = {}
    for label, ai_t in ai_options.items():
        needed = base_tickers + [ai_t]
        prices = pd.concat([all_series[t].rename(t if t != ai_t else ai_t) for t in needed], axis=1)
        # SOXX 슬롯에 AI ticker 할당
        if ai_t != "SOXX":
            prices = prices.rename(columns={ai_t: ai_t})  # already correct

        # TLT 컬럼이 없으면 스킵
        prices = prices.dropna()
        if prices.empty:
            continue
        vix_aligned = vix.reindex(prices.index).ffill().bfill()
        eq = _run_core(prices, vix_aligned, label, ai_ticker=ai_t)
        results[label] = eq

    if not results:
        return pd.DataFrame()

    compare = pd.concat(results.values(), axis=1).dropna()
    compare.columns = list(results.keys())

    rows = [_metrics(compare[c], c) for c in compare.columns]
    metrics_df = pd.DataFrame(rows)

    # 연도별 수익률
    annual = compare.resample("YE").last().pct_change() * 100
    annual.index = annual.index.year

    compare.to_csv(out_dir / "rotation_ai_compare_equity.csv")
    metrics_df.to_csv(out_dir / "rotation_ai_compare_metrics.csv", index=False)
    annual.round(1).to_csv(out_dir / "rotation_ai_compare_annual.csv")

    return metrics_df, compare, annual


if __name__ == "__main__":
    import sys
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

    print("=== US ETF 5년 백테스트 (금리보정) ===")
    eq, metrics, phase = run()
    print(metrics.to_string(index=False))
    print()
    print(phase.to_string(index=False))

    print("\n=== AI 슬롯 비교 (2023.10~) ===")
    ai_metrics, ai_eq, ai_annual = run_ai_compare()
    print(ai_metrics.to_string(index=False))
    print()
    print(ai_annual.to_string())
