import streamlit as st
import pandas as pd
from pathlib import Path
import plotly.graph_objects as go
import sys

sys.path.append(str(Path(__file__).resolve().parent))
from scripts.asset_allocation import load_core_etfs
from scripts.etf_recommend import market_regime, score_etfs, sector_cycles

BASE    = Path(__file__).resolve().parent
RESULTS = BASE / "results"

st.title("🏛️ 코어 ETF (참고)")
st.caption("코어 ETF 수익률 비교 및 기본 정보. 매일 새벽 7시 자동 갱신.")

summary_file = RESULTS / "summary_signals.csv"
summary = pd.read_csv(summary_file) if summary_file.exists() else pd.DataFrame()
core_etfs = load_core_etfs()

if summary.empty:
    st.info("신호 데이터 없음 — 내일 새벽 7시 갱신 후 확인하세요.")
    st.stop()

# ── 시장 국면 & ETF 점수 ──────────────────────────────────────────────────────
_regime  = market_regime(summary)
_scored  = score_etfs(core_etfs, summary, _regime["key"])
_valid   = _scored.dropna(subset=["close", "score"]).sort_values("score", ascending=False)
_all     = _scored.sort_values("return_12m_pct", ascending=False, na_position="last")

# ── 요약 메트릭 ───────────────────────────────────────────────────────────────
_c1, _c2, _c3, _c4 = st.columns(4)
_c1.metric("📊 데이터 수집", f"{len(_valid)} / {len(_all)}개")
_c2.metric("📈 Bull 추세",   f"{int((_valid['state']=='bull').sum())}개")
if not _valid.empty:
    _best12 = _all.dropna(subset=["return_12m_pct"]).sort_values("return_12m_pct", ascending=False)
    _c3.metric(f"🥇 12M 최고 ({_best12.iloc[0]['ticker']})",  f"{_best12.iloc[0]['return_12m_pct']:+.1f}%")
    _c4.metric(f"🥉 12M 최저 ({_best12.iloc[-1]['ticker']})", f"{_best12.iloc[-1]['return_12m_pct']:+.1f}%")

st.divider()

# ── 국면 표시 ─────────────────────────────────────────────────────────────────
st.subheader(f"시장 국면: {_regime['label']}")
st.caption(_regime["desc"])
_m1, _m2, _m3, _m4 = st.columns(4)
_m1.metric("시장 브레드스", f"{_regime['breadth']:.0f}%",
           help="전체 추적 종목 중 골든크로스(bull) 비율")
_m2.metric("SPY 1M",        f"{_regime['spy_1m']:+.1f}%")
_m3.metric("SPY 12M",       f"{_regime['spy_12m']:+.1f}%")
_m4.metric("채권(TLT) 1M",  f"{_regime['tlt_1m']:+.1f}%",
           delta="채권 우세" if _regime["bond_winning"] else "주식 우세",
           delta_color="inverse" if _regime["bond_winning"] else "normal")

st.divider()

# ── 섹터 사이클 현황 ──────────────────────────────────────────────────────────
st.subheader("🔄 섹터 사이클 현황")
st.caption("각 섹터 대표 ETF의 1M 상대강도 기준. 점수 계산에 자동 반영됩니다.")

_cy_df = sector_cycles(summary)
if not _cy_df.empty:
    _cy_show = _cy_df[["섹터", "지표ETF", "벤치마크", "지표 1M", "벤치 1M", "상대강도", "사이클"]].copy()
    _cy_show = _cy_show.sort_values("상대강도", ascending=False)
    st.dataframe(
        _cy_show, hide_index=True, use_container_width=True,
        column_config={
            "지표 1M":  st.column_config.NumberColumn("지표 1M(%)", format="%+.1f"),
            "벤치 1M":  st.column_config.NumberColumn("벤치 1M(%)", format="%+.1f"),
            "상대강도":  st.column_config.NumberColumn("상대강도(%p)", format="%+.1f"),
        },
    )

st.divider()

# ── 추천 섹션 ─────────────────────────────────────────────────────────────────
st.subheader("🎯 시장 국면 반영 추천 ETF")
st.caption("모멘텀(12M 70% + 1M 30%) × 시장 국면 × 섹터 사이클. Bull 추세 + RSI 70 미만 우선.")

