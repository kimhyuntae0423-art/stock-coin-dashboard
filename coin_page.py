import streamlit as st
import pandas as pd
from pathlib import Path
import plotly.graph_objects as go
import sys

ROOT = Path(__file__).resolve().parent
sys.path.append(str(ROOT))
from scripts.fear_greed import fetch_crypto_fear_greed
from scripts.onchain import (
    classify_regime, score_mvrv, score_nupl, score_puell,
    score_pi_cycle, score_fng, composite_score,
)
from scripts.ui import render_fng_gauge
from scripts.config import RESULTS_DIR as RESULTS, COIN_NAMES_FILE as NAMES_FILE


def load_names() -> dict:
    if not NAMES_FILE.exists():
        return {}
    n = pd.read_csv(NAMES_FILE)
    return dict(zip(n["ticker"], n["name"]))


NAMES = load_names()


def label(t: str) -> str:
    return f"{t} · {NAMES[t]}" if t in NAMES else t


def fmt(v, fmt_str="{:,.2f}", suffix=""):
    if v is None or pd.isna(v):
        return "-"
    try:
        return fmt_str.format(v) + suffix
    except Exception:
        return str(v)


@st.cache_data(ttl=3600)
def get_usd_krw_rate() -> float:
    """USD/KRW 환율 — yfinance 사용, 1시간 캐시, 실패 시 폴백 1370."""
    try:
        import yfinance as yf
        hist = yf.Ticker("USDKRW=X").history(period="5d")
        if not hist.empty:
            return float(hist["Close"].iloc[-1])
    except Exception:
        pass
    return 1370.0


def fmt_krw(usd_value, rate):
    """USD 값을 KRW로 환산해 사람이 읽기 좋은 단위(억/만)로 포맷."""
    if usd_value is None or pd.isna(usd_value) or rate is None:
        return "-"
    try:
        krw = float(usd_value) * float(rate)
    except Exception:
        return "-"
    if krw >= 1e8:
        return f"{krw/1e8:,.2f}억원"
    if krw >= 1e4:
        return f"{krw/1e4:,.1f}만원"
    return f"{krw:,.0f}원"


st.title("🪙 코인 분석 대시보드")
st.caption(
    "여러 신뢰받는 코인 분석 지표를 종합하여 **합성 매매 신호**를 만들고, 그에 따라 **매수 우선순위 추천**까지 보여줍니다."
)

# 데이터 로드
summary_file = RESULTS / "coin_summary.csv"
metrics_file = RESULTS / "cycle_metrics.csv"
if not summary_file.exists() or not metrics_file.exists():
    st.warning("코인 분석 결과가 없습니다. 먼저 `python run_analysis.py`를 실행하세요.")
    st.stop()

summary = pd.read_csv(summary_file)
M = pd.read_csv(metrics_file).iloc[0].to_dict()


# ===================== 1. 시장 심리 (F&G) — 최상단 =====================
@st.cache_data(ttl=3600)
def _cached_crypto_fng():
    return fetch_crypto_fear_greed()


fng = _cached_crypto_fng()
st.subheader("🧠 코인 시장 심리 (Crypto Fear & Greed Index)")
fg1, fg2 = st.columns([1, 2])
with fg1:
    render_fng_gauge(fng, "Crypto F&G Index")
with fg2:
    st.markdown(
        """
**Crypto F&G** (Alternative.me) — 변동성·거래량·SNS 언급·도미넌스 등을 종합한 단기 분위기 지표.
- **0~25 극단 공포**: 패닉, 역사적 바닥 부근. *워런 버핏: 남들이 두려워할 때 탐욕스러워라*
- **25~45 공포**: 약세 분위기
- **75~100 극단 탐욕**: 과열, 조정 가능성

이 지수만으로 매매하지 말고, 아래 온체인 지표들과 같은 방향이면 신뢰도가 높아진다는 식으로 보세요.
"""
    )

st.divider()

# ===================== 2. 종합 신호 (5개 지표) =====================
st.subheader("🎯 종합 매매 신호 — 5개 지표 합성")

fng_score_val = fng.get("score")
scores = {
    "MVRV Z-Score": score_mvrv(M.get("mvrv_z")),
    "NUPL": score_nupl(M.get("nupl")),
    "Puell Multiple": score_puell(M.get("puell")),
    "Pi Cycle Top": score_pi_cycle(M.get("pi_ratio")),
    "Fear & Greed": score_fng(fng_score_val),
}
comp = composite_score(scores)

