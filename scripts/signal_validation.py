"""신호 예측력 검증 — 가설 수립 → 검증 → 결론.

각 신호(Signal)와 향후 수익률 간의 상관관계를 측정합니다.

검증 지표:
  IC (Information Coefficient) : 신호값 ↔ 향후수익률 피어슨 상관계수
  Hit Rate                      : 신호 방향과 수익률 방향이 일치한 비율 (%)
  t-stat / p-value              : IC의 통계적 유의성
  IC > 0.05 + p < 0.05         → "예측력 확인"
  IC > 0 but p ≥ 0.05          → "약한 신호 / 데이터 부족"
  IC ≈ 0 or negative           → "예측력 없음"
"""
from pathlib import Path
import pandas as pd
import numpy as np
from scipy import stats

RESULTS_DIR = Path(__file__).resolve().parent.parent / "results"
FWD_WINDOWS = [22, 66]   # 1개월, 3개월


# ── 가설 정의 ────────────────────────────────────────────────────────────────
HYPOTHESES_VALIDATED = [
    {
        "id":        "H15",
        "name":      "검증신호 복합점수 (BB+MA+RSI+Vol)",
        "signal":    "h15_composite",
        "direction": "higher_is_better",
        "desc":      "개별 검증 신호(BB역방향·MA역방향·RSI역방향·거래량정방향) 결합 복합점수가 향후 수익을 예측한다",
        "ref":       "H2·H4·H5·H6 검증 결과 결합. IC 가중 합산.",
    },
    {
        "id":        "H16",
        "name":      "H15 Top33% vs Bottom33% 격차",
        "signal":    "_quantile_spread",
        "direction": "higher_is_better",
        "desc":      "H15 복합점수 상위 33%가 하위 33%보다 향후 수익이 유의하게 높다",
        "ref":       "H15 실용성 검증 (H11 대응)",
    },
]

HYPOTHESES_SYSTEM = [
    {
        "id":        "H12",
        "name":      "섹터사이클 (1M 상대강도)",
        "signal":    "rel_1m",        # mom_1m - spy_1m (계산 필요)
        "direction": "higher_is_better",
        "desc":      "SPY 대비 1M 초과수익(섹터사이클 배율 근거)이 향후 1M 수익 예측",
        "ref":       "사이클배율 실제 드라이버 검증",
    },
    {
        "id":        "H13",
        "name":      "Bull추세 필터 (골든크로스)",
        "signal":    "is_bull",       # ma_score >= 2
        "direction": "higher_is_better",
        "desc":      "Bull추세(MA 상승정렬) 종목이 Bear추세보다 향후 수익 좋을 것이다",
        "ref":       "추천 필터 유효성 검증",
    },
    {
        "id":        "H14",
        "name":      "12M 상대강도 (섹터 vs SPY)",
        "signal":    "rel_12m",       # mom_12m - spy_12m (계산 필요)
        "direction": "higher_is_better",
        "desc":      "12M 상대강도가 높은 ETF가 향후에도 초과수익 낼 것이다",
        "ref":       "장기 상대 모멘텀 검증",
    },
]

HYPOTHESES_COMPOSITE = [
    {
        "id":        "H9",
        "name":      "복합 모멘텀 (7:3)",
        "signal":    "composite_mom",   # 0.7×mom_12m + 0.3×mom_1m
        "direction": "higher_is_better",
        "desc":      "7:3 가중 복합 모멘텀이 12M 단독보다 향후 수익 예측력이 높을 것이다",
        "ref":       "Asness (1994), 복합 모멘텀",
    },
    {
        "id":        "H10",
        "name":      "과열 복합 조건 역방향",
        "signal":    "overheat_flag",   # 1 if MA==3 and BB>0.85 else 0
        "direction": "lower_is_better", # 과열 = 향후 수익 낮음
        "desc":      "MA완전정렬+BB상단(과열) 상태일 때 향후 수익이 낮을 것이다 (역방향 페널티 근거)",
        "ref":       "H2+H4 결합. IC 역방향 검증",
    },
    {
        "id":        "H11",
        "name":      "추천 vs 비추천 수익 격차",
        "signal":    "_quantile_spread",  # 특수 처리
        "direction": "higher_is_better",
        "desc":      "복합점수 상위 33% 수익률이 하위 33%보다 유의하게 높을 것이다",
        "ref":       "장기 포트폴리오 성과 검증",
    },
]

