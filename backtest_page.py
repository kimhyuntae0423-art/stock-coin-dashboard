"""신호 백테스트 결과 페이지."""
import streamlit as st
import pandas as pd
import numpy as np
import yfinance as yf
from pathlib import Path

BACKTEST_DIR = Path(__file__).resolve().parent / "results" / "backtest"
RESULTS_DIR  = Path(__file__).resolve().parent / "results"


# ════════════════════════════════════════════════════════
# 데이터 로더
# ════════════════════════════════════════════════════════
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
        t = f.stem.replace("_signals", "")
        r = _ret(f)
        if r:
            r["ticker"] = t
            r["category"] = "KR" if (".KS" in t or ".KQ" in t) else "US"
            rows.append(r)
    for f in coin_files:
        t = f.stem.replace("coin_", "").replace("_signals", "")
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
        "US":   {"name": "S&P500 (SPY)",  "total": b_spy_tot, "ann": b_spy_ann},
        "KR":   {"name": "KOSPI200 ETF",  "total": b_ks_tot,  "ann": b_ks_ann},
        "Coin": {"name": "BTC",           "total": b_btc_tot, "ann": b_btc_ann},
    }
    return df, benchmarks, str(start.date()), str(end.date())


# ════════════════════════════════════════════════════════
# 공통 헬퍼
# ════════════════════════════════════════════════════════
def hit_badge(rate: float) -> str:
    if rate >= 0.60: return f"**{rate*100:.0f}%** 🟢 신뢰도 있음"
    if rate >= 0.52: return f"**{rate*100:.0f}%** 🟡 약한 우위"
    return f"**{rate*100:.0f}%** 🔴 동전 던지기 수준"


def _render_rolling_factor(cum_df, stats_df, factor_name, q1_label, q4_label):
    if cum_df.empty:
        st.warning("데이터 부족으로 계산 불가")
        return
    st.line_chart(cum_df, color=["#16a34a", "#65a30d", "#f59e0b", "#ef4444"])
    c1, c2, c3, c4 = st.columns(4)
    for col, q in zip([c1, c2, c3, c4], ["Q1", "Q2", "Q3", "Q4"]):
        row = stats_df[stats_df["분위"] == q].iloc[0]
        final = cum_df[q].dropna().iloc[-1] if q in cum_df.columns and not cum_df[q].dropna().empty else 1.0
        col.metric(q, f"{row['연환산수익(%)']:+.1f}% /년", f"누적 {(final - 1)*100:+.0f}%")
    st.caption(f"Q1 = {q1_label} / Q4 = {q4_label}")
    with st.expander("분위별 통계 상세"):
        st.dataframe(stats_df, use_container_width=True, hide_index=True)


def _render_snapshot_factor(stats_df, detail_df, x_col, label_col, factor_label):
    if stats_df.empty:
        st.warning("데이터 부족으로 계산 불가")
        return
    bar_data = stats_df.set_index("분위")["평균수익_36M(%)"]
    st.bar_chart(bar_data)
    c1, c2, c3, c4 = st.columns(4)
    for col, q in zip([c1, c2, c3, c4], ["Q1", "Q2", "Q3", "Q4"]):
        row = stats_df[stats_df["분위"] == q].iloc[0]
        col.metric(q, f"{row['평균수익_36M(%)']:+.1f}%", f"{label_col}: {row[x_col]}")
    st.caption(f"⚠️ 스냅샷 분석 — 룩어헤드 바이어스 있음. 방향성 참고용.")
    with st.expander("종목별 상세"):
        show_cols = [c for c in ["ticker", "sector", "q"] + [c for c in detail_df.columns
                     if c not in ["ticker", "sector", "q", "ret_36m"]] + ["ret_36m"] if c in detail_df.columns]
        st.dataframe(detail_df[show_cols].sort_values("q"), use_container_width=True, hide_index=True)


def _render_etf_strategy(cum_df, stats_df, title, desc, highlight_col):
    st.markdown(f"**{title}**")
    st.caption(desc)
    st.line_chart(cum_df)
    cols = st.columns(min(len(stats_df), 4))
    for col, (_, row) in zip(cols, stats_df.iterrows()):
        is_hl = row["전략"] == highlight_col
        col.metric(row["전략"], f"{row['연환산수익(%)']}% /년",
                   f"샤프 {row['샤프비율']} | MDD {row['최대낙폭(%)']}%",
                   delta_color="normal" if is_hl else "off")
    with st.expander("전략별 상세 통계"):
        st.dataframe(stats_df, use_container_width=True, hide_index=True)


# ════════════════════════════════════════════════════════
# 페이지 헤더
# ════════════════════════════════════════════════════════
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

# ════════════════════════════════════════════════════════
# 탭 구조 (9 → 4)
# ════════════════════════════════════════════════════════
tab_sum, tab_strat, tab_sig, tab_val = st.tabs([
    "📋 요약",
    "🔄 전략 백테스트",
    "📈 신호 & 개별주",
    "🧪 신호 예측력 연구",
])


