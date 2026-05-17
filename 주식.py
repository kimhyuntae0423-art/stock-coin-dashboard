import streamlit as st
import pandas as pd
from pathlib import Path
import plotly.graph_objects as go
import sys

sys.path.append(str(Path(__file__).resolve().parent))
from scripts.fear_greed import fetch_cnn_fear_greed
from scripts.ui import render_fng_gauge, render_action_legend
from scripts.stock_score import (
    score_value, score_quality, score_momentum, score_technical,
    composite_stock_score, rank_stocks,
)

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


st.title("📈 주식 분석 대시보드")
st.caption(
    "50일선이 200일선을 **상향돌파**하면 골든 크로스(매수), **하향돌파**하면 데드 크로스(매도)로 보는 추세추종 전략입니다. "
    "절대적 정답이 아니며 과거 데이터 기준임을 유의하세요. 사이드바에서 코인 페이지로 이동할 수 있습니다."
)

summary_file = RESULTS / "summary_signals.csv"
if not summary_file.exists():
    st.warning("분석 결과가 없습니다. 먼저 `python run_analysis.py`를 실행하세요.")
    st.stop()

summary = pd.read_csv(summary_file)

funda_file = RESULTS / "fundamentals.csv"
funda = pd.read_csv(funda_file) if funda_file.exists() else pd.DataFrame(columns=["ticker"])


# ----- 공포·탐욕 지수 -----
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
- **0~25 극단적 공포**: 시장이 과매도. 역사적으로 매수 기회가 됐던 구간 (단 추가 하락 가능)
- **25~45 공포**: 약세 분위기
- **45~55 중립**: 방향성 불분명
- **55~75 탐욕**: 강세 분위기
- **75~100 극단적 탐욕**: 과열. 역사적으로 단기 고점 부근에서 자주 관측 (조정 가능성)

> 워런 버핏: *"남들이 탐욕스러울 때 두려워하고, 남들이 두려워할 때 탐욕스러워라."*

이 지수는 7개 하위 지표(주가 모멘텀, 변동성, 풋콜비율 등)를 종합한 값입니다. 단독 매매신호가 아닌 **분위기 참고용**으로 사용하세요.
"""
    )

st.divider()

# ===================== QVM + Technical 종합 점수 + 추천 =====================
st.subheader("🎯 종목 종합 평가 (Quality × Value × Momentum × Technical)")
st.caption(
    "학술적으로 검증된 4개 팩터를 결합한 종합 점수입니다. "
    "Fama-French·AQR·Greenblatt·Piotroski 등 30년간 학술 연구에서 일관되게 초과수익을 보인 "
    "**가치(Value) · 품질(Quality) · 모멘텀(Momentum) · 진입 타이밍(Technical/RSI)** 4개 팩터를 점수화."
)

# 점수 계산
score_input = summary.merge(funda[["ticker", "per", "pbr", "roe_pct", "profit_margin_pct"]],
                            on="ticker", how="left")
scores_df = rank_stocks(score_input)

# 종목명 + 종합 점수 + 추천 행동
score_disp = scores_df.merge(score_input[["ticker", "close", "state", "rsi14",
                                          "return_12m_pct", "per", "pbr", "roe_pct"]],
                             on="ticker", how="left")
score_disp["종목명"] = score_disp["ticker"].map(NAMES).fillna("-")


def composite_label(avg):
    if avg >= 1.5: return "🟢🟢 강한 매수"
    if avg >= 0.5: return "🟢 매수 우호"
    if avg > -0.5: return "🔵 중립"
    if avg > -1.5: return "🟠 매도 우호"
    return "🔴 매수 자제"


score_disp["판정"] = score_disp["composite"].apply(composite_label)

# 상위 5개 카드
st.markdown("#### 💰 매수 우선순위 TOP 5")
top5 = score_disp.head(5)
cols = st.columns(5)
for i, (_, r) in enumerate(top5.iterrows()):
    with cols[i]:
        st.markdown(f"#### #{i+1}")
        st.markdown(f"**{r['종목명']}**")
        st.markdown(f"`{r['ticker']}`")
        st.markdown(f"종합: **{r['composite']:+.2f}**")
        st.caption(f"{r['판정']}")
        st.markdown(
            f"V {fmt(r.get('value_score'), '{:+d}')} · Q {fmt(r.get('quality_score'), '{:+d}')}"
            f" · M {fmt(r.get('momentum_score'), '{:+d}')} · T {fmt(r.get('technical_score'), '{:+d}')}"
        )

# 전체 순위표
st.markdown("#### 전체 순위표")
rank_table = score_disp.copy()
rank_table["순위"] = range(1, len(rank_table) + 1)
rank_table = rank_table.rename(columns={
    "ticker": "티커",
    "composite": "종합 점수",
    "value_score": "가치",
    "quality_score": "품질",
    "momentum_score": "모멘텀",
    "technical_score": "기술적",
    "per": "PER",
    "pbr": "PBR",
    "roe_pct": "ROE(%)",
    "return_12m_pct": "12M 수익률(%)",
    "rsi14": "RSI",
})
st.dataframe(
    rank_table[["순위", "티커", "종목명", "판정", "종합 점수",
                "가치", "품질", "모멘텀", "기술적",
                "PER", "PBR", "ROE(%)", "12M 수익률(%)", "RSI"]],
    use_container_width=True,
    hide_index=True,
    column_config={
        "종합 점수": st.column_config.NumberColumn(format="%+.2f"),
        "가치": st.column_config.NumberColumn(format="%+d"),
        "품질": st.column_config.NumberColumn(format="%+d"),
        "모멘텀": st.column_config.NumberColumn(format="%+d"),
        "기술적": st.column_config.NumberColumn(format="%+d"),
        "PER": st.column_config.NumberColumn(format="%.2f"),
        "PBR": st.column_config.NumberColumn(format="%.2f"),
        "ROE(%)": st.column_config.NumberColumn(format="%.1f"),
        "12M 수익률(%)": st.column_config.NumberColumn(format="%+.1f"),
        "RSI": st.column_config.NumberColumn(format="%.1f"),
    },
)

with st.expander("📘 4-팩터 점수 산정 기준"):
    st.markdown(
        """