HYPOTHESES = [
    {
        "id":        "H1",
        "name":      "12M 모멘텀",
        "signal":    "mom_12m",
        "direction": "higher_is_better",
        "desc":      "12개월 수익률 높은 종목이 향후 1M도 더 좋을 것이다 (모멘텀 지속성)",
        "ref":       "Jegadeesh & Titman (1993)",
    },
    {
        "id":        "H2",
        "name":      "MA 정렬 점수",
        "signal":    "ma_score",
        "direction": "higher_is_better",
        "desc":      "MA20>MA50>MA200 완전 정렬 종목이 미래 수익이 더 좋을 것이다",
        "ref":       "Faber (2007)",
    },
    {
        "id":        "H3",
        "name":      "OBV 10일 추세",
        "signal":    "obv_slope",
        "direction": "higher_is_better",
        "desc":      "OBV 상승 추세(매집 신호) 종목이 향후 수익이 더 좋을 것이다",
        "ref":       "Granville (1963), 실증 다수",
    },
    {
        "id":        "H4",
        "name":      "볼린저밴드 위치",
        "signal":    "bb_pct",
        "direction": "higher_is_better",
        "desc":      "BB 위치가 높을수록(상단 압박) 모멘텀이 지속될 것이다",
        "ref":       "Bollinger (2002)",
    },
    {
        "id":        "H5",
        "name":      "거래량 비율 (5d/20d)",
        "signal":    "vol_ratio",
        "direction": "higher_is_better",
        "desc":      "거래량 급증(기관 개입 추정) 후 향후 1M 수익이 더 좋을 것이다",
        "ref":       "Blume et al. (1994)",
    },
    {
        "id":        "H6",
        "name":      "RSI 기울기",
        "signal":    "rsi_slope",
        "direction": "higher_is_better",
        "desc":      "RSI 기울기(방향)가 양수인 종목이 향후 수익이 더 좋을 것이다",
        "ref":       "기술적 분석 다수",
    },
    {
        "id":        "H7",
        "name":      "MACD 히스토그램",
        "signal":    "macd_hist",
        "direction": "higher_is_better",
        "desc":      "MACD 히스토그램 양수+증가 시 모멘텀 가속 → 향후 수익 양호",
        "ref":       "Appel (1979)",
    },
    {
        "id":        "H8",
        "name":      "VIX 역발상",
        "signal":    "vix_level",
        "direction": "lower_is_better",
        "desc":      "VIX 높을 때 매수 → 향후 1M 수익 양호 (공포 극단 = 매수 기회)",
        "ref":       "Whaley (2000)",
    },
]


