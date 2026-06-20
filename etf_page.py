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
core_etfs  = load_core_etfs()
_notes_map = (
    dict(zip(core_etfs["ticker"], core_etfs["notes"]))
    if "notes" in core_etfs.columns else {}
)

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

# ── 오늘의 핵심 인사이트 ─────────────────────────────────────────────────────
_ins_vix  = _regime.get("vix", 0.0)
_ins_lbl  = _regime.get("label", "—")
_ins_1m   = _regime.get("spy_1m", 0.0)
_ins_12m  = _regime.get("spy_12m", 0.0)
_ins_br   = _regime.get("breadth", 0.0)

_oh_list  = [
    f"{r['ticker']} ({r.get('과열신호','')})"
    for _, r in _valid.iterrows()
    if "⚠️" in str(r.get("과열신호", "")) or "🔥" in str(r.get("과열신호", ""))
] if not _valid.empty and "과열신호" in _valid.columns else []

if _ins_vix > 25:
    _vc, _vtxt = "#dcfce7", f"🔥 VIX {_ins_vix:.0f} — **공포 구간. 백테스트 최고 수익 구간 (IC=0.14 ✅)** — 분할 매수 적극 검토"
elif _ins_vix > 20:
    _vc, _vtxt = "#fef3c7", f"⚠️ VIX {_ins_vix:.0f} — 불안 구간. 신중하게 진입 가능"
elif _ins_vix < 13:
    _vc, _vtxt = "#fef2f2", f"🌡️ VIX {_ins_vix:.0f} — 저공포 과열 경계. 신규 대량 매수 자제"
else:
    _vc, _vtxt = "#f0f9ff", f"VIX {_ins_vix:.0f} — 보통 구간. 급격한 공포/탐욕 없음"

st.markdown(
    f"<div style='background:{_vc};border-radius:8px;padding:14px 16px;margin-bottom:10px'>"
    f"<div style='font-size:14px;line-height:1.8'>"
    f"{_vtxt}<br>"
    f"📊 국면: <b>{_ins_lbl}</b> &nbsp;|&nbsp; "
    f"SPY 1개월 {_ins_1m:+.1f}% · 12개월 {_ins_12m:+.1f}% &nbsp;|&nbsp; "
    f"{'🟢' if _ins_br > 50 else '🔴'} 시장의 {_ins_br:.0f}%가 상승 추세"
    f"</div></div>",
    unsafe_allow_html=True,
)

_ci1, _ci2 = st.columns(2)
with _ci1:
    st.markdown(
        "<div style='background:#f0fdf4;border-left:3px solid #22c55e;"
        "border-radius:6px;padding:12px;margin-bottom:10px'>"
        "<div style='font-size:12px;font-weight:700;color:#15803d;margin-bottom:6px'>"
        "✅ 백테스트 검증된 신호 — 이것만 믿어라</div>"
        "<div style='font-size:12px;color:#374151;line-height:1.9'>"
        "• <b>VIX&gt;25</b> = 분할 매수 타이밍 (IC=0.14, 가장 강력한 신호 ★★★)<br>"
        "• <b>BB 위치 0.85↑ + MA 완전정렬</b> = 과열 → 신규 매수 자제 (IC=-0.087)<br>"
        "• <b>거래량 급증(매집)</b> = 기관 개입 추정, 참고 (IC=0.04 ★)"
        "</div></div>",
        unsafe_allow_html=True,
    )
with _ci2:
    st.markdown(
        "<div style='background:#fef2f2;border-left:3px solid #ef4444;"
        "border-radius:6px;padding:12px;margin-bottom:10px'>"
        "<div style='font-size:12px;font-weight:700;color:#b91c1c;margin-bottom:6px'>"
        "❌ 백테스트 미검증 신호 — 믿지 마라</div>"
        "<div style='font-size:12px;color:#374151;line-height:1.9'>"
        "• <b>배분점수 순위</b> = 미래 수익 예측 안 됨 (IC=0.019, p=0.61 ❌)<br>"
        "• <b>12개월 많이 오른 ETF</b> = 앞으로도 오른다 ❌ (ETF는 모멘텀 효과 없음)<br>"
        "• <b>섹터사이클 순위</b> = 예측력 없음 (IC=−0.023, p=0.34 ❌)"
        "</div></div>",
        unsafe_allow_html=True,
    )