각 팩터는 -2(나쁨) ~ +2(좋음)로 점수화되고 평균이 종합 점수입니다.

**🏷️ Value (가치)** — PER + PBR 평균
- PER <10: +2 | 10-15: +1 | 15-25: 0 | 25-40: -1 | >40: -2
- PBR <1: +2 | 1-2: +1 | 2-4: 0 | 4-6: -1 | >6: -2

**💎 Quality (품질)** — ROE + 영업이익률 평균
- ROE ≥25%: +2 | 15-25%: +1 | 8-15%: 0 | 0-8%: -1 | <0%: -2
- 영업이익률 동일 기준

**🚀 Momentum (모멘텀)** — 12개월 수익률 + 추세 상태 평균
- 12M 수익률 ≥40%: +2 | 15-40%: +1 | 0-15%: 0 | -20-0%: -1 | <-20%: -2
- 50일선 > 200일선(bull): +1, 반대: -1

**📐 Technical (진입 타이밍)** — RSI
- RSI ≤30(과매도): +2 | 30-45: +1 | 45-60: 0 | 60-70: -1 | >70: -2

**근거 학술 자료**:
- Quality·Value·Momentum 3-팩터 모델 — Fama-French (1993, 2015), AQR Capital
- Piotroski F-Score 9점 척도: 시장 대비 연 13.4% 초과 (1976-1996 백테스트)
- Magic Formula (Greenblatt): 이익수익률 + 자본수익률, 연 30%+ 보고
- 12개월 모멘텀 (Jegadeesh-Titman 1993): 2024년에도 최고 성과 팩터
"""
    )

st.divider()

# ----- 전체 종목 요약 (기존 표) -----
st.subheader("📊 전체 종목 추세(골든크로스 기반) 현재 상태")
render_action_legend()

action_color = {
    "매수": "🟢 매수",
    "보유": "🔵 보유",
    "매도": "🔴 매도",
    "미보유": "⚪ 미보유",
}

display = summary.copy()
display["종목명"] = display["ticker"].map(NAMES).fillna("-")
display["추천 행동"] = display["action"].map(action_color).fillna(display["action"])

merged = display.merge(funda, on="ticker", how="left")
merged = merged.rename(
    columns={
        "ticker": "티커",
        "date": "기준일",
        "close": "종가",
        "last_cross": "최근 신호",
        "last_cross_date": "신호 발생일",
        "per": "PER",
        "forward_per": "선행 PER",
        "pbr": "PBR",
        "dividend_yield_pct": "배당수익률(%)",
        "roe_pct": "ROE(%)",
        "sector": "섹터",
    }
)
cols = [
    "티커", "종목명", "추천 행동", "종가", "최근 신호", "신호 발생일",
    "PER", "선행 PER", "PBR", "배당수익률(%)", "ROE(%)", "섹터",
]
cols = [c for c in cols if c in merged.columns]
st.dataframe(
    merged[cols],
    use_container_width=True,
    hide_index=True,
    column_config={
        "PER": st.column_config.NumberColumn(format="%.2f"),
        "선행 PER": st.column_config.NumberColumn(format="%.2f"),
        "PBR": st.column_config.NumberColumn(format="%.2f"),
        "배당수익률(%)": st.column_config.NumberColumn(format="%.2f"),
        "ROE(%)": st.column_config.NumberColumn(format="%.1f"),
        "종가": st.column_config.NumberColumn(format="%,.2f"),
    },
)

with st.expander("📘 지표 해설"):
    st.markdown(
        """
