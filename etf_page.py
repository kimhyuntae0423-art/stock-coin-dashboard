import streamlit as st
import pandas as pd
from pathlib import Path
import plotly.graph_objects as go
import sys

sys.path.append(str(Path(__file__).resolve().parent))
from scripts.asset_allocation import load_core_etfs

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

_sig = summary[["ticker", "close", "return_1m_pct", "return_12m_pct", "rsi14", "state"]].copy()
_sig["ticker"] = _sig["ticker"].astype(str).str.upper()

_base = core_etfs.copy()
_base["ticker"] = _base["ticker"].astype(str).str.upper()

_cmp = _base.merge(_sig, on="ticker", how="left")
_cmp_valid = _cmp.dropna(subset=["close"]).sort_values("return_12m_pct", ascending=False)
_cmp_all   = _cmp.sort_values("return_12m_pct", ascending=False, na_position="last")

# ── 요약 메트릭 ────────────────────────────────────────────────────────────────
if not _cmp_valid.empty:
    _best  = _cmp_valid.iloc[0]
    _worst = _cmp_valid.iloc[-1]
    _bull_cnt = (_cmp_valid["state"] == "bull").sum()
    _c1, _c2, _c3, _c4 = st.columns(4)
    _c1.metric("📊 데이터 수집", f"{len(_cmp_valid)} / {len(_cmp_all)}개")
    _c2.metric("📈 Bull 추세", f"{_bull_cnt}개",
               delta=f"{_bull_cnt}/{len(_cmp_valid)}")
    _c3.metric(f"🥇 12M 최고 ({_best['ticker']})",
               f"{_best['return_12m_pct']:+.1f}%")
    _c4.metric(f"🥉 12M 최저 ({_worst['ticker']})",
               f"{_worst['return_12m_pct']:+.1f}%")

st.divider()

# ── 수익률 비교 차트 ────────────────────────────────────────────────────────────
st.subheader("수익률 비교")

_view = _cmp_valid.copy()
_fig = go.Figure()
_fig.add_trace(go.Bar(
    name="1개월",
    x=_view["ticker"],
    y=_view["return_1m_pct"],
    marker_color=["#22a06b" if v >= 0 else "#e34935" for v in _view["return_1m_pct"]],
    opacity=0.75,
    text=[f"{v:+.1f}%" for v in _view["return_1m_pct"]],
    textposition="outside",
))
_fig.add_trace(go.Bar(
    name="12개월",
    x=_view["ticker"],
    y=_view["return_12m_pct"],
    marker_color=["#1a7f64" if v >= 0 else "#c0392b" for v in _view["return_12m_pct"]],
    text=[f"{v:+.1f}%" for v in _view["return_12m_pct"]],
    textposition="outside",
))
_fig.add_hline(y=0, line_color="rgba(0,0,0,0.25)", line_width=1)
_fig.update_layout(
    barmode="group",
    height=420,
    margin=dict(t=30, b=10, l=10, r=10),
    legend=dict(orientation="h", y=1.08, x=0),
    yaxis=dict(title="수익률 (%)", zeroline=True),
    paper_bgcolor="rgba(0,0,0,0)",
)
st.plotly_chart(_fig, use_container_width=True)

# ── 상세 테이블 ────────────────────────────────────────────────────────────────
st.subheader("전체 목록")

_tbl = _cmp_all[["ticker", "name", "category", "asset_class", "close",
                  "return_1m_pct", "return_12m_pct", "rsi14",
                  "expense_ratio", "state", "notes"]].rename(columns={
    "ticker": "티커", "name": "종목명", "category": "카테고리",
    "asset_class": "자산군", "close": "현재가",
    "return_1m_pct": "1M(%)", "return_12m_pct": "12M(%)",
    "rsi14": "RSI", "expense_ratio": "운용보수(%)",
    "state": "추세", "notes": "비고",
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