if _oh_list:
    st.warning(f"⚠️ 과열 ETF — 신규 매수 자제: {', '.join(_oh_list[:5])}")

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
st.caption("경기·공포·채권 신호 — 가격보다 1~4주 선행하는 경향이 있는 지표들 (백테스트 IC 검증 기반)")

# VIX 강조 배너 (IC=0.14, 가장 강력한 신호)
_vix = _regime.get("vix")
_vsig = _regime.get("vix_signal", "")
if _vix:
    if _vix > 25:
        st.success(f"🔥 VIX {_vix:.0f} — {_vsig}  |  백테스트 검증: VIX>25일 때 향후 1개월 평균 수익 최고 (IC=0.14)")
    elif _vix < 13:
        st.warning(f"🌡️ VIX {_vix:.0f} — {_vsig}  |  저공포 = 과열 경계, 신규 매수 신중")
    else:
        st.info(f"VIX {_vix:.0f} — {_vsig}")

_mr_cols = st.columns(4)
_mr_idx  = 0

if "경기신호" in _macro:
    cu_str = f"{_macro['구리금비율']:+.1f}%p" if "구리금비율" in _macro else "—"
    _mr_cols[_mr_idx].metric(
        "구리/금 비율 (경기 선행)",
        _macro["경기신호"],
        cu_str,
        help="COPX 1개월 - GLD 1개월. 구리 > 금 = 경기 기대, 반대 = 위험회피. 경기에 2~4주 선행."
    )
    _mr_idx += 1

