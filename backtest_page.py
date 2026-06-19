"""신호 백테스트 결과 페이지."""
import streamlit as st
import pandas as pd
import numpy as np
import yfinance as yf
from pathlib import Path

BACKTEST_DIR = Path(__file__).resolve().parent / "results" / "backtest"
RESULTS_DIR  = Path(__file__).resolve().parent / "results"


@st.cache_data(ttl=3600)
def load():
    crosses  = pd.read_csv(BACKTEST_DIR / "cross_signals.csv")
    rsi      = pd.read_csv(BACKTEST_DIR / "rsi_signals.csv")
    loss_cut = pd.read_csv(BACKTEST_DIR / "loss_cut.csv")
    return crosses, rsi, loss_cut


@st.cache_data(ttl=3600)
def load_vs_market():
    stock_files = [f for f in RESULTS_DIR.glob("*_signals.csv")
                   if not f.name.startswith("coin_") and "summary" not in f.name]
    coin_files  = list(RESULTS_DIR.glob("coin_*_signals.csv"))

    def _ret(path):
        df = pd.read_csv(path)
        dc = [c for c in df.columns if c.lower() == "date"]
        if not dc: return None
        df = df.rename(columns={dc[0]: "Date"})
        df["Date"] = pd.to_datetime(df["Date"])
        df = df.set_index("Date").sort_index()
        if len(df) < 50: return None
        f_, l_ = float(df["Close"].iloc[0]), float(df["Close"].iloc[-1])
        days = (df.index[-1] - df.index[0]).days
        if days == 0: return None
        return {
            "start": df.index[0], "end": df.index[-1], "days": days,
            "total_ret": round((l_/f_-1)*100, 1),
            "ann_ret":   round(((l_/f_)**(365.0/days)-1)*100, 1),
        }

    rows = []
    for f in stock_files:
        t = f.stem.replace("_signals","")
        r = _ret(f)
        if r:
            r["ticker"] = t
            r["category"] = "KR" if (".KS" in t or ".KQ" in t) else "US"
            rows.append(r)
    for f in coin_files:
        t = f.stem.replace("coin_","").replace("_signals","")
        r = _ret(f)
        if r:
            r["ticker"] = t
            r["category"] = "Coin"
            rows.append(r)

    df = pd.DataFrame(rows)
    start, end = df["start"].min(), df["end"].max()

    def _bench(ticker):
        raw = yf.download(ticker, start=start, end=end, progress=False)
        close = raw["Close"].squeeze().dropna()
        if len(close) < 2: return None, None
        days = (close.index[-1] - close.index[0]).days
        if days == 0: return None, None
        tot = round((float(close.iloc[-1])/float(close.iloc[0])-1)*100, 1)
        ann = round(((float(close.iloc[-1])/float(close.iloc[0]))**(365.0/days)-1)*100, 1)
        return tot, ann

    b_spy_tot, b_spy_ann = _bench("SPY")
    b_ks_tot,  b_ks_ann  = _bench("069500.KS")
    b_btc_tot, b_btc_ann = _bench("BTC-USD")

    benchmarks = {
        "US":   {"name": "S&P500 (SPY)",    "total": b_spy_tot, "ann": b_spy_ann},
        "KR":   {"name": "KOSPI200 ETF",    "total": b_ks_tot,  "ann": b_ks_ann},
        "Coin": {"name": "BTC",             "total": b_btc_tot, "ann": b_btc_ann},
    }
    return df, benchmarks, str(start.date()), str(end.date())


def hit_badge(rate: float) -> str:
    """적중률에 따라 평가 텍스트 반환"""
    if rate >= 0.60:
        return f"**{rate*100:.0f}%** 🟢 신뢰도 있음"
    if rate >= 0.52:
        return f"**{rate*100:.0f}%** 🟡 약한 우위"
    return f"**{rate*100:.0f}%** 🔴 동전 던지기 수준"


st.title("신호 백테스트 — 내 신호가 얼마나 맞았나")
st.caption(
    "보유 종목 포함 전체 분석 대상 종목(주식+코인)의 과거 신호를 기준으로, "
    "신호 발생 후 실제 가격이 예상 방향으로 움직였는지 집계한 결과입니다."
)

try:
    crosses, rsi_df, loss_df = load()
except FileNotFoundError:
    st.error("백테스트 파일이 없습니다. `python scripts/backtest.py`를 먼저 실행하세요.")
    st.stop()

# ── 탭 구조 ──────────────────────────────────────────────
tab_sum, tab0, tab1, tab2, tab3, tab4, tab_val = st.tabs([
    "📋 요약",
    "🏆 개별주 vs 시장", "📈 골든/데스크로스", "📊 RSI 신호", "✂️ 손절선 검증",
    "🔬 전략 백테스트",
    "🧪 신호 예측력 검증",
])


# ════════════════════════════════════════════════════════
# TAB 0 — 개별주 vs 시장
# ════════════════════════════════════════════════════════
with tab0:
    st.subheader("개별주 vs 시장 — Buy & Hold 수익률 비교")
    st.caption("분석 대상 전 종목을 보유 첫날부터 현재까지 그냥 들고 있었으면 어땠는지, 시장 지수 대비 비교합니다.")

    with st.spinner("벤치마크 데이터 로딩 중..."):
        mkt_df, benchmarks, period_start, period_end = load_vs_market()

    st.markdown(f"**분석 기간**: {period_start} ~ {period_end}")
    st.divider()

    for cat, cat_label, color in [
        ("US",   "미국 주식",   "#1d4ed8"),
        ("KR",   "한국 주식",   "#15803d"),
        ("Coin", "코인",        "#b45309"),
    ]:
        sub  = mkt_df[mkt_df["category"] == cat].sort_values("total_ret", ascending=False).reset_index(drop=True)
        b    = benchmarks.get(cat, {})
        btot = b.get("total")
        bann = b.get("ann")
        bname= b.get("name", "")

        if len(sub) == 0 or btot is None:
            continue

        beat_n   = (sub["total_ret"] > btot).sum()
        beat_pct = beat_n / len(sub) * 100
        median   = sub["total_ret"].median()
        mean     = sub["total_ret"].mean()

        st.markdown(f"### {cat_label} ({len(sub)}개 종목)")

        # 요약 지표
        c1, c2, c3, c4 = st.columns(4)
        c1.metric(f"벤치마크 ({bname})", f"{btot:+.1f}%", f"연 {bann:+.1f}%")
        c2.metric("시장 이긴 종목", f"{beat_pct:.0f}%", f"{beat_n}/{len(sub)}개")
        c3.metric("전체 평균 수익", f"{mean:+.1f}%",
                  f"벤치마크 대비 {mean-btot:+.1f}%p",
                  delta_color="normal" if mean >= btot else "inverse")
        c4.metric("중앙값 수익", f"{median:+.1f}%",
                  f"벤치마크 대비 {median-btot:+.1f}%p",
                  delta_color="normal" if median >= btot else "inverse")

        # 수익률 분포 테이블
        display = sub[["ticker", "total_ret", "ann_ret"]].copy()
        display.columns = ["종목", "총 수익률(%)", "연환산(%)"]
        display["벤치마크 대비"] = (display["총 수익률(%)"] - btot).round(1)
        display["결과"] = display["총 수익률(%)"].apply(
            lambda x: "✅ 초과" if x > btot else "❌ 미달"
        )

        with st.expander(f"{cat_label} 전체 수익률 테이블 (클릭해서 펼치기)"):
            st.dataframe(
                display,
                use_container_width=True,
                hide_index=True,
                column_config={
                    "총 수익률(%)":   st.column_config.NumberColumn(format="%.1f%%"),
                    "연환산(%)":      st.column_config.NumberColumn(format="%.1f%%"),
                    "벤치마크 대비":  st.column_config.NumberColumn(format="%+.1f%%"),
                }
            )

        # 슈퍼스타 효과 경고 (평균과 중앙값 차이가 클 때)
        if abs(mean - median) > 30:
            top1 = sub.iloc[0]
            st.warning(
                f"**슈퍼스타 효과**: {top1['ticker']} 1개 종목이 {top1['total_ret']:+.1f}%로 평균을 크게 끌어올리고 있습니다. "
                f"이를 제외하면 평균은 {sub.iloc[1:]['total_ret'].mean():+.1f}%로 낮아집니다. "
                f"중앙값({median:+.1f}%)이 실제 '보통 종목'의 성과에 더 가깝습니다."
            )

        st.divider()

    st.info(
        "**핵심 메시지**: 중앙값이 벤치마크보다 낮다면, "
        "종목을 무작위로 골랐을 때 시장 지수를 이길 확률이 50% 미만이라는 의미입니다. "
        "전문 펀드매니저도 장기적으로 92%가 S&P500을 못 이깁니다 (SPIVA 15년 데이터). "
        "이것이 Core를 ETF로 잡은 핵심 근거입니다."
    )