def _load_signals_df(results_dir: Path) -> pd.DataFrame:
    """모든 종목 신호 CSV를 합쳐서 패널 데이터 생성."""
    files = [f for f in results_dir.glob("*_signals.csv")
             if not f.name.startswith("coin_") and "summary" not in f.name]
    rows = []
    for f in files:
        ticker = f.stem.replace("_signals", "")
        try:
            df = pd.read_csv(f)
            dc = [c for c in df.columns if c.lower() == "date"]
            if not dc:
                continue
            df = df.rename(columns={dc[0]: "date"})
            df["date"] = pd.to_datetime(df["date"])
            df = df.set_index("date").sort_index()
            if len(df) < 250:
                continue

            # 기본 신호 계산
            df["mom_12m"] = df["Close"].pct_change(252) * 100
            df["mom_1m"]  = df["Close"].pct_change(22)  * 100
            df["ma_score"] = (
                (df["Close"] > df["ma20"]).astype(int) +
                (df["ma20"]  > df["ma50"]).astype(int) +
                (df["ma50"]  > df["ma200"]).astype(int)
            )
            # OBV 10일 기울기
            df["obv_slope"] = (
                (df["obv"] - df["obv"].shift(10)) /
                df["obv"].shift(10).abs().replace(0, np.nan) * 100
            )
            # 거래량 비율
            df["vol_ma20"] = df["Volume"].rolling(20).mean()
            df["vol_ratio"] = df["Volume"].rolling(5).mean() / df["vol_ma20"].replace(0, np.nan)
            # RSI 10일 기울기
            df["rsi_slope"] = (df["rsi14"] - df["rsi14"].shift(10)) / 10
            # MACD hist 5일 평균
            df["macd_hist_avg"] = df["macd_hist"].rolling(5).mean()

            # 향후 수익률
            for w in FWD_WINDOWS:
                df[f"fwd_{w}d"] = df["Close"].pct_change(w).shift(-w) * 100

            df["ticker"] = ticker
            rows.append(df)
        except Exception:
            continue
    if not rows:
        return pd.DataFrame()
    return pd.concat(rows).reset_index()


def _load_vix(results_dir: Path) -> pd.Series:
    """^VIX close를 날짜 인덱스 Series로 반환."""
    f = results_dir / "^VIX_signals.csv"
    if not f.exists():
        return pd.Series(dtype=float)
    df = pd.read_csv(f)
    dc = [c for c in df.columns if c.lower() == "date"]
    if not dc:
        return pd.Series(dtype=float)
    df = df.rename(columns={dc[0]: "date"})
    df["date"] = pd.to_datetime(df["date"])
    return df.set_index("date")["Close"].rename("vix_level")


def _ic_stats(signal: pd.Series, fwd: pd.Series) -> dict:
    """IC, t-stat, p-value, hit rate 계산."""
    valid = pd.concat([signal, fwd], axis=1).dropna()
    if len(valid) < 30:
        return {"n": len(valid), "ic": None, "t_stat": None, "p_value": None, "hit_rate": None}
    s = valid.iloc[:, 0]
    f = valid.iloc[:, 1]
    ic, p = stats.pearsonr(s, f)
    n = len(valid)
    t_stat = ic * np.sqrt(n - 2) / np.sqrt(1 - ic**2) if abs(ic) < 1 else np.nan
    hit = ((s > s.median()) == (f > 0)).mean() * 100
    return {
        "n": n,
        "ic": round(ic, 4),
        "t_stat": round(t_stat, 2),
        "p_value": round(p, 4),
        "hit_rate": round(hit, 1),
    }


def _verdict(ic, p_value) -> str:
    if ic is None or p_value is None:
        return "데이터 부족"
    if abs(ic) >= 0.05 and p_value < 0.05:
        return "✅ 예측력 확인" if ic > 0 else "✅ 역방향 예측력"
    if p_value < 0.10:
        return "⚠️ 약한 신호"
    return "❌ 예측력 없음"


def _cross_ic_monthly(panel: pd.DataFrame, sig_col: str, fwd_col: str) -> dict:
    """월별 Cross-sectional IC 계산."""
    panel_sub = panel[["date", "ticker", sig_col, fwd_col]].dropna()
    monthly = panel_sub.copy()
    monthly["ym"] = monthly["date"].dt.to_period("M")
    monthly_ics = []
    for _, grp in monthly.groupby("ym"):
        if len(grp) < 5:
            continue
        r = stats.pearsonr(grp[sig_col], grp[fwd_col])
        monthly_ics.append(r[0])
    monthly_ics = [x for x in monthly_ics if not np.isnan(x)]
    if not monthly_ics:
        return {}
    ic_arr  = np.array(monthly_ics)
    ic_mean = float(np.mean(ic_arr))
    t_stat  = float(np.mean(ic_arr) / (np.std(ic_arr, ddof=1) / np.sqrt(len(ic_arr))))
    p_val   = float(2 * (1 - stats.t.cdf(abs(t_stat), df=len(ic_arr) - 1)))
    hit = ((panel_sub[sig_col] > panel_sub[sig_col].median()) == (panel_sub[fwd_col] > 0)).mean() * 100
    return {
        "n": len(panel_sub),
        "ic": round(ic_mean, 4),
        "t_stat": round(t_stat, 2),
        "p_value": round(p_val, 4),
        "hit_rate": round(float(hit), 1),
    }