if not _valid.empty:
    _bull_ok = _valid[(_valid["state"] == "bull") & (_valid["rsi14"] < 70)]
    _watch   = _valid[~_valid.index.isin(_bull_ok.index)].head(3)

    def _tag(row):
        parts = [f"[{row['버킷']}]"]
        if row["return_12m_pct"] >= 20: parts.append(f"12M {row['return_12m_pct']:+.0f}%")
        if row["return_1m_pct"]  >= 3:  parts.append(f"1M {row['return_1m_pct']:+.1f}%")
        if row["rsi14"] < 50:           parts.append("RSI 여유")
        if row["expense_ratio"] <= 0.1: parts.append("저보수")
        return " · ".join(parts)

    if not _bull_ok.empty:
        _top  = _bull_ok.head(5)
        _cols = st.columns(min(len(_top), 5))
        for i, (_, row) in enumerate(_top.iterrows()):
            with _cols[i]:
                st.metric(f"**{row['ticker']}**",
                          f"{row['return_12m_pct']:+.1f}%",
                          f"1M {row['return_1m_pct']:+.1f}%")
                st.caption(row["name"])
                st.caption(f"RSI {row['rsi14']:.0f} · 점수 {row['score']:.0f}")
                st.caption(_tag(row))
                if pd.notna(row.get("섹터사이클")) and row["섹터사이클"] != "—":
                    st.caption(f"사이클: {row['섹터사이클']}")

    if not _watch.empty:
        with st.expander("👀 관심 ETF (Bear 또는 RSI ≥ 70)"):
            for _, row in _watch.iterrows():
                reason = "Bear 추세" if row["state"] != "bull" else f"RSI {row['rsi14']:.0f} 과열"
                st.markdown(f"- **{row['ticker']}** {row['name']} — 12M {row['return_12m_pct']:+.1f}% / {reason}")

    st.divider()
    st.markdown("**카테고리별 국면 반영 1위**")
    _cat_best = (
        _valid.sort_values("score", ascending=False)
              .groupby("category", sort=False).first().reset_index()
              [["category", "버킷", "ticker", "name", "return_1m_pct", "return_12m_pct", "score", "state"]]
              .sort_values("score", ascending=False)
    )
    st.dataframe(
        _cat_best.rename(columns={
            "category": "카테고리", "버킷": "위험도", "ticker": "티커", "name": "종목명",
            "return_1m_pct": "1M(%)", "return_12m_pct": "12M(%)", "score": "점수", "state": "추세",
        }),
        hide_index=True, use_container_width=True,
        column_config={
            "1M(%)":  st.column_config.NumberColumn(format="%+.2f"),
            "12M(%)": st.column_config.NumberColumn(format="%+.2f"),
            "점수":   st.column_config.ProgressColumn(format="%.0f", min_value=0, max_value=130),
        },
    )

st.divider()

# ── 수익률 비교 차트 ─────────────────────────────────────────────────────────
st.subheader("수익률 비교")
_view = _all.dropna(subset=["return_12m_pct"]).sort_values("return_12m_pct", ascending=False)
_fig = go.Figure()
_fig.add_trace(go.Bar(
    name="1개월",
    x=_view["ticker"], y=_view["return_1m_pct"],
    marker_color=["#22a06b" if v >= 0 else "#e34935" for v in _view["return_1m_pct"]],
    opacity=0.75,
    text=[f"{v:+.1f}%" for v in _view["return_1m_pct"]], textposition="outside",
))
_fig.add_trace(go.Bar(
    name="12개월",
    x=_view["ticker"], y=_view["return_12m_pct"],
    marker_color=["#1a7f64" if v >= 0 else "#c0392b" for v in _view["return_12m_pct"]],
    text=[f"{v:+.1f}%" for v in _view["return_12m_pct"]], textposition="outside",
))
_fig.add_hline(y=0, line_color="rgba(0,0,0,0.25)", line_width=1)
_fig.update_layout(
    barmode="group", height=420, margin=dict(t=30, b=10, l=10, r=10),
    legend=dict(orientation="h", y=1.08, x=0),
    yaxis=dict(title="수익률 (%)"), paper_bgcolor="rgba(0,0,0,0)",
)
st.plotly_chart(_fig, use_container_width=True)

# ── 전체 목록 테이블 ──────────────────────────────────────────────────────────
st.subheader("전체 목록")
_tbl = _all[["ticker", "name", "category", "asset_class", "close",
             "return_1m_pct", "return_12m_pct", "rsi14",
             "expense_ratio", "state", "notes"]].rename(columns={
    "ticker": "티커", "name": "종목명", "category": "카테고리",
    "asset_class": "자산군", "close": "현재가",
    "return_1m_pct": "1M(%)", "return_12m_pct": "12M(%)",
    "rsi14": "RSI", "expense_ratio": "운용보수(%)", "state": "추세", "notes": "비고",
})
st.dataframe(
    _tbl, hide_index=True, use_container_width=True,
    column_config={
        "현재가":     st.column_config.NumberColumn("현재가", format="%,.2f"),
        "1M(%)":      st.column_config.NumberColumn("1M(%)", format="%+.2f"),
        "12M(%)":     st.column_config.NumberColumn("12M(%)", format="%+.2f"),
        "RSI":        st.column_config.NumberColumn("RSI", format="%.1f"),
        "운용보수(%)": st.column_config.NumberColumn("운용보수(%)", format="%.2f"),
    },
)