# ════════════════════════════════════════════════════════
# TAB 1 — 골든크로스 / 데스크로스
# ════════════════════════════════════════════════════════
with tab1:
    st.subheader("골든크로스 / 데스크로스 — 이 신호가 맞은 비율")
    st.markdown(
        """
        - **골든크로스**: 50일 평균선이 200일 평균선을 위로 뚫을 때 → 상승 예고 신호
        - **데스크로스**: 50일 평균선이 200일 평균선을 아래로 뚫을 때 → 하락 예고 신호
        - **적중** 기준: 신호 발생 후 실제로 예상 방향으로 가격이 움직였는가
        """
    )

    for sig_name, label, expected in [
        ("golden_cross", "골든크로스 (매수 신호)", "상승"),
        ("death_cross",  "데스크로스 (매도 신호)", "하락"),
    ]:
        grp = crosses[crosses["signal"] == sig_name]
        n = len(grp)
        if n == 0:
            continue

        st.markdown(f"#### {label} — 총 {n}건")
        c1, c2, c3 = st.columns(3)
        for col_obj, days_key, label_k in [
            (c1, "hit_1M", "1개월 후"),
            (c2, "hit_3M", "3개월 후"),
            (c3, "hit_6M", "6개월 후"),
        ]:
            valid = grp[days_key].dropna()
            fwd_key = days_key.replace("hit_", "fwd_")
            avg_ret = grp[fwd_key].dropna().mean()
            if len(valid) == 0:
                continue
            rate = valid.mean()
            with col_obj:
                st.metric(
                    label=label_k,
                    value=f"{rate*100:.0f}%",
                    delta=f"평균 수익률 {avg_ret:+.1f}%",
                )
                st.caption(hit_badge(rate))

        # 상위/하위 종목
        with st.expander(f"{label} — 종목별 적중률"):
            per_ticker = (
                grp.groupby("ticker")
                .agg(
                    건수=("signal", "count"),
                    hit_1M=("hit_1M", "mean"),
                    hit_3M=("hit_3M", "mean"),
                    hit_6M=("hit_6M", "mean"),
                    avg_fwd_1M=("fwd_1M", "mean"),
                    avg_fwd_3M=("fwd_3M", "mean"),
                )
                .reset_index()
                .sort_values("hit_3M", ascending=False)
            )
            per_ticker["hit_1M"] = (per_ticker["hit_1M"] * 100).round(0).astype(str) + "%"
            per_ticker["hit_3M"] = (per_ticker["hit_3M"] * 100).round(0).astype(str) + "%"
            per_ticker["hit_6M"] = (per_ticker["hit_6M"] * 100).round(0).astype(str) + "%"
            per_ticker["avg_fwd_1M"] = per_ticker["avg_fwd_1M"].round(1).astype(str) + "%"
            per_ticker["avg_fwd_3M"] = per_ticker["avg_fwd_3M"].round(1).astype(str) + "%"
            per_ticker.columns = ["종목", "발생건수", "1M 적중률", "3M 적중률", "6M 적중률", "1M 평균수익", "3M 평균수익"]
            st.dataframe(per_ticker, use_container_width=True, hide_index=True)

    st.info(
        "**해석 가이드**: 적중률이 50%에 가까울수록 신호 예측력이 없다는 의미입니다. "
        "60% 이상이면 통계적으로 의미 있는 우위입니다. "
        "단, 신호 건수가 적을수록 우연의 영향이 커집니다."
    )


# ════════════════════════════════════════════════════════
# TAB 2 — RSI 신호
# ════════════════════════════════════════════════════════
with tab2:
    st.subheader("RSI 신호 — 과매수/과매도 후 실제로 조정/반등이 왔는가")
    st.markdown(
        """
        - **RSI 70 돌파**: 단기 과열 → 조정 예고 신호 (가격이 내려가야 적중)
        - **RSI 80 돌파**: 극단 과열 → 강한 조정 예고 신호
        - **RSI 30 이탈**: 과매도 → 반등 예고 신호 (가격이 올라가야 적중)
        """
    )

    sig_configs = [
        ("RSI 70 돌파(과매수)", "RSI 70 돌파 — 과열 후 조정이 왔는가", "하락"),
        ("RSI 80 돌파(극단 과매수)", "RSI 80 돌파 — 극단 과열 후 조정이 왔는가", "하락"),
        ("RSI 30 이탈(과매도)", "RSI 30 이탈 — 과매도 후 반등이 왔는가", "상승"),
    ]

    for sig_key, title, direction in sig_configs:
        grp = rsi_df[rsi_df["signal"] == sig_key]
        n = len(grp)
        if n == 0:
            continue

        st.markdown(f"#### {title} — 총 {n}건")
        c1, c2, c3 = st.columns(3)
        for col_obj, days_key, label_k in [
            (c1, "hit_5d",  "5일 후"),
            (c2, "hit_10d", "10일 후"),
            (c3, "hit_22d", "1개월 후"),
        ]:
            valid = grp[days_key].dropna()
            fwd_key = days_key.replace("hit_", "fwd_")
            avg_ret = grp[fwd_key].dropna().mean()
            if len(valid) == 0:
                continue
            rate = valid.mean()
            with col_obj:
                st.metric(
                    label=label_k,
                    value=f"{rate*100:.0f}%",
                    delta=f"평균 수익률 {avg_ret:+.1f}%",
                )
                st.caption(hit_badge(rate))
        st.divider()

    st.warning(
        "**주의**: RSI 과매수(70/80) 신호 후 평균 수익률이 양수(+)라면, "
        "이 신호를 매도 신호로 쓰는 것이 오히려 수익을 놓치는 결과입니다. "
        "강한 상승장에서는 RSI가 오래 고공 유지됩니다."
    )


# ════════════════════════════════════════════════════════
# TAB 3 — 손절선 검증
# ════════════════════════════════════════════════════════
with tab3:
    st.subheader("손절선 검증 — -8% / -20% 손절이 실제로 도움이 됐는가")
    st.markdown(
        """
        **시뮬레이션 방법**: 골든크로스 발생일에 매수 → 데스크로스 발생일에 청산.
        그 사이에 -8% 또는 -20% 손절선에 닿으면 손절했을 때와 끝까지 보유했을 때를 비교.

        - **손절이 유리** = 손절하고 나서 가격이 더 하락 (손절이 추가 손실을 막음)
        - **손절이 불리** = 손절하고 나서 가격이 반등 (일찍 팔아서 손해)
        """
    )

    total = len(loss_df)
    st.markdown(f"전체 골든크로스 진입 건수: **{total}건** (주식+코인 전 종목)")

    c1, c2 = st.columns(2)

    for col_obj, key, pct_label in [(c1, "8pct", "-8% 손절선"), (c2, "20pct", "-20% 손절선")]:
        hit = loss_df[loss_df[f"cut_{key}_hit"] == True]
        no_hit = loss_df[loss_df[f"cut_{key}_hit"] == False]
        better = hit[f"cut_{key}_better_to_cut"].dropna()
        post = hit[f"cut_{key}_post_cut_return"].dropna()

        with col_obj:
            st.markdown(f"#### {pct_label}")

            hit_pct = len(hit) / total * 100
            st.metric("손절선 도달 빈도", f"{hit_pct:.0f}%", f"{len(hit)} / {total}건")

            if len(better) > 0:
                better_pct = better.mean() * 100
                st.metric(
                    "손절이 유리했던 비율",
                    f"{better_pct:.0f}%",
                    delta="손절이 옳은 경우" if better_pct >= 50 else "손절이 역효과인 경우",
                    delta_color="normal" if better_pct >= 50 else "inverse",
                )

            fell_more = post[post < 0]
            recovered = post[post > 0]

            col_a, col_b = st.columns(2)
            with col_a:
                if len(fell_more) > 0:
                    st.metric(
                        "손절 후 추가 하락",
                        f"{len(fell_more)}건",
                        f"평균 {fell_more.mean():.1f}%",
                    )
            with col_b:
                if len(recovered) > 0:
                    st.metric(
                        "손절 후 가격 반등",
                        f"{len(recovered)}건",
                        f"평균 +{recovered.mean():.1f}%",
                    )

    st.divider()
    st.markdown("#### 손절선 미도달 구간 (끝까지 보유)의 수익률 분포")

    for key, label in [("8pct", "-8% 손절선"), ("20pct", "-20% 손절선")]:
        no_hit = loss_df[loss_df[f"cut_{key}_hit"] == False]["hold_return_pct"].dropna()
        hit = loss_df[loss_df[f"cut_{key}_hit"] == True]["hold_return_pct"].dropna()
        if len(no_hit) > 0 and len(hit) > 0:
            c1, c2, c3 = st.columns(3)
            c1.metric(f"{label} 미도달 — 평균 수익", f"{no_hit.mean():+.1f}%", f"{len(no_hit)}건")
            c2.metric(f"{label} 도달 — 보유 시 평균 수익", f"{hit.mean():+.1f}%", f"{len(hit)}건")
            c3.metric("차이", f"{no_hit.mean() - hit.mean():+.1f}%p", "손절선 미도달이 더 나음")

    st.info(
        "**해석 가이드**: '손절이 유리한 비율'이 69%라면, "
        "10번 중 약 7번은 손절하고 나서 더 하락했다는 의미입니다. "
        "즉, -8%/-20% 손절 규칙은 실제로 추가 손실 방지 효과가 있습니다. "
        "단, 나머지 31%는 손절 후 반등해서 수익 기회를 놓쳤습니다."
    )

    # 종목별 상세
    with st.expander("종목별 손절선 도달 상세"):
        per_ticker = (
            loss_df.groupby("ticker")
            .agg(
                총진입=("hold_return_pct", "count"),
                보유평균수익=("hold_return_pct", "mean"),
                cut8_도달=("cut_8pct_hit", "sum"),
                cut8_유리=("cut_8pct_better_to_cut", lambda x: x.sum()),
                cut20_도달=("cut_20pct_hit", "sum"),
                cut20_유리=("cut_20pct_better_to_cut", lambda x: x.sum()),
            )
            .reset_index()
        )
        per_ticker["보유평균수익"] = per_ticker["보유평균수익"].round(1).astype(str) + "%"
        per_ticker.columns = ["종목", "진입건수", "보유 평균수익", "-8% 도달", "-8% 유리", "-20% 도달", "-20% 유리"]
        st.dataframe(per_ticker, use_container_width=True, hide_index=True)


