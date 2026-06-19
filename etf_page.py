import streamlit as st
import pandas as pd
from pathlib import Path
import plotly.graph_objects as go
import sys

sys.path.append(str(Path(__file__).resolve().parent))
from scripts.asset_allocation import load_core_etfs
from scripts.etf_recommend import (
    market_regime, score_etfs, sector_cycles,
    macro_signals, enrich_with_volume,
)

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
_scored  = enrich_with_volume(_scored, RESULTS)
_macro   = macro_signals(summary)
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

# ── 매크로 레이더 ─────────────────────────────────────────────────────────────
st.subheader("🌐 매크로 레이더")
st.caption("경기·공포·채권 신호 — 가격보다 1~4주 선행하는 경향이 있는 지표들")

_mr_cols = st.columns(4)
_mr_idx  = 0

if "경기신호" in _macro:
    cu_str = f"{_macro['구리금비율']:+.1f}%p" if "구리금비율" in _macro else "—"
    _mr_cols[_mr_idx].metric(
        "구리/금 비율 (경기 선행)",
        _macro["경기신호"],
        cu_str,
        help="COPX 1M - GLD 1M. 구리 > 금 = 경기 기대, 반대 = 위험회피. 경기에 2~4주 선행."
    )
    _mr_idx += 1

if "곡선신호" in _macro:
    cv_str = f"TLT-SHY {_macro['수익률곡선']:+.1f}%p" if "수익률곡선" in _macro else "—"
    _mr_cols[_mr_idx].metric(
        "수익률 곡선 (채권 흐름)",
        _macro["곡선신호"],
        cv_str,
        help="장기채(TLT) vs 단기채(SHY) 1M 성과. 장기채 우위 = 안전자산 선호."
    )
    _mr_idx += 1

if "공포신호" in _macro:
    _mr_cols[_mr_idx].metric(
        "공포지수 VIX",
        _macro["공포신호"],
        f"VIX {_macro['VIX']:.0f}",
        help=">30 역사적 저점 매수 기회, <15 과열 경계. 역발상 지표."
    )
    _mr_idx += 1

if "달러강도" in _macro:
    _mr_cols[_mr_idx % 4].metric(
        "달러 강도 (추정)",
        _macro["달러강도"],
        help="DXJ(일본 헤지) vs VEU(비미국) 상대강도. 강달러 = 신흥국·원자재 ETF 역풍."
    )

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

# ── 추천 섹션 ─────────────────────────────────────────────────────────────────
st.subheader("🎯 ETF 추천")
st.caption("점수 = 모멘텀(12M×70% + 1M×30%) × 시장 국면 배율 × 섹터 사이클 배율")

_cy_df = sector_cycles(summary)

if not _valid.empty:
    _bull_ok = _valid[(_valid["state"] == "bull") & (_valid["rsi14"] < 70)].head(5)
    _watch   = _valid[~_valid.index.isin(_bull_ok.index)].head(3)

    # ── Top 5 추천 카드 ────────────────────────────────────────────────────────
    if not _bull_ok.empty:
        _cols = st.columns(min(len(_bull_ok), 5))
        for i, (_, row) in enumerate(_bull_ok.iterrows()):
            with _cols[i]:
                st.metric(f"**{row['ticker']}**",
                          f"{row['return_12m_pct']:+.1f}%",
                          f"1M {row['return_1m_pct']:+.1f}%")
                st.caption(row["name"])
                cy = row.get("섹터사이클", "—")
                cy_str = cy if pd.notna(cy) and cy != "—" else "➡️ 중립"
                st.caption(f"사이클 {cy_str}")
                st.caption(f"RSI {row['rsi14']:.0f} · 점수 **{row['score']:.0f}**")

    st.divider()

    # ── 전체 추천 테이블 (섹터 사이클 통합) ────────────────────────────────────
    st.markdown("**전체 ETF 점수 · 사이클 현황**")

    _full = _valid.copy()
    _full["사이클상태"] = _full["섹터사이클"].fillna("—") if "섹터사이클" in _full.columns else "—"

    _tbl_full = _full[[
        "ticker", "name", "버킷", "사이클상태",
        "return_1m_pct", "return_12m_pct", "rsi14",
        "기술신호", "거래량신호", "MA정렬", "BB위치", "OBV추세",
        "mom_score", "사이클배율", "score", "state",
    ]].copy() if "기술신호" in _full.columns else _full[[
        "ticker", "name", "버킷", "사이클상태",
        "return_1m_pct", "return_12m_pct", "rsi14",
        "mom_score", "사이클배율", "score", "state",
    ]].copy()
    _tbl_full["사이클배율"] = _tbl_full["사이클배율"].apply(
        lambda x: f"×{x:.2f}" if pd.notna(x) else "×1.00"
    )
    st.dataframe(
        _tbl_full.rename(columns={
            "ticker": "티커", "name": "종목명", "버킷": "위험도",
            "사이클상태": "섹터사이클", "return_1m_pct": "1M(%)",
            "return_12m_pct": "12M(%)", "rsi14": "RSI",
            "기술신호": "기술신호", "거래량신호": "거래량",
            "MA정렬": "MA(0-3)", "BB위치": "BB위치",
            "OBV추세": "OBV(%)",
            "mom_score": "모멘텀", "사이클배율": "배율",
            "score": "최종점수", "state": "추세",
        }),
        hide_index=True, use_container_width=True,
        column_config={
            "1M(%)":    st.column_config.NumberColumn(format="%+.2f"),
            "12M(%)":   st.column_config.NumberColumn(format="%+.2f"),
            "RSI":      st.column_config.NumberColumn(format="%.0f"),
            "MA(0-3)":  st.column_config.NumberColumn(format="%.0f",
                         help="3=MA20>MA50>MA200 완전 정렬(강세), 0=역배열(약세)"),
            "BB위치":   st.column_config.NumberColumn(format="%.2f",
                         help="볼린저밴드 위치. 0.8↑=상단압박, 0.2↓=하단지지"),
            "OBV(%)":   st.column_config.NumberColumn(format="%+.1f",
                         help="10일 OBV 변화율. 양수=매집, 음수=분배"),
            "모멘텀":   st.column_config.NumberColumn(format="%.0f"),
            "최종점수": st.column_config.ProgressColumn(format="%.0f", min_value=0, max_value=180),
        },
    )

    if not _watch.empty:
        with st.expander("👀 제외 ETF (Bear 추세 또는 RSI ≥ 70)"):
            for _, row in _watch.iterrows():
                reason = "Bear 추세" if row["state"] != "bull" else f"RSI {row['rsi14']:.0f} 과열"
                cy = row.get("섹터사이클", "—")
                cy_str = f" · 사이클 {cy}" if pd.notna(cy) and cy != "—" else ""
                st.markdown(f"- **{row['ticker']}** {row['name']} — 12M {row['return_12m_pct']:+.1f}% / {reason}{cy_str}")

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
