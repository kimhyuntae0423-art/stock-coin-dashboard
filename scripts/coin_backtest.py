"""
코인 전략 백테스트 — 3가지

1. 코인 모멘텀 (12-1M)  — 19개 코인 Q1~Q4 분위 월별 롤링 백테스트
2. BTC MVRV 사이클 전략 — Z-Score 구간별 BTC 비중 조절 vs 단순보유
3. BTC+ETH 리밸런싱     — 50/50 월별 리밸런싱 vs 단순보유 (리밸런싱 프리미엄 검증)
"""
from __future__ import annotations

import numpy as np
import pandas as pd
from pathlib import Path

RESULTS = Path(__file__).resolve().parent.parent / "results"
OUT = RESULTS / "backtest"
OUT.mkdir(exist_ok=True)

_MIN_DAYS = 1500  # 유효 코인 최소 일수


# ── 공통 유틸 ────────────────────────────────────────────

def _load_coin_close(ticker: str) -> pd.Series:
    f = RESULTS / f"coin_{ticker}_signals.csv"
    df = pd.read_csv(f)
    dc = next((c for c in df.columns if c.lower() == "date"), None)
    df["Date"] = pd.to_datetime(df[dc])
    return df.set_index("Date")["Close"].dropna()


def _build_monthly_panel() -> pd.DataFrame:
    files = [f for f in RESULTS.glob("coin_*_signals.csv")]
    series = {}
    for f in files:
        ticker = f.name.replace("coin_", "").replace("_signals.csv", "")
        df = pd.read_csv(f)
        dc = next((c for c in df.columns if c.lower() == "date"), None)
        if dc is None:
            continue
        df["Date"] = pd.to_datetime(df[dc])
        close = df.set_index("Date")["Close"].dropna()
        if len(close) >= _MIN_DAYS:
            series[ticker] = close
    panel = pd.concat(series, axis=1, sort=True)
    return panel.resample("ME").last()


def _perf_stats(ret: pd.Series) -> dict:
    ann = (1 + ret.mean()) ** 12 - 1
    vol = ret.std() * np.sqrt(12)
    sharpe = ann / vol if vol > 0 else 0
    cum = (1 + ret).cumprod()
    mdd = ((cum - cum.cummax()) / cum.cummax()).min()
    return {
        "총수익(%)": round((cum.iloc[-1] - 1) * 100, 1),
        "연환산수익(%)": round(ann * 100, 1),
        "연환산변동성(%)": round(vol * 100, 1),
        "샤프비율": round(sharpe, 2),
        "최대낙폭(%)": round(mdd * 100, 1),
        "월승률(%)": round((ret > 0).mean() * 100, 1),
    }


def _quartile_backtest(factor_panel, ret_panel, ascending=False):
    rows = []
    for date in factor_panel.index[:-1]:
        factors = factor_panel.loc[date].dropna()
        rets = ret_panel.loc[date].dropna()
        common = factors.index.intersection(rets.index)
        if len(common) < 8:
            continue
        ranked = factors[common].rank(ascending=ascending, method="average")
        n = len(ranked)
        for q in range(1, 5):
            mask = (ranked > (q - 1) * n / 4) & (ranked <= q * n / 4)
            q_rets = rets[common][mask]
            if len(q_rets) == 0:
                continue
            rows.append({"date": ret_panel.index[
                ret_panel.index.get_loc(date) + 1
                if ret_panel.index.get_loc(date) + 1 < len(ret_panel.index)
                else ret_panel.index.get_loc(date)
            ], "q": f"Q{q}", "ret": q_rets.mean()})

    df = pd.DataFrame(rows)
    if df.empty:
        return pd.DataFrame(), pd.DataFrame()

    cum = {}
    for q in ["Q1", "Q2", "Q3", "Q4"]:
        sub = df[df["q"] == q].set_index("date")["ret"]
        cum[q] = (1 + sub).cumprod()
    cum_df = pd.DataFrame(cum)

    stats = []
    for q in ["Q1", "Q2", "Q3", "Q4"]:
        sub = df[df["q"] == q]["ret"]
        ann = round(((1 + sub.mean()) ** 12 - 1) * 100, 1)
        stats.append({
            "분위": q,
            "월평균수익(%)": round(sub.mean() * 100, 2),
            "연환산수익(%)": ann,
            "승률(%)": round((sub > 0).mean() * 100, 1),
            "관측월수": len(sub),
        })

    return cum_df, pd.DataFrame(stats)