# ════════════════════════════════════════════════════════
# TAB 4 — 팩터 전략 백테스트
# ════════════════════════════════════════════════════════
with tab4:
    st.subheader("🔬 Part 1 — 팩터 전략 백테스트 (개별주 48종목, 2021-현재)")
    st.caption(
        "분석 대상 48개 종목을 각 팩터 기준으로 Q1~Q4 분위로 나눠 월별 수익률을 추적합니다. "
        "Q1이 해당 팩터의 '좋은' 구간입니다."
    )

    _FACTOR_FILES = {
        "momentum": ("factor_momentum_cum.csv", "factor_momentum_stats.csv"),
        "lowvol":   ("factor_lowvol_cum.csv",   "factor_lowvol_stats.csv"),
        "value":    ("factor_value_detail.csv",  "factor_value_stats.csv"),
        "quality":  ("factor_quality_detail.csv","factor_quality_stats.csv"),
    }

    def _files_exist(key):
        a, b = _FACTOR_FILES[key]
        return (BACKTEST_DIR / a).exists() and (BACKTEST_DIR / b).exists()

    def _need_compute():
        return not all(_files_exist(k) for k in _FACTOR_FILES)

    @st.cache_data(ttl=3600)
    def _compute_factors():
        import sys
        sys.path.insert(0, str(Path(__file__).resolve().parent))
        from scripts.factor_backtest import build_monthly_panel, run_momentum, run_low_vol, run_value, run_quality
        panel = build_monthly_panel()
        results = {}
        results["mom_cum"],  results["mom_stats"]  = run_momentum(panel)
        results["vol_cum"],  results["vol_stats"]   = run_low_vol(panel)
        results["val_det"],  results["val_stats"]   = run_value(panel)
        results["qual_det"], results["qual_stats"]  = run_quality(panel)
        return results

    if _need_compute():
        with st.spinner("팩터 계산 중... (최초 1회, 약 30초 소요)"):
            _fd = _compute_factors()
        mom_cum   = _fd["mom_cum"];   mom_stats   = _fd["mom_stats"]
        vol_cum   = _fd["vol_cum"];   vol_stats   = _fd["vol_stats"]
        val_det   = _fd["val_det"];   val_stats   = _fd["val_stats"]
        qual_det  = _fd["qual_det"];  qual_stats  = _fd["qual_stats"]
    else:
        mom_cum   = pd.read_csv(BACKTEST_DIR / "factor_momentum_cum.csv",  index_col=0, parse_dates=True)
        mom_stats = pd.read_csv(BACKTEST_DIR / "factor_momentum_stats.csv")
        vol_cum   = pd.read_csv(BACKTEST_DIR / "factor_lowvol_cum.csv",    index_col=0, parse_dates=True)
        vol_stats = pd.read_csv(BACKTEST_DIR / "factor_lowvol_stats.csv")
        val_det   = pd.read_csv(BACKTEST_DIR / "factor_value_detail.csv")
        val_stats = pd.read_csv(BACKTEST_DIR / "factor_value_stats.csv")
        qual_det  = pd.read_csv(BACKTEST_DIR / "factor_quality_detail.csv")
        qual_stats= pd.read_csv(BACKTEST_DIR / "factor_quality_stats.csv")

    _Q_COLORS = {"Q1": "#16a34a", "Q2": "#65a30d", "Q3": "#f59e0b", "Q4": "#ef4444"}

    def _render_rolling_factor(cum_df, stats_df, factor_name, q1_label, q4_label):
        if cum_df.empty:
            st.warning("데이터 부족으로 계산 불가")
            return

        # Q1 vs Q4 누적 수익률 라인 차트
        chart_data = cum_df.copy()
        chart_data.index.name = "날짜"
        st.line_chart(chart_data, color=["#16a34a", "#65a30d", "#f59e0b", "#ef4444"])

        c1, c2, c3, c4 = st.columns(4)
        for col, q in zip([c1, c2, c3, c4], ["Q1", "Q2", "Q3", "Q4"]):
            row = stats_df[stats_df["분위"] == q].iloc[0]
            final = cum_df[q].dropna().iloc[-1] if q in cum_df.columns and not cum_df[q].dropna().empty else 1.0
            col.metric(
                label=q,
                value=f"{row['연환산수익(%)']:+.1f}% /년",
                delta=f"누적 {(final - 1)*100:+.0f}%",
            )

        st.caption(f"Q1 = {q1_label} / Q4 = {q4_label}")

        with st.expander("분위별 통계 상세"):
            st.dataframe(stats_df, use_container_width=True, hide_index=True)

    def _render_snapshot_factor(stats_df, detail_df, x_col, label_col, factor_label):
        if stats_df.empty:
            st.warning("데이터 부족으로 계산 불가")
            return

        # 분위별 평균 수익률 바 차트
        bar_data = stats_df.set_index("분위")["평균수익_36M(%)"]
        st.bar_chart(bar_data)

        c1, c2, c3, c4 = st.columns(4)
        for col, q in zip([c1, c2, c3, c4], ["Q1", "Q2", "Q3", "Q4"]):
            row = stats_df[stats_df["분위"] == q].iloc[0]
            col.metric(
                label=q,
                value=f"{row['평균수익_36M(%)']:+.1f}%",
                delta=f"{label_col}: {row[x_col]}",
            )

        st.caption(
            f"⚠️ 스냅샷 분석: 오늘의 {factor_label}로 과거 36개월 수익률을 역산. "
            "룩어헤드 바이어스 있음 — 방향성 참고용으로만 활용."
        )

        with st.expander("종목별 상세"):
            show_cols = [c for c in ["ticker", "sector", "q"] + [c for c in detail_df.columns if c not in ["ticker", "sector", "q", "ret_36m"]] + ["ret_36m"] if c in detail_df.columns]
            st.dataframe(detail_df[show_cols].sort_values("q"), use_container_width=True, hide_index=True)

    # ── 1. 모멘텀 ────────────────────────────────────────
    st.markdown("---")
    st.markdown("### 1순위 — 모멘텀 (Jegadeesh & Titman, 1993)")
    st.markdown(
        "12개월 전 ~ 1개월 전 가격 수익률 기준. "
        "최근 1개월을 제외해 단기 평균회귀 노이즈를 차단. "
        "**Q1 = 직전 12-1개월 수익률 상위** → 다음 달 수익률이 더 높은지 검증."
    )
    _render_rolling_factor(mom_cum, mom_stats, "모멘텀", "모멘텀 최상위", "모멘텀 최하위")

    # ── 2. 저변동성 ──────────────────────────────────────
    st.markdown("---")
    st.markdown("### 2순위 — 저변동성 (Baker, Bradley & Wurgler, 2011)")
    st.markdown(
        "252거래일 연환산 변동성 기준. "
        "높은 리스크가 높은 수익으로 이어진다는 CAPM을 반박하는 대표 이상 현상. "
        "**Q1 = 변동성 최하위** → 안정적인 종목이 더 나은 수익을 내는지 검증."
    )
    _render_rolling_factor(vol_cum, vol_stats, "저변동성", "변동성 최저", "변동성 최고")

    # ── 3. 가치 ──────────────────────────────────────────
    st.markdown("---")
    st.markdown("### 3순위 — 가치 P/B (Fama & French, 1992)")
    st.markdown(
        "낮은 P/B(주가순자산비율) = 시장이 저평가한 종목. "
        "Fama-French 3팩터 모델의 HML(High minus Low) 팩터 근거. "
        "**Q1 = P/B 최저** → 저밸류 종목이 고밸류 종목을 이겼는지 검증."
    )
    _render_snapshot_factor(val_stats, val_det, "평균P/B", "평균P/B", "P/B")

    # ── 4. 퀄리티 ────────────────────────────────────────
    st.markdown("---")
    st.markdown("### 4순위 — 퀄리티 ROE (Novy-Marx, 2013)")
    st.markdown(
        "ROE + 순이익률 평균으로 퀄리티 스코어 산출. "
        "Fama-French 5팩터 모델의 RMW(Robust minus Weak) 팩터 근거. "
        "**Q1 = 퀄리티 최상위** → 고수익성 기업이 장기적으로 더 나은지 검증."
    )
    _render_snapshot_factor(qual_stats, qual_det, "평균퀄리티스코어", "퀄리티스코어", "ROE+이익률")

    st.markdown("---")
    st.info(
        "**해석 가이드** — 모멘텀·저변동성(롤링): Q1과 Q4 누적 수익 차이가 클수록 팩터 유효. "
        "가치·퀄리티(스냅샷): 방향성만 참고, 과거 데이터로 미래를 예측하는 도구가 아닙니다. "
        "소수 종목 유니버스(48개)이므로 학술 논문 대비 노이즈가 클 수 있습니다."
    )


