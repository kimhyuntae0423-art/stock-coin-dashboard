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

# ── 시장 국면 판단 ─────────────────────────────────────────────────────────────
_sig_latest = summary.sort_values("date").groupby("ticker").last().reset_index()

# 1) 시장 브레드스: 전체 종목 중 bull 비율
_breadth = (_sig_latest["state"] == "bull").mean() * 100

# 2) SPY 1M 수익률 (없으면 0)
_spy_row  = _sig_latest[_sig_latest["ticker"] == "SPY"]
_spy_1m   = float(_spy_row["return_1m_pct"].values[0]) if not _spy_row.empty else 0.0
_spy_12m  = float(_spy_row["return_12m_pct"].values[0]) if not _spy_row.empty else 0.0

# 3) 채권 vs 주식 상대강도 (TLT 1M vs SPY 1M)
_tlt_row  = _sig_latest[_sig_latest["ticker"] == "TLT"]
_tlt_1m   = float(_tlt_row["return_1m_pct"].values[0]) if not _tlt_row.empty else 0.0
_bond_winning = _tlt_1m > _spy_1m   # 채권이 주식보다 강하면 risk-off 신호

# 4) 국면 분류
if _breadth >= 55 and _spy_1m >= 0 and not _bond_winning:
    _regime      = "🟢 강세 (Risk-On)"
    _regime_key  = "bull"
    _regime_desc = f"시장 브레드스 {_breadth:.0f}% · SPY 1M {_spy_1m:+.1f}% · 주식 > 채권"
elif _breadth <= 40 or _spy_1m <= -5 or (_bond_winning and _spy_1m < 0):
    _regime      = "🔴 약세 (Risk-Off)"
    _regime_key  = "bear"
    _regime_desc = f"시장 브레드스 {_breadth:.0f}% · SPY 1M {_spy_1m:+.1f}% · {'채권 > 주식' if _bond_winning else '낙폭 과대'}"
else:
    _regime      = "🟡 혼조"
    _regime_key  = "mixed"
    _regime_desc = f"시장 브레드스 {_breadth:.0f}% · SPY 1M {_spy_1m:+.1f}% · 방향성 불명확"

# 자산군 → 위험 버킷 매핑
def _risk_bucket(row):
    cat = str(row.get("category", ""))
    asc = str(row.get("asset_class", ""))
    if asc == "bond" or "채권" in cat:         return "방어"
    if asc == "commodity" or "원자재" in cat:  return "대안"
    if any(k in cat for k in ["유틸리티", "헬스케어", "현금"]):  return "방어"
    if any(k in cat for k in ["나스닥", "반도체", "AI", "방산", "테마", "우라늄", "구리", "인프라"]):
        return "공격"
    return "핵심"

# 국면별 버킷 가중치
_bucket_weight = {
    "bull":  {"공격": 1.30, "핵심": 1.10, "대안": 0.90, "방어": 0.70},
    "mixed": {"공격": 1.00, "핵심": 1.00, "대안": 1.00, "방어": 1.00},
    "bear":  {"공격": 0.70, "핵심": 0.90, "대안": 1.20, "방어": 1.30},
}

# ── 국면 표시 ──────────────────────────────────────────────────────────────────
st.subheader(f"시장 국면: {_regime}")
st.caption(_regime_desc)
_mc1, _mc2, _mc3, _mc4 = st.columns(4)
_mc1.metric("시장 브레드스", f"{_breadth:.0f}%", help="전체 추적 종목 중 골든크로스(bull) 비율")
_mc2.metric("SPY 1M",  f"{_spy_1m:+.1f}%")
_mc3.metric("SPY 12M", f"{_spy_12m:+.1f}%")
_mc4.metric("채권(TLT) 1M", f"{_tlt_1m:+.1f}%",
            delta="채권 우세" if _bond_winning else "주식 우세",
            delta_color="inverse" if _bond_winning else "normal")

st.divider()

# ── 추천 섹션 ──────────────────────────────────────────────────────────────────
st.subheader("🎯 시장 국면 반영 추천 ETF")
st.caption("모멘텀(12M 70% + 1M 30%) × 국면 가중치. Bull 추세 + RSI 70 미만 우선.")

if not _cmp_valid.empty:
    _scored = _cmp_valid.copy()
    _scored["버킷"] = _scored.apply(_risk_bucket, axis=1)
    _scored["r12_rank"]  = _scored["return_12m_pct"].rank(pct=True)
    _scored["r1_rank"]   = _scored["return_1m_pct"].rank(pct=True)
    _scored["mom_score"] = (_scored["r12_rank"] * 0.7 + _scored["r1_rank"] * 0.3) * 100
    _w = _bucket_weight[_regime_key]
    _scored["score"] = _scored.apply(
        lambda r: r["mom_score"] * _w.get(r["버킷"], 1.0), axis=1
    )

    _bull_ok = _scored[(_scored["state"] == "bull") & (_scored["rsi14"] < 70)].sort_values("score", ascending=False)
    _watch   = _scored[~_scored.index.isin(_bull_ok.index)].sort_values("score", ascending=False).head(3)

    def _tag(row):
        parts = [f"[{row['버킷']}]"]
        if row["return_12m_pct"] >= 20: parts.append(f"12M {row['return_12m_pct']:+.0f}%")
        if row["return_1m_pct"]  >= 3:  parts.append(f"1M {row['return_1m_pct']:+.1f}%")
        if row["rsi14"] < 50:           parts.append("RSI 여유")
        if row["expense_ratio"] <= 0.1: parts.append("저보수")
        return " · ".join(parts)

    if not _bull_ok.empty:
        _top = _bull_ok.head(5)
        _cols = st.columns(min(len(_top), 5))
        for i, (_, row) in enumerate(_top.iterrows()):
            with _cols[i]:
                st.metric(
                    label=f"**{row['ticker']}**",
                    value=f"{row['return_12m_pct']:+.1f}%",
                    delta=f"1M {row['return_1m_pct']:+.1f}%",
                )
                st.caption(row["name"])
                st.caption(f"RSI {row['rsi14']:.0f} · 점수 {row['score']:.0f}")
                st.caption(_tag(row))

    if not _watch.empty:
        with st.expander("👀 관심 ETF (Bear 또는 RSI ≥ 70)"):
            for _, row in _watch.iterrows():
                reason = "Bear 추세" if row["state"] != "bull" else f"RSI {row['rsi14']:.0f} 과열"
                st.markdown(f"- **{row['ticker']}** {row['name']} — 12M {row['return_12m_pct']:+.1f}% / {reason}")

    st.divider()
    st.markdown("**카테고리별 국면 반영 1위**")
    _cat_best = (
        _scored.sort_values("score", ascending=False)
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