cs1, cs2 = st.columns([1, 2])
with cs1:
    st.metric("종합 신호", comp["label"], delta=f"평균 점수 {comp['avg']:+.2f} / +2")
    st.caption("각 지표를 -2(강한 매도) ~ +2(강한 매수)로 점수화하여 평균")

with cs2:
    # 점수 시각화
    score_df = pd.DataFrame({
        "지표": list(scores.keys()),
        "점수": list(scores.values()),
    })
    fig_score = go.Figure(go.Bar(
        x=score_df["점수"], y=score_df["지표"], orientation="h",
        marker=dict(color=score_df["점수"], colorscale=[
            [0.0, "#c0392b"], [0.25, "#e67e22"], [0.5, "#f1c40f"],
            [0.75, "#27ae60"], [1.0, "#16a085"],
        ], cmin=-2, cmax=2),
        text=[f"{v:+d}" for v in score_df["점수"]], textposition="outside",
    ))
    fig_score.update_layout(
        height=260, xaxis=dict(range=[-2.5, 2.5], title="-2(매도) ~ +2(매수)"),
        margin=dict(l=20, r=20, t=20, b=20), showlegend=False,
    )
    st.plotly_chart(fig_score, use_container_width=True)

# 각 지표 상세
st.markdown("#### 📊 지표별 현재 값")
g = st.columns(5)
mvrv_z = M.get("mvrv_z")
g[0].metric("MVRV Z-Score", fmt(mvrv_z, "{:.2f}"),
            delta=classify_regime(mvrv_z)["label"], delta_color="off")
g[1].metric("NUPL", fmt(M.get("nupl"), "{:.3f}"),
            delta="0=손익분기 · 0.5+=낙관 · 0.75+=도취", delta_color="off")
g[2].metric("Puell Multiple", fmt(M.get("puell"), "{:.3f}"),
            delta="<0.5=채굴자 항복 · >4=차익실현", delta_color="off")
pi_ratio = M.get("pi_ratio")
g[3].metric("Pi Cycle (111/350×2)", fmt(pi_ratio, "{:.3f}"),
            delta=">=1 이면 사이클 천정", delta_color="off")
g[4].metric("F&G", fmt(fng_score_val, "{:.0f}"),
            delta=fng.get("label", ""), delta_color="off")

with st.expander("📘 지표 해설 (왜 이 5개를 골랐는가)"):
    st.markdown(
        """
**선정 근거** — 비트코인 매거진·CoinMarketCap·Glassnode 등 주요 분석처에서 가장 자주 인용되는 "역사적으로 검증된 사이클 지표" 4개 + 단기 심리 1개:

| 지표 | 출처 | 무엇을 측정 | 신뢰성 평가 |
|---|---|---|---|
| **MVRV Z-Score** | 온체인 | 평균 보유자 매수가 대비 현재가 (표준편차 정규화) | 모든 사이클 천정/바닥 정확히 표시 |
| **NUPL** | 온체인 | 미실현 손익 비율 (시장 전체의 평가손익) | MVRV와 보완. 단계별로 "희망/낙관/탐욕/도취" 구분 |
| **Puell Multiple** | 온체인 | 채굴자 수익 / 365일 평균 채굴 수익 | 채굴자 항복(바닥) · 차익실현(천정) 포착 |
| **Pi Cycle Top** | 가격 | 111-day MA vs 350-day MA × 2 | 2013·2017·2021 천정을 모두 정확히 표시. 2024 사이클에선 약화 의견 있음 |
| **Crypto F&G** | 시장 | 변동성·거래량·SNS·도미넌스 종합 | 단기 분위기. 위 4개와 같은 방향이면 신뢰도 ↑ |

**해석법:** 1~2개 지표만으로 결정하지 말고 **3개 이상이 같은 방향**일 때 신뢰. 본 페이지의 합성 점수는 그 단순화 버전.
"""
    )

st.divider()

# ===================== 3. Altcoin Season Index =====================
st.subheader("🪙 Altcoin Season Index (보유 코인 기준)")
alt_score = M.get("alt_season_score")
alt_label = M.get("alt_season_label")
alt_regime = M.get("alt_season_regime")
btc_90d = M.get("btc_return_90d_pct")

a1, a2 = st.columns([1, 2])
with a1:
    st.metric("Altcoin Season Score", fmt(alt_score, "{:.0f}", "/100"),
              delta=alt_label, delta_color="off")
    st.caption(f"BTC 최근 90일 수익률: {btc_90d:+.2f}%" if btc_90d is not None else "")