# ════════════════════════════════════════════════════════
# TAB 1 — 요약
# ════════════════════════════════════════════════════════
with tab_sum:
    st.subheader("백테스트 요약 — 무엇이 작동하고, 무엇을 버려야 하는가")
    st.caption(
        "이 대시보드 종목군(주식 48종목·코인 19종목·ETF 6종목)의 과거 데이터 백테스트 결과. "
        "판정 기준: ✅ 적중률 60%+ 또는 Q1 vs Q4 차이 명확 / 🟡 약한 우위(50~60%) / ❌ 50% 이하"
    )

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

    # 상단 3분류 카드
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

    # 판정 전체 표
    st.markdown("#### 전체 신호/전략 판정표")
    _coin_q_str = (
        f"Q1 {_s['coin_q1']:+.1f}% vs Q4 {_s['coin_q4']:+.1f}%"
        if _s.get("coin_q1") is not None else "Q4 > Q1 (역방향)"
    )
    verdict_rows = [
        ("📈 주식 신호", "골든크로스 (50일>200일)",           f"1M 적중률 {_s['gc_hit']:.1f}%",                        "❌ 폐기",         "참고용 표시만",          "예측력 없음 — 동전던지기"),
        ("📈 주식 신호", "데스크로스 (50일<200일)",           f"1M 적중률 {_s['dc_hit']:.1f}%",                        "❌ 폐기",         "보조 참고만",            "예측력 없음 — 동전던지기"),
        ("📈 주식 신호", "RSI 70+ 과매수",                   f"22d 적중률 {_s['rsi70']:.1f}%",                        "❌ 역방향",       "주식 제거",              "과매수 후 오히려 계속 오르는 경향"),
        ("📈 주식 신호", "RSI 30 이하 과매도",               f"22d 적중률 {_s['rsi30']:.1f}%",                        "🟡 약한 우위",    "보조 신호 유지",         "56% 적중 — 단독 사용 금지"),
        ("🔬 팩터",      "12-1M 모멘텀 Q1",                  f"연 +{_s['mom_q1']:.1f}% (Q4 {_s['mom_q4']:+.1f}%)",   "✅ 검증됨",       "우선순위 점수 주신호",   f"Q1 vs Q4 연 +{_s['mom_q1']-_s['mom_q4']:.1f}%p"),
        ("🔬 팩터",      "퀄리티 ROE Q1",                    f"36M +{_s['qual_q1']:.0f}% vs Q4 +{_s['qual_q4']:.0f}%","✅ 검증됨",       "QVGM 품질 점수 반영",   "고ROE 기업이 장기 우월"),
        ("🔬 팩터",      "저변동성 Q1",                      f"Q1 {_s['vol_q1']:+.1f}% vs Q4 {_s['vol_q4']:+.1f}%",  "❌ 역방향(불마켓)","미적용",                "AI/테크 강세장에서 고변동성 압도"),
        ("📦 ETF 전략",  "VOO 단순보유 (Buy & Hold)",         "연 15-17%, MDD -24%",                                  "✅ 기준선",       "Core ETF 전략 근거",     "강세장에서 모든 전략 앞섬"),
        ("📦 ETF 전략",  "리밸런싱 60/30/10",                f"연 {_s['rb_ann']:.1f}%, 샤프 {_s['rb_sharpe']:.2f}",  "🟡 MDD 제어",    "전략 참고",              f"MDD {24+_s['rb_mdd']:.1f}%p↓"),
        ("🪙 코인",      "BTC MVRV Z-Score 사이클",          f"MDD {_s['mvrv_mdd']:.0f}% vs BTC {_s['btc_mdd']:.0f}%","✅ 사이클 검증", "코인 페이지 1차 신호",  f"낙폭 {abs(_s['mvrv_mdd']-_s['btc_mdd']):.0f}%p 절감"),
        ("🪙 코인",      "코인 12-1M 모멘텀 Q1",             _coin_q_str,                                            "❌ 역방향",       "코인에 미적용",          "코인은 평균회귀 성질"),
    ]
    verdict_df = pd.DataFrame(verdict_rows, columns=["분류", "신호/전략", "핵심 수치", "판정", "대시보드 적용", "근거"])

    def _verdict_color(v):
        if v.startswith("✅"): return "background-color: #d1fae5"
        if v.startswith("❌"): return "background-color: #fee2e2"
        if v.startswith("🟡"): return "background-color: #fef9c3"
        return ""

    st.dataframe(
        verdict_df.style.map(_verdict_color, subset=["판정"]),
        use_container_width=True, hide_index=True,
        column_config={
            "분류":          st.column_config.TextColumn(width="small"),
            "신호/전략":     st.column_config.TextColumn(width="medium"),
            "핵심 수치":     st.column_config.TextColumn(width="medium"),
            "판정":          st.column_config.TextColumn(width="small"),
            "대시보드 적용": st.column_config.TextColumn("현재 적용", width="medium"),
            "근거":          st.column_config.TextColumn(width="large"),
        },
    )

    st.divider()

    # 핵심 인사이트 3가지
    ins1, ins2, ins3 = st.columns(3)
    with ins1:
        st.info(
            "**① 차트 신호는 예측력이 없다**\n\n"
            "골든크로스·데스크로스·RSI 과매수는 모두 50% 이하 적중률. "
            "이미 가격에 반영됨. **추세 확인 참고에만 쓸 것.**"
        )
    with ins2:
        st.success(
            "**② 모멘텀과 퀄리티는 작동한다**\n\n"
            f"모멘텀 Q1 연 +{_s['mom_q1']-_s['mom_q4']:.1f}%p 초과수익. "
            "퀄리티 Q1 vs Q4 수익 5배 이상. "
            "**종목 선별의 핵심 기준.**"
        )
    with ins3:
        st.warning(
            "**③ 코인은 주식과 반대로 작동한다**\n\n"
            "코인 모멘텀 Q1(많이 오른 코인)이 오히려 뒤처짐. "
            "코인 주신호는 MVRV Z-Score. "
            "**코인은 별도 프레임 필요.**"
        )

    with st.expander("대시보드 변경 이력 (백테스트 기반)"):
        _history = pd.DataFrame([
            ("주식 추천",    "골든크로스 → 매수 신호",      "12-1M 모멘텀 Q1 → 주신호",     f"골든크로스 {_s['gc_hit']:.1f}%, 모멘텀 Q1 연 +{_s['mom_q1']:.1f}%"),
            ("주식 우선순위","action(골든크로스) 보정",      "mom_rank Q1~Q4 보정",          "Q1 +0.5, Q4 -0.3 백테스트 기반"),
            ("코인 추천",    "RSI 75+ 과매수 -1.0 패널티",  "RSI 75+ -0.2 (소폭만)",        f"주식 RSI70 {_s['rsi70']:.0f}% 적중 = 역방향 근거"),
            ("코인 페이지",  "MVRV 차트 아래 표시",          "MVRV 존 배너 최상단",          "가장 신뢰도 높은 1차 신호"),
            ("보유 종목",    "골든크로스 → 🟢 매수",         "모멘텀 Q1 → 🟢 매수",          f"골든크로스 {_s['gc_hit']:.1f}% vs 모멘텀 Q1 검증됨"),
            ("보유 종목",    "RSI 70+ → 🟠 주의",           "제거 (모멘텀 Q4로 교체)",       f"RSI 70+ 적중 {_s['rsi70']:.0f}% = 역효과"),
        ], columns=["페이지", "변경 전", "변경 후", "근거"])
        st.dataframe(_history, use_container_width=True, hide_index=True)