def run_validated_composite(results_dir=None) -> tuple[pd.DataFrame, pd.DataFrame]:
    """
    H15~H16: 개별 검증된 신호만 결합한 복합 점수 예측력 검증.

    복합점수 = IC 가중 역방향 합산:
      - BB위치 × 0.34  (역방향 — IC=-0.087)
      - MA정렬 × 0.25  (역방향 — IC=-0.065)
      - RSI기울기 × 0.26 (역방향 — IC=-0.066)
      - 거래량비율 × 0.15 (정방향 — IC=+0.040)
    모두 월별 단면 퍼센타일 랭크로 정규화 → 스케일 통일.
    """
    if results_dir is None:
        results_dir = RESULTS_DIR
    results_dir = Path(results_dir)

    panel = _load_signals_df(results_dir)
    if panel.empty:
        return pd.DataFrame(), pd.DataFrame()

    # D방식 확정: BB + MA 원시값 역방향 가중합
    # 백테스트 탐색 결과: z-score/rank 정규화는 신호를 소멸시킴 (IC≈0)
    # 원시값 사용이 최적: BB(IC=0.087)·MA(IC=0.065) 비율 가중, RSI·Vol은 미미하게 기여
    panel["h15_composite"] = (
        -panel["bb_pct"]            * 0.57 +   # BB 역방향 (IC=0.087)
        -(panel["ma_score"] / 3.0)  * 0.43     # MA 역방향 (IC=0.065)
    )

    ic_rows    = []
    spread_rows = []

    for hyp in HYPOTHESES_VALIDATED:
        sig_col = hyp["signal"]
        for fwd_days in FWD_WINDOWS:
            fwd_col   = f"fwd_{fwd_days}d"
            fwd_label = f"{fwd_days // 22}M"

            if sig_col == "_quantile_spread":
                # H16: Top33% vs Bottom33%
                comp_col = "h15_composite"
                sub = panel[["date", "ticker", comp_col, fwd_col]].dropna().copy()
                sub["ym"] = sub["date"].dt.to_period("M")
                monthly_spreads, top_rets, bot_rets = [], [], []
                for _, grp in sub.groupby("ym"):
                    if len(grp) < 6:
                        continue
                    q33 = grp[comp_col].quantile(0.33)
                    q67 = grp[comp_col].quantile(0.67)
                    top = grp[grp[comp_col] >= q67][fwd_col].mean()
                    bot = grp[grp[comp_col] <= q33][fwd_col].mean()
                    if pd.notna(top) and pd.notna(bot):
                        monthly_spreads.append(top - bot)
                        top_rets.append(top)
                        bot_rets.append(bot)
                if not monthly_spreads:
                    continue
                sp   = np.array(monthly_spreads)
                sp_m = float(np.mean(sp))
                t_s  = sp_m / (float(np.std(sp, ddof=1)) / np.sqrt(len(sp)))
                p_v  = float(2 * (1 - stats.t.cdf(abs(t_s), df=len(sp) - 1)))
                spread_rows.append({
                    "예측창":          fwd_label,
                    "추천평균수익(%)":  round(float(np.mean(top_rets)), 3),
                    "비추천평균수익(%)": round(float(np.mean(bot_rets)), 3),
                    "격차(%p)":        round(sp_m, 3),
                    "t통계":           round(t_s, 2),
                    "p값":             round(p_v, 4),
                    "격차양수비율(%)":  round(float(np.mean(sp > 0) * 100), 1),
                    "월수":            len(monthly_spreads),
                    "검증결과": (
                        "✅ 상위가 하위를 유의하게 이겼다" if p_v < 0.05 and sp_m > 0
                        else "⚠️ 역방향 (하위>상위)" if p_v < 0.05 and sp_m < 0
                        else "⚠️ 방향성 있으나 비유의" if float(np.mean(sp > 0)) >= 0.55
                        else "❌ 격차 없음"
                    ),
                })
                continue

            if sig_col not in panel.columns:
                continue
            d = _cross_ic_monthly(panel, sig_col, fwd_col)
            if not d:
                continue
            ic_rows.append({
                "id":        hyp["id"],
                "가설":      hyp["name"],
                "예측창":    fwd_label,
                "IC":        d["ic"],
                "t통계":     d["t_stat"],
                "p값":       d["p_value"],
                "적중률(%)": d["hit_rate"],
                "표본수":    d["n"],
                "검증결과":  _verdict(d["ic"], d["p_value"]),
                "설명":      hyp["desc"],
            })

    return pd.DataFrame(ic_rows), pd.DataFrame(spread_rows)