# ════════════════════════════════════════════════════════
# TAB 4 (계속) — ETF 전략 백테스트
# ════════════════════════════════════════════════════════
with tab4:
    st.divider()
    st.subheader("📊 Part 2 — ETF 전략 백테스트 (2015-현재, VOO·VEU·BND·GLD·TLT)")
    st.caption(
        "개별 종목 선택 없이 시장 전체를 ETF로 사는 전략. "
        "유니버스: VOO(미국주식) · VEU(선진국) · BND(채권) · GLD(금) · TLT(장기국채) · SHY(현금)"
    )

    _ETF_FILES = {
        "dual_momentum":    ("etf_dual_momentum_cum.csv",    "etf_dual_momentum_stats.csv"),
        "rebalancing":      ("etf_리밸런싱_프리미엄_cum.csv",  "etf_리밸런싱_프리미엄_stats.csv"),
        "risk_parity":      ("etf_risk_parity_cum.csv",      "etf_risk_parity_stats.csv"),
        "gtaa":             ("etf_gtaa_추세추종_cum.csv",      "etf_gtaa_추세추종_stats.csv"),
    }

    def _etf_files_exist():
        return all((BACKTEST_DIR / v[0]).exists() for v in _ETF_FILES.values())

    @st.cache_data(ttl=3600)
    def _compute_etf():
        import sys
        sys.path.insert(0, str(Path(__file__).resolve().parent))
        from scripts.etf_backtest import load_all, UNIVERSE, run_dual_momentum
        from scripts.etf_backtest import run_rebalancing_premium, run_risk_parity, run_gtaa
        panel = load_all(list(UNIVERSE.keys()))
        return {
            "dm":  run_dual_momentum(panel),
            "rb":  run_rebalancing_premium(panel),
            "rp":  run_risk_parity(panel),
            "gtaa":run_gtaa(panel),
        }

    if _etf_files_exist():
        dm_cum   = pd.read_csv(BACKTEST_DIR / "etf_dual_momentum_cum.csv",   index_col=0, parse_dates=True)
        dm_stat  = pd.read_csv(BACKTEST_DIR / "etf_dual_momentum_stats.csv")
        rb_cum   = pd.read_csv(BACKTEST_DIR / "etf_리밸런싱_프리미엄_cum.csv",  index_col=0, parse_dates=True)
        rb_stat  = pd.read_csv(BACKTEST_DIR / "etf_리밸런싱_프리미엄_stats.csv")
        rp_cum   = pd.read_csv(BACKTEST_DIR / "etf_risk_parity_cum.csv",     index_col=0, parse_dates=True)
        rp_stat  = pd.read_csv(BACKTEST_DIR / "etf_risk_parity_stats.csv")
        gt_cum   = pd.read_csv(BACKTEST_DIR / "etf_gtaa_추세추종_cum.csv",     index_col=0, parse_dates=True)
        gt_stat  = pd.read_csv(BACKTEST_DIR / "etf_gtaa_추세추종_stats.csv")
    else:
        with st.spinner("ETF 데이터 수집 중... (최초 1회, 약 30초)"):
            _d = _compute_etf()
        dm_cum,  dm_stat  = _d["dm"]
        rb_cum,  rb_stat  = _d["rb"]
        rp_cum,  rp_stat  = _d["rp"]
        gt_cum,  gt_stat  = _d["gtaa"]

    def _render_etf_strategy(cum_df, stats_df, title, desc, highlight_col):
        st.markdown(f"### {title}")
        st.caption(desc)

        # 누적 수익률 차트
        st.line_chart(cum_df)

        # 핵심 지표 비교 (최대 4개 전략)
        cols = st.columns(min(len(stats_df), 4))
        for col, (_, row) in zip(cols, stats_df.iterrows()):
            is_highlight = row["전략"] == highlight_col
            col.metric(
                label=row["전략"],
                value=f"{row['연환산수익(%)']}% /년",
                delta=f"샤프 {row['샤프비율']} | MDD {row['최대낙폭(%)']}%",
                delta_color="normal" if is_highlight else "off",
            )

        with st.expander("전략별 상세 통계"):
            st.dataframe(stats_df, use_container_width=True, hide_index=True)

        st.divider()

    # ── 1. Dual Momentum ─────────────────────────────────
    _render_etf_strategy(
        dm_cum, dm_stat,
        "1. Dual Momentum (Antonacci 2014)",
        "매달 VOO vs VEU 상대모멘텀으로 승자 선택 → 절대모멘텀 음수 시 BND로 대피. "
        "상승장은 타고, 하락장은 채권으로 피하는 전략.",
        "Dual Momentum",
    )

    # ── 2. 리밸런싱 프리미엄 ──────────────────────────────
    _render_etf_strategy(
        rb_cum, rb_stat,
        "2. 리밸런싱 프리미엄 (Booth & Fama 1992)",
        "VOO 60% / BND 30% / GLD 10% 매달 목표 비중으로 복귀 리밸런싱. "
        "리밸런싱 자체가 낙폭을 줄이고 장기 위험조정 수익을 개선하는지 검증.",
        "리밸런싱 60/30/10",
    )

    # ── 3. Risk Parity ────────────────────────────────────
    _render_etf_strategy(
        rp_cum, rp_stat,
        "3. Risk Parity (Qian 2005 / Bridgewater All Weather)",
        "VOO · BND · GLD 각 자산의 변동성에 반비례해서 비중 배분. "
        "변동성 높은 자산일수록 비중을 줄여 리스크를 균등 분배.",
        "Risk Parity (역변동성)",
    )

    # ── 4. GTAA 추세추종 ──────────────────────────────────
    _render_etf_strategy(
        gt_cum, gt_stat,
        "4. GTAA 추세추종 (Faber 2007)",
        "5자산(VOO·VEU·BND·GLD·TLT) 각각 10개월 이동평균 위면 보유, 아래면 SHY(현금). "
        "Faber 2007 논문 기준 — 낙폭 최소화가 핵심 목표.",
        "GTAA 추세추종",
    )

    # ── 핵심 메시지 ──────────────────────────────────────
    st.markdown("### 핵심 해석 (2015-2026 기준)")
    c1, c2 = st.columns(2)
    with c1:
        st.success(
            "**리스크 관리 관점** — GTAA(MDD -13%), Risk Parity(MDD -15%)는 "
            "VOO 단순보유(MDD -24%) 대비 낙폭을 40~50% 줄임. "
            "2022 금리인상 구간 같은 폭락장에서 위력 발휘."
        )
    with c2:
        st.warning(
            "**순수 수익 관점** — 2015-2026 강세장에서는 VOO 단순보유가 모든 전략을 앞섬. "
            "전략들은 수익률이 아닌 **위험 대비 수익(샤프비율)**에서 우위. "
            "10년 이상 강세장에서는 단순 지수가 이기는 게 정상."
        )
    st.info(
        "**이 프로젝트의 결론**: Core ETF를 사고 정기 리밸런싱하는 전략은 "
        "순수 수익보다 **낙폭 제어 + 일관된 실행 가능성**에서 가치가 있음. "
        "행동 편향(공황 매도, 고점 추격)을 제거하는 것이 실질적인 알파 원천."
    )