with a2:
    st.markdown(
        """
**Altcoin Season Index** = 보유 코인 중 *최근 90일 BTC 대비 outperform한 코인 비율*.
- **≥ 75 알트시즌**: 알트가 BTC를 광범위하게 능가 → 알트 비중 확대 시기로 인식
- **≤ 25 비트코인 시즌**: 알트 부진 → BTC 중심 포트가 안전
- **25~75 전환**: 방향성 불분명

> CoinMarketCap 정식 지수는 상위 100코인 기준이지만, 본 페이지는 우리가 분석 중인 14개 코인 기준이라 약간 다를 수 있습니다.
"""
    )

st.divider()

# ===================== 4. 매수 추천 =====================
st.subheader("💰 매수 우선순위 추천")


# MVRV 존 라벨 — 백테스트 검증된 1차 신호 (classify_regime()과 동일 기준, 단일 소스)
_mvrv_now = M.get("mvrv_z")
if _mvrv_now is not None:
    _mvrv_regime = classify_regime(_mvrv_now)
    _mvrv_st_method = {
        "deep_value": "success", "accumulation": "info",
        "bull": "warning", "top": "error",
    }.get(_mvrv_regime["regime"], "info")
    getattr(st, _mvrv_st_method)(
        f"**MVRV Z-Score 1차 신호 (백테스트 검증)**: {_mvrv_now:.2f} → {_mvrv_regime['label']}  \n"
        f"코인 RSI 과매수(70/75/80)는 H20 백테스트 적중률 34~47%(동전던지기보다 나쁨) — "
        f"MVRV 구간이 훨씬 더 신뢰할 수 있는 신호입니다."
    )

st.markdown(
    f"""
**현재 종합 신호**: {comp['label']}
**시장 단계**: {alt_label or '데이터 없음'}

추천 로직:
1. **MVRV Z-Score** (1차 신호, 백테스트 검증) — 현재 구간별 BTC 최적 비중
2. 종합 점수가 **+0.5 이상**이면 매수 추천 활성화 (현재 평균 **{comp['avg']:+.2f}**)
3. **비트코인 시즌**이면 → BTC, ETH 위주 / **알트시즌**이면 → BTC를 앞서는 알트 우선
4. RSI <= 25 과매도만 +0.3 가산 (H20 적중률 51~54%, 약한 신호) — 과매수 페널티는 제거함(적중률 34~47%로 역방향/무효 확인)
"""
)

# 추천 점수 계산
def recommend_score(row, comp_avg, alt_regime):
    """코인별 매수 추천 점수"""
    score = comp_avg  # 시장 베이스
    ticker = row["ticker"]
    rsi = row.get("rsi14")

    # 1. 시장 시즌 보정 — 알트시즌 점수 자체는 검증된 신호(CLAUDE.md)이지만, "개별
    # 코인이 BTC 90일 수익률을 넘었는가"라는 상대모멘텀 조건은 별도 백테스트가 없어
    # (2026-07-21 재검증) 제거. 시즌 규정 자체를 근거로 한 BTC/ETH 가산만 유지.
    if alt_regime == "bitcoin_season":
        if ticker in ("BTC-USD", "ETH-USD"):
            score += 0.5    # BTC·ETH 가산

    # 2. RSI 보정 — H20 백테스트(scripts/signal_validation.run_coin_rsi_validation) 결과 반영
    # 과매수 RSI>70/75/80 페널티는 적중률 34~47%(동전던지기보다 나쁨, 임계값 높을수록 더 나쁨)로 전부 제거.
    # 코인은 RSI가 높을수록 오히려 상승 지속 경향 — 주식식 역모멘텀 가정이 틀렸음.
    # RSI<=25 과매도만 적중률 51~54%로 약하게 유효 → 소폭 가산만 유지.
    if pd.notna(rsi) and rsi <= 25:
        score += 0.3          # 과매도 가산 (약한 신호, H20 적중률 51~54%)

    # (2026-07-21) 90일 모멘텀 기반 보정은 제거함 — 임계값(-30%/+100%)이 코인
    # 대상 백테스트 없이 하드코딩돼 있었음(재검증 결과: CLAUDE.md의 "모멘텀 단독
    # 신호 IC=+0.019, p=0.61"은 ETF/주식 12M 모멘텀 검증치이지 코인 90일 임계값
    # 검증이 아님 — 잘못 인용했었음, 정정). 위 RSI≤25 가산과 달리 코인 자체
    # 검증 결과가 아예 없어서 "근거 없으면 추가 금지" 원칙에 따라 제거.

    return round(score, 2)