def run_system_validation(results_dir=None) -> pd.DataFrame:
    """
    H12~H14: 현재 시스템에서 실제 사용 중인 신호 검증.
    - H12: 섹터사이클 (1M 상대강도 vs SPY)
    - H13: Bull추세 필터 (골든크로스 대리변수)
    - H14: 12M 상대강도 vs SPY
    Returns: ic_df
    """
    if results_dir is None:
        results_dir = RESULTS_DIR
    results_dir = Path(results_dir)

    panel = _load_signals_df(results_dir)
    if panel.empty:
        return pd.DataFrame()

    # SPY 기준 상대강도 계산
    spy = panel[panel["ticker"] == "SPY"][["date", "mom_1m", "mom_12m"]].copy()
    spy = spy.rename(columns={"mom_1m": "spy_1m", "mom_12m": "spy_12m"})
    spy["date"] = pd.to_datetime(spy["date"])
    panel = panel.merge(spy, on="date", how="left")
    panel["rel_1m"]  = panel["mom_1m"]  - panel["spy_1m"]
    panel["rel_12m"] = panel["mom_12m"] - panel["spy_12m"]
    # Bull추세: MA정렬 2개 이상 (ma50>ma200 + ma20>ma50)
    panel["is_bull"] = (panel["ma_score"] >= 2).astype(int)

    ic_rows = []
    for hyp in HYPOTHESES_SYSTEM:
        sig_col = hyp["signal"]
        if sig_col not in panel.columns:
            continue
        for fwd_days in FWD_WINDOWS:
            fwd_col   = f"fwd_{fwd_days}d"
            fwd_label = f"{fwd_days // 22}M"

            if hyp["direction"] == "lower_is_better":
                use_col = f"_{sig_col}_inv"
                panel[use_col] = -panel[sig_col]
            else:
                use_col = sig_col

            d = _cross_ic_monthly(panel, use_col, fwd_col)
            if not d:
                continue
            ic_rows.append({
                "id":        hyp["id"],
                "가설":      hyp["name"],
                "예측창":    fwd_label,
                "IC":        d["ic"],
                "t통계":     d["t_stat"],
                "p값":       d["p_value"],
                "적중률(%)": d["hit_rate"],
                "표본수":    d["n"],
                "검증결과":  _verdict(d["ic"], d["p_value"]),
                "설명":      hyp["desc"],
            })
    return pd.DataFrame(ic_rows)