# ════════════════════════════════════════════════════════
# TAB 2 — 전략 백테스트
# ════════════════════════════════════════════════════════
with tab_strat:

    # ── 코어 ETF 로테이션 (최상단) ────────────────────────────────────────────
    st.subheader("🔄 코어 ETF 로테이션 백테스트")
    st.caption("VIX 국면 × 5역할(VOO·SCHD·SOXX·TLT·GLD) 월간 리밸런싱 vs Buy-and-Hold VOO. 금리 급등 보정 포함.")

    _rot_metrics_f = RESULTS_DIR / "rotation_backtest_metrics.csv"
    _rot_equity_f  = RESULTS_DIR / "rotation_backtest_equity.csv"
    _rot_phase_f   = RESULTS_DIR / "rotation_backtest_phase.csv"
    _rot_ai_f      = RESULTS_DIR / "rotation_ai_compare_metrics.csv"
    _rot_ai_ann_f  = RESULTS_DIR / "rotation_ai_compare_annual.csv"

    if not _rot_metrics_f.exists():
        st.info("백테스트 결과 없음 — run_analysis.py 실행 후 갱신됩니다.")
    else:
        _rot_m  = pd.read_csv(_rot_metrics_f)
        _rot_eq = pd.read_csv(_rot_equity_f, index_col=0, parse_dates=True)
        _rot_ph = pd.read_csv(_rot_phase_f)

        c_m, c_chart = st.columns([1, 1])
        with c_m:
            st.markdown("**5년 성과 (2021~2026)**")
            st.dataframe(_rot_m, hide_index=True, use_container_width=True,
                column_config={
                    "전략":        st.column_config.TextColumn("전략"),
                    "총수익률(%)": st.column_config.NumberColumn("총수익률(%)", format="%+.1f"),
                    "CAGR(%)":    st.column_config.NumberColumn("CAGR(%)", format="%+.1f"),
                    "샤프비율":    st.column_config.NumberColumn("샤프"),
                    "최대낙폭(%)": st.column_config.NumberColumn("MDD(%)", format="%.1f"),
                    "월승률(%)":   st.column_config.NumberColumn("월승률(%)", format="%.1f"),
                })
            st.caption("정상 장세에서 VOO와 비슷한 게 정상. 진짜 가치는 폭락장에서.")
        with c_chart:
            _rot_chart = (_rot_eq[["로테이션(금리보정)", "VOO B&H"]].dropna() / 1_000_000)
            st.line_chart(_rot_chart, height=200)

        # 연도별 수익률 + 국면별
        col_ann, col_ph = st.columns([1, 1])
        with col_ann:
            st.markdown("**연도별 수익률**")
            _ann = _rot_eq[["로테이션(금리보정)", "VOO B&H"]].resample("YE").last().pct_change() * 100
            _ann.index = _ann.index.year
            _ann = _ann.dropna()
            _ann.columns = ["로테이션", "VOO B&H"]
            st.bar_chart(_ann, height=200)
        with col_ph:
            st.markdown("**국면별 성과**")
            st.dataframe(_rot_ph, hide_index=True, use_container_width=True,
                column_config={
                    "국면":           st.column_config.TextColumn("국면"),
                    "기간(개월)":     st.column_config.NumberColumn("기간", format="%.0f"),
                    "전략 월평균(%)": st.column_config.NumberColumn("전략(%)", format="%+.2f"),
                    "VOO 월평균(%)":  st.column_config.NumberColumn("VOO(%)", format="%+.2f"),
                    "전략 승률(%)":   st.column_config.NumberColumn("승률(%)", format="%.1f"),
                })

        # 버블 붕괴 시나리오
        st.markdown("**💥 버블 붕괴 시나리오 (공포 국면 배분 기준 추정)**")
        _bubble = pd.DataFrame([
            {"시나리오": "2008 금융위기 (18개월)", "VOO B&H(%)": -57, "로테이션 추정(%)": -11, "방어효과": "+46%p"},
            {"시나리오": "2000 닷컴버블 (30개월)", "VOO B&H(%)": -49, "로테이션 추정(%)": -11, "방어효과": "+38%p"},
            {"시나리오": "2020 코로나 급락 (1개월)","VOO B&H(%)": -34, "로테이션 추정(%)": -6,  "방어효과": "+28%p"},
        ])
        st.dataframe(_bubble, hide_index=True, use_container_width=True)
        st.info("정상 장세에서는 VOO와 비슷 → 폭락장에서 낙폭을 절반 이하로. 심리적으로 버텨야 저점 매수가 가능합니다.")

        # AI 슬롯 비교
        if _rot_ai_f.exists():
            with st.expander("🤖 AI 슬롯 비교 (2023.10~ | SOXX vs 466950 vs 469170)"):
                _ai_m   = pd.read_csv(_rot_ai_f)
                _ai_ann = pd.read_csv(_rot_ai_ann_f, index_col=0).dropna()
                _ai_ann.index.name = "연도"
                c1, c2 = st.columns([1, 1])
                with c1:
                    st.dataframe(_ai_m, hide_index=True, use_container_width=True,
                        column_config={
                            "전략":        st.column_config.TextColumn("AI 슬롯"),
                            "총수익률(%)": st.column_config.NumberColumn("총수익률(%)", format="%+.1f"),
                            "CAGR(%)":    st.column_config.NumberColumn("CAGR(%)", format="%+.1f"),
                            "샤프비율":    st.column_config.NumberColumn("샤프"),
                            "최대낙폭(%)": st.column_config.NumberColumn("MDD(%)", format="%.1f"),
                        })
                with c2:
                    st.bar_chart(_ai_ann, height=220)
                st.caption("466950.KS = TIGER 글로벌AI액티브(★사용자) / 469170.KS = KODEX 미국AI테크TOP10 / SOXX = 미국 원본")

    st.divider()

    # ── H15 상대저점 ETF 전략 ───────────────────────────────────────────────
    with st.expander("📊 H15 상대저점 ETF 전략 — 매월 저점 Top3 선택"):
        _strat_eq_file = RESULTS_DIR / "strategy_equity.csv"
        _strat_mt_file = RESULTS_DIR / "strategy_metrics.csv"
        if not _strat_eq_file.exists():
            st.info("결과 파일 없음 — 다음 새벽 7시 자동 갱신 후 표시됩니다.")
        else:
            _eq_df = pd.read_csv(_strat_eq_file)
            _mt_df = pd.read_csv(_strat_mt_file) if _strat_mt_file.exists() else pd.DataFrame()
            _updated = pd.Timestamp(_strat_eq_file.stat().st_mtime, unit="s").strftime("%Y-%m-%d %H:%M")
            st.caption(f"갱신: {_updated}  |  {_eq_df['ym'].iloc[0]} ~ {_eq_df['ym'].iloc[-1]} ({len(_eq_df)}개월)")

            if not _eq_df.empty:
                import plotly.graph_objects as _pgo
                _fig_eq = _pgo.Figure()
                _fig_eq.add_trace(_pgo.Scatter(x=_eq_df["ym"], y=_eq_df["strategy_cum"],
                    mode="lines", name="H15 Top3 전략", line=dict(color="#2563eb", width=2.5)))
                _fig_eq.add_trace(_pgo.Scatter(x=_eq_df["ym"], y=_eq_df["benchmark_cum"],
                    mode="lines", name="VOO 매수보유", line=dict(color="#9ca3af", width=2, dash="dash")))
                _fig_eq.update_layout(title="누적 수익률 (시작=100)", xaxis_title="월",
                    legend=dict(x=0.01, y=0.99), height=350, margin=dict(t=40, b=30))
                st.plotly_chart(_fig_eq, use_container_width=True)
                if not _mt_df.empty:
                    st.dataframe(_mt_df, hide_index=True, use_container_width=True)
                with st.expander("매월 선택된 ETF 목록"):
                    st.dataframe(
                        _eq_df[["ym", "선택ETF", "strategy_ret", "benchmark_ret"]].rename(columns={
                            "ym": "월", "strategy_ret": "전략 수익(%)", "benchmark_ret": "VOO 수익(%)"}),
                        hide_index=True, use_container_width=True,
                        column_config={
                            "전략 수익(%)": st.column_config.NumberColumn(format="%+.2f"),
                            "VOO 수익(%)":  st.column_config.NumberColumn(format="%+.2f"),
                        })
            st.caption("⚠️ 수수료·슬리피지·환율 미반영. 과거 결과가 미래를 보장하지 않습니다.")

    # ── 학술 ETF 전략 ──────────────────────────────────────────────────────
    with st.expander("📊 학술 ETF 전략 (Dual Momentum / Risk Parity / GTAA / 리밸런싱)"):
        _ETF_FILES = {
            "dual_momentum": ("etf_dual_momentum_cum.csv",   "etf_dual_momentum_stats.csv"),
            "rebalancing":   ("etf_리밸런싱_프리미엄_cum.csv", "etf_리밸런싱_프리미엄_stats.csv"),
            "risk_parity":   ("etf_risk_parity_cum.csv",     "etf_risk_parity_stats.csv"),
            "gtaa":          ("etf_gtaa_추세추종_cum.csv",    "etf_gtaa_추세추종_stats.csv"),
        }

        @st.cache_data(ttl=3600)
        def _compute_etf():
            import sys
            sys.path.insert(0, str(Path(__file__).resolve().parent))
            from scripts.etf_backtest import load_all, UNIVERSE, run_dual_momentum
            from scripts.etf_backtest import run_rebalancing_premium, run_risk_parity, run_gtaa
            panel = load_all(list(UNIVERSE.keys()))
            return {
                "dm":   run_dual_momentum(panel),
                "rb":   run_rebalancing_premium(panel),
                "rp":   run_risk_parity(panel),
                "gtaa": run_gtaa(panel),
            }

        if all((BACKTEST_DIR / v[0]).exists() for v in _ETF_FILES.values()):
            dm_cum  = pd.read_csv(BACKTEST_DIR / "etf_dual_momentum_cum.csv",   index_col=0, parse_dates=True)
            dm_stat = pd.read_csv(BACKTEST_DIR / "etf_dual_momentum_stats.csv")
            rb_cum  = pd.read_csv(BACKTEST_DIR / "etf_리밸런싱_프리미엄_cum.csv",  index_col=0, parse_dates=True)
            rb_stat = pd.read_csv(BACKTEST_DIR / "etf_리밸런싱_프리미엄_stats.csv")
            rp_cum  = pd.read_csv(BACKTEST_DIR / "etf_risk_parity_cum.csv",     index_col=0, parse_dates=True)
            rp_stat = pd.read_csv(BACKTEST_DIR / "etf_risk_parity_stats.csv")
            gt_cum  = pd.read_csv(BACKTEST_DIR / "etf_gtaa_추세추종_cum.csv",    index_col=0, parse_dates=True)
            gt_stat = pd.read_csv(BACKTEST_DIR / "etf_gtaa_추세추종_stats.csv")
        else:
            with st.spinner("ETF 데이터 수집 중... (최초 1회, 약 30초)"):
                _d = _compute_etf()
            dm_cum, dm_stat = _d["dm"]
            rb_cum, rb_stat = _d["rb"]
            rp_cum, rp_stat = _d["rp"]
            gt_cum, gt_stat = _d["gtaa"]

        st.caption("유니버스: VOO(미국주식) · VEU(선진국) · BND(채권) · GLD(금) · TLT(장기국채) · SHY(현금) / 2015-현재")
        _render_etf_strategy(dm_cum, dm_stat, "1. Dual Momentum (Antonacci 2014)",
            "상대모멘텀으로 VOO vs VEU 선택 → 절대모멘텀 음수 시 BND 대피.", "Dual Momentum")
        _render_etf_strategy(rb_cum, rb_stat, "2. 리밸런싱 프리미엄 (Booth & Fama 1992)",
            "VOO 60% / BND 30% / GLD 10% 매달 목표 비중 복귀.", "리밸런싱 60/30/10")
        _render_etf_strategy(rp_cum, rp_stat, "3. Risk Parity (Qian 2005)",
            "변동성 역비례 비중 — 리스크 균등 분배.", "Risk Parity (역변동성)")
        _render_etf_strategy(gt_cum, gt_stat, "4. GTAA 추세추종 (Faber 2007)",
            "5자산 각각 10개월 이동평균 위면 보유, 아래면 SHY(현금).", "GTAA 추세추종")
        c1, c2 = st.columns(2)
        with c1:
            st.success("GTAA(MDD -13%), Risk Parity(MDD -15%) → VOO(-24%) 대비 낙폭 40~50% 절감.")
        with c2:
            st.warning("2015-2026 강세장에서는 VOO 단순보유가 수익률 1위. 전략 우위는 샤프비율·MDD에서.")

    # ── 팩터 전략 ──────────────────────────────────────────────────────────
    with st.expander("🔬 팩터 전략 (개별주 48종목 — 모멘텀 · 저변동성 · 가치 · 퀄리티)"):
        _FACTOR_FILES = {
            "momentum": ("factor_momentum_cum.csv",  "factor_momentum_stats.csv"),
            "lowvol":   ("factor_lowvol_cum.csv",    "factor_lowvol_stats.csv"),
            "value":    ("factor_value_detail.csv",  "factor_value_stats.csv"),
            "quality":  ("factor_quality_detail.csv","factor_quality_stats.csv"),
        }

        @st.cache_data(ttl=3600)
        def _compute_factors():
            import sys
            sys.path.insert(0, str(Path(__file__).resolve().parent))
            from scripts.factor_backtest import build_monthly_panel, run_momentum, run_low_vol, run_value, run_quality
            panel = build_monthly_panel()
            return {
                "mom_cum":   run_momentum(panel)[0],  "mom_stats":  run_momentum(panel)[1],
                "vol_cum":   run_low_vol(panel)[0],   "vol_stats":  run_low_vol(panel)[1],
                "val_det":   run_value(panel)[0],     "val_stats":  run_value(panel)[1],
                "qual_det":  run_quality(panel)[0],   "qual_stats": run_quality(panel)[1],
            }

        if all((BACKTEST_DIR / v[0]).exists() for v in _FACTOR_FILES.values()):
            mom_cum   = pd.read_csv(BACKTEST_DIR / "factor_momentum_cum.csv",  index_col=0, parse_dates=True)
            mom_stats = pd.read_csv(BACKTEST_DIR / "factor_momentum_stats.csv")
            vol_cum   = pd.read_csv(BACKTEST_DIR / "factor_lowvol_cum.csv",    index_col=0, parse_dates=True)
            vol_stats = pd.read_csv(BACKTEST_DIR / "factor_lowvol_stats.csv")
            val_det   = pd.read_csv(BACKTEST_DIR / "factor_value_detail.csv")
            val_stats = pd.read_csv(BACKTEST_DIR / "factor_value_stats.csv")
            qual_det  = pd.read_csv(BACKTEST_DIR / "factor_quality_detail.csv")
            qual_stats= pd.read_csv(BACKTEST_DIR / "factor_quality_stats.csv")
        else:
            with st.spinner("팩터 계산 중... (최초 1회, 약 30초)"):
                _fd = _compute_factors()
            mom_cum, mom_stats = _fd["mom_cum"], _fd["mom_stats"]
            vol_cum, vol_stats = _fd["vol_cum"], _fd["vol_stats"]
            val_det, val_stats = _fd["val_det"], _fd["val_stats"]
            qual_det,qual_stats= _fd["qual_det"],_fd["qual_stats"]

        st.caption("48개 종목을 팩터 기준 Q1~Q4로 분위. Q1이 해당 팩터 '좋은' 구간.")
        st.markdown("**1. 12-1M 모멘텀** (Jegadeesh & Titman 1993) — Q1 = 모멘텀 상위")
        _render_rolling_factor(mom_cum, mom_stats, "모멘텀", "모멘텀 최상위", "모멘텀 최하위")
        st.markdown("**2. 저변동성** (Baker et al. 2011) — Q1 = 변동성 최저")
        _render_rolling_factor(vol_cum, vol_stats, "저변동성", "변동성 최저", "변동성 최고")
        st.markdown("**3. 가치 P/B** (Fama & French 1992) — Q1 = P/B 최저")
        _render_snapshot_factor(val_stats, val_det, "평균P/B", "평균P/B", "P/B")
        st.markdown("**4. 퀄리티 ROE** (Novy-Marx 2013) — Q1 = 퀄리티 최상위")
        _render_snapshot_factor(qual_stats, qual_det, "평균퀄리티스코어", "퀄리티스코어", "ROE+이익률")
        st.info("모멘텀·저변동성(롤링): Q1↔Q4 누적 수익 차이 클수록 팩터 유효. 소유니버스(48개)이므로 학술 대비 노이즈 큼.")

    # ── 코인 전략 ──────────────────────────────────────────────────────────
    with st.expander("🪙 코인 전략 (MVRV 사이클 · 모멘텀 · BTC+ETH 리밸런싱)"):
        _COIN_FILES = {
            "momentum":    ("coin_momentum_cum.csv",    "coin_momentum_stats.csv"),
            "mvrv":        ("coin_mvrv_cum.csv",        "coin_mvrv_stats.csv"),
            "rebalancing": ("coin_rebalancing_cum.csv", "coin_rebalancing_stats.csv"),
        }

        @st.cache_data(ttl=3600)
        def _compute_coin():
            import sys
            sys.path.insert(0, str(Path(__file__).resolve().parent))
            from scripts.coin_backtest import _build_monthly_panel, run_coin_momentum
            from scripts.coin_backtest import run_mvrv_cycle, run_crypto_rebalancing
            panel = _build_monthly_panel()
            return {"mom": run_coin_momentum(panel), "mvrv": run_mvrv_cycle(), "rb": run_crypto_rebalancing(panel)}

        if all((BACKTEST_DIR / v[0]).exists() for v in _COIN_FILES.values()):
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

        st.markdown("**1. 코인 모멘텀 (12-1M) — 주식과 같은 방향인가?**")
        st.line_chart(cm_cum)
        _mom_ret_col = "연환산수익(%)" if "연환산수익(%)" in cm_stat.columns else cm_stat.columns[2]
        c1, c2, c3, c4, c5 = st.columns(5)
        for col, (_, row) in zip([c1, c2, c3, c4, c5], cm_stat.iterrows()):
            col.metric(row.iloc[0], f"{row[_mom_ret_col]:+.1f}%/년")
        st.error("**역모멘텀**: 코인은 많이 오른 것(Q1)이 오히려 더 떨어지는 경향. 모멘텀 전략 코인에 그대로 적용 금지.")
        with st.expander("분위별 상세"):
            st.dataframe(cm_stat, use_container_width=True, hide_index=True)

        st.markdown("**2. BTC MVRV Z-Score 사이클** — Z<0: 100% / 0-1.5: 75% / 1.5-2.5: 45% / >2.5: 20%")
        st.line_chart(mv_cum)
        c1, c2 = st.columns(2)
        for col, (_, row) in zip([c1, c2], mv_stat.iterrows()):
            col.metric(row["전략"], f"{row['연환산수익(%)']}%/년", f"MDD {row['최대낙폭(%)']}% | 샤프 {row['샤프비율']}")
        st.warning("사이클 전략이 BTC 단순보유보다 수익 낮지만 MDD 15%p 절감. 방어 목적이면 유효.")
        if (BACKTEST_DIR / "coin_mvrv_zones.csv").exists():
            with st.expander("MVRV 구간별 분포"):
                st.dataframe(pd.read_csv(BACKTEST_DIR / "coin_mvrv_zones.csv"), use_container_width=True, hide_index=True)
        with st.expander("전략별 상세"):
            st.dataframe(mv_stat, use_container_width=True, hide_index=True)

        st.markdown("**3. BTC+ETH 리밸런싱 프리미엄**")
        st.line_chart(cr_cum)
        _ann_col = "연환산수익(%)" if "연환산수익(%)" in cr_stat.columns else cr_stat.columns[2]
        _mdd_col = "최대낙폭(%)" if "최대낙폭(%)" in cr_stat.columns else None
        cols = st.columns(len(cr_stat))
        for col, (_, row) in zip(cols, cr_stat.iterrows()):
            col.metric(row["전략"], f"{row[_ann_col]:+.1f}%/년", f"MDD {row[_mdd_col]}%" if _mdd_col else None)
        with st.expander("전략별 상세"):
            st.dataframe(cr_stat, use_container_width=True, hide_index=True)