rec_df = summary.copy()
rec_df["추천 점수"] = rec_df.apply(
    lambda r: recommend_score(r, comp["avg"], alt_regime), axis=1
)
rec_df["코인명"] = rec_df["ticker"].map(NAMES).fillna("-")
rec_df = rec_df.sort_values("추천 점수", ascending=False).reset_index(drop=True)
rec_df["순위"] = rec_df.index + 1

# 상위 5개 강조
top5 = rec_df.head(5)
if comp["avg"] >= 0.5:
    st.success(f"✅ 종합 신호가 매수 우호적 ({comp['avg']:+.2f}). 상위 추천 코인:")
    cols = st.columns(5)
    for i, (_, r) in enumerate(top5.iterrows()):
        with cols[i]:
            st.markdown(f"### #{r['순위']}")
            st.markdown(f"**{r['코인명']}**")
            st.markdown(f"`{r['ticker']}`")
            st.markdown(f"점수: **{r['추천 점수']:+.2f}**")
            st.markdown(f"RSI: {fmt(r.get('rsi14'), '{:.1f}')}")
            st.markdown(f"90일: {fmt(r.get('return_90d_pct'), '{:+.1f}', '%')}")
elif comp["avg"] >= -0.5:
    st.info(f"🔵 종합 신호 중립 ({comp['avg']:+.2f}). 새로 매수보다 보유/관망 권장.")
else:
    st.error(f"⚠️ 종합 신호 매도 우호 ({comp['avg']:+.2f}). 신규 매수 자제 권장.")

st.markdown("#### 전체 추천 순위표")
usd_krw = get_usd_krw_rate()
st.caption(f"💱 적용 환율: 1 USD = **{usd_krw:,.2f} KRW** (yfinance, 1시간 캐시)")

display = rec_df.copy()
display["종가(KRW)"] = display["close"] * usd_krw  # 원화 환산 (raw numeric for sortable)
display = display.rename(columns={
    "ticker": "티커",
    "close": "종가(USD)",
    "rsi14": "RSI",
    "return_90d_pct": "90일 수익률(%)",
})
st.dataframe(
    display[["순위", "티커", "코인명", "추천 점수", "종가(USD)", "종가(KRW)", "RSI", "90일 수익률(%)"]],
    use_container_width=True,
    hide_index=True,
    column_config={
        "종가(USD)": st.column_config.NumberColumn(format="$%.4f"),
        "종가(KRW)": st.column_config.NumberColumn(format="₩%,.0f",
                                                   help=f"USD × {usd_krw:,.2f} KRW 환산"),
        "RSI": st.column_config.NumberColumn(format="%.1f"),
        "90일 수익률(%)": st.column_config.NumberColumn(format="%+.1f"),
        "추천 점수": st.column_config.NumberColumn(format="%+.2f"),
    },
)

st.caption(
    "**중요**: 이 추천은 통계적 신호의 단순 합성이지 미래 수익을 보장하지 않습니다. "
    "특히 알트코인은 단일 사이클로 90% 이상 빠지는 경우가 흔합니다. 분할 매수와 손절 기준을 반드시 정하세요."
)

st.divider()

# ===================== 5. MVRV Z-Score 차트 =====================
mvrv_hist_file = RESULTS / "mvrv_history.csv"
if mvrv_hist_file.exists() and mvrv_z is not None:
    st.subheader("📐 MVRV Z-Score 히스토리")
    hist = pd.read_csv(mvrv_hist_file, parse_dates=["date"], index_col="date")
    z_col = "value" if "value" in hist.columns else "z_score"
    fig_z = go.Figure()
    fig_z.add_trace(go.Scatter(x=hist.index, y=hist[z_col], name="MVRV Z-Score",
                               line=dict(color="#9b59b6", width=2)))
    for y0, y1, c, txt in [
        (-2, 0, "#16a085", "BTC 100%"), (0, 1.5, "#27ae60", "BTC 75%"),
        (1.5, 2.5, "#e67e22", "BTC 45%"), (2.5, 12, "#c0392b", "BTC 20%(과열)"),
    ]:
        fig_z.add_hrect(y0=y0, y1=y1, fillcolor=c, opacity=0.12, line_width=0,
                        annotation_text=txt, annotation_position="left")
    fig_z.add_hline(y=mvrv_z, line_dash="dot", line_color="black",
                    annotation_text=f"현재 {mvrv_z:.2f}", annotation_position="right")
    fig_z.update_layout(height=380, hovermode="x unified", yaxis_title="Z-Score",
                        legend=dict(orientation="h"))
    st.plotly_chart(fig_z, use_container_width=True)