if "곡선신호" in _macro:
    cv_str = f"TLT-SHY {_macro['수익률곡선']:+.1f}%p" if "수익률곡선" in _macro else "—"
    _mr_cols[_mr_idx].metric(
        "수익률 곡선 (채권 흐름)",
        _macro["곡선신호"],
        cv_str,
        help="장기채(TLT) vs 단기채(SHY) 1개월 성과. 장기채 우위 = 안전자산 선호."
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
_m2.metric("SPY 1개월",        f"{_regime['spy_1m']:+.1f}%")
_m3.metric("SPY 12개월",       f"{_regime['spy_12m']:+.1f}%")
_m4.metric("채권(TLT) 1개월",  f"{_regime['tlt_1m']:+.1f}%",
           delta="채권 우세" if _regime["bond_winning"] else "주식 우세",
           delta_color="inverse" if _regime["bond_winning"] else "normal")

st.divider()

# ── 추천 섹션 ─────────────────────────────────────────────────────────────────
st.subheader("🎯 ETF 배분 점수")
st.info(
    "**백테스트 결과 반영**: ETF 모멘텀 순위 IC=0.019 (p=0.61, 유의성 없음)  \n"
    "→ 배분점수는 **섹터사이클(실제 드라이버)** + **VIX 국면** 이 결정. 모멘텀은 25% 보조 가중치만 적용  \n"
    "→ **과열 신호(IC 역방향 검증)**와 **VIX 타이밍(IC=0.14)** 만 통계적으로 신뢰 가능"
)

_cy_df = sector_cycles(summary)

def _entry_desc(bb, ma) -> str:
    """BB + MA 상태를 한 줄 진입 설명으로 변환."""
    bb = float(bb) if pd.notna(bb) else 0.5
    ma = int(ma)   if pd.notna(ma) else 1
    # BB 상태
    if bb < 0:
        bb_txt = "밴드 아래 이탈 (극단 조정)"
    elif bb < 0.20:
        bb_txt = "하단 지지 구간"
    elif bb < 0.40:
        bb_txt = "과열 해소됨"
    elif bb < 0.60:
        bb_txt = "중립 구간"
    elif bb < 0.80:
        bb_txt = "상단 근접 (주의)"
    else:
        bb_txt = "상단 과열"
    # MA 추세 보조
    ma_txt = ["추세 없음", "약세 추세", "추세 형성 중", "완전 상승 추세"][ma]
    # 종합 한줄 코멘트
    if bb < 0.40 and ma <= 1:
        verdict = "→ 조정 구간, 반등 여지"
    elif bb < 0.40 and ma >= 2:
        verdict = "→ 매수 여건 양호"
    elif bb >= 0.80 and ma == 3:
        verdict = "→ 신규 매수 자제"
    elif bb >= 0.60:
        verdict = "→ 추가 진입 신중"
    else:
        verdict = ""
    return f"{bb_txt} · {ma_txt} {verdict}".strip()


if not _valid.empty:
    # 상대적 저점 순위 기준 Top 5 (H15 검증 — 낮은 BB + 낮은 MA = 향후 수익 좋은 경향)
    # RSI<75 필터 (극단 과열 제외)
    if "냉각지수" in _valid.columns:
        _cool_sorted = _valid[_valid["rsi14"] < 75].sort_values(
            "냉각지수", ascending=False, na_position="last"
        )
    else:
        _cool_sorted = _valid[_valid["rsi14"] < 75]
    _bull_ok = _cool_sorted.head(5)
    _watch   = _valid[~_valid.index.isin(_bull_ok.index)].head(3)

    # ── Top 5 카드: 상대적 저점 순위 기준 (H15 검증) ────────────────────────
    if not _bull_ok.empty:
        _cols = st.columns(min(len(_bull_ok), 5))
        for i, (_, row) in enumerate(_bull_ok.iterrows()):
            with _cols[i]:
                cr = row.get("냉각순위")
                cr_str = f"#{int(cr)}" if pd.notna(cr) else "—"
                oh = str(row.get("과열신호", ""))
                bb_v = row.get("BB위치")
                ma_v = row.get("MA정렬")
                st.metric(
                    f"**{row['ticker']}**",
                    f"상대적 저점 {cr_str}",
                    f"1개월 {row['return_1m_pct']:+.1f}%",
                )
                st.caption(row["name"])
                # ETF 보유 내용 설명 (core_etfs.csv notes)
                _note = _notes_map.get(row["ticker"], "")
                if _note:
                    st.caption(f"📦 {_note}")
                # 진입 사유 (BB + MA 기반)
                if pd.notna(bb_v) and pd.notna(ma_v):
                    st.caption(_entry_desc(bb_v, ma_v))
                    bb_str = f"BB={bb_v:.2f}" if pd.notna(bb_v) else ""
                    ma_str = f"MA={int(ma_v)}/3" if pd.notna(ma_v) else ""
                    st.caption(f"{bb_str} · {ma_str}")
                if "⚠️" in oh:
                    st.caption("⚠️ 과열 주의")

    st.divider()

    # ── 전체 테이블 ────────────────────────────────────────────────────────────
    st.markdown("**전체 ETF 상대적 저점 순위**")
    st.caption(
        "**상대적 저점순위** = 백테스트 검증 (H15 IC=0.087, p<0.001). "
        "낮은 BB + 낮은 MA정렬 ETF가 향후 1개월 평균 2.82% vs 과열 ETF 1.03%. "
        "VIX>25 구간에서 저점순위 1~3위 ETF 매수 = 두 검증 신호의 교집합."
    )

    _full = _valid.copy()
    _full["사이클상태"] = _full["섹터사이클"].fillna("—") if "섹터사이클" in _full.columns else "—"

    _extra_cols = ["냉각순위", "거래량신호", "과열신호", "MA정렬", "BB위치", "OBV추세"]
    _base_cols  = ["ticker", "name", "버킷", "사이클상태",
                   "return_1m_pct", "return_12m_pct", "rsi14"]
    _opt_cols   = [c for c in _extra_cols if c in _full.columns]
    _tbl_full   = _full[_base_cols + _opt_cols + ["사이클배율", "score", "state"]].copy()

    _tbl_full["사이클배율"] = _tbl_full["사이클배율"].apply(
        lambda x: f"×{x:.2f}" if pd.notna(x) else "×1.00"
    )
    if "냉각순위" in _tbl_full.columns:
        _tbl_full["냉각순위"] = _tbl_full["냉각순위"].apply(
            lambda x: f"#{int(x)}" if pd.notna(x) else "—"
        )

    st.dataframe(
        _tbl_full.rename(columns={
            "ticker": "티커", "name": "종목명", "버킷": "위험도",
            "사이클상태": "섹터사이클", "return_1m_pct": "1개월(%)",
            "return_12m_pct": "12개월(%)", "rsi14": "RSI",
            "냉각순위": "상대적 저점", "거래량신호": "거래량", "과열신호": "과열신호",
            "MA정렬": "MA(0-3)", "BB위치": "BB위치",
            "OBV추세": "OBV(%)",
            "사이클배율": "사이클배율", "score": "배분점수", "state": "추세",
        }),
        hide_index=True, use_container_width=True,
        column_config={
            "상대적 저점": st.column_config.TextColumn("상대적 저점 ✅",
                         help="백테스트 검증 (H15 IC=0.087 p<0.001). "
                              "#1 = 최근 가격 범위 기준 가장 낮은 위치 = 향후 수익 좋은 경향. "
                              "낮은 BB위치 + 낮은 MA정렬 = 좋은 순위. "
                              "VIX>25 구간에서 이 순위대로 매수."),
            "1개월(%)":  st.column_config.NumberColumn("1개월(%)", format="%+.2f",
                         help="참고 정보. ETF 모멘텀은 백테스트 유의성 없음 (p=0.61)"),
            "12개월(%)": st.column_config.NumberColumn("12개월(%)", format="%+.2f",
                         help="참고 정보. ETF 모멘텀은 백테스트 유의성 없음 (p=0.61)"),
            "RSI":      st.column_config.NumberColumn(format="%.0f"),
            "섹터사이클": st.column_config.TextColumn("섹터사이클",
                         help="참고만. 섹터사이클 IC=-0.023, p=0.34 → 예측력 없음"),
            "과열신호": st.column_config.TextColumn("과열",
                         help="IC 역방향 검증: 과열 = 향후 수익 낮은 경향. 신규 매수 자제"),
            "MA(0-3)":  st.column_config.NumberColumn(format="%.0f",
                         help="3=완전정렬 → 과열 경보(IC=-0.065 역방향). 상대적 저점 구성 요소"),
            "BB위치":   st.column_config.NumberColumn(format="%.2f",
                         help="0.85↑ = 과열. 0↓ = 밴드 이탈(극단 조정). 상대적 저점 구성 요소"),
            "OBV(%)":   st.column_config.NumberColumn(format="%+.1f",
                         help="IC=+0.04 (약한 양방향). 매집 신호 참고용"),
            "사이클배율": st.column_config.TextColumn("사이클배율",
                         help="IC=-0.023, p=0.34 → ±5% 참고만"),
            "배분점수": st.column_config.ProgressColumn("배분점수",
                         format="%.0f", min_value=0, max_value=180,
                         help="섹터사이클×VIX국면 기반. 상대적 저점 순위를 함께 참고하세요"),
        },
    )

    if not _watch.empty:
        with st.expander("👀 제외 ETF (Bear 추세 또는 RSI ≥ 70)"):
            for _, row in _watch.iterrows():
                reason = "Bear 추세" if row["state"] != "bull" else f"RSI {row['rsi14']:.0f} 과열"
                cy = row.get("섹터사이클", "—")
                cy_str = f" · 사이클 {cy}" if pd.notna(cy) and cy != "—" else ""
                st.markdown(f"- **{row['ticker']}** {row['name']} — 12개월 {row['return_12m_pct']:+.1f}% / {reason}{cy_str}")

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
    "return_1m_pct": "1개월(%)", "return_12m_pct": "12개월(%)",
    "rsi14": "RSI", "expense_ratio": "운용보수(%)", "state": "추세", "notes": "비고",
})
st.dataframe(
    _tbl, hide_index=True, use_container_width=True,
    column_config={
        "현재가":     st.column_config.NumberColumn("현재가", format="%,.2f"),
        "1개월(%)":   st.column_config.NumberColumn("1개월(%)", format="%+.2f"),
        "12개월(%)":  st.column_config.NumberColumn("12개월(%)", format="%+.2f"),
        "RSI":        st.column_config.NumberColumn("RSI", format="%.1f"),
        "운용보수(%)": st.column_config.NumberColumn("운용보수(%)", format="%.2f"),
    },
)