# ════════════════════════════════════════════════════════
# 전략 1 — 코인 모멘텀 (12-1M)
# ════════════════════════════════════════════════════════

def run_coin_momentum(panel: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame]:
    """
    매달 19개 코인 12-1M 수익률 순위 → Q1(상위) ~ Q4(하위) 분위 포트폴리오
    vs BTC 단순보유
    """
    factor = panel.shift(1) / panel.shift(13) - 1
    next_ret = panel.pct_change().shift(-1)
    idx = factor.index.intersection(next_ret.index)

    cum_df, stats_df = _quartile_backtest(
        factor.loc[idx], next_ret.loc[idx], ascending=False
    )

    if cum_df.empty:
        return cum_df, stats_df

    # BTC 단순보유 추가
    btc_ret = next_ret["BTC-USD"].dropna()
    btc_ret = btc_ret[btc_ret.index.isin(cum_df.index)]
    cum_df["BTC 단순보유"] = (1 + btc_ret).cumprod()

    stats_df = pd.concat([
        stats_df,
        pd.DataFrame([{"분위": "BTC 단순보유", **_perf_stats(btc_ret), "관측월수": len(btc_ret)}]),
    ], ignore_index=True)

    return cum_df, stats_df


# ════════════════════════════════════════════════════════
# 전략 2 — BTC MVRV 사이클 전략
# ════════════════════════════════════════════════════════

def run_mvrv_cycle() -> tuple[pd.DataFrame, pd.DataFrame]:
    """
    MVRV Z-Score 구간별 BTC 비중 동적 조절 (월별 리밸런싱)
    Z < 0        → BTC 100% (역사적 바닥 구간)
    0 <= Z < 1.5 → BTC 75%  (저평가)
    1.5 <= Z < 2.5 → BTC 45% (중립~과열 경계)
    Z >= 2.5     → BTC 20%  (과열, 현금 비중↑)
    비교군: BTC 100% 단순보유
    """
    mvrv = pd.read_csv(RESULTS / "mvrv_history.csv", parse_dates=["date"])
    mvrv = mvrv.set_index("date")["value"].resample("ME").last()

    btc_close = _load_coin_close("BTC-USD").resample("ME").last()
    btc_ret = btc_close.pct_change()

    # 공통 기간
    common = mvrv.index.intersection(btc_ret.index)
    mvrv = mvrv.loc[common]
    btc_ret = btc_ret.loc[common]

    def _btc_weight(z):
        if z < 0:
            return 1.00
        elif z < 1.5:
            return 0.75
        elif z < 2.5:
            return 0.45
        else:
            return 0.20

    cycle_rets = []
    for i in range(1, len(btc_ret)):
        z = mvrv.iloc[i - 1]  # 전달 MVRV로 이번 달 비중 결정
        w = _btc_weight(z) if pd.notna(z) else 0.5
        r = btc_ret.iloc[i]
        if pd.notna(r):
            cycle_rets.append(w * r)
        else:
            cycle_rets.append(np.nan)

    cycle = pd.Series(cycle_rets, index=btc_ret.index[1:], name="MVRV 사이클 전략").dropna()
    btc_hold = btc_ret.loc[cycle.index].rename("BTC 단순보유")

    cum_df = pd.DataFrame({
        "MVRV 사이클 전략": (1 + cycle).cumprod(),
        "BTC 단순보유": (1 + btc_hold).cumprod(),
    })

    # MVRV 구간 분포 저장
    zone_counts = pd.cut(
        mvrv,
        bins=[-np.inf, 0, 1.5, 2.5, np.inf],
        labels=["< 0 (BTC 100%)", "0-1.5 (BTC 75%)", "1.5-2.5 (BTC 45%)", "> 2.5 (BTC 20%)"],
    ).value_counts().reset_index()
    zone_counts.columns = ["구간", "월수"]
    zone_counts.to_csv(OUT / "coin_mvrv_zones.csv", index=False)

    stats_df = pd.DataFrame([
        {"전략": "MVRV 사이클 전략", **_perf_stats(cycle)},
        {"전략": "BTC 단순보유", **_perf_stats(btc_hold)},
    ])

    return cum_df, stats_df


