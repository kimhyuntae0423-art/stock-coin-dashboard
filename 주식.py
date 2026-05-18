import streamlit as st
import pandas as pd
from pathlib import Path
import plotly.graph_objects as go
import sys

sys.path.append(str(Path(__file__).resolve().parent))
from scripts.fear_greed import fetch_cnn_fear_greed
from scripts.ui import render_fng_gauge
from scripts.stock_score import rank_stocks

st.set_page_config(layout="wide", page_title="주식 분석 대시보드", page_icon="📈")

BASE = Path(__file__).resolve().parent
RESULTS = BASE / "results"
NAMES_FILE = BASE / "names.csv"


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


def fmt_mcap(v, currency="USD"):
    if v is None or pd.isna(v):
        return "-"
    units = [("T", 1e12), ("B", 1e9), ("M", 1e6)]
    for u, n in units:
        if v >= n:
            return f"{v/n:,.2f}{u} {currency}"
    return f"{v:,.0f} {currency}"


# ============== 헤더 ==============
st.title("📈 주식 분석 대시보드")
st.caption(
    "QVM 4-팩터 펀더멘털 점수 + 골든크로스 추세 신호를 결합한 종합 추천. "
    "사이드바에서 코인 페이지로 이동할 수 있습니다."
)

# ============== 데이터 로드 ==============
summary_file = RESULTS / "summary_signals.csv"
if not summary_file.exists():
    st.warning("분석 결과가 없습니다. 먼저 `python run_analysis.py`를 실행하세요.")
    st.stop()

summary = pd.read_csv(summary_file)
funda_file = RESULTS / "fundamentals.csv"
funda = pd.read_csv(funda_file) if funda_file.exists() else pd.DataFrame(columns=["ticker"])


# ============== F&G (항상 상단) ==============
@st.cache_data(ttl=3600)
def _cached_cnn_fng():
    return fetch_cnn_fear_greed()


st.subheader("🧠 시장 심리 (Fear & Greed Index)")
fng_col1, fng_col2 = st.columns([1, 2])
with fng_col1:
    render_fng_gauge(_cached_cnn_fng(), "CNN 공포·탐욕 지수")
with fng_col2:
    st.markdown(
        """
**해석 기준**
- **0~25 극단적 공포** — 역사적 매수 기회 구간
- **25~45 공포** · **45~55 중립** · **55~75 탐욕**
- **75~100 극단적 탐욕** — 과열, 조정 가능성

> *남들이 탐욕스러울 때 두려워하고, 남들이 두려워할 때 탐욕스러워라.* — 워런 버핏
"""
    )

st.divider()


# ============== 점수 계산 (모든 탭 공통) ==============
action_color = {
    "매수": "🟢 매수",
    "보유": "🔵 보유",
    "매도": "🔴 매도",
    "미보유": "⚪ 미보유",
}

score_input = summary.merge(
    funda[["ticker", "per", "pbr", "roe_pct", "profit_margin_pct"]],
    on="ticker", how="left",
)
scores_df = rank_stocks(score_input)
score_disp = scores_df.merge(
    score_input[["ticker", "close", "state", "action", "rsi14",
                 "return_12m_pct", "per", "pbr", "roe_pct"]],
    on="ticker", how="left",
)
score_disp["종목명"] = score_disp["ticker"].map(NAMES).fillna("-")


def composite_label(avg):
    if avg >= 1.5: return "🟢🟢 강한 매수"
    if avg >= 0.5: return "🟢 매수 우호"
    if avg > -0.5: return "🔵 중립"
    if avg > -1.5: return "🟠 매도 우호"
    return "🔴 매수 자제"


def integrated_recommendation(qvm, action):
    good_funda = qvm >= 0.5
    avg_funda = qvm > -0.5
    if good_funda:
        if action == "매수":  return "💎 강력 매수", "펀더 우수 + 골든크로스 발생"
        if action == "보유":  return "✅ 보유/분할매수", "펀더 우수 + 상승 추세 유지"
        if action == "미보유": return "⏳ 골든크로스 대기", "펀더 우수, 추세 전환 신호 기다리기"
        if action == "매도":  return "🟠 신중 매수", "펀더 우수하나 단기 약세"
    elif avg_funda:
        if action == "매수":  return "🔵 단기 신호", "펀더는 평범, 추세는 매수"
        return "⚪ 관망", "특별한 매력 없음"
    else:
        return "❌ 회피", "펀더 약함"