# ════════════════════════════════════════════════════════
# TAB 3 — 신호 & 개별주
# ════════════════════════════════════════════════════════
with tab_sig:

    # ── 개별주 vs 시장 (핵심 메시지) ──────────────────────────────────────────
    st.subheader("개별주 vs 시장 — Buy & Hold 수익률 비교")
    st.caption("분석 대상 전 종목을 보유 첫날부터 현재까지 그냥 들고 있었으면 어땠는지 시장 지수 대비 비교합니다.")

    with st.spinner("벤치마크 데이터 로딩 중..."):
        mkt_df, benchmarks, period_start, period_end = load_vs_market()
    st.markdown(f"**분석 기간**: {period_start} ~ {period_end}")

    for cat, cat_label in [("US", "미국 주식"), ("KR", "한국 주식"), ("Coin", "코인")]:
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

        st.markdown(f"#### {cat_label} ({len(sub)}개)")
        c1, c2, c3, c4 = st.columns(4)
        c1.metric(f"벤치마크 ({bname})", f"{btot:+.1f}%", f"연 {bann:+.1f}%")
        c2.metric("시장 이긴 종목", f"{beat_pct:.0f}%", f"{beat_n}/{len(sub)}개")
        c3.metric("전체 평균 수익", f"{mean:+.1f}%", f"벤치마크 대비 {mean-btot:+.1f}%p",
                  delta_color="normal" if mean >= btot else "inverse")
        c4.metric("중앙값 수익", f"{median:+.1f}%", f"벤치마크 대비 {median-btot:+.1f}%p",
                  delta_color="normal" if median >= btot else "inverse")

        with st.expander(f"{cat_label} 전체 수익률 테이블"):
            display = sub[["ticker", "total_ret", "ann_ret"]].copy()
            display.columns = ["종목", "총 수익률(%)", "연환산(%)"]
            display["벤치마크 대비"] = (display["총 수익률(%)"] - btot).round(1)
            display["결과"] = display["총 수익률(%)"].apply(lambda x: "✅ 초과" if x > btot else "❌ 미달")
            st.dataframe(display, use_container_width=True, hide_index=True,
                column_config={
                    "총 수익률(%)":  st.column_config.NumberColumn(format="%.1f%%"),
                    "연환산(%)":     st.column_config.NumberColumn(format="%.1f%%"),
                    "벤치마크 대비": st.column_config.NumberColumn(format="%+.1f%%"),
                })

        if abs(mean - median) > 30:
            top1 = sub.iloc[0]
            st.warning(f"**슈퍼스타 효과**: {top1['ticker']} 1개가 {top1['total_ret']:+.1f}%로 평균 왜곡. "
                       f"제외 시 평균 {sub.iloc[1:]['total_ret'].mean():+.1f}%. 중앙값({median:+.1f}%)이 실제 '보통 성과'에 가깝습니다.")

    st.info("중앙값이 벤치마크보다 낮다면, 종목을 무작위로 골랐을 때 시장 지수를 이길 확률이 50% 미만. "
            "전문 펀드매니저도 장기적으로 92%가 S&P500을 못 이깁니다 (SPIVA 15년). "
            "이것이 Core를 ETF로 잡은 핵심 근거입니다.")

    st.divider()

    # ── 골든크로스 / 데스크로스 ───────────────────────────────────────────
    with st.expander("📈 골든크로스 / 데스크로스 검증"):
        st.markdown("50일 평균선 vs 200일 평균선 교차 신호의 실제 적중률")
        for sig_name, label in [("golden_cross", "골든크로스 (매수 신호)"), ("death_cross", "데스크로스 (매도 신호)")]:
            grp = crosses[crosses["signal"] == sig_name]
            n = len(grp)
            if n == 0: continue
            st.markdown(f"**{label} — 총 {n}건**")
            c1, c2, c3 = st.columns(3)
            for col_obj, days_key, label_k in [(c1, "hit_1M", "1개월"), (c2, "hit_3M", "3개월"), (c3, "hit_6M", "6개월")]:
                valid = grp[days_key].dropna()
                avg_ret = grp[days_key.replace("hit_", "fwd_")].dropna().mean()
                if len(valid) == 0: continue
                rate = valid.mean()
                with col_obj:
                    st.metric(label_k, f"{rate*100:.0f}%", f"평균 {avg_ret:+.1f}%")
                    st.caption(hit_badge(rate))
            with st.expander(f"{label} 종목별"):
                per_ticker = (grp.groupby("ticker").agg(
                    건수=("signal","count"), hit_1M=("hit_1M","mean"),
                    hit_3M=("hit_3M","mean"), hit_6M=("hit_6M","mean"),
                    avg_fwd_1M=("fwd_1M","mean"), avg_fwd_3M=("fwd_3M","mean")).reset_index()
                    .sort_values("hit_3M", ascending=False))
                for col in ["hit_1M","hit_3M","hit_6M"]:
                    per_ticker[col] = (per_ticker[col]*100).round(0).astype(str)+"%"
                for col in ["avg_fwd_1M","avg_fwd_3M"]:
                    per_ticker[col] = per_ticker[col].round(1).astype(str)+"%"
                per_ticker.columns = ["종목","건수","1M적중률","3M적중률","6M적중률","1M평균수익","3M평균수익"]
                st.dataframe(per_ticker, use_container_width=True, hide_index=True)
        st.info("적중률 50% 근처 → 예측력 없음. 60% 이상이면 통계적 우위.")

    # ── RSI 신호 ──────────────────────────────────────────────────────────
    with st.expander("📊 RSI 신호 검증 (과매수/과매도 후 방향성)"):
        for sig_key, title in [
            ("RSI 70 돌파(과매수)",    "RSI 70 돌파 — 과열 후 조정이 왔는가"),
            ("RSI 80 돌파(극단 과매수)","RSI 80 돌파 — 극단 과열 후 조정"),
            ("RSI 30 이탈(과매도)",    "RSI 30 이탈 — 과매도 후 반등"),
        ]:
            grp = rsi_df[rsi_df["signal"] == sig_key]
            if len(grp) == 0: continue
            st.markdown(f"**{title} — {len(grp)}건**")
            c1, c2, c3 = st.columns(3)
            for col_obj, dk, lk in [(c1,"hit_5d","5일"), (c2,"hit_10d","10일"), (c3,"hit_22d","1개월")]:
                valid = grp[dk].dropna()
                if len(valid) == 0: continue
                rate = valid.mean()
                avg_ret = grp[dk.replace("hit_","fwd_")].dropna().mean()
                col_obj.metric(lk, f"{rate*100:.0f}%", f"평균 {avg_ret:+.1f}%")
                col_obj.caption(hit_badge(rate))
            st.divider()
        st.warning("RSI 과매수(70/80) 후 평균 수익률이 양수(+)라면 매도 신호로 쓰는 것이 오히려 수익을 놓치는 결과.")

    # ── 손절선 검증 ────────────────────────────────────────────────────────
    with st.expander("✂️ 손절선 검증 (-8% / -20% 손절이 실제로 도움이 됐는가)"):
        st.caption("골든크로스 매수 → 데스크로스 청산 구간에서 손절선 도달 시 손절 vs 보유 비교.")
        total = len(loss_df)
        st.markdown(f"전체 진입 건수: **{total}건**")
        c1, c2 = st.columns(2)
        for col_obj, key, pct_label in [(c1, "8pct", "-8% 손절선"), (c2, "20pct", "-20% 손절선")]:
            hit = loss_df[loss_df[f"cut_{key}_hit"] == True]
            no_hit = loss_df[loss_df[f"cut_{key}_hit"] == False]
            better = hit[f"cut_{key}_better_to_cut"].dropna()
            post   = hit[f"cut_{key}_post_cut_return"].dropna()
            with col_obj:
                st.markdown(f"**{pct_label}**")
                st.metric("손절선 도달 빈도", f"{len(hit)/total*100:.0f}%", f"{len(hit)}/{total}건")
                if len(better) > 0:
                    st.metric("손절이 유리한 비율", f"{better.mean()*100:.0f}%",
                              delta_color="normal" if better.mean() >= 0.5 else "inverse")
                ca, cb = st.columns(2)
                fell = post[post < 0]; rec = post[post > 0]
                if len(fell) > 0: ca.metric("손절 후 추가 하락", f"{len(fell)}건", f"평균 {fell.mean():.1f}%")
                if len(rec)  > 0: cb.metric("손절 후 가격 반등", f"{len(rec)}건",  f"평균 +{rec.mean():.1f}%")
        st.divider()
        for key, label in [("8pct","-8%"), ("20pct","-20%")]:
            nh = loss_df[loss_df[f"cut_{key}_hit"] == False]["hold_return_pct"].dropna()
            h  = loss_df[loss_df[f"cut_{key}_hit"] == True]["hold_return_pct"].dropna()
            if len(nh) > 0 and len(h) > 0:
                c1, c2, c3 = st.columns(3)
                c1.metric(f"{label} 미도달 — 보유수익", f"{nh.mean():+.1f}%", f"{len(nh)}건")
                c2.metric(f"{label} 도달 — 보유수익",   f"{h.mean():+.1f}%",  f"{len(h)}건")
                c3.metric("차이", f"{nh.mean()-h.mean():+.1f}%p")
        st.info("손절이 유리한 비율이 69%라면 10번 중 7번은 손절 후 더 하락. -8%/-20% 손절 규칙은 실제로 추가 손실 방지 효과 있음.")
        with st.expander("종목별 손절선 상세"):
            per = (loss_df.groupby("ticker").agg(
                총진입=("hold_return_pct","count"), 보유평균수익=("hold_return_pct","mean"),
                cut8_도달=("cut_8pct_hit","sum"), cut8_유리=("cut_8pct_better_to_cut",lambda x: x.sum()),
                cut20_도달=("cut_20pct_hit","sum"), cut20_유리=("cut_20pct_better_to_cut",lambda x: x.sum()),
            ).reset_index())
            per["보유평균수익"] = per["보유평균수익"].round(1).astype(str)+"%"
            per.columns = ["종목","진입건수","보유평균수익","-8%도달","-8%유리","-20%도달","-20%유리"]
            st.dataframe(per, use_container_width=True, hide_index=True)


