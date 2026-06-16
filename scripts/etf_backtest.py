"""
ETF 전략 백테스트 — 학술 검증 4대 전략

1. Dual Momentum     (Antonacci 2014)   — 상대모멘텀 + 절대모멘텀 로테이션
2. 리밸런싱 프리미엄  (Booth & Fama 1992) — 정기 리밸런싱 vs 단순 보유
3. Risk Parity       (Qian 2005)        — 변동성 역비례 배분
4. GTAA 추세추종      (Faber 2007)       — 200일 MA 기반 진입/현금 전환

회사 네트워크 SSL 프록시 환경: curl_cffi verify=False 로 우회.
"""
from __future__ import annotations

import json
import numpy as np
import pandas as pd
from pathlib import Path
from datetime import datetime

OUT = Path(__file__).resolve().parent.parent / "results" / "backtest"
OUT.mkdir(exist_ok=True)

START = "2015-01-01"

# ── ETF 유니버스 ─────────────────────────────────────────
# 전략별 역할 주석
UNIVERSE = {
    "VOO": "미국주식(S&P500)",
    "VEU": "선진국주식(미국 제외)",
    "BND": "미국채권(종합)",
    "GLD": "금",
    "TLT": "미국장기국채",
    "SHY": "단기국채(현금대용)",
}


# ── 데이터 수집 (curl_cffi SSL 우회) ──────────────────────

def _fetch_monthly(ticker: str, start: str) -> pd.Series:
    from curl_cffi import requests as cr
    url = (
        f"https://query1.finance.yahoo.com/v8/finance/chart/{ticker}"
        f"?interval=1mo&period1={_to_ts(start)}&period2={_to_ts('2030-01-01')}"
    )
    r = cr.get(url, impersonate="chrome", verify=False, timeout=15)
    r.raise_for_status()
    result = r.json()["chart"]["result"][0]
    ts = result["timestamp"]
    closes = result["indicators"]["adjclose"][0]["adjclose"]
    dates = pd.to_datetime(ts, unit="s").normalize()
    s = pd.Series(closes, index=dates, name=ticker).dropna()
    return s.resample("ME").last()


def _to_ts(date_str: str) -> int:
    return int(datetime.strptime(date_str, "%Y-%m-%d").timestamp())


def load_all(tickers: list[str], start: str = START) -> pd.DataFrame:
    frames = {}
    for t in tickers:
        try:
            frames[t] = _fetch_monthly(t, start)
            print(f"  {t}: {len(frames[t])}개월")
        except Exception as e:
            print(f"  {t} 실패: {e}")
    return pd.DataFrame(frames).sort_index()


# ── 공통 유틸 ────────────────────────────────────────────

def _perf_stats(ret_series: pd.Series) -> dict:
    """월별 수익률 시리즈 → 성과 통계"""
    ann = (1 + ret_series.mean()) ** 12 - 1
    vol = ret_series.std() * np.sqrt(12)
    sharpe = ann / vol if vol > 0 else 0
    cum = (1 + ret_series).cumprod()
    roll_max = cum.cummax()
    dd = (cum - roll_max) / roll_max
    mdd = dd.min()
    win = (ret_series > 0).mean()
    total = cum.iloc[-1] - 1
    return {
        "총수익(%)": round(total * 100, 1),
        "연환산수익(%)": round(ann * 100, 1),
        "연환산변동성(%)": round(vol * 100, 1),
        "샤프비율": round(sharpe, 2),
        "최대낙폭(%)": round(mdd * 100, 1),
        "월승률(%)": round(win * 100, 1),
    }


# ════════════════════════════════════════════════════════
# 전략 1 — Dual Momentum (Antonacci 2014)
# ════════════════════════════════════════════════════════

def run_dual_momentum(panel: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame]:
    """
    매월 말 기준:
    1) VOO vs VEU 상대 12-1M 모멘텀 → 승자 선택
    2) 승자의 절대 모멘텀(vs SHY) 양수 → 승자 보유
                                 음수 → BND(채권)으로 대피
    비교군: 단순 VOO 보유, 60/40(VOO+BND)
    """
    needed = ["VOO", "VEU", "BND", "SHY"]
    df = panel[needed].dropna(how="all")
    ret = df.pct_change()

    # 12-1 모멘텀 (1개월 skip)
    mom = df.shift(1) / df.shift(13) - 1
    shy_mom = mom["SHY"]

    port_rets = []
    positions = []
    dates = []

    for i in range(13, len(df) - 1):
        date = df.index[i]
        m_voo = mom.iloc[i]["VOO"]
        m_veu = mom.iloc[i]["VEU"]
        m_shy = shy_mom.iloc[i]

        if pd.isna(m_voo) or pd.isna(m_veu):
            continue

        # 상대 모멘텀 승자
        winner = "VOO" if m_voo >= m_veu else "VEU"
        winner_mom = m_voo if winner == "VOO" else m_veu

        # 절대 모멘텀 필터
        if pd.notna(m_shy) and winner_mom < m_shy:
            hold = "BND"  # 채권 대피
        else:
            hold = winner

        next_ret = ret.iloc[i + 1][hold]
        if pd.isna(next_ret):
            continue

        port_rets.append(next_ret)
        positions.append(hold)
        dates.append(df.index[i + 1])

    port = pd.Series(port_rets, index=dates, name="Dual Momentum")

    # 비교군
    voo_ret = ret["VOO"].loc[port.index]
    blend_ret = (ret["VOO"] * 0.6 + ret["BND"] * 0.4).loc[port.index]

    cum = pd.DataFrame({
        "Dual Momentum": (1 + port).cumprod(),
        "VOO (Buy&Hold)": (1 + voo_ret).cumprod(),
        "60/40 (VOO+BND)": (1 + blend_ret).cumprod(),
    })

    stats = pd.DataFrame([
        {"전략": "Dual Momentum", **_perf_stats(port)},
        {"전략": "VOO Buy&Hold", **_perf_stats(voo_ret)},
        {"전략": "60/40 리밸런싱", **_perf_stats(blend_ret)},
    ])

    # 포지션 이력 저장
    pos_df = pd.DataFrame({"date": dates, "position": positions})
    pos_df.to_csv(OUT / "etf_dual_momentum_positions.csv", index=False)

    return cum, stats