def priority_score(qvm, action):
    bonus = {"매수": 0.5, "보유": 0.0, "미보유": -0.2, "매도": -0.5}.get(action, 0)
    return qvm + bonus


score_disp["판정"] = score_disp["composite"].apply(composite_label)
score_disp["추세"] = score_disp["action"].map(action_color).fillna(score_disp["action"])
recs = score_disp.apply(
    lambda r: integrated_recommendation(r["composite"], r["action"]), axis=1
)
score_disp["통합 추천"] = [r[0] for r in recs]
score_disp["추천 이유"] = [r[1] for r in recs]
score_disp["우선순위 점수"] = score_disp.apply(
    lambda r: round(priority_score(r["composite"], r["action"]), 2), axis=1
)
score_disp = score_disp.sort_values("우선순위 점수", ascending=False).reset_index(drop=True)


# ============== 탭 ==============
tab_summary, tab_compare, tab_detail = st.tabs([
    "📊 요약 & 추천",
    "📈 종목 비교",
    "🔍 종목 상세",
])


# ============== 탭 1: 요약 & 추천 ==============
with tab_summary:
    st.subheader("🎯 통합 추천 — 좋은 종목 + 지금이 살 타이밍인가")
    st.caption(
        "**무엇을 살까 (QVM 4-팩터)** 와 **언제 살까 (골든크로스 50/200일선)** 를 결합."
    )

    st.markdown("#### 💰 매수 우선순위 TOP 5")
    top5 = score_disp.head(5)
    cols = st.columns(5)
    for i, (_, r) in enumerate(top5.iterrows()):
        with cols[i]:
            st.markdown(f"#### #{i+1}")
            st.markdown(f"**{r['종목명']}**")
            st.markdown(f"`{r['ticker']}`")
            st.markdown(f"### {r['통합 추천']}")
            st.markdown(
                f"**우선순위 {r['우선순위 점수']:+.2f}**  \n"
                f"QVM {r['composite']:+.2f} · 추세 {r['추세']}"
            )
            st.caption(r["추천 이유"])
            st.markdown(
                f"V {fmt(r.get('value_score'), '{:+d}')} · "
                f"Q {fmt(r.get('quality_score'), '{:+d}')} · "
                f"M {fmt(r.get('momentum_score'), '{:+d}')} · "
                f"T {fmt(r.get('technical_score'), '{:+d}')}"
            )

    st.markdown("#### 전체 통합 순위표")
    rank_table = score_disp.copy()
    rank_table["순위"] = range(1, len(rank_table) + 1)
    rank_table = rank_table.rename(columns={
        "ticker": "티커", "close": "종가", "composite": "QVM 점수",
        "value_score": "가치", "quality_score": "품질",
        "momentum_score": "모멘텀", "technical_score": "기술적",
        "per": "PER", "pbr": "PBR", "roe_pct": "ROE(%)",
        "return_12m_pct": "12M 수익률(%)", "rsi14": "RSI",
    })
    st.dataframe(
        rank_table[["순위", "티커", "종목명", "통합 추천", "우선순위 점수",
                    "QVM 점수", "추세", "판정",
                    "가치", "품질", "모멘텀", "기술적",
                    "종가", "PER", "PBR", "ROE(%)", "12M 수익률(%)", "RSI"]],
        use_container_width=True,
        hide_index=True,
        column_config={
            "우선순위 점수": st.column_config.NumberColumn(format="%+.2f"),
            "QVM 점수": st.column_config.NumberColumn(format="%+.2f"),
            "가치": st.column_config.NumberColumn(format="%+d"),
            "품질": st.column_config.NumberColumn(format="%+d"),
            "모멘텀": st.column_config.NumberColumn(format="%+d"),
            "기술적": st.column_config.NumberColumn(format="%+d"),
            "종가": st.column_config.NumberColumn(format="%,.2f"),
            "PER": st.column_config.NumberColumn(format="%.2f"),
            "PBR": st.column_config.NumberColumn(format="%.2f"),
            "ROE(%)": st.column_config.NumberColumn(format="%.1f"),
            "12M 수익률(%)": st.column_config.NumberColumn(format="%+.1f"),
            "RSI": st.column_config.NumberColumn(format="%.1f"),
        },
    )

    with st.expander("📘 통합 추천 로직 + 점수 산정 기준"):
        st.markdown(
            """
**우선순위 점수** = QVM 종합 점수 + 추세 보정 (매수 +0.5 · 보유 0 · 미보유 -0.2 · 매도 -0.5)

**통합 추천 매트릭스**

| QVM | 매수(골든크로스) | 보유(추세 위) | 미보유(추세 아래) | 매도(데드크로스) |
|---|---|---|---|---|
| **≥0.5** 좋은 종목 | 💎 강력 매수 | ✅ 보유/분할매수 | ⏳ 골든크로스 대기 | 🟠 신중 매수 |
| **0 근방** 평범 | 🔵 단기 신호 | ⚪ 관망 | ⚪ 관망 | ⚪ 관망 |
| **<-0.5** 안 좋음 | ❌ 회피 | ❌ 회피 | ❌ 회피 | ❌ 회피 |

---

**📈 4-팩터 점수 (각 -2~+2)**
- **🏷️ Value** PER+PBR · **💎 Quality** ROE+영업이익률 · **🚀 Momentum** 12M수익률+추세 · **📐 Technical** RSI

**근거**: Fama-French QVM / Piotroski F-Score / Magic Formula / Jegadeesh-Titman 모멘텀
"""
        )