- **PER (주가수익비율)**: 주가 ÷ 1주당 순이익. 낮을수록 이익 대비 싸다고 봄. 일반적으로 10 이하면 저평가, 25 이상이면 고평가(섹터별로 다름).
- **선행 PER**: 향후 1년 예상 이익 기준 PER. 미래 성장이 반영됨.
- **PBR (주가순자산비율)**: 주가 ÷ 1주당 순자산. 1 미만이면 청산가치 이하 거래(전통적으로 저평가). 단 IT/플랫폼처럼 자산이 적은 업종은 PBR이 의미가 약함.
- **배당수익률**: 연 배당금 ÷ 주가. 4% 이상이면 고배당주.
- **ROE**: 자기자본수익률. 15% 이상이면 우량 기업으로 평가.
        """
    )

st.divider()

# ----- 종목별 상세 -----
tickers = sorted(summary["ticker"].tolist())
sel = st.selectbox("티커 선택", tickers, format_func=label)

row = summary[summary["ticker"] == sel].iloc[0]
st.markdown(f"### {label(sel)}")

# 추천 행동 + 종가 + 최근 신호
c1, c2, c3 = st.columns(3)
c1.metric("추천 행동", action_color.get(row["action"], row["action"]))
c2.metric("종가", f"{row['close']:,.2f}")
c3.metric(
    "최근 신호",
    row["last_cross"] if pd.notna(row["last_cross"]) else "-",
    delta=row["last_cross_date"] if pd.notna(row["last_cross_date"]) else None,
    delta_color="off",
)

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

# ----- 차트 -----
st.markdown("#### 가격 차트 (50일선 / 200일선 + 크로스 표시)")
fig = go.Figure()
fig.add_trace(go.Scatter(x=df.index, y=df["Close"], name="종가", line=dict(color="#888")))
if "ma50" in df.columns:
    fig.add_trace(go.Scatter(x=df.index, y=df["ma50"], name="50일선", line=dict(color="#3498db")))
if "ma200" in df.columns:
    fig.add_trace(go.Scatter(x=df.index, y=df["ma200"], name="200일선", line=dict(color="#e67e22")))

golden = df[df["signal"] == "golden_cross"]
dead = df[df["signal"] == "death_cross"]
if not golden.empty:
    fig.add_trace(
        go.Scatter(
            x=golden.index, y=golden["Close"],
            mode="markers", name="골든크로스 (매수)",
            marker=dict(symbol="triangle-up", size=14, color="green"),
        )
    )
if not dead.empty:
    fig.add_trace(
        go.Scatter(
            x=dead.index, y=dead["Close"],
            mode="markers", name="데드크로스 (매도)",
            marker=dict(symbol="triangle-down", size=14, color="red"),
        )
    )

fig.update_layout(height=550, hovermode="x unified", legend=dict(orientation="h"))
st.plotly_chart(fig, use_container_width=True)

# ----- 간이 백테스트 -----
st.markdown("#### 간이 백테스트 (이 종목)")
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
fig2.add_trace(go.Scatter(x=df_bt.index, y=df_bt["strategy_cum"], name="골든크로스 전략"))
fig2.add_trace(go.Scatter(x=df_bt.index, y=df_bt["bh_cum"], name="매수 후 보유"))
fig2.update_layout(height=350, hovermode="x unified", legend=dict(orientation="h"),
                   yaxis_title="누적 (1.0 = 원금)")
st.plotly_chart(fig2, use_container_width=True)

st.caption(
    "백테스트는 수수료/세금/슬리피지를 반영하지 않습니다. "
    "골든크로스는 큰 하락장을 회피하지만 횡보장에서는 매수후보유보다 부진할 수 있습니다. "
    "밸류 지표는 yfinance에서 가져온 값으로 일부 한국 종목은 누락되거나 부정확할 수 있습니다."
)