# ════════════════════════════════════════════════════════
# 전략 3 — BTC + ETH 리밸런싱 프리미엄
# ════════════════════════════════════════════════════════

def run_crypto_rebalancing(panel: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame]:
    """
    BTC 50% + ETH 50% 매월 리밸런싱 vs 각각 단순보유
    리밸런싱 자체가 코인에서도 프리미엄을 만드는지 검증.
    """
    df = panel[["BTC-USD", "ETH-USD"]].dropna()
    ret = df.pct_change().dropna()

    rb_rets = []
    for i in range(len(ret)):
        rb_rets.append(ret.iloc[i].mean())  # 50/50 동일비중 월별 리셋

    rb = pd.Series(rb_rets, index=ret.index, name="BTC+ETH 리밸런싱")

    # 드리프트 (리밸런싱 없음)
    drift_w = pd.Series({"BTC-USD": 0.5, "ETH-USD": 0.5})
    drift_rets = []
    for i in range(len(ret)):
        month_ret = ret.iloc[i]
        drift_rets.append((drift_w * month_ret).sum())
        drift_w = drift_w * (1 + month_ret)
        drift_w /= drift_w.sum()

    drift = pd.Series(drift_rets, index=ret.index, name="드리프트(리밸런싱 無)")
    btc = ret["BTC-USD"].rename("BTC 단순보유")
    eth = ret["ETH-USD"].rename("ETH 단순보유")

    cum_df = pd.DataFrame({
        "BTC+ETH 리밸런싱": (1 + rb).cumprod(),
        "드리프트(리밸런싱 無)": (1 + drift).cumprod(),
        "BTC 단순보유": (1 + btc).cumprod(),
        "ETH 단순보유": (1 + eth).cumprod(),
    })

    stats_df = pd.DataFrame([
        {"전략": "BTC+ETH 리밸런싱 50/50", **_perf_stats(rb)},
        {"전략": "드리프트(리밸런싱 無)", **_perf_stats(drift)},
        {"전략": "BTC 단순보유", **_perf_stats(btc)},
        {"전략": "ETH 단순보유", **_perf_stats(eth)},
    ])

    return cum_df, stats_df


# ── 실행 ─────────────────────────────────────────────────

def run():
    print("코인 백테스트 시작...")
    panel = _build_monthly_panel()
    print(f"  패널: {panel.shape[0]}개월 x {panel.shape[1]}코인")

    cum, stats = run_coin_momentum(panel)
    if not cum.empty:
        cum.to_csv(OUT / "coin_momentum_cum.csv")
        stats.to_csv(OUT / "coin_momentum_stats.csv", index=False)
        print("  [OK] 코인 모멘텀")

    cum, stats = run_mvrv_cycle()
    if not cum.empty:
        cum.to_csv(OUT / "coin_mvrv_cum.csv")
        stats.to_csv(OUT / "coin_mvrv_stats.csv", index=False)
        print("  [OK] MVRV 사이클")

    cum, stats = run_crypto_rebalancing(panel)
    if not cum.empty:
        cum.to_csv(OUT / "coin_rebalancing_cum.csv")
        stats.to_csv(OUT / "coin_rebalancing_stats.csv", index=False)
        print("  [OK] BTC+ETH 리밸런싱")

    print("완료!")


if __name__ == "__main__":
    run()