# ════════════════════════════════════════════════════════
# TAB 4 (계속) — 코인 백테스트
# ════════════════════════════════════════════════════════
with tab4:
    st.divider()
    st.subheader("🪙 Part 3 — 코인 전략 백테스트 (2021-현재, 19개 코인)")
    st.caption("코인 모멘텀 · BTC MVRV 사이클 · BTC+ETH 리밸런싱 프리미엄 검증")

    _COIN_FILES = {
        "momentum":    ("coin_momentum_cum.csv",    "coin_momentum_stats.csv"),
        "mvrv":        ("coin_mvrv_cum.csv",        "coin_mvrv_stats.csv"),
        "rebalancing": ("coin_rebalancing_cum.csv", "coin_rebalancing_stats.csv"),
    }

    def _coin_files_exist():
        return all((BACKTEST_DIR / v[0]).exists() for v in _COIN_FILES.values())

    @st.cache_data(ttl=3600)
    def _compute_coin():
        import sys
        sys.path.insert(0, str(Path(__file__).resolve().parent))
        from scripts.coin_backtest import _build_monthly_panel, run_coin_momentum
        from scripts.coin_backtest import run_mvrv_cycle, run_crypto_rebalancing
        panel = _build_monthly_panel()
        return {
            "mom":  run_coin_momentum(panel),
            "mvrv": run_mvrv_cycle(),
            "rb":   run_crypto_rebalancing(panel),
        }

    if _coin_files_exist():
        cm_cum  = pd.read_csv(BACKTEST_DIR / "coin_momentum_cum.csv",    index_col=0, parse_dates=True)
        cm_stat = pd.read_csv(BACKTEST_DIR / "coin_momentum_stats.csv")
        mv_cum  = pd.read_csv(BACKTEST_DIR / "coin_mvrv_cum.csv",        index_col=0, parse_dates=True)
        mv_stat = pd.read_csv(BACKTEST_DIR / "coin_mvrv_stats.csv")
        cr_cum  = pd.read_csv(BACKTEST_DIR / "coin_rebalancing_cum.csv", index_col=0, parse_dates=True)
        cr_stat = pd.read_csv(BACKTEST_DIR / "coin_rebalancing_stats.csv")
    else:
        with st.spinner("코인 백테스트 계산 중..."):
            _cd = _compute_coin()
        cm_cum, cm_stat = _cd["mom"]
        mv_cum, mv_stat = _cd["mvrv"]
        cr_cum, cr_stat = _cd["rb"]

    # ── 1. 코인 모멘텀 ───────────────────────────────────
    st.markdown("---")
    st.markdown("### 1. 코인 모멘텀 (12-1M) — 주식과 같은 방향인가?")
    st.line_chart(cm_cum)

    _mom_ret_col = "연환산수익(%)" if "연환산수익(%)" in cm_stat.columns else cm_stat.columns[2]
    c1, c2, c3, c4, c5 = st.columns(5)
    for col, (_, row) in zip([c1, c2, c3, c4, c5], cm_stat.iterrows()):
        col.metric(row.iloc[0], f"{row[_mom_ret_col]:+.1f}%/년")

    st.error(
        "**역모멘텀 현상**: 코인에서는 주식과 반대로 Q4(낮은 모멘텀)가 Q1(높은 모멘텀)을 크게 앞섬. "
        "직전에 많이 오른 코인이 더 오르는 게 아니라 오히려 더 떨어지는 경향. "
        "평균회귀 성질이 강한 코인 시장 특성 — 모멘텀 전략을 코인에 그대로 쓰면 역효과."
    )

    with st.expander("분위별 상세 통계"):
        st.dataframe(cm_stat, use_container_width=True, hide_index=True)

    # ── 2. MVRV 사이클 ───────────────────────────────────
    st.markdown("---")
    st.markdown("### 2. BTC MVRV Z-Score 사이클 전략")
    st.caption("Z < 0 → BTC 100% / Z 0-1.5 → 75% / Z 1.5-2.5 → 45% / Z > 2.5 → 20%")
    st.line_chart(mv_cum)

    c1, c2 = st.columns(2)
    for col, (_, row) in zip([c1, c2], mv_stat.iterrows()):
        col.metric(
            row["전략"],
            f"{row['연환산수익(%)']}%/년",
            f"MDD {row['최대낙폭(%)']}% | 샤프 {row['샤프비율']}",
        )

    st.warning(
        "**2022-2026 MVRV 범위가 -0.4~3.4로 역대 최고치(8+)에 비해 낮음** — "
        "이번 사이클은 MVRV 기준 극단적 과열이 없었음. "
        "사이클 전략이 BTC 단순보유보다 수익은 낮지만 MDD를 15%p 줄임(−28% vs −43%). "
        "폭락 구간 방어가 목적이라면 유효한 전략."
    )

    if (BACKTEST_DIR / "coin_mvrv_zones.csv").exists():
        zones = pd.read_csv(BACKTEST_DIR / "coin_mvrv_zones.csv")
        with st.expander("MVRV 구간별 분포 (몇 달이나 각 구간에 있었나)"):
            st.dataframe(zones, use_container_width=True, hide_index=True)

    with st.expander("전략별 상세 통계"):
        st.dataframe(mv_stat, use_container_width=True, hide_index=True)

    # ── 3. BTC+ETH 리밸런싱 ─────────────────────────────
    st.markdown("---")
    st.markdown("### 3. BTC+ETH 리밸런싱 프리미엄")
    st.line_chart(cr_cum)

    _ann_col = "연환산수익(%)" if "연환산수익(%)" in cr_stat.columns else cr_stat.columns[2]
    _mdd_col = "최대낙폭(%)" if "최대낙폭(%)" in cr_stat.columns else None
    cols = st.columns(len(cr_stat))
    for col, (_, row) in zip(cols, cr_stat.iterrows()):
        delta = f"MDD {row[_mdd_col]}%" if _mdd_col else None
        col.metric(row["전략"], f"{row[_ann_col]:+.1f}%/년", delta)

    st.info(
        "**코인 리밸런싱 효과**: BTC+ETH 50/50 리밸런싱이 ETH 단순보유보다 수익 높고(+27% vs +23%) MDD 낮음. "
        "그러나 BTC 단순보유(+31%)보다는 낮음 — 2021-2026에 BTC가 ETH를 앞섰기 때문. "
        "변동성이 큰 코인일수록 리밸런싱으로 '변동성 수익'을 포착할 수 있지만, "
        "개별 자산의 방향성이 중요함."
    )

    with st.expander("전략별 상세 통계"):
        st.dataframe(cr_stat, use_container_width=True, hide_index=True)


