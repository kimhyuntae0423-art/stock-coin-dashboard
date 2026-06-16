import streamlit as st
import pandas as pd
from pathlib import Path
import plotly.graph_objects as go
import sys

sys.path.append(str(Path(__file__).resolve().parent))
from scripts.fear_greed import fetch_cnn_fear_greed
from scripts.ui import render_fng_gauge
from scripts.stock_score import rank_stocks
from scripts.factor_calc import enrich_price_factors

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
    "QVM 4-팩터 펀더멘털 점수 + **12-1M 모멘텀** (백테스트 검증) 결합 종합 추천. "
    "골든크로스는 적중률 50.8%로 참고용 표시만 합니다."
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

FUNDA_COLS = [
    "ticker", "per", "forward_per", "pbr", "roe_pct", "profit_margin_pct",
    "revenue_growth_yoy_pct", "earnings_growth_yoy_pct", "eps_growth_q_pct",
]
# funda에 새 컬럼이 아직 없으면 안전하게 보강
for col in FUNDA_COLS:
    if col not in funda.columns:
        funda[col] = None

score_input = summary.merge(funda[FUNDA_COLS], on="ticker", how="left")
score_input = enrich_price_factors(score_input)
scores_df = rank_stocks(score_input)
_SCORE_INPUT_COLS = ["ticker", "close", "state", "action", "rsi14",
                     "return_12m_pct", "return_1m_pct", "per", "pbr", "roe_pct",
                     "revenue_growth_yoy_pct", "earnings_growth_yoy_pct"]
# 누락된 컬럼은 None으로 채워서 KeyError 방지
for col in _SCORE_INPUT_COLS:
    if col not in score_input.columns:
        score_input[col] = None
score_disp = scores_df.merge(score_input[_SCORE_INPUT_COLS], on="ticker", how="left")
# scores_df에 growth_score 누락 시 (구버전 호환) 보강
if "growth_score" not in score_disp.columns:
    score_disp["growth_score"] = None
score_disp["종목명"] = score_disp["ticker"].map(NAMES).fillna("-")


def composite_label(avg):
    if avg >= 1.5: return "🟢🟢 강한 매수 추천"
    if avg >= 0.5: return "🟢 매수 검토"
    if avg > -0.5: return "🔵 중립 (관망)"
    if avg > -1.5: return "🟠 매도 우호"
    return "🔴 매수 자제"


def integrated_recommendation(qvm, mom_rank):
    """종합 점수 + 12-1M 모멘텀 분위(백테스트 검증)를 결합한 추천 라벨."""
    if qvm is None or pd.isna(qvm):
        return "⚪ 데이터 부족", "분석 데이터 미확보"
    good_funda = qvm >= 0.5
    avg_funda = qvm > -0.5
    if good_funda:
        if mom_rank == "Q1": return "💎 지금이 기회", "퀄리티 좋고 + 모멘텀 상위 25% (백테스트 검증)"
        if mom_rank == "Q2": return "✅ 계속 모아도 좋음", "퀄리티 좋고 + 모멘텀 중상위"
        if mom_rank == "Q3": return "⏳ 모멘텀 개선 대기", "퀄리티 좋지만 모멘텀 중하위 — 회복 확인 후 진입"
        if mom_rank == "Q4": return "🟠 신중 매수", "퀄리티 좋으나 모멘텀 하위 25% — 분할매수"
        return "✅ 우수 종목", "모멘텀 데이터 미확보"
    if avg_funda:
        if mom_rank == "Q1": return "🔵 모멘텀만 강함", "펀더 보통 + 모멘텀 상위 — 단기 매매용"
        return "⚪ 매수 보류", "특별한 매력 없음"
    return "❌ 회피 권장", "회사 펀더 약함"


def priority_score(qvm, mom_rank):
    # 골든크로스(적중률 50.8%) 대신 12-1M 모멘텀 분위(백테스트 검증) 사용
    bonus = {"Q1": 0.5, "Q2": 0.1, "Q3": -0.1, "Q4": -0.3}.get(str(mom_rank) if mom_rank else "", 0)
    return (qvm or 0) + bonus


score_disp["판정"] = score_disp["composite"].apply(composite_label)
score_disp["추세"] = score_disp["action"].map(action_color).fillna(score_disp["action"])