# ============== 탭 2: 종목 비교 (레이더 차트) ==============
with tab_compare:
    st.subheader("📈 종목 비교 — 레이더 차트")
    st.caption(
        "2~6개 종목을 선택하면 4-팩터 점수를 레이더 차트로 시각 비교합니다. "
        "면적이 클수록 종합적으로 우수."
    )

    all_tickers = sorted(score_disp["ticker"].tolist())
    # 기본값: 우선순위 TOP 3
    default_selection = score_disp["ticker"].head(3).tolist()

    selected = st.multiselect(
        "비교할 종목 선택",
        options=all_tickers,
        default=default_selection,
        format_func=label,
        max_selections=6,
    )

    if len(selected) < 2:
        st.info("2개 이상 선택해주세요.")
    else:
        axes = ["가치", "품질", "모멘텀", "기술적"]

        def s(v):
            """None/NaN은 중립값 0으로 처리, 0~4 범위로 시프트."""
            if v is None or pd.isna(v):
                return 2
            return float(v) + 2

        fig_radar = go.Figure()
        for t in selected:
            r = score_disp[score_disp["ticker"] == t]
            if r.empty:
                continue
            r = r.iloc[0]
            vals = [
                s(r["value_score"]),
                s(r["quality_score"]),
                s(r["momentum_score"]),
                s(r["technical_score"]),
            ]
            fig_radar.add_trace(go.Scatterpolar(
                r=vals + [vals[0]],
                theta=axes + [axes[0]],
                fill="toself",
                name=label(t),
                opacity=0.55,
            ))
        fig_radar.update_layout(
            polar=dict(
                radialaxis=dict(
                    visible=True, range=[0, 4],
                    tickvals=[0, 1, 2, 3, 4],
                    ticktext=["-2 (나쁨)", "-1", "0", "+1", "+2 (좋음)"],
                ),
            ),
            showlegend=True, height=520,
            margin=dict(l=30, r=30, t=30, b=30),
        )
        st.plotly_chart(fig_radar, use_container_width=True)

        # 비교 표 (각 종목이 컬럼)
        st.markdown("#### 상세 지표 비교")
        compare = score_disp[score_disp["ticker"].isin(selected)].copy()
        compare = compare.set_index("ticker")
        rows = {
            "종목명": compare["종목명"],
            "통합 추천": compare["통합 추천"],
            "우선순위 점수": compare["우선순위 점수"].map(lambda v: f"{v:+.2f}"),
            "QVM 점수": compare["composite"].map(lambda v: f"{v:+.2f}"),
            "추세": compare["추세"],
            "가치 (V)": compare["value_score"],
            "품질 (Q)": compare["quality_score"],
            "모멘텀 (M)": compare["momentum_score"],
            "기술적 (T)": compare["technical_score"],
            "종가": compare["close"].map(lambda v: f"{v:,.2f}"),
            "PER": compare["per"].map(lambda v: fmt(v)),
            "PBR": compare["pbr"].map(lambda v: fmt(v)),
            "ROE(%)": compare["roe_pct"].map(lambda v: fmt(v, "{:.1f}")),
            "12M 수익률(%)": compare["return_12m_pct"].map(lambda v: fmt(v, "{:+.1f}")),
            "RSI": compare["rsi14"].map(lambda v: fmt(v, "{:.1f}")),
        }
        comp_df = pd.DataFrame(rows).T
        st.dataframe(comp_df, use_container_width=True)