# ════════════════════════════════════════════════════════
# 전략 2 — 리밸런싱 프리미엄 (Booth & Fama 1992)
# ════════════════════════════════════════════════════════

def run_rebalancing_premium(panel: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame]:
    """
    60% VOO / 30% BND / 10% GLD 매월 리밸런싱
    vs 동일 비중으로 시작하되 리밸런싱 없이 드리프트
    vs 100% VOO 단순 보유
    → 리밸런싱 자체가 얼마나 수익을 추가하는지 검증
    """
    needed = ["VOO", "BND", "GLD"]
    df = panel[needed].dropna()
    ret = df.pct_change().dropna()

    TARGET = {"VOO": 0.60, "BND": 0.30, "GLD": 0.10}

    # ── 리밸런싱 포트폴리오 ──────────────────────────────
    weights = pd.Series(TARGET)
    rb_rets = []
    for i in range(len(ret)):
        month_ret = ret.iloc[i]
        port_ret = (weights * month_ret).sum()
        rb_rets.append(port_ret)
        # 다음 달 초에 리밸런싱 (목표 비중 복귀)
        weights = pd.Series(TARGET)

    rb = pd.Series(rb_rets, index=ret.index, name="리밸런싱 60/30/10")

    # ── 드리프트 포트폴리오 (리밸런싱 없음) ──────────────
    drift_weights = pd.Series(TARGET, dtype=float)
    drift_rets = []
    for i in range(len(ret)):
        month_ret = ret.iloc[i]
        port_ret = (drift_weights * month_ret).sum()
        drift_rets.append(port_ret)
        # 리밸런싱 없이 가중치 드리프트
        drift_weights = drift_weights * (1 + month_ret)
        drift_weights /= drift_weights.sum()

    drift = pd.Series(drift_rets, index=ret.index, name="드리프트(리밸런싱 無)")

    voo = ret["VOO"].rename("VOO 단순보유")
    bnd = ret["BND"].rename("BND 단순보유")
    gld = ret["GLD"].rename("GLD 단순보유")

    cum = pd.DataFrame({
        "리밸런싱 60/30/10": (1 + rb).cumprod(),
        "드리프트(리밸런싱 無)": (1 + drift).cumprod(),
        "VOO 단순보유": (1 + voo).cumprod(),
        "BND 단순보유": (1 + bnd).cumprod(),
        "GLD 단순보유": (1 + gld).cumprod(),
    })

    stats = pd.DataFrame([
        {"전략": "리밸런싱 60/30/10", **_perf_stats(rb)},
        {"전략": "드리프트(리밸런싱 無)", **_perf_stats(drift)},
        {"전략": "VOO 단순보유", **_perf_stats(voo)},
        {"전략": "BND 단순보유", **_perf_stats(bnd)},
        {"전략": "GLD 단순보유", **_perf_stats(gld)},
    ])

    return cum, stats


# ════════════════════════════════════════════════════════
# 전략 3 — Risk Parity (Qian 2005)
# ════════════════════════════════════════════════════════