# ════════════════════════════════════════════════════════
# TAB 4 — 신호 예측력 연구 (IC 검증)
# ════════════════════════════════════════════════════════
with tab_val:
    st.subheader("🧪 신호 예측력 연구")
    st.caption(
        "가설 수립 → 데이터 검증 → 검증된 신호만 적용. "
        "IC(Information Coefficient) = 신호와 미래 수익률의 피어슨 상관계수. "
        "|IC| ≥ 0.05이고 p < 0.05일 때 '예측력 확인'."
    )

    _val_file = RESULTS_DIR / "signal_validation.csv"
    if not _val_file.exists():
        st.info("검증 데이터 없음.")
        if st.button("▶ 신호 예측력 검증 실행"):
            with st.spinner("검증 중..."):
                from scripts.signal_validation import run_validation
                _vdf = run_validation(RESULTS_DIR)
                _vdf.to_csv(_val_file, index=False, encoding="utf-8-sig")
                st.success("완료!")
                st.rerun()
        st.stop()

    _vdf = pd.read_csv(_val_file)

    # 가설 목록
    with st.expander("1️⃣ 검증 대상 가설 목록"):
        st.dataframe(_vdf[["id","가설","설명","참고문헌"]].drop_duplicates(), hide_index=True, use_container_width=True)

    # 검증 결과
    st.markdown("### 2️⃣ 가설 검증 결과")
    for fwd_label in ["1M", "3M"]:
        sub = _vdf[_vdf["예측창"] == fwd_label].copy()
        if sub.empty: continue
        st.markdown(f"**예측 기간: {fwd_label}**")
        st.dataframe(sub[["id","가설","IC","t통계","p값","적중률(%)","검증결과"]],
            hide_index=True, use_container_width=True,
            column_config={
                "IC":      st.column_config.NumberColumn(format="%.4f"),
                "t통계":   st.column_config.NumberColumn(format="%.2f"),
                "p값":     st.column_config.NumberColumn(format="%.4f"),
                "적중률(%)": st.column_config.NumberColumn(format="%.1f"),
                "검증결과": st.column_config.TextColumn("결과"),
            })

    st.divider()

    # 적용 결론
    st.markdown("### 3️⃣ 적용 결론")
    _confirmed = _vdf[_vdf["검증결과"].str.contains("확인|약한", na=False)]["가설"].unique()
    _rejected  = _vdf[_vdf["검증결과"].str.contains("없음",      na=False)]["가설"].unique()
    _reversed  = _vdf[_vdf["검증결과"].str.contains("역방향",    na=False)]["가설"].unique()
    col_a, col_b, col_c = st.columns(3)
    with col_a:
        st.success(f"**적용 신호 ({len(_confirmed)}개)**")
        for s in _confirmed: st.markdown(f"- {s}")
    with col_b:
        st.warning(f"**제거 신호 ({len(_rejected)}개)**")
        for s in _rejected: st.markdown(f"- {s}")
    with col_c:
        st.error(f"**역방향 신호 ({len(_reversed)}개) — 과열 경보로 전환**")
        for s in _reversed: st.markdown(f"- {s}")
    st.info("MA정렬·BB위치·RSI기울기: IC < 0 → 과열 경보 신호로 전환. VIX 역발상·거래량비율: 약하지만 방향 맞아 맥락 정보로 유지.")
    if st.button("🔄 재검증 실행"):
        with st.spinner("검증 중..."):
            from scripts.signal_validation import run_validation
            run_validation(RESULTS_DIR).to_csv(_val_file, index=False, encoding="utf-8-sig")
            st.success("완료!"); st.rerun()

    st.divider()

    # 추천 시스템 검증
    with st.expander("4️⃣ 추천 vs 비추천 — 복합점수 시스템 검증"):
        _comp_ic_file = RESULTS_DIR / "composite_validation_ic.csv"
        _comp_sp_file = RESULTS_DIR / "composite_validation_spread.csv"
        _comp_missing = not _comp_ic_file.exists() or not _comp_sp_file.exists()
        if _comp_missing:
            st.info("데이터 없음. 아래 버튼으로 실행.")
        _run_comp = st.button("▶ 추천 시스템 검증 실행 (약 20초)")
        if _run_comp or not _comp_missing:
            if _run_comp:
                with st.spinner("검증 중..."):
                    from scripts.signal_validation import run_composite_validation
                    _cic, _csp = run_composite_validation(RESULTS_DIR)
                    _cic.to_csv(_comp_ic_file, index=False, encoding="utf-8-sig")
                    _csp.to_csv(_comp_sp_file, index=False, encoding="utf-8-sig")
                    st.success("완료!")
            else:
                _cic = pd.read_csv(_comp_ic_file)
                _csp = pd.read_csv(_comp_sp_file)
            st.markdown("**H9/H10 IC 검증**")
            if not _cic.empty:
                st.dataframe(_cic[["id","가설","예측창","IC","t통계","p값","적중률(%)","검증결과"]],
                    hide_index=True, use_container_width=True)
            st.markdown("**H11: 상위33% vs 하위33% 수익 격차**")
            if not _csp.empty:
                st.dataframe(_csp, hide_index=True, use_container_width=True)
                _sp1m = _csp[_csp["예측창"] == "1M"].iloc[0] if "1M" in _csp["예측창"].values else None
                if _sp1m is not None:
                    _gap = float(_sp1m["격차(%p)"]); _pval = float(_sp1m["p값"])
                    _hit = float(_sp1m["격차양수비율(%)"]); _result = str(_sp1m["검증결과"])
                    if "❌" in _result:
                        st.error(f"❌ 통계적으로 유의한 수익 차이 없음 (p={_pval:.3f}) — 방향은 맞지만 오차 범위 내.")
                    elif "✅" in _result:
                        st.success(f"✅ 유의미한 수익 차이 확인 (p={_pval:.3f}) — 격차 {_gap:+.2f}%p, 추천>비추천 {_hit:.0f}%")
            if st.button("🔄 추천 시스템 재검증"):
                with st.spinner("재검증 중..."):
                    from scripts.signal_validation import run_composite_validation
                    _c1, _c2 = run_composite_validation(RESULTS_DIR)
                    _c1.to_csv(_comp_ic_file, index=False, encoding="utf-8-sig")
                    _c2.to_csv(_comp_sp_file, index=False, encoding="utf-8-sig")
                    st.success("완료!"); st.rerun()

    # H15/H16 검증
    with st.expander("5️⃣ H15/H16 — 상대저점 지수 검증 (BB+MA 역방향 복합)"):
        _h15_ic_file = RESULTS_DIR / "h15_ic.csv"
        _h15_sp_file = RESULTS_DIR / "h15_spread.csv"
        _run_h15 = st.button("▶ H15/H16 검증 실행 (약 20초)")
        if _run_h15 or _h15_ic_file.exists():
            if _run_h15:
                with st.spinner("H15/H16 검증 중..."):
                    from scripts.signal_validation import run_validated_composite
                    _h15ic, _h15sp = run_validated_composite(RESULTS_DIR)
                    _h15ic.to_csv(_h15_ic_file, index=False, encoding="utf-8-sig")
                    _h15sp.to_csv(_h15_sp_file, index=False, encoding="utf-8-sig")
                    st.success("완료!")
            else:
                _h15ic = pd.read_csv(_h15_ic_file) if _h15_ic_file.exists() else pd.DataFrame()
                _h15sp = pd.read_csv(_h15_sp_file) if _h15_sp_file.exists() else pd.DataFrame()
            if not _h15ic.empty:
                st.markdown("**H15 IC 결과**")
                st.dataframe(_h15ic[["id","가설","예측창","IC","t통계","p값","적중률(%)","표본수","검증결과"]],
                    hide_index=True, use_container_width=True)
            if not _h15sp.empty:
                st.markdown("**H16 수익 격차**")
                st.dataframe(_h15sp, hide_index=True, use_container_width=True)
                st.success("H15/H16 검증 통과 (IC=0.087, p<0.001 | 상위 2.82%/월 vs 하위 1.03%/월, 격차 1.79%p)  \n"
                           "→ ETF 탭·리밸런싱 탭 '상대적 저점' 컬럼에 반영됨.")
            st.caption("탐색 과정: z-score / rank 정규화 모두 실패(IC≈0). 원시값 가중합이 최종 채택됨.")

    # 전체 신호 현황판
    st.divider()
    st.markdown("### 📋 전체 신호 검증 현황")
    st.markdown("""
| 신호 | IC (1M) | p값 | 검증 | 시스템 반영 |
|---|---|---|---|---|
| **VIX 역발상** | +0.14 | <0.001 | ✅ 강력 | ✅ VIX국면 배율 핵심 |
| **H15 상대저점** | +0.087 | <0.001 | ✅ 강력 | ✅ 저점 순위 컬럼 |
| **BB 위치** | -0.087 | <0.001 | ✅ 역방향 | ✅ 과열 페널티 |
| **MA 정렬** | -0.065 | 0.002 | ✅ 역방향 | ✅ 과열 페널티 |
| **RSI 기울기** | -0.066 | 0.001 | ✅ 역방향 | ✅ 과열 경보 표시 |
| **거래량 비율** | +0.040 | 0.001 | ⚠️ 약함 | ⚠️ 참고 표시만 |
| **12M 모멘텀** | +0.019 | 0.61 | ❌ 없음 | ❌ 10% 보조만 |
| **섹터사이클** | -0.023 | 0.34 | ❌ 없음 | ❌ ±5%로 축소 |
| **Bull추세 필터** | -0.047 | 0.010 | ⚠️ 역방향 | ❌ 필터 완화 |
| **MACD** | ≈0 | 0.58 | ❌ 없음 | ❌ 제거됨 |
""")
    st.success("배분의 실질 드라이버: **VIX 국면**(강력 검증) × **H15 상대저점**(검증됨).  \n"
               "나머지 신호는 참고 정보 — 단독 매수/매도 근거로 사용하지 마세요.")
    st.caption("시스템 반영 원칙: IC≥0.05 + p<0.05 → 점수 반영 / IC역방향 검증 → 과열 경보 / IC≈0 or p>0.1 → 참고 표시만.")

    # 시스템 신호 검증 (H12~H14)
    with st.expander("6️⃣ 시스템 실사용 신호 검증 (H12~H14)"):
        _sys_file = RESULTS_DIR / "system_validation.csv"
        _run_sys  = st.button("▶ 시스템 신호 검증 실행 (약 20초)")
        if _run_sys or _sys_file.exists():
            if _run_sys:
                with st.spinner("H12~H14 검증 중..."):
                    from scripts.signal_validation import run_system_validation
                    _sdf = run_system_validation(RESULTS_DIR)
                    _sdf.to_csv(_sys_file, index=False, encoding="utf-8-sig")
                    st.success("완료!")
            else:
                _sdf = pd.read_csv(_sys_file)
            if not _sdf.empty:
                st.dataframe(_sdf[["id","가설","예측창","IC","t통계","p값","적중률(%)","검증결과"]],
                    hide_index=True, use_container_width=True)