# Pi Cycle 차트
pi_series_file = RESULTS / "pi_cycle_series.csv"
if pi_series_file.exists() and pi_ratio is not None:
    st.subheader("🥧 Pi Cycle Top Indicator")
    pi = pd.read_csv(pi_series_file, parse_dates=[0], index_col=0)
    fig_pi = go.Figure()
    fig_pi.add_trace(go.Scatter(x=pi.index, y=pi["sma111"], name="111-day SMA",
                                line=dict(color="#e74c3c", width=2)))
    fig_pi.add_trace(go.Scatter(x=pi.index, y=pi["sma350x2"], name="350-day SMA × 2",
                                line=dict(color="#3498db", width=2)))
    fig_pi.update_layout(
        height=380, hovermode="x unified", yaxis_title="BTC 가격 (USD)",
        yaxis_type="log", legend=dict(orientation="h")
    )
    st.plotly_chart(fig_pi, use_container_width=True)
    st.caption(
        "두 선이 교차(111SMA ≥ 350SMA×2)하면 천정 신호. "
        f"현재 비율: {pi_ratio:.3f} — 1.0에 가까울수록 천정 임박."
    )

st.divider()

# ===================== 6. 코인별 상세 =====================
st.subheader("🔍 코인별 상세 분석")
tickers = sorted(summary["ticker"].tolist())
sel = st.selectbox("코인 선택", tickers, format_func=label)

row = summary[summary["ticker"] == sel].iloc[0]
rec_row = rec_df[rec_df["ticker"] == sel].iloc[0]
st.markdown(f"### {label(sel)}")

c1, c2, c3, c4, c5 = st.columns(5)
c1.metric("추천 점수", f"{rec_row['추천 점수']:+.2f}", delta=f"순위 #{rec_row['순위']}",
          delta_color="off")
c2.metric("종가 (USD)", f"${row['close']:,.4f}")
c3.metric("종가 (KRW)", fmt_krw(row['close'], usd_krw),
          delta=f"@ {usd_krw:,.0f}원/USD", delta_color="off")
c4.metric("RSI(14)", fmt(row.get("rsi14")))
c5.metric("90일 수익률", fmt(row.get("return_90d_pct"), "{:+.1f}", "%"))

rsi = row.get("rsi14")
if pd.notna(rsi):
    if rsi >= 80:
        st.info(f"RSI {rsi:.1f} — 강한 상승 모멘텀. 코인은 과매수가 매도 신호로 작동하지 않음 "
                f"(H20 백테스트: RSI≥80 적중률 34%, 오히려 상승 지속 경향)")
    elif rsi <= 25:
        st.success(f"RSI {rsi:.1f} — 과매도 (약한 반등 신호, H20 적중률 51~54%)")

df_file = RESULTS / f"coin_{sel}_signals.csv"
if df_file.exists():
    df = pd.read_csv(df_file, index_col=0, parse_dates=True)
    fig = go.Figure()
    fig.add_trace(go.Scatter(x=df.index, y=df["Close"], name="종가", line=dict(color="#888")))
    if "ma50" in df.columns:
        fig.add_trace(go.Scatter(x=df.index, y=df["ma50"], name="50일선",
                                 line=dict(color="#3498db")))
    if "ma200" in df.columns:
        fig.add_trace(go.Scatter(x=df.index, y=df["ma200"], name="200일선",
                                 line=dict(color="#e67e22")))
    fig.update_layout(height=450, hovermode="x unified", yaxis_type="log",
                      legend=dict(orientation="h"))
    st.plotly_chart(fig, use_container_width=True)

    # RSI
    fig_rsi = go.Figure()
    fig_rsi.add_trace(go.Scatter(x=df.index, y=df["rsi14"], name="RSI(14)",
                                 line=dict(color="#9b59b6")))
    fig_rsi.add_hline(y=70, line_dash="dash", line_color="red")
    fig_rsi.add_hline(y=30, line_dash="dash", line_color="green")
    fig_rsi.update_layout(height=240, yaxis_range=[0, 100], hovermode="x unified")
    st.plotly_chart(fig_rsi, use_container_width=True)

st.caption("투자는 본인 책임이며 본 분석은 참고용입니다. 사이클 지표가 다 매수를 가리켜도 단기 추가 하락은 흔합니다.")