def run_risk_parity(panel: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame]:
    """
    VOO / BND / GLD 3자산
    월말 기준 직전 12개월 변동성의 역수로 비중 결정 (월별 리밸런싱)
    vs 동일 비중(1/3), vs 60/40
    """
    needed = ["VOO", "BND", "GLD"]
    df = panel[needed].dropna()
    ret = df.pct_change()

    rp_rets = []
    eq_rets = []
    blend_rets = []
    rp_dates = []

    for i in range(12, len(ret) - 1):
        window = ret.iloc[i - 12: i]
        vols = window.std()
        if vols.isna().any() or (vols == 0).any():
            continue

        # 역변동성 비중
        inv_vol = 1 / vols
        rp_w = inv_vol / inv_vol.sum()

        next_ret = ret.iloc[i + 1]
        if next_ret.isna().any():
            continue

        rp_rets.append((rp_w * next_ret).sum())
        eq_rets.append(next_ret.mean())                        # 동일 비중
        blend_rets.append(next_ret["VOO"] * 0.6 + next_ret["BND"] * 0.4)
        rp_dates.append(ret.index[i + 1])

    rp   = pd.Series(rp_rets,    index=rp_dates, name="Risk Parity")
    eq   = pd.Series(eq_rets,    index=rp_dates, name="동일 비중(1/3)")
    bl   = pd.Series(blend_rets, index=rp_dates, name="60/40 (VOO+BND)")

    cum = pd.DataFrame({
        "Risk Parity": (1 + rp).cumprod(),
        "동일 비중(1/3)": (1 + eq).cumprod(),
        "60/40 (VOO+BND)": (1 + bl).cumprod(),
    })

    stats = pd.DataFrame([
        {"전략": "Risk Parity (역변동성)", **_perf_stats(rp)},
        {"전략": "동일 비중 1/3", **_perf_stats(eq)},
        {"전략": "60/40 (VOO+BND)", **_perf_stats(bl)},
    ])

    return cum, stats


# ════════════════════════════════════════════════════════
# 전략 4 — GTAA 추세추종 (Faber 2007)
# ════════════════════════════════════════════════════════

def run_gtaa(panel: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame]:
    """
    5자산(VOO, VEU, BND, GLD, TLT): 월말 종가 > 10개월 이동평균 → 보유
                                                                  → SHY(현금)로 대피
    매달 리밸런싱: 보유 중인 자산 동일 비중
    vs VOO 단순 보유, vs 60/40
    """
    needed = ["VOO", "VEU", "BND", "GLD", "TLT", "SHY"]
    df = panel[needed].dropna(how="all")
    ret = df.pct_change()

    # 10개월 이동평균 (Faber 원논문 기준)
    ma10 = df.rolling(10).mean()
    risky = ["VOO", "VEU", "BND", "GLD", "TLT"]

    gtaa_rets = []
    voo_rets = []
    blend_rets = []
    gtaa_dates = []

    for i in range(10, len(df) - 1):
        date = df.index[i]
        in_assets = []
        for asset in risky:
            if pd.notna(df.iloc[i][asset]) and pd.notna(ma10.iloc[i][asset]):
                if df.iloc[i][asset] > ma10.iloc[i][asset]:
                    in_assets.append(asset)
                else:
                    in_assets.append("SHY")

        if not in_assets:
            continue

        next_ret_row = ret.iloc[i + 1]
        port_ret = np.mean([next_ret_row.get(a, 0) for a in in_assets])
        voo_r = next_ret_row.get("VOO", np.nan)
        bnd_r = next_ret_row.get("BND", np.nan)

        if pd.isna(port_ret) or pd.isna(voo_r):
            continue

        gtaa_rets.append(port_ret)
        voo_rets.append(voo_r)
        blend_rets.append(voo_r * 0.6 + bnd_r * 0.4 if pd.notna(bnd_r) else voo_r)
        gtaa_dates.append(df.index[i + 1])

    gtaa  = pd.Series(gtaa_rets,  index=gtaa_dates, name="GTAA 추세추종")
    voo   = pd.Series(voo_rets,   index=gtaa_dates, name="VOO 단순보유")
    blend = pd.Series(blend_rets, index=gtaa_dates, name="60/40 (VOO+BND)")

    cum = pd.DataFrame({
        "GTAA 추세추종": (1 + gtaa).cumprod(),
        "VOO 단순보유": (1 + voo).cumprod(),
        "60/40 (VOO+BND)": (1 + blend).cumprod(),
    })

    stats = pd.DataFrame([
        {"전략": "GTAA 추세추종", **_perf_stats(gtaa)},
        {"전략": "VOO 단순보유", **_perf_stats(voo)},
        {"전략": "60/40 (VOO+BND)", **_perf_stats(blend)},
    ])

    return cum, stats


# ── 실행 ─────────────────────────────────────────────────

def run():
    print("ETF 전략 백테스트 시작...")
    tickers = list(UNIVERSE.keys())
    panel = load_all(tickers)

    if panel.empty:
        print("ETF 데이터 로드 실패")
        return

    print(f"  패널: {panel.shape[0]}개월 x {panel.shape[1]}종목 ({panel.index[0].date()} ~ {panel.index[-1].date()})")

    for name, fn, args in [
        ("Dual Momentum",    run_dual_momentum,      (panel,)),
        ("리밸런싱 프리미엄", run_rebalancing_premium, (panel,)),
        ("Risk Parity",      run_risk_parity,         (panel,)),
        ("GTAA 추세추종",    run_gtaa,                (panel,)),
    ]:
        try:
            cum, stats = fn(*args)
            slug = name.replace(" ", "_").replace("/", "").lower()
            cum.to_csv(OUT / f"etf_{slug}_cum.csv")
            stats.to_csv(OUT / f"etf_{slug}_stats.csv", index=False)
            print(f"  [OK] {name}")
        except Exception as e:
            print(f"  [FAIL] {name}: {e}")

    print("완료!")


if __name__ == "__main__":
    run()
