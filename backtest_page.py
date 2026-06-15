"""신호 백테스트 결과 페이지."""
import streamlit as st
import pandas as pd
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
tab0, tab1, tab2, tab3 = st.tabs(["🏆 개별주 vs 시장", "📈 골든/데스크로스", "📊 RSI 신호", "✂️ 손절선 검증"])


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