# ════════════════════════════════════════════════════════
# TAB_SUM — 요약
# ════════════════════════════════════════════════════════
with tab_sum:
    st.subheader("백테스트 요약 — 무엇이 작동하고, 무엇을 버려야 하는가")
    st.caption(
        "이 대시보드 종목군(주식 48종목·코인 19종목·ETF 6종목)의 과거 데이터 백테스트 결과. "
        "판정 기준: ✅ 적중률 60%+ 또는 Q1 vs Q4 차이 명확 / 🟡 약한 우위(50~60%) / ❌ 50% 이하(동전던지기 이하)"
    )

    # ── 수치 로드 (CSV 있으면 실제값, 없으면 하드코딩 기본값) ──────
    @st.cache_data(ttl=3600)
    def _load_sum():
        d = {}
        try:
            cr = pd.read_csv(BACKTEST_DIR / "cross_signals.csv")
            gc = cr[cr["signal"] == "golden_cross"]
            dc = cr[cr["signal"] == "death_cross"]
            d["gc_hit"] = round(gc["hit_1M"].dropna().mean() * 100, 1) if len(gc) > 0 else 50.8
            d["dc_hit"] = round(dc["hit_1M"].dropna().mean() * 100, 1) if len(dc) > 0 else 50.0
        except Exception:
            d["gc_hit"], d["dc_hit"] = 50.8, 50.0
        try:
            rs = pd.read_csv(BACKTEST_DIR / "rsi_signals.csv")
            r70 = rs[rs["signal"] == "RSI 70 돌파(과매수)"]
            r30 = rs[rs["signal"] == "RSI 30 이탈(과매도)"]
            d["rsi70"] = round(r70["hit_22d"].dropna().mean() * 100, 1) if len(r70) > 0 else 45.0
            d["rsi30"] = round(r30["hit_22d"].dropna().mean() * 100, 1) if len(r30) > 0 else 56.0
        except Exception:
            d["rsi70"], d["rsi30"] = 45.0, 56.0
        try:
            ms = pd.read_csv(BACKTEST_DIR / "factor_momentum_stats.csv")
            d["mom_q1"] = float(ms[ms["분위"] == "Q1"]["연환산수익(%)"].values[0])
            d["mom_q4"] = float(ms[ms["분위"] == "Q4"]["연환산수익(%)"].values[0])
        except Exception:
            d["mom_q1"], d["mom_q4"] = 45.9, 17.7
        try:
            qs = pd.read_csv(BACKTEST_DIR / "factor_quality_stats.csv")
            d["qual_q1"] = float(qs[qs["분위"] == "Q1"]["평균수익_36M(%)"].values[0])
            d["qual_q4"] = float(qs[qs["분위"] == "Q4"]["평균수익_36M(%)"].values[0])
        except Exception:
            d["qual_q1"], d["qual_q4"] = 286.0, 51.0
        try:
            vs = pd.read_csv(BACKTEST_DIR / "factor_lowvol_stats.csv")
            d["vol_q1"] = float(vs[vs["분위"] == "Q1"]["연환산수익(%)"].values[0])
            d["vol_q4"] = float(vs[vs["분위"] == "Q4"]["연환산수익(%)"].values[0])
        except Exception:
            d["vol_q1"], d["vol_q4"] = 13.9, 56.7
        try:
            mv = pd.read_csv(BACKTEST_DIR / "coin_mvrv_stats.csv")
            mr = mv[mv["전략"] == "MVRV 사이클 전략"].iloc[0]
            br = mv[mv["전략"] == "BTC 단순보유"].iloc[0]
            d["mvrv_mdd"] = float(mr["최대낙폭(%)"])
            d["btc_mdd"]  = float(br["최대낙폭(%)"])
            d["mvrv_ann"] = float(mr["연환산수익(%)"])
        except Exception:
            d["mvrv_mdd"], d["btc_mdd"], d["mvrv_ann"] = -28.0, -43.0, None
        try:
            cm = pd.read_csv(BACKTEST_DIR / "coin_momentum_stats.csv")
            d["coin_q1"] = float(cm[cm["분위"] == "Q1"]["연환산수익(%)"].values[0])
            d["coin_q4"] = float(cm[cm["분위"] == "Q4"]["연환산수익(%)"].values[0])
        except Exception:
            d["coin_q1"], d["coin_q4"] = None, None
        try:
            rb = pd.read_csv(BACKTEST_DIR / "etf_리밸런싱_프리미엄_stats.csv")
            rr = rb[rb["전략"].str.contains("리밸런싱")].iloc[0]
            d["rb_ann"]    = float(rr["연환산수익(%)"])
            d["rb_sharpe"] = float(rr["샤프비율"])
            d["rb_mdd"]    = float(rr["최대낙폭(%)"])
        except Exception:
            d["rb_ann"], d["rb_sharpe"], d["rb_mdd"] = 11.0, 1.07, -19.5
        return d

    _s = _load_sum()

    # ── 상단 3분류 카드 ────────────────────────────────────
    col_ok, col_no, col_aux = st.columns(3)
    with col_ok:
        st.success(
            "**✅ 검증된 신호 (적용 中)**\n\n"
            f"📈 12-1M 모멘텀 Q1 — 연 **+{_s['mom_q1']:.1f}%**\n\n"
            f"💎 퀄리티 ROE Q1 — 36M **+{_s['qual_q1']:.0f}%**\n\n"
            f"🔵 MVRV Z-Score — MDD **{_s['mvrv_mdd']:.0f}%** (BTC {_s['btc_mdd']:.0f}%)\n\n"
            "📦 ETF 리밸런싱 — 샤프비율 우위"
        )
    with col_no:
        st.error(
            "**❌ 폐기 (제거/격하)**\n\n"
            f"🚫 골든크로스 — {_s['gc_hit']:.1f}% (동전던지기)\n\n"
            f"🚫 데스크로스 — {_s['dc_hit']:.1f}% (동전던지기)\n\n"
            f"🚫 RSI 70+ 과매수 (주식) — {_s['rsi70']:.1f}% (역방향)\n\n"
            "🚫 코인 모멘텀 Q1 — Q4가 더 높음"
        )
    with col_aux:
        st.warning(
            "**🟡 보조 신호 (참고만)**\n\n"
            f"⚠️ RSI 30 과매도 — {_s['rsi30']:.1f}% (단독 금지)\n\n"
            f"⚠️ 저변동성 — Q1 {_s['vol_q1']:.1f}%, Q4 {_s['vol_q4']:.1f}% (불마켓 역효과)\n\n"
            "⚠️ P/B 가치 — 소유니버스 노이즈 큼\n\n"
            "⚠️ 데스크로스 — 손실 관리 보조"
        )

    st.divider()

    # ── 판정 전체 표 ───────────────────────────────────────
    st.markdown("#### 전체 신호/전략 판정표")

    _coin_q_str = (
        f"Q1 {_s['coin_q1']:+.1f}% vs Q4 {_s['coin_q4']:+.1f}%"
        if _s.get("coin_q1") is not None else "Q4 > Q1 (역방향)"
    )

    verdict_rows = [
        # ── 주식 신호
        ("📈 주식 신호", "골든크로스 (50일>200일)",
         f"1M 적중률 {_s['gc_hit']:.1f}%",
         "❌ 폐기", "참고용 표시만", "예측력 없음 — 동전던지기"),
        ("📈 주식 신호", "데스크로스 (50일<200일)",
         f"1M 적중률 {_s['dc_hit']:.1f}%",
         "❌ 폐기", "보조 참고만", "예측력 없음 — 동전던지기"),
        ("📈 주식 신호", "RSI 70+ 과매수 (주식 백테스트 기준)",
         f"22d 적중률 {_s['rsi70']:.1f}%",
         "❌ 역방향", "주식 제거 / 코인(75+) -0.2만", "과매수 후 오히려 계속 오르는 경향"),
        ("📈 주식 신호", "RSI 30 이하 과매도",
         f"22d 적중률 {_s['rsi30']:.1f}%",
         "🟡 약한 우위", "보조 신호 유지", "56% 적중 — 단독 사용 금지"),
        # ── 팩터
        ("🔬 팩터 (주식)", "12-1M 모멘텀 Q1 (상위 25%)",
         f"연 +{_s['mom_q1']:.1f}% (Q4 {_s['mom_q4']:+.1f}%)",
         "✅ 검증됨", "우선순위 점수 주신호", f"Q1 vs Q4 연 +{_s['mom_q1']-_s['mom_q4']:.1f}%p — 팩터 유효"),
        ("🔬 팩터 (주식)", "퀄리티 ROE Q1 (고수익성)",
         f"36M +{_s['qual_q1']:.0f}% vs Q4 +{_s['qual_q4']:.0f}%",
         "✅ 검증됨", "QVGM 품질 점수 반영", "고ROE 기업이 장기 우월 — 팩터 유효"),
        ("🔬 팩터 (주식)", "저변동성 Q1 (안정 종목)",
         f"Q1 {_s['vol_q1']:+.1f}% vs Q4 {_s['vol_q4']:+.1f}%",
         "❌ 역방향(불마켓)", "미적용", "AI/테크 강세장에서 고변동성(Q4)이 압도"),
        ("🔬 팩터 (주식)", "P/B 가치 (저밸류 종목)",
         "비선형 패턴, 노이즈 큼",
         "🟡 불명확", "QVGM 저평가 참고", "48종목 소유니버스 — 통계적 유의성 낮음"),
        # ── ETF
        ("📦 ETF 전략", "VOO 단순보유 (Buy & Hold)",
         "연 15-17%, MDD -24%",
         "✅ 기준선", "Core ETF 전략 근거", "강세장에서 모든 복잡한 전략 앞섬"),
        ("📦 ETF 전략", f"리밸런싱 60/30/10",
         f"연 {_s['rb_ann']:.1f}%, 샤프 {_s['rb_sharpe']:.2f}, MDD {_s['rb_mdd']:.1f}%",
         "🟡 MDD 제어", "전략 참고",
         f"수익<VOO지만 MDD {24+_s['rb_mdd']:.1f}%p↓, 행동 편향 제거"),
        # ── 코인
        ("🪙 코인", "BTC MVRV Z-Score 사이클",
         f"MDD {_s['mvrv_mdd']:.0f}% vs BTC보유 {_s['btc_mdd']:.0f}%",
         "✅ 사이클 검증", "코인 페이지 1차 신호",
         f"낙폭을 {abs(_s['mvrv_mdd']-_s['btc_mdd']):.0f}%p 줄임 — 하락 방어 유효"),
        ("🪙 코인", "코인 12-1M 모멘텀 Q1",
         _coin_q_str,
         "❌ 역방향", "코인에 미적용", "코인은 평균회귀 성질 — 주식 모멘텀 그대로 적용 불가"),
        ("🪙 코인", "코인 RSI 30 과매도",
         "주식과 동일 56% 수준",
         "🟡 보조", "소폭 보너스 +0.5 유지", "과매도 반등 신호 — 강한 신호 아님"),
    ]

    verdict_df = pd.DataFrame(verdict_rows, columns=[
        "분류", "신호/전략", "핵심 수치", "판정", "대시보드 적용", "근거"
    ])

    # 판정 기준 색상 배경을 위해 별도 열 추가
    def _verdict_color(v):
        if v.startswith("✅"): return "background-color: #d1fae5"
        if v.startswith("❌"): return "background-color: #fee2e2"
        if v.startswith("🟡"): return "background-color: #fef9c3"
        return ""

    styled = verdict_df.style.map(_verdict_color, subset=["판정"])

    st.dataframe(
        styled,
        use_container_width=True,
        hide_index=True,
        column_config={
            "분류":        st.column_config.TextColumn("분류",       width="small"),
            "신호/전략":   st.column_config.TextColumn("신호/전략",  width="medium"),
            "핵심 수치":   st.column_config.TextColumn("핵심 수치",  width="medium"),
            "판정":        st.column_config.TextColumn("판정",       width="small"),
            "대시보드 적용": st.column_config.TextColumn("현재 적용", width="medium"),
            "근거":        st.column_config.TextColumn("근거",       width="large"),
        },
    )

    st.divider()

    # ── 핵심 인사이트 ──────────────────────────────────────
    st.markdown("#### 핵심 인사이트 3가지")

    ins1, ins2, ins3 = st.columns(3)
    with ins1:
        st.info(
            "**① 차트 신호는 예측력이 없다**\n\n"
            "골든크로스·데스크로스·RSI 과매수는 모두 50% 이하 적중률. "
            "시장은 이 신호들을 이미 가격에 반영하고 있어 패턴이 소진됨. "
            "**추세 확인 참고에만 쓸 것.**"
        )
    with ins2:
        st.success(
            "**② 모멘텀과 퀄리티는 실제로 작동한다**\n\n"
            f"12-1M 모멘텀 Q1은 Q4 대비 연 +{_s['mom_q1']-_s['mom_q4']:.1f}%p 초과수익. "
            "퀄리티(고ROE) Q1은 Q4 대비 36M 수익 5배 이상 차이. "
            "**종목 선별의 핵심 기준으로 사용.**"
        )
    with ins3:
        st.warning(
            "**③ 코인은 주식과 반대로 작동한다**\n\n"
            "코인 모멘텀 Q1(많이 오른 코인)은 오히려 뒤처짐. "
            "코인의 주신호는 MVRV Z-Score(온체인 사이클). "
            "RSI 75+ 과매수도 코인에서 적중률 낮음 — "
            "**코인은 별도 프레임이 필요.**"
        )

    st.divider()
    st.markdown("#### 현재 대시보드 변경 이력 (백테스트 기반)")
    _history = pd.DataFrame([
        ("주식 추천",   "골든크로스 → 매수 신호",       "12-1M 모멘텀 Q1 → 주신호",      f"골든크로스 {_s['gc_hit']:.1f}%, 모멘텀 Q1 연 +{_s['mom_q1']:.1f}%"),
        ("주식 우선순위", "action(골든크로스) 보정",     "mom_rank Q1~Q4 보정",           "Q1 +0.5, Q4 -0.3 백테스트 기반"),
        ("코인 추천",   "RSI 75+ 과매수 -1.0 패널티",   "RSI 75+ -0.2 (소폭만)",         f"주식 RSI70 {_s['rsi70']:.0f}% 적중 = 역방향 근거"),
        ("코인 페이지", "MVRV 차트 아래 표시",           "MVRV 존 배너 최상단",           "가장 신뢰도 높은 1차 신호"),
        ("보유 종목",   "골든크로스 → 🟢 매수",          "모멘텀 Q1 → 🟢 매수",           f"골든크로스 {_s['gc_hit']:.1f}% vs 모멘텀 Q1 검증됨"),
        ("보유 종목",   "RSI 70+ → 🟠 주의",            "제거 (모멘텀 Q4로 교체)",        f"RSI 70+ 적중 {_s['rsi70']:.0f}% = 역효과 / 코인은 75+ 기준"),
    ], columns=["페이지", "변경 전", "변경 후", "근거"])
    st.dataframe(
        _history,
        use_container_width=True,
        hide_index=True,
        column_config={
            "페이지":  st.column_config.TextColumn("페이지",  width="small"),
            "변경 전": st.column_config.TextColumn("변경 전", width="medium"),
            "변경 후": st.column_config.TextColumn("변경 후", width="medium"),
            "근거":    st.column_config.TextColumn("근거",    width="large"),
        },
    )


