"""
팩터 백테스트 — 학술적으로 입증된 4개 팩터 검증

1. 모멘텀  (Jegadeesh & Titman 1993)   — 12-1개월 가격 수익률
2. 저변동성 (Baker et al. 2011)         — 연환산 변동성 하위
3. 가치    (Fama & French 1992)         — 낮은 P/B (스냅샷)
4. 퀄리티  (Novy-Marx 2013)             — 높은 ROE + 이익률 (스냅샷)

월말 가격 패널 기반 분위(Q1~Q4) 포트폴리오 구성 후 다음달 수익률 추적.
"""
from __future__ import annotations

import numpy as np
import pandas as pd
from pathlib import Path

RESULTS = Path(__file__).resolve().parent.parent / "results"
OUT = RESULTS / "backtest"
OUT.mkdir(exist_ok=True)


# ── 공통: 월말 가격 패널 ──────────────────────────────────

def build_monthly_panel() -> pd.DataFrame:
    files = [
        f for f in RESULTS.glob("*_signals.csv")
        if not f.name.startswith("coin_") and "summary" not in f.name
    ]
    series = {}
    for f in files:
        ticker = f.stem.replace("_signals", "")
        df = pd.read_csv(f)
        dc = next((c for c in df.columns if c.lower() == "date"), None)
        if dc is None:
            continue
        df["Date"] = pd.to_datetime(df[dc])
        close = df.set_index("Date")["Close"].dropna()
        if len(close) >= 252:
            series[ticker] = close
    panel = pd.concat(series, axis=1, sort=True)
    return panel.resample("ME").last()


# ── 공통: 분위 롤링 백테스트 ─────────────────────────────

def _quartile_backtest(
    factor_panel: pd.DataFrame,
    ret_panel: pd.DataFrame,
    ascending: bool = False,
) -> tuple[pd.DataFrame, pd.DataFrame]:
    """
    factor_panel: 월별 팩터값 (rows=날짜, cols=ticker)
    ret_panel   : 다음달 수익률 (동일 인덱스)
    ascending   : True = 낮은 값이 Q1 (저변동성)
                  False = 높은 값이 Q1 (모멘텀)
    returns: (cum_df, stats_df)
    """
    rows = []
    for date in factor_panel.index[:-1]:
        factors = factor_panel.loc[date].dropna()
        rets = ret_panel.loc[date].dropna()
        common = factors.index.intersection(rets.index)
        if len(common) < 8:
            continue
        factors, rets = factors[common], rets[common]

        ranked = factors.rank(ascending=ascending, method="average")
        n = len(ranked)
        q_sz = n / 4

        for q in range(1, 5):
            mask = (ranked > (q - 1) * q_sz) & (ranked <= q * q_sz)
            q_rets = rets[mask]
            if len(q_rets) == 0:
                continue
            rows.append({"date": date, "q": f"Q{q}", "ret": q_rets.mean()})

    df = pd.DataFrame(rows)
    if df.empty:
        return pd.DataFrame(), pd.DataFrame()

    # 누적 수익률
    cum = {}
    for q in ["Q1", "Q2", "Q3", "Q4"]:
        sub = df[df["q"] == q].set_index("date")["ret"]
        cum[q] = (1 + sub).cumprod().round(4)
    cum_df = pd.DataFrame(cum)

    # 요약 통계
    stats = []
    for q in ["Q1", "Q2", "Q3", "Q4"]:
        sub = df[df["q"] == q]["ret"]
        avg_m = sub.mean()
        ann = round(((1 + avg_m) ** 12 - 1) * 100, 1)
        win = round((sub > 0).mean() * 100, 1)
        stats.append({
            "분위": q,
            "월평균수익(%)": round(avg_m * 100, 2),
            "연환산수익(%)": ann,
            "승률(%)": win,
            "관측월수": len(sub),
        })

    return cum_df, pd.DataFrame(stats)


# ── 팩터 1: 모멘텀 (12-1) ───────────────────────────────

def run_momentum(panel: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame]:
    # t-1 ~ t-13 사이 수익률 (최근 1개월 skip으로 단기 반전 노이즈 제거)
    factor = panel.shift(1) / panel.shift(13) - 1
    next_ret = panel.pct_change().shift(-1)
    idx = factor.index.intersection(next_ret.index)
    return _quartile_backtest(factor.loc[idx], next_ret.loc[idx], ascending=False)


# ── 팩터 2: 저변동성 ─────────────────────────────────────

def run_low_vol(panel: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame]:
    files = [
        f for f in RESULTS.glob("*_signals.csv")
        if not f.name.startswith("coin_") and "summary" not in f.name
    ]
    # 종목별로 독립 계산 후 월말 스냅샷만 합산
    # (KR/US 거래일 불일치로 concat 후 rolling 시 전부 NaN이 되는 문제 방지)
    vol_series = {}
    for f in files:
        ticker = f.stem.replace("_signals", "")
        df = pd.read_csv(f)
        dc = next((c for c in df.columns if c.lower() == "date"), None)
        if dc is None:
            continue
        df["Date"] = pd.to_datetime(df[dc])
        close = df.set_index("Date")["Close"].dropna()
        ret = close.pct_change()
        vol = ret.rolling(252).std() * np.sqrt(252)
        vol_monthly = vol.resample("ME").last().dropna()
        if len(vol_monthly) >= 12:
            vol_series[ticker] = vol_monthly

    vol_monthly = pd.DataFrame(vol_series)
    next_ret = panel.pct_change().shift(-1)
    idx = vol_monthly.index.intersection(next_ret.index)
    # ascending=True → 낮은 변동성이 Q1
    return _quartile_backtest(vol_monthly.loc[idx], next_ret.loc[idx], ascending=True)