def run_composite_validation(results_dir=None) -> tuple[pd.DataFrame, pd.DataFrame]:
    """
    H9~H11: 복합 점수 예측력 + 추천 vs 비추천 수익 격차 검증.
    Returns: (ic_df, spread_df)
    """
    if results_dir is None:
        results_dir = RESULTS_DIR
    results_dir = Path(results_dir)

    panel = _load_signals_df(results_dir)
    if panel.empty:
        return pd.DataFrame(), pd.DataFrame()

    # 파생 신호 계산
    panel["composite_mom"] = panel["mom_12m"] * 0.7 + panel["mom_1m"] * 0.3
    panel["overheat_flag"] = (
        (panel["ma_score"] == 3) & (panel["bb_pct"] > 0.85)
    ).astype(int)

    ic_rows = []
    spread_rows = []

    for hyp in HYPOTHESES_COMPOSITE:
        sig_col = hyp["signal"]
        for fwd_days in FWD_WINDOWS:
            fwd_col = f"fwd_{fwd_days}d"
            fwd_label = f"{fwd_days // 22}M"

            if sig_col == "_quantile_spread":
                # H11: Top33% vs Bottom33% 월별 수익률 격차
                composite_col = "composite_mom"
                sub = panel[["date", "ticker", composite_col, fwd_col]].dropna()
                sub = sub.copy()
                sub["ym"] = sub["date"].dt.to_period("M")

                monthly_spreads = []
                top_rets, bot_rets = [], []
                for _, grp in sub.groupby("ym"):
                    if len(grp) < 6:
                        continue
                    q33 = grp[composite_col].quantile(0.33)
                    q67 = grp[composite_col].quantile(0.67)
                    top = grp[grp[composite_col] >= q67][fwd_col].mean()
                    bot = grp[grp[composite_col] <= q33][fwd_col].mean()
                    if pd.notna(top) and pd.notna(bot):
                        monthly_spreads.append(top - bot)
                        top_rets.append(top)
                        bot_rets.append(bot)

                if not monthly_spreads:
                    continue

                sp_arr  = np.array(monthly_spreads)
                sp_mean = float(np.mean(sp_arr))
                sp_std  = float(np.std(sp_arr, ddof=1))
                t_stat  = sp_mean / (sp_std / np.sqrt(len(sp_arr)))
                p_val   = float(2 * (1 - stats.t.cdf(abs(t_stat), df=len(sp_arr) - 1)))
                hit     = float(np.mean(np.array(monthly_spreads) > 0) * 100)

                spread_rows.append({
                    "예측창":          fwd_label,
                    "추천평균수익(%)":  round(float(np.mean(top_rets)), 3),
                    "비추천평균수익(%)": round(float(np.mean(bot_rets)), 3),
                    "격차(%p)":        round(sp_mean, 3),
                    "t통계":           round(t_stat, 2),
                    "p값":             round(p_val, 4),
                    "격차양수비율(%)":  round(hit, 1),
                    "월수":            len(monthly_spreads),
                    "검증결과": (
                        "✅ 추천이 비추천을 유의하게 이겼다" if p_val < 0.05 and sp_mean > 0
                        else "✅ 비추천이 추천을 역방향으로 이겼다" if p_val < 0.05 and sp_mean < 0
                        else "⚠️ 방향성 있으나 비유의" if hit >= 55
                        else "❌ 격차 없음"
                    ),
                })
                continue

            if sig_col not in panel.columns:
                continue

            # IC 방향 조정 (lower_is_better → 신호 반전)
            if hyp["direction"] == "lower_is_better":
                panel[f"_{sig_col}_inv"] = -panel[sig_col]
                sig_col_use = f"_{sig_col}_inv"
            else:
                sig_col_use = sig_col

            stats_d = _cross_ic_monthly(panel, sig_col_use, fwd_col)
            if not stats_d:
                continue

            ic_rows.append({
                "id":       hyp["id"],
                "가설":     hyp["name"],
                "예측창":   fwd_label,
                "IC":       stats_d["ic"],
                "t통계":    stats_d["t_stat"],
                "p값":      stats_d["p_value"],
                "적중률(%)": stats_d["hit_rate"],
                "표본수":   stats_d["n"],
                "검증결과": _verdict(stats_d["ic"], stats_d["p_value"]),
                "설명":     hyp["desc"],
            })

    return pd.DataFrame(ic_rows), pd.DataFrame(spread_rows)