# ── 12-1M 모멘텀 분위 (백테스트 검증 신호) ─────────────────
def _add_mom_quartile(df: pd.DataFrame) -> pd.DataFrame:
    r12 = pd.to_numeric(df.get("return_12m_pct", pd.Series(dtype=float)), errors="coerce")
    r1  = pd.to_numeric(df.get("return_1m_pct",  pd.Series(dtype=float)), errors="coerce")
    mom = r12 - r1  # 12-1M 모멘텀
    valid = mom.notna()
    df = df.copy()
    df["mom_12_1"] = mom
    df["mom_rank"] = None
    if valid.sum() >= 4:
        df.loc[valid, "mom_rank"] = pd.qcut(
            mom[valid].rank(method="first"), q=4, labels=["Q4", "Q3", "Q2", "Q1"]
        ).astype(str)
    return df

score_disp = _add_mom_quartile(score_disp)
_MOM_LABEL = {
    "Q1": "📈 모멘텀 상위 25%",
    "Q2": "🔵 모멘텀 중상위",
    "Q3": "⚪ 모멘텀 중하위",
    "Q4": "📉 모멘텀 하위 25%",
}
score_disp["모멘텀"] = score_disp["mom_rank"].map(_MOM_LABEL).fillna("⚪ -")


def timing_label(row):
    """타이밍 라벨 — 일반인이 한눈에 이해할 수 있게 친근한 한국어로 표기.

    우선순위:
      1) 강한 과열 → 🔴 너무 올라 위험
      2) 조정 받은 우량주 → 💎 / 💚
      3) 가격이 실적보다 빨리 올랐음 → ⚠️
      4) 약한 단기 과열 → 🟠
    """
    oh = row.get("overheat_penalty", 0) or 0
    mr = row.get("mean_reversion_bonus", 0) or 0
    me = row.get("multi_exp_penalty", 0) or 0
    if oh <= -0.4:
        return "🔴 너무 올라 위험"
    if mr >= 0.30:
        return "💎 떨어진 우량주"
    if mr >= 0.15:
        return "💚 매수 검토"
    if me <= -0.30:
        return "⚠️ 가격이 실적보다 빨리 오름"
    if oh <= -0.20:
        return "🟠 살짝 비쌈"
    return ""