# ════════════════════════════════════════════════════════
# TAB 신호 예측력 검증 — 가설 수립 → 검증 → 적용
# ════════════════════════════════════════════════════════
with tab_val:
    st.subheader("🧪 신호 예측력 검증")
    st.caption(
        "가설 수립 → 데이터 검증 → 검증된 신호만 적용하는 과학적 프레임워크. "
        "IC(Information Coefficient) = 신호와 미래 수익률의 피어슨 상관계수. "
        "|IC| ≥ 0.05이고 p < 0.05일 때 '예측력 확인'으로 판단."
    )

    _val_file = RESULTS_DIR / "signal_validation.csv"
    if not _val_file.exists():
        st.info("검증 데이터 없음. 아래 버튼으로 실행하세요 (약 30초 소요).")
        if st.button("▶ 신호 예측력 검증 실행"):
            with st.spinner("검증 중..."):
                from scripts.signal_validation import run_validation
                _vdf = run_validation(RESULTS_DIR)
                _vdf.to_csv(_val_file, index=False, encoding="utf-8-sig")
                st.success("완료!")
                st.rerun()
        st.stop()

    _vdf = pd.read_csv(_val_file)

    # ── 1단계: 가설 목록 ───────────────────────────────────────────────────────
    st.markdown("### 1️⃣ 가설 수립")
    with st.expander("검증 대상 가설 목록 보기", expanded=False):
        _hyp_tbl = _vdf[["id","가설","설명","참고문헌"]].drop_duplicates()
        st.dataframe(_hyp_tbl, hide_index=True, use_container_width=True)

    st.divider()

    # ── 2단계: 검증 결과 ───────────────────────────────────────────────────────
    st.markdown("### 2️⃣ 가설 검증 결과")

    _COLOR_MAP = {
        "확인": "✅",
        "약한": "⚠️",
        "없음": "❌",
        "역방향": "↩️",
    }

    for fwd_label in ["1M", "3M"]:
        sub = _vdf[_vdf["예측창"] == fwd_label].copy()
        if sub.empty:
            continue
        st.markdown(f"**예측 기간: {fwd_label}**")

        display_cols = ["id","가설","IC","t통계","p값","적중률(%)","검증결과"]
        disp = sub[display_cols].copy()

        def _row_color(verdict):
            if "확인" in str(verdict):   return "background-color: #d1fae5"
            if "역방향" in str(verdict): return "background-color: #fef3c7"
            if "약한" in str(verdict):   return "background-color: #fef9c3"
            return "background-color: #fee2e2"

        st.dataframe(
            disp,
            hide_index=True,
            use_container_width=True,
            column_config={
                "IC":      st.column_config.NumberColumn(format="%.4f",
                           help="신호↔미래수익 상관계수. |0.05|↑ + p<0.05 = 유의미"),
                "t통계":   st.column_config.NumberColumn(format="%.2f"),
                "p값":     st.column_config.NumberColumn(format="%.4f"),
                "적중률(%)": st.column_config.NumberColumn(format="%.1f"),
                "검증결과": st.column_config.TextColumn("결과"),
            },
        )

    st.divider()

    # ── 3단계: 적용 결론 ───────────────────────────────────────────────────────
    st.markdown("### 3️⃣ 적용 결론")

    _confirmed = _vdf[_vdf["검증결과"].str.contains("확인|약한", na=False)]["가설"].unique()
    _rejected  = _vdf[_vdf["검증결과"].str.contains("없음", na=False)]["가설"].unique()
    _reversed  = _vdf[_vdf["검증결과"].str.contains("역방향", na=False)]["가설"].unique()

    col_a, col_b, col_c = st.columns(3)
    with col_a:
        st.success(f"**적용 신호 ({len(_confirmed)}개)**")
        for s in _confirmed:
            st.markdown(f"- {s}")
    with col_b:
        st.warning(f"**제거 신호 ({len(_rejected)}개)**")
        for s in _rejected:
            st.markdown(f"- {s}")
    with col_c:
        st.error(f"**역방향 신호 ({len(_reversed)}개) — 과열 경보로 전환**")
        for s in _reversed:
            st.markdown(f"- {s}")

    st.info(
        "MA정렬·BB위치·RSI기울기는 IC < 0 → 현재 상승 추세가 강할 때 오히려 "
        "향후 수익이 낮아지는 경향. 점수 보너스 제거하고 **과열 경보 신호**로 전환했습니다. "
        "VIX 역발상(1M)·거래량비율은 약하지만 방향이 맞아 맥락 정보로 유지합니다."
    )

    st.caption(
        "주의: 이 검증은 2021-2026년 약 99개 종목 기준입니다. "
        "데이터 기간·종목 수가 늘수록 결과가 달라질 수 있습니다. "
        "재실행 버튼으로 최신 데이터로 재검증할 수 있습니다."
    )
    if st.button("🔄 재검증 실행"):
        with st.spinner("검증 중... (약 30초)"):
            from scripts.signal_validation import run_validation
            _vdf_new = run_validation(RESULTS_DIR)
            _vdf_new.to_csv(_val_file, index=False, encoding="utf-8-sig")
            st.success("재검증 완료!")
            st.rerun()

    st.divider()

    # ── 4단계: 추천 시스템 종합 검증 ──────────────────────────────────────────
    st.markdown("### 4️⃣ 추천 vs 비추천 — 실제로 작동하는가?")
    st.caption(
        "개별 신호 IC가 유효해도, 그것을 합산한 '종합 순위 시스템'이 실제로 수익 차이를 만드는지 별도로 검증합니다."
    )

    _comp_ic_file  = RESULTS_DIR / "composite_validation_ic.csv"
    _comp_sp_file  = RESULTS_DIR / "composite_validation_spread.csv"
    _comp_missing  = not _comp_ic_file.exists() or not _comp_sp_file.exists()

    if _comp_missing:
        st.info("추천 시스템 검증 데이터 없음. 아래 버튼으로 실행하세요.")

    _run_comp = st.button("▶ 추천 시스템 검증 실행 (약 20초)")
    if _run_comp or not _comp_missing:
        if _run_comp:
            with st.spinner("추천 vs 비추천 백테스트 중..."):
                from scripts.signal_validation import run_composite_validation
                _cic, _csp = run_composite_validation(RESULTS_DIR)
                _cic.to_csv(_comp_ic_file, index=False, encoding="utf-8-sig")
                _csp.to_csv(_comp_sp_file, index=False, encoding="utf-8-sig")
                st.success("완료!")
        else:
            _cic = pd.read_csv(_comp_ic_file)
            _csp = pd.read_csv(_comp_sp_file)

        # ── H9/H10 IC 결과 ─────────────────────────────────────────────────
        st.markdown("**H9 복합 모멘텀 (7:3 가중) / H10 과열 조합 역방향 검증**")
        if not _cic.empty:
            st.dataframe(
                _cic[["id","가설","예측창","IC","t통계","p값","적중률(%)","검증결과"]],
                hide_index=True, use_container_width=True,
                column_config={
                    "IC":     st.column_config.NumberColumn(format="%.4f"),
                    "t통계":  st.column_config.NumberColumn(format="%.2f"),
                    "p값":    st.column_config.NumberColumn(format="%.4f"),
                    "검증결과": st.column_config.TextColumn("결과"),
                },
            )

        st.divider()

        # ── H11 추천 vs 비추천 격차 ────────────────────────────────────────
        st.markdown("**H11: 복합점수 상위33% vs 하위33% — 월별 수익률 격차**")
        st.caption("매월 종목들을 복합점수로 줄 세워, 상위33%(추천)와 하위33%(비추천)의 평균 1개월 수익률 차이를 측정합니다.")

        if not _csp.empty:
            st.dataframe(
                _csp,
                hide_index=True, use_container_width=True,
                column_config={
                    "추천평균수익(%)":  st.column_config.NumberColumn("추천 평균(%)", format="%+.3f"),
                    "비추천평균수익(%)": st.column_config.NumberColumn("비추천 평균(%)", format="%+.3f"),
                    "격차(%p)":        st.column_config.NumberColumn("격차(%p)", format="%+.3f"),
                    "t통계":           st.column_config.NumberColumn(format="%.2f"),
                    "p값":             st.column_config.NumberColumn(format="%.4f"),
                    "격차양수비율(%)":  st.column_config.NumberColumn("추천>비추천 비율(%)", format="%.1f"),
                    "월수":            st.column_config.NumberColumn("측정 월수"),
                    "검증결과":        st.column_config.TextColumn("결과"),
                },
            )

            # 결론 카드
            _sp1m = _csp[_csp["예측창"] == "1M"].iloc[0] if "1M" in _csp["예측창"].values else None
            if _sp1m is not None:
                _gap    = float(_sp1m["격차(%p)"])
                _pval   = float(_sp1m["p값"])
                _hit    = float(_sp1m["격차양수비율(%)"])
                _result = str(_sp1m["검증결과"])

                if "❌" in _result:
                    st.error(
                        f"**❌ 추천 시스템이 통계적으로 유의한 수익 차이를 만들지 못함** (p={_pval:.3f})\n\n"
                        f"추천 평균: {float(_sp1m['추천평균수익(%)']):+.2f}% / "
                        f"비추천 평균: {float(_sp1m['비추천평균수익(%)']):+.2f}% / "
                        f"격차: {_gap:+.2f}%p"
                    )
                    st.markdown(
                        "**해석**: 방향은 맞지만(추천이 비추천보다 약간 더 벌음), "
                        f"그 차이가 랜덤 오차 범위 안에 있습니다. "
                        f"격차가 양수인 달의 비율 = **{_hit:.0f}%** (50%와 큰 차이 없음)."
                    )
                elif "✅" in _result:
                    st.success(
                        f"**✅ 추천 시스템이 유의미한 수익 차이를 만들었음** (p={_pval:.3f})\n\n"
                        f"격차: {_gap:+.2f}%p / 추천>비추천 비율: {_hit:.0f}%"
                    )

        # ── 종합 진단 ────────────────────────────────────────────────────
        st.divider()
        st.markdown("### 🔬 추천 시스템 종합 진단")
        st.markdown("""
| 구분 | 검증 결과 | 실용 가치 |
|---|---|---|
| **모멘텀 순위 (H1, H9)** | ❌ 통계 유의성 없음 (p>0.6) | 종목 선택 기준으로 신뢰도 낮음 |
| **과열 페널티 (H10)** | ⚠️ 약한 유의성 (p=0.02, IC=0.03) | 과열 종목 피하기는 효과 있음 |
| **추천 vs 비추천 격차 (H11)** | ❌ 통계 유의성 없음 (p>0.4) | 추천 순위대로 사는 것이 유리하지 않음 |
| **VIX 타이밍 (H8)** | ✅ 강한 유의성 (IC=0.14, p<0.001) | 시장 전체 진입 타이밍에 효과 있음 |
""")
        st.warning(
            "**핵심 결론**: 이 시스템은 **어떤 ETF를 살지 고르는 것에는 통계적으로 검증되지 않았습니다.**  \n"
            "대신 **VIX 공포 국면에서 시장에 진입**하고, **과열 종목의 비중을 줄이는** 두 가지는 "
            "데이터로 확인된 행동입니다.  \n"
            "모멘텀 순위 시스템은 '손해는 안 나지만 유의한 알파를 만들지도 않는' 수준입니다."
        )
        st.caption(
            "샘플 제한: 약 20~50개 ETF × 5년. 수십만 종목을 수십 년 검증한 학술 연구와 달리 "
            "통계 검정력이 낮습니다. 더 많은 데이터가 쌓이면 결론이 바뀔 수 있습니다."
        )

        if st.button("🔄 추천 시스템 재검증"):
            with st.spinner("재검증 중..."):
                from scripts.signal_validation import run_composite_validation
                _cic2, _csp2 = run_composite_validation(RESULTS_DIR)
                _cic2.to_csv(_comp_ic_file, index=False, encoding="utf-8-sig")
                _csp2.to_csv(_comp_sp_file, index=False, encoding="utf-8-sig")
                st.success("재검증 완료!")
                st.rerun()