# ── 팩터 3: 가치 (P/B 스냅샷) ────────────────────────────

def run_value(panel: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame]:
    """
    현재 P/B로 분위 구분 후 과거 36개월 수익률 비교.
    (스냅샷 분석 — 룩어헤드 바이어스 있음, 탐색적 참고용)
    """
    fund = pd.read_csv(RESULTS / "fundamentals.csv")[["ticker", "pbr", "sector"]].dropna(subset=["pbr"])

    rows = []
    for _, row in fund.iterrows():
        t = row["ticker"]
        if t not in panel.columns:
            continue
        s = panel[t].dropna()
        if len(s) < 12:
            continue
        n = min(36, len(s) - 1)
        ret_36m = round((s.iloc[-1] / s.iloc[-1 - n] - 1) * 100, 1)
        rows.append({"ticker": t, "pbr": row["pbr"], "sector": row["sector"], "ret_36m": ret_36m})

    df = pd.DataFrame(rows)
    if len(df) < 8:
        return pd.DataFrame(), pd.DataFrame()

    # 낮은 P/B → Q1 (가치주)
    df["q"] = pd.qcut(df["pbr"], 4, labels=["Q1", "Q2", "Q3", "Q4"])

    stats = []
    for q in ["Q1", "Q2", "Q3", "Q4"]:
        sub = df[df["q"] == q]
        stats.append({
            "분위": q,
            "평균P/B": round(sub["pbr"].mean(), 2),
            "평균수익_36M(%)": round(sub["ret_36m"].mean(), 1),
            "종목수": len(sub),
        })

    return df, pd.DataFrame(stats)


# ── 팩터 4: 퀄리티 (ROE + 이익률 스냅샷) ────────────────

def run_quality(panel: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame]:
    """
    ROE와 순이익률 평균으로 퀄리티 스코어 → 과거 36개월 수익률 비교.
    (스냅샷 분석 — 룩어헤드 바이어스 있음, 탐색적 참고용)
    """
    fund = pd.read_csv(RESULTS / "fundamentals.csv")[
        ["ticker", "roe_pct", "profit_margin_pct", "sector"]
    ].dropna(subset=["roe_pct", "profit_margin_pct"])

    rows = []
    for _, row in fund.iterrows():
        t = row["ticker"]
        if t not in panel.columns:
            continue
        s = panel[t].dropna()
        if len(s) < 12:
            continue
        n = min(36, len(s) - 1)
        ret_36m = round((s.iloc[-1] / s.iloc[-1 - n] - 1) * 100, 1)
        q_score = (row["roe_pct"] + row["profit_margin_pct"]) / 2
        rows.append({
            "ticker": t,
            "roe": row["roe_pct"],
            "profit_margin": row["profit_margin_pct"],
            "quality_score": round(q_score, 1),
            "sector": row["sector"],
            "ret_36m": ret_36m,
        })

    df = pd.DataFrame(rows)
    if len(df) < 8:
        return pd.DataFrame(), pd.DataFrame()

    # 높은 퀄리티 → Q1
    df["q"] = pd.qcut(
        df["quality_score"].rank(method="first"),
        4,
        labels=["Q4", "Q3", "Q2", "Q1"],
    )

    stats = []
    for q in ["Q1", "Q2", "Q3", "Q4"]:
        sub = df[df["q"] == q]
        stats.append({
            "분위": q,
            "평균퀄리티스코어": round(sub["quality_score"].mean(), 1),
            "평균ROE(%)": round(sub["roe"].mean(), 1),
            "평균수익_36M(%)": round(sub["ret_36m"].mean(), 1),
            "종목수": len(sub),
        })

    return df, pd.DataFrame(stats)


# ── 실행 ─────────────────────────────────────────────────

def run():
    print("팩터 백테스트 시작...")
    panel = build_monthly_panel()
    print(f"  가격 패널: {panel.shape[0]}개월 × {panel.shape[1]}종목")

    cum, stats = run_momentum(panel)
    if not cum.empty:
        cum.to_csv(OUT / "factor_momentum_cum.csv")
        stats.to_csv(OUT / "factor_momentum_stats.csv", index=False)
        print("  [OK] 모멘텀")

    cum, stats = run_low_vol(panel)
    if not cum.empty:
        cum.to_csv(OUT / "factor_lowvol_cum.csv")
        stats.to_csv(OUT / "factor_lowvol_stats.csv", index=False)
        print("  [OK] 저변동성")

    detail, stats = run_value(panel)
    if not detail.empty:
        detail.to_csv(OUT / "factor_value_detail.csv", index=False)
        stats.to_csv(OUT / "factor_value_stats.csv", index=False)
        print("  [OK] 가치")

    detail, stats = run_quality(panel)
    if not detail.empty:
        detail.to_csv(OUT / "factor_quality_detail.csv", index=False)
        stats.to_csv(OUT / "factor_quality_stats.csv", index=False)
        print("  [OK] 퀄리티")

    print("완료!")


if __name__ == "__main__":
    run()