score_disp["타이밍"] = score_disp.apply(timing_label, axis=1)
recs = score_disp.apply(
    lambda r: integrated_recommendation(r["composite"], r.get("mom_rank")), axis=1
)
score_disp["통합 추천"] = [r[0] for r in recs]
score_disp["추천 이유"] = [r[1] for r in recs]
score_disp["우선순위 점수"] = score_disp.apply(
    lambda r: round(priority_score(r["composite"], r.get("mom_rank")), 2), axis=1
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
        "**무엇을 살까 (회사 펀더멘털)** 와 **언제 살까 (추세 + 단기 과열도)** 를 결합한 점수입니다."
    )

    with st.expander("📖 용어 사전 — 어렵게 느낀 표현 풀이"):
        st.markdown("""
**🧩 5개 평가 항목 (-2 = 매우 나쁨, 0 = 평균, +2 = 매우 좋음)**
- **저평가**: PER·PBR이 낮을수록 좋음. "지금 사면 싸다"
- **품질**: ROE·영업이익률. "회사가 효율적으로 돈을 버는가"
- **성장**: 매출·이익 증가율. "회사가 빠르게 크는가"
- **추세**: 12-1M 모멘텀 (백테스트 검증 ✓). "12개월 수익률 - 1개월 수익률로 추세 강도 측정"
- **타이밍**: RSI 기반. "지금 사도 단기 부담 없는가"

**🚦 타이밍 라벨 (점수 옆에 표시)**
- 🔴 **너무 올라 위험**: 단기 과매수(RSI≥75 또는 52주 고가 97%+) — 분할매수 권장
- 🟠 **살짝 비쌈**: 단기 과열 약한 신호. 일부만 진입 권장
- ⚠️ **가격이 실적보다 빨리 오름**: 1년 가격 상승률이 실적 성장률을 30%p+ 초과
- 💎 **떨어진 우량주**: 펀더 좋고 + 추세 살아있고 + 최근 조정. 좋은 진입 기회
- 💚 **매수 검토**: 약한 매수 기회 신호

**📊 종합 점수 = 5개 항목 + 보너스/페널티 합산**
- ≥ +1.5: 강한 매수 추천
- +0.5 ~ +1.5: 매수 검토
- -0.5 ~ +0.5: 중립
- ≤ -1.5: 매수 자제

**🎯 통합 추천 (펀더 + 12-1M 모멘텀 결합 / 백테스트 검증)**
- 💎 **지금이 기회**: 퀄리티 좋고 + 모멘텀 상위 25% (Q1, 연 +45.9% 백테스트)
- ✅ **계속 모아도 좋음**: 퀄리티 좋고 + 모멘텀 중상위 (Q2)
- ⏳ **모멘텀 개선 대기**: 퀄리티 좋지만 모멘텀 중하위 (Q3) — 회복 확인 후 진입
- 🟠 **신중 매수**: 퀄리티 좋으나 모멘텀 하위 25% (Q4) — 분할매수
- 🔵 **모멘텀만 강함**: 펀더 보통 + 모멘텀 상위 — 단기매매용
- ⚪ **매수 보류**: 특별한 매력 없음
- ❌ **회피 권장**: 회사 펀더 약함

**💡 점수 시스템의 한계**
- 점수 1·2위가 미래 수익률 1·2위 보장 ❌
- 모멘텀 편향: 이미 오른 종목을 우대하는 구조적 한계
- 단일 시점 스냅샷 → 사이클·외부 변화 미반영
- **점수는 종목 후보 압축 도구**. 최종 결정은 본인 판단 + 공식 공시 확인.
        """)

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
                f"종합점수 {r['composite']:+.2f} · 추세 {r['추세']}"
            )
            st.caption(r["추천 이유"])
            if r.get("타이밍"):
                st.markdown(f"**{r['타이밍']}**")
            st.markdown(
                f"저평가 {fmt(r.get('value_score'), '{:+d}')} · "
                f"품질 {fmt(r.get('quality_score'), '{:+d}')} · "
                f"성장 {fmt(r.get('growth_score'), '{:+d}')} · "
                f"추세 {fmt(r.get('momentum_score'), '{:+d}')} · "
                f"타이밍 {fmt(r.get('technical_score'), '{:+d}')}"
            )

    st.markdown("#### 전체 통합 순위표")
    st.caption("💡 컬럼 이름 옆 **?** 아이콘에 마우스를 올리면 설명이 나옵니다. 자세한 풀이는 위 📖 용어 사전 참고.")
    rank_table = score_disp.copy()
    rank_table["순위"] = range(1, len(rank_table) + 1)
    # "추세"는 이미 action 매핑된 컬럼이라 momentum_score는 "1년 추세"로 구분
    rank_table = rank_table.rename(columns={
        "ticker": "티커", "close": "종가", "composite": "종합 점수",
        "value_score": "저평가", "quality_score": "품질", "growth_score": "성장",
        "momentum_score": "1년 추세", "technical_score": "RSI 신호",
        "per": "PER", "pbr": "PBR", "roe_pct": "ROE(%)",
        "revenue_growth_yoy_pct": "매출YoY(%)", "earnings_growth_yoy_pct": "EPS YoY(%)",
        "return_12m_pct": "12M 수익률(%)", "return_1m_pct": "1M 수익률(%)", "rsi14": "RSI",
    })
    st.dataframe(
        rank_table[["순위", "티커", "종목명", "통합 추천", "타이밍", "우선순위 점수",
                    "종합 점수", "추세", "판정",
                    "저평가", "품질", "성장", "1년 추세", "RSI 신호",
                    "종가", "PER", "PBR", "ROE(%)",
                    "매출YoY(%)", "EPS YoY(%)", "12M 수익률(%)", "1M 수익률(%)", "RSI"]],
        use_container_width=True,
        hide_index=True,
        column_config={
            "우선순위 점수": st.column_config.NumberColumn(
                "우선순위 점수",
                help="종합 점수 + 모멘텀 분위 보정 (Q1 +0.5, Q2 +0.1, Q3 -0.1, Q4 -0.3). 백테스트 검증.",
                format="%+.2f"),
            "종합 점수": st.column_config.NumberColumn(
                "종합 점수",
                help="5개 평가 항목 z-score 가중합 + 보너스/페널티. 0이 평균, ±1.5 이상이 극단.",
                format="%+.2f"),
            "저평가": st.column_config.NumberColumn(
                "저평가", help="PER/PBR 기반. -2 비쌈, +2 매우 쌈.", format="%+d"),
            "품질": st.column_config.NumberColumn(
                "품질", help="ROE + 영업이익률. 회사가 얼마나 잘 버는가.", format="%+d"),
            "성장": st.column_config.NumberColumn(
                "성장", help="매출·이익 YoY 성장률. 빠르게 크는 회사일수록 높음.", format="%+d"),
            "1년 추세": st.column_config.NumberColumn(
                "1년 추세", help="12-1M 모멘텀 점수 (12개월 수익률 - 1개월 수익률 기반). 골든크로스는 참고용.", format="%+d"),
            "RSI 신호": st.column_config.NumberColumn(
                "RSI 신호", help="RSI 기반 매수 타이밍. 과매도(+2)일수록 좋음, 과매수(-2) 부담.",
                format="%+d"),
            "종가": st.column_config.NumberColumn(format="%,.2f"),
            "PER": st.column_config.NumberColumn(format="%.2f"),
            "PBR": st.column_config.NumberColumn(format="%.2f"),
            "ROE(%)": st.column_config.NumberColumn(format="%.1f"),
            "매출YoY(%)": st.column_config.NumberColumn(format="%+.1f"),
            "EPS YoY(%)": st.column_config.NumberColumn(format="%+.1f"),
            "12M 수익률(%)": st.column_config.NumberColumn(format="%+.1f"),
            "1M 수익률(%)": st.column_config.NumberColumn(
                "1M 수익률(%)", help="최근 22거래일(약 1개월) 수익률. 단기 흐름 확인용.", format="%+.1f"),
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

**📈 5-팩터 점수 — QVGMT (각 -2~+2)**
- **🏷️ Value** PER+PBR · **💎 Quality** ROE+영업이익률 · **🌱 Growth** 매출/EPS YoY · **🚀 Momentum** 12M수익률+추세 · **📐 Technical** RSI

**근거**: Fama-French QVM / Piotroski F-Score / Magic Formula / Jegadeesh-Titman 모멘텀 / Growth factor(MSCI/AQR)
"""
        )


# ============== 탭 2: 종목 비교 (레이더 차트) ==============
with tab_compare:
    st.subheader("📈 종목 비교 — 레이더 차트")
    st.caption(
        "2~6개 종목을 선택하면 5-팩터(QVGMT) 점수를 레이더 차트로 비교합니다. "
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
        axes = ["가치", "품질", "성장", "모멘텀", "기술적"]

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
                s(r["growth_score"]),
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
            "QVGM 점수": compare["composite"].map(lambda v: f"{v:+.2f}"),
            "추세": compare["추세"],
            "가치 (V)": compare["value_score"],
            "품질 (Q)": compare["quality_score"],
            "성장 (G)": compare["growth_score"],
            "모멘텀 (M)": compare["momentum_score"],
            "기술적 (T)": compare["technical_score"],
            "종가": compare["close"].map(lambda v: f"{v:,.2f}"),
            "PER": compare["per"].map(lambda v: fmt(v)),
            "PBR": compare["pbr"].map(lambda v: fmt(v)),
            "ROE(%)": compare["roe_pct"].map(lambda v: fmt(v, "{:.1f}")),
            "매출YoY(%)": compare["revenue_growth_yoy_pct"].map(lambda v: fmt(v, "{:+.1f}")),
            "EPS YoY(%)": compare["earnings_growth_yoy_pct"].map(lambda v: fmt(v, "{:+.1f}")),
            "12M 수익률(%)": compare["return_12m_pct"].map(lambda v: fmt(v, "{:+.1f}")),
            "1M 수익률(%)": compare["return_1m_pct"].map(lambda v: fmt(v, "{:+.1f}")),
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
    sc3.metric("QVGM 점수", f"{sel_row['composite']:+.2f}",
               delta=sel_row["판정"], delta_color="off")
    sc4.metric("추세", sel_row["추세"],
               delta=row["last_cross"] if pd.notna(row["last_cross"]) else None,
               delta_color="off")

    # 5-팩터 점수
    st.markdown("#### 5-팩터 세부 점수 (QVGMT)")
    f1, f2, f3, f4, f5 = st.columns(5)
    f1.metric("🏷️ 가치 (V)", fmt(sel_row.get("value_score"), "{:+d}"))
    f2.metric("💎 품질 (Q)", fmt(sel_row.get("quality_score"), "{:+d}"))
    f3.metric("🌱 성장 (G)", fmt(sel_row.get("growth_score"), "{:+d}"))
    f4.metric("🚀 모멘텀 (M)", fmt(sel_row.get("momentum_score"), "{:+d}"))
    f5.metric("📐 기술적 (T)", fmt(sel_row.get("technical_score"), "{:+d}"))

    # 밸류에이션 카드
    st.markdown("#### 밸류에이션 / 펀더멘털")
    if sel in funda["ticker"].values:
        f = funda[funda["ticker"] == sel].iloc[0]
        currency = f.get("currency") if pd.notna(f.get("currency")) else ""
        v1, v2, v3, v4 = st.columns(4)
        consensus_tgt = f.get("consensus_target")
        analyst_n = f.get("analyst_count")
        tgt_label = (f"목표 {fmt(consensus_tgt, '{:,.0f}')} ({int(analyst_n)}명)" if (
            pd.notna(consensus_tgt) and consensus_tgt and
            pd.notna(analyst_n) and analyst_n)
            else fmt(consensus_tgt, "{:,.0f}") if pd.notna(consensus_tgt) and consensus_tgt
            else "-")
        v1.metric("PER", fmt(f.get("per")))
        v2.metric("선행 PER (컨센서스)", fmt(f.get("forward_per")),
                  help="yfinance 추정치. 한국 종목은 실제 컨센서스(삼성 ~7x)와 다를 수 있음.")
        v3.metric("PBR", fmt(f.get("pbr")))
        v4.metric("배당수익률", fmt(f.get("dividend_yield_pct"), suffix="%"))

        rec = f.get("recommendation_mean")
        rec_text = {1: "강력매수", 2: "매수", 3: "중립", 4: "매도", 5: "강력매도"}
        rec_label = rec_text.get(round(rec) if pd.notna(rec) and rec else None, "-") if pd.notna(rec) and rec else "-"

        c1, c2, c3, c4 = st.columns(4)
        c1.metric("애널리스트 목표가", tgt_label,
                  help="yfinance consensus targetMeanPrice. 한국 종목은 없을 수 있음.")
        c2.metric("투자의견", f"{rec_label} ({fmt(rec, '{:.1f}')})" if pd.notna(rec) and rec else "-",
                  help="1=강력매수 ~ 5=강력매도 (애널리스트 평균)")
        c3.metric("시가총액", fmt_mcap(f.get("market_cap"), currency or ""))
        c4.metric("ROE", fmt(f.get("roe_pct"), suffix="%"))

        v5, v6, v7 = st.columns(3)
        v5.metric("영업이익률", fmt(f.get("profit_margin_pct"), suffix="%"))
        sector = f.get("sector") if pd.notna(f.get("sector")) else "-"
        industry = f.get("industry") if pd.notna(f.get("industry")) else "-"
        v6.metric("섹터", str(sector), delta=str(industry), delta_color="off")

        # 성장률 (Growth) — 새로 추가
        st.markdown("##### 🌱 성장률 (YoY)")
        g1, g2, g3 = st.columns(3)
        g1.metric("매출 YoY", fmt(f.get("revenue_growth_yoy_pct"), "{:+.1f}", suffix="%"))
        g2.metric("EPS YoY (연간)", fmt(f.get("earnings_growth_yoy_pct"), "{:+.1f}", suffix="%"))
        g3.metric("분기 EPS YoY", fmt(f.get("eps_growth_q_pct"), "{:+.1f}", suffix="%"))
    else:
        st.info("이 종목의 밸류에이션 정보가 없습니다.")

    df_file = RESULTS / f"{sel}_signals.csv"
    if not df_file.exists():
        st.warning("선택한 티커의 상세 결과 파일이 없습니다.")
        st.stop()

    df = pd.read_csv(df_file, index_col=0, parse_dates=True)

    # 가격 차트 + 보조 지표 토글
    st.markdown("#### 가격 차트 + 기술적 지표")
    opt_cols = st.columns(4)
    show_bb = opt_cols[0].checkbox("📊 볼린저밴드", value=False, help="20일 평균 ± 2σ. 상단터치=과열, 하단터치=과매도")
    show_macd = opt_cols[1].checkbox("📉 MACD", value=False, help="12-26 EMA 차이 + 9일 시그널선. 골든/데드 크로스로 추세 확인")
    show_rsi = opt_cols[2].checkbox("⚡ RSI(14)", value=False, help="70 이상 과매수, 30 이하 과매도")
    show_obv = opt_cols[3].checkbox("📦 OBV", value=False, help="거래량 누적. 가격과 다이버전스 보면 추세 약화 신호")

    fig = go.Figure()
    fig.add_trace(go.Scatter(x=df.index, y=df["Close"], name="종가",
                             line=dict(color="#888")))
    if "ma50" in df.columns:
        fig.add_trace(go.Scatter(x=df.index, y=df["ma50"], name="50일선",
                                 line=dict(color="#3498db")))
    if "ma200" in df.columns:
        fig.add_trace(go.Scatter(x=df.index, y=df["ma200"], name="200일선",
                                 line=dict(color="#e67e22")))

    if show_bb and "bb_upper" in df.columns:
        fig.add_trace(go.Scatter(x=df.index, y=df["bb_upper"], name="BB 상단",
                                 line=dict(color="#9b59b6", width=1, dash="dot")))
        fig.add_trace(go.Scatter(x=df.index, y=df["bb_lower"], name="BB 하단",
                                 line=dict(color="#9b59b6", width=1, dash="dot"),
                                 fill="tonexty", fillcolor="rgba(155,89,182,0.08)"))

    golden = df[df["signal"] == "golden_cross"]
    dead = df[df["signal"] == "death_cross"]
    if not golden.empty:
        fig.add_trace(go.Scatter(
            x=golden.index, y=golden["Close"], mode="markers",
            name="골든크로스",
            marker=dict(symbol="triangle-up", size=14, color="green"),
        ))
    if not dead.empty:
        fig.add_trace(go.Scatter(
            x=dead.index, y=dead["Close"], mode="markers",
            name="데드크로스",
            marker=dict(symbol="triangle-down", size=14, color="red"),
        ))
    fig.update_layout(height=480, hovermode="x unified",
                      legend=dict(orientation="h"))
    st.plotly_chart(fig, use_container_width=True)

    # MACD 보조 차트
    if show_macd and "macd" in df.columns:
        fig_macd = go.Figure()
        fig_macd.add_trace(go.Scatter(x=df.index, y=df["macd"], name="MACD",
                                       line=dict(color="#3498db")))
        fig_macd.add_trace(go.Scatter(x=df.index, y=df["macd_signal"], name="Signal",
                                       line=dict(color="#e67e22")))
        colors = ["#26a96c" if v >= 0 else "#e54d4d" for v in df["macd_hist"].fillna(0)]
        fig_macd.add_trace(go.Bar(x=df.index, y=df["macd_hist"], name="Histogram",
                                   marker_color=colors, opacity=0.5))
        fig_macd.add_hline(y=0, line_dash="dot", line_color="#888")
        fig_macd.update_layout(height=220, hovermode="x unified", title="MACD(12,26,9)",
                                legend=dict(orientation="h"), margin=dict(t=30))
        st.plotly_chart(fig_macd, use_container_width=True)

    # RSI 보조 차트
    if show_rsi and "rsi14" in df.columns:
        fig_rsi = go.Figure()
        fig_rsi.add_trace(go.Scatter(x=df.index, y=df["rsi14"], name="RSI(14)",
                                      line=dict(color="#9b59b6")))
        fig_rsi.add_hline(y=70, line_dash="dash", line_color="#e54d4d",
                          annotation_text="과매수 70")
        fig_rsi.add_hline(y=30, line_dash="dash", line_color="#26a96c",
                          annotation_text="과매도 30")
        fig_rsi.update_layout(height=200, hovermode="x unified", title="RSI(14)",
                               yaxis=dict(range=[0, 100]), margin=dict(t=30))
        st.plotly_chart(fig_rsi, use_container_width=True)

    # OBV 보조 차트
    if show_obv and "obv" in df.columns:
        fig_obv = go.Figure()
        fig_obv.add_trace(go.Scatter(x=df.index, y=df["obv"], name="OBV",
                                      line=dict(color="#16a085")))
        fig_obv.update_layout(height=200, hovermode="x unified", title="OBV (On-Balance Volume)",
                               margin=dict(t=30))
        st.plotly_chart(fig_obv, use_container_width=True)
        st.caption("가격은 오르는데 OBV가 못 따라오면 상승 동력 약화 신호 (다이버전스).")

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