# ============== 탭 3: 종목 상세 ==============
with tab_detail:
    st.subheader("🔍 종목 상세 분석")

    tickers = sorted(summary["ticker"].tolist())
    sel = st.selectbox("티커 선택", tickers, format_func=label)

    sel_row = score_disp[score_disp["ticker"] == sel].iloc[0]
    row = summary[summary["ticker"] == sel].iloc[0]

    st.markdown(f"### {label(sel)}")

    # 점수 카드
    sc1, sc2, sc3, sc4 = st.columns(4)
    sc1.metric("통합 추천", sel_row["통합 추천"], delta=sel_row["추천 이유"],
               delta_color="off")
    sc2.metric("우선순위 점수", f"{sel_row['우선순위 점수']:+.2f}",
               delta=f"순위 #{int(sel_row.name)+1}", delta_color="off")
    sc3.metric("QVM 점수", f"{sel_row['composite']:+.2f}",
               delta=sel_row["판정"], delta_color="off")
    sc4.metric("추세", sel_row["추세"],
               delta=row["last_cross"] if pd.notna(row["last_cross"]) else None,
               delta_color="off")

    # 4-팩터 점수
    st.markdown("#### 4-팩터 세부 점수")
    f1, f2, f3, f4 = st.columns(4)
    f1.metric("🏷️ 가치 (V)", fmt(sel_row.get("value_score"), "{:+d}"))
    f2.metric("💎 품질 (Q)", fmt(sel_row.get("quality_score"), "{:+d}"))
    f3.metric("🚀 모멘텀 (M)", fmt(sel_row.get("momentum_score"), "{:+d}"))
    f4.metric("📐 기술적 (T)", fmt(sel_row.get("technical_score"), "{:+d}"))

    # 밸류에이션 카드
    st.markdown("#### 밸류에이션 / 펀더멘털")
    if sel in funda["ticker"].values:
        f = funda[funda["ticker"] == sel].iloc[0]
        currency = f.get("currency") if pd.notna(f.get("currency")) else ""
        v1, v2, v3, v4 = st.columns(4)
        v1.metric("PER", fmt(f.get("per")))
        v2.metric("선행 PER", fmt(f.get("forward_per")))
        v3.metric("PBR", fmt(f.get("pbr")))
        v4.metric("배당수익률", fmt(f.get("dividend_yield_pct"), suffix="%"))

        v5, v6, v7, v8 = st.columns(4)
        v5.metric("시가총액", fmt_mcap(f.get("market_cap"), currency or ""))
        v6.metric("ROE", fmt(f.get("roe_pct"), suffix="%"))
        v7.metric("영업이익률", fmt(f.get("profit_margin_pct"), suffix="%"))
        sector = f.get("sector") if pd.notna(f.get("sector")) else "-"
        industry = f.get("industry") if pd.notna(f.get("industry")) else "-"
        v8.metric("섹터", str(sector), delta=str(industry), delta_color="off")
    else:
        st.info("이 종목의 밸류에이션 정보가 없습니다.")

    df_file = RESULTS / f"{sel}_signals.csv"
    if not df_file.exists():
        st.warning("선택한 티커의 상세 결과 파일이 없습니다.")
        st.stop()

    df = pd.read_csv(df_file, parse_dates=["Date"], index_col="Date")

    # 가격 차트
    st.markdown("#### 가격 차트 (50일선 / 200일선 + 크로스)")
    fig = go.Figure()
    fig.add_trace(go.Scatter(x=df.index, y=df["Close"], name="종가",
                             line=dict(color="#888")))
    if "ma50" in df.columns:
        fig.add_trace(go.Scatter(x=df.index, y=df["ma50"], name="50일선",
                                 line=dict(color="#3498db")))
    if "ma200" in df.columns:
        fig.add_trace(go.Scatter(x=df.index, y=df["ma200"], name="200일선",
                                 line=dict(color="#e67e22")))
    golden = df[df["signal"] == "golden_cross"]
    dead = df[df["signal"] == "death_cross"]
    if not golden.empty:
        fig.add_trace(go.Scatter(
            x=golden.index, y=golden["Close"], mode="markers",
            name="골든크로스 (매수)",
            marker=dict(symbol="triangle-up", size=14, color="green"),
        ))
    if not dead.empty:
        fig.add_trace(go.Scatter(
            x=dead.index, y=dead["Close"], mode="markers",
            name="데드크로스 (매도)",
            marker=dict(symbol="triangle-down", size=14, color="red"),
        ))
    fig.update_layout(height=500, hovermode="x unified",
                      legend=dict(orientation="h"))
    st.plotly_chart(fig, use_container_width=True)

    # 백테스트
    st.markdown("#### 간이 백테스트 (골든크로스 vs 매수후보유)")
    df_bt = df.dropna(subset=["ma50", "ma200"]).copy()
    df_bt["position"] = (df_bt["ma50"] > df_bt["ma200"]).astype(int)
    df_bt["ret"] = df_bt["Close"].pct_change().fillna(0)
    df_bt["strategy_ret"] = df_bt["position"].shift(1).fillna(0) * df_bt["ret"]
    df_bt["strategy_cum"] = (1 + df_bt["strategy_ret"]).cumprod()
    df_bt["bh_cum"] = (1 + df_bt["ret"]).cumprod()

    last_bt = df_bt.iloc[-1]
    years = (df_bt.index[-1] - df_bt.index[0]).days / 365.25
    cagr_strat = last_bt["strategy_cum"] ** (1 / years) - 1 if years > 0 else 0
    cagr_bh = last_bt["bh_cum"] ** (1 / years) - 1 if years > 0 else 0

    b1, b2, b3, b4 = st.columns(4)
    b1.metric("전략 누적수익률", f"{(last_bt['strategy_cum']-1)*100:,.1f}%")
    b2.metric("매수후보유 누적수익률", f"{(last_bt['bh_cum']-1)*100:,.1f}%")
    b3.metric("전략 CAGR", f"{cagr_strat*100:,.2f}%")
    b4.metric("매수후보유 CAGR", f"{cagr_bh*100:,.2f}%")

    fig2 = go.Figure()
    fig2.add_trace(go.Scatter(x=df_bt.index, y=df_bt["strategy_cum"],
                              name="골든크로스 전략"))
    fig2.add_trace(go.Scatter(x=df_bt.index, y=df_bt["bh_cum"],
                              name="매수 후 보유"))
    fig2.update_layout(height=350, hovermode="x unified",
                       legend=dict(orientation="h"),
                       yaxis_title="누적 (1.0 = 원금)")
    st.plotly_chart(fig2, use_container_width=True)

    st.caption(
        "백테스트는 수수료/세금/슬리피지를 반영하지 않습니다. "
        "골든크로스는 큰 하락장은 회피하나 횡보장에서는 매수후보유보다 부진할 수 있습니다."
    )