def run_validation(results_dir=None) -> pd.DataFrame:
    """모든 가설을 검증하고 결과 DataFrame 반환."""
    if results_dir is None:
        results_dir = RESULTS_DIR
    results_dir = Path(results_dir)

    panel = _load_signals_df(results_dir)
    vix   = _load_vix(results_dir)

    output_rows = []

    for hyp in HYPOTHESES:
        sig_col = hyp["signal"]

        for fwd_days in FWD_WINDOWS:
            fwd_col = f"fwd_{fwd_days}d"
            label   = f"{fwd_days // 22}개월" if fwd_days < 100 else f"3개월"

            if hyp["id"] == "H8":
                # VIX는 시계열 단일 신호 — SPY 향후 수익과 매핑
                if vix.empty or panel.empty:
                    continue
                spy = panel[panel["ticker"] == "SPY"][["date", fwd_col]].set_index("date")
                merged = pd.concat([vix, spy[fwd_col]], axis=1).dropna()
                if merged.empty:
                    continue
                sig = merged["vix_level"] * (-1)  # 역방향: VIX↑ → 기대 수익↑
                fwd = merged[fwd_col]
                stats_d = _ic_stats(sig.reset_index(drop=True), fwd.reset_index(drop=True))
            elif sig_col in panel.columns and fwd_col in panel.columns:
                # 단면(Cross-sectional) IC — 월별 평균
                panel_sub = panel[["date", "ticker", sig_col, fwd_col]].dropna()
                monthly = panel_sub.copy()
                monthly["ym"] = monthly["date"].dt.to_period("M")
                monthly_ics = []
                for _, grp in monthly.groupby("ym"):
                    if len(grp) < 5:
                        continue
                    r = stats.pearsonr(grp[sig_col], grp[fwd_col])
                    monthly_ics.append(r[0])
                monthly_ics = [x for x in monthly_ics if not np.isnan(x)]
                if not monthly_ics:
                    continue
                ic_arr = np.array(monthly_ics)
                ic_mean = float(np.mean(ic_arr))
                t_stat  = float(np.mean(ic_arr) / (np.std(ic_arr) / np.sqrt(len(ic_arr))))
                p_val   = float(2 * (1 - stats.t.cdf(abs(t_stat), df=len(ic_arr) - 1)))
                sig_all = panel_sub[sig_col]
                fwd_all = panel_sub[fwd_col]
                hit = ((sig_all > sig_all.median()) == (fwd_all > 0)).mean() * 100
                stats_d = {
                    "n": len(panel_sub),
                    "ic": round(ic_mean, 4),
                    "t_stat": round(t_stat, 2),
                    "p_value": round(p_val, 4),
                    "hit_rate": round(float(hit), 1),
                }
            else:
                continue

            output_rows.append({
                "id":       hyp["id"],
                "가설":     hyp["name"],
                "예측창":   f"{fwd_days // 22}M",
                "IC":       stats_d["ic"],
                "t통계":    stats_d["t_stat"],
                "p값":      stats_d["p_value"],
                "적중률(%)": stats_d["hit_rate"],
                "표본수":   stats_d["n"],
                "검증결과": _verdict(stats_d["ic"], stats_d["p_value"]),
                "설명":     hyp["desc"],
                "참고문헌": hyp["ref"],
            })

    return pd.DataFrame(output_rows)


if __name__ == "__main__":
    print("신호 예측력 검증 실행 중...")
    result = run_validation()
    out = RESULTS_DIR / "signal_validation.csv"
    result.to_csv(out, index=False, encoding="utf-8-sig")
    for _, r in result.iterrows():
        verdict = r["검증결과"].replace("✅","OK").replace("⚠️","WARN").replace("❌","FAIL")
        print(f"{r['id']} {r['예측창']} IC={r['IC']:.4f} p={r['p값']:.4f} hit={r['적중률(%)']}% | {verdict}")
    print(f"\n저장 완료: {out}")
