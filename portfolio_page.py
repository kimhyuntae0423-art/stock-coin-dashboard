"""포트폴리오 페이지 — 보유 종목 + 매수가 추적 + 매도 신호 알림."""
import streamlit as st
import pandas as pd
import plotly.graph_objects as go
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parent
sys.path.append(str(ROOT))
from scripts.stock_score import rank_stocks
from scripts.factor_calc import enrich_price_factors
from scripts.portfolio_builder import build_portfolio
from scripts.asset_allocation import (
    load_core_etfs, classify_holdings, allocation_summary,
    rebalancing_actions, add_on_buy_triggers,
)
from scripts.dca_simulator import dca_simulate, dca_path

RESULTS = ROOT / "results"
HOLDINGS_FILE = ROOT / "holdings.csv"
NAMES_FILE = ROOT / "names.csv"
COIN_NAMES_FILE = ROOT / "coin_names.csv"
CORE_ETF_FILE = ROOT / "core_etfs.csv"


def load_names() -> dict:
    names: dict = {}
    for path in (NAMES_FILE, COIN_NAMES_FILE):
        if path.exists():
            df = pd.read_csv(path)
            names.update(dict(zip(df["ticker"], df["name"])))
    return names


def build_asset_options() -> list[tuple[str, str]]:
    """이름 검색용 (display_label, ticker) 목록.
    순서: 국내 ETF → 해외 ETF → 코인 → 한국 주식 → 미국 주식
    """
    rows = []

    # 1) Core ETF 목록
    if CORE_ETF_FILE.exists():
        etf_df = pd.read_csv(CORE_ETF_FILE)
        for _, r in etf_df.iterrows():
            t = str(r["ticker"])
            name = str(r["name"])
            cat = str(r.get("category", "ETF"))
            cur = str(r.get("currency", ""))
            tag = "국내 ETF" if cur == "KRW" else "해외 ETF"
            rows.append((f"{name}  ({t}) · {tag}", t))

    # 2) 코인
    if COIN_NAMES_FILE.exists():
        coin_df = pd.read_csv(COIN_NAMES_FILE)
        for _, r in coin_df.iterrows():
            t = str(r["ticker"])
            rows.append((f"{r['name']}  ({t}) · 코인", t))

    # 3) 한국 주식
    if NAMES_FILE.exists():
        names_df = pd.read_csv(NAMES_FILE)
        for _, r in names_df.iterrows():
            t = str(r["ticker"])
            tag = "한국 주식" if t.endswith(".KS") or t.endswith(".KQ") else "미국 주식"
            rows.append((f"{r['name']}  ({t}) · {tag}", t))

    return rows


NAMES = load_names()
ASSET_OPTIONS = build_asset_options()
ASSET_LABEL_TO_TICKER = {label: ticker for label, ticker in ASSET_OPTIONS}
ASSET_LABELS = [label for label, _ in ASSET_OPTIONS]


def _load_holdings() -> pd.DataFrame:
    if not HOLDINGS_FILE.exists() or HOLDINGS_FILE.stat().st_size < 10:
        return pd.DataFrame(columns=["ticker", "qty", "buy_price", "buy_date", "notes"])
    return pd.read_csv(HOLDINGS_FILE)


def _save_holdings(df: pd.DataFrame):
    df.to_csv(HOLDINGS_FILE, index=False, encoding="utf-8")


st.title("💼 보유 종목")
st.caption("장기 분할매수 포트폴리오 추적. 매수 내역 입력 → 수익률·비중·리밸런싱 자동 계산.")

# =====================================================================
# ➕ 매수 내역 추가 (이름 검색)
# =====================================================================
with st.expander("➕ 매수 내역 추가", expanded=True):
    st.caption("종목 이름으로 검색해서 선택하세요. 티커를 몰라도 됩니다.")
    with st.form("add_holding_form", clear_on_submit=True):
        selected_label = st.selectbox(
            "종목 검색",
            options=[""] + ASSET_LABELS,
            index=0,
            help="이름 일부를 입력하면 필터링됩니다. 예: 'S&P', '삼성', '비트코인'",
        )
        fc1, fc2, fc3 = st.columns([2, 2, 3])
        with fc1:
            add_qty = st.number_input("수량", min_value=0.0, step=0.00000001, format="%.8f")
        with fc2:
            add_price = st.number_input("매수가", min_value=0.0, step=1.0, format="%.2f")
        with fc3:
            add_notes = st.text_input("메모 (선택)")
        add_date = st.text_input("매수일 (선택)", placeholder="YYYY-MM-DD, 비워도 됩니다")
        submitted = st.form_submit_button("✅ 추가")

    if submitted:
        if not selected_label or selected_label not in ASSET_LABEL_TO_TICKER:
            st.error("종목을 선택해주세요.")
        elif add_qty <= 0 or add_price <= 0:
            st.error("수량과 매수가는 0보다 커야 합니다.")
        else:
            ticker = ASSET_LABEL_TO_TICKER[selected_label]
            current = _load_holdings()
            new_row = pd.DataFrame([{
                "ticker": ticker,
                "qty": add_qty,
                "buy_price": add_price,
                "buy_date": str(add_date),
                "notes": add_notes,
            }])
            updated = pd.concat([current, new_row], ignore_index=True)
            _save_holdings(updated)
            st.success(f"✅ {ticker} ({add_qty} @ {add_price:,.2f}) 추가 완료!")
            st.rerun()

with st.expander("📖 용어 사전", expanded=False):
    st.markdown("""
**🚦 타이밍 라벨** (추천 포트폴리오 표 옆에 표시)
- 🔴 **너무 올라 위험**: 단기 과매수 — 분할매수 권장
- 🟠 **살짝 비쌈**: 약한 단기 과열 신호
- ⚠️ **가격이 실적보다 빨리 오름**: 1년 가격 상승률이 실적 성장률을 30%p+ 초과
- 💎 **떨어진 우량주**: 펀더 좋고 + 추세 살아있고 + 최근 조정 — 좋은 진입 기회
- 💚 **매수 검토**: 약한 매수 기회 신호

**📊 점수** = -3 ~ +3 사이의 종합 평가. 0이 평균. +1 이상이면 매수 우호, -1 이하면 매도 우호.

**🏛️ Core**: 시장 지수 ETF (예: VOO, KODEX 200) — 시장 평균 수익률 추구
**🎯 Satellite**: 본인이 선정한 개별주 — 시장 + α 시도 영역
**💵 Cash**: 현금/MMF/CMA — 시장 폭락 시 추가매수 탄약

**⚖️ 리밸런싱**: 분기 1회, 목표 비중 대비 ±5%p 벗어나면 비싸진 자산 일부 매도 + 싸진 자산 추가매수.
연 0.5~1% 추가 알파 (Vanguard 30년 연구).

**📈 DCA (Dollar Cost Averaging)**: 매월 일정 금액 적립식 매수. 월급근로자에게 자연스러운 전략.
시장 타이밍 고민 불필요, 정점 매수 회피.

**🎯 분할매수**: 1회에 전량 매수하지 않고 2~4회로 나눠서 진입. 평균단가 안정 + 변동성 흡수.
    """)

# ===== 데이터 로드 =====
holdings = _load_holdings()

# 분석 결과
summary_file = RESULTS / "summary_signals.csv"
funda_file = RESULTS / "fundamentals.csv"
summary = pd.read_csv(summary_file) if summary_file.exists() else pd.DataFrame()
funda = pd.read_csv(funda_file) if funda_file.exists() else pd.DataFrame(columns=["ticker"])

# QVGM 점수도 같이 계산
if not summary.empty and not funda.empty:
    FUNDA_COLS = ["ticker", "per", "forward_per", "pbr", "roe_pct", "profit_margin_pct",
                  "revenue_growth_yoy_pct", "earnings_growth_yoy_pct", "eps_growth_q_pct"]
    for col in FUNDA_COLS:
        if col not in funda.columns:
            funda[col] = None
    score_input = summary.merge(funda[FUNDA_COLS], on="ticker", how="left")
    score_input = enrich_price_factors(score_input)
    scores_df = rank_stocks(score_input)
else:
    scores_df = pd.DataFrame(columns=["ticker", "composite"])


# ===== 편집 가능한 테이블 =====
st.subheader("✏️ 보유 내역 편집")
st.caption("수량·매수가·메모 수정 가능. 행 삭제는 체크박스 선택 후 Delete키. 수정 후 반드시 '💾 저장' 클릭.")

edited = st.data_editor(
    holdings,
    num_rows="dynamic",
    use_container_width=True,
    column_config={
        "ticker": st.column_config.TextColumn("티커", help="위 '매수 추가' 폼으로 입력하면 자동 채워집니다.", required=True),
        "qty": st.column_config.NumberColumn("수량", format="%.8f"),
        "buy_price": st.column_config.NumberColumn("매수가", format="%.2f"),
        "buy_date": st.column_config.TextColumn("매수일", help="YYYY-MM-DD"),
        "notes": st.column_config.TextColumn("메모"),
    },
    key="holdings_editor",
)

sc1, sc2 = st.columns([1, 4])
with sc1:
    if st.button("💾 저장", type="primary", use_container_width=True):
        _save_holdings(edited)
        st.success("저장 완료!")
        st.rerun()
with sc2:
    st.caption("추가는 위 '➕ 매수 내역 추가' 폼 사용 권장. 여기서 직접 편집 후 저장도 가능.")

if edited.empty or edited["ticker"].dropna().empty:
    st.info("보유 종목이 없습니다. 위 표에 추가해보세요.")
    st.stop()

st.divider()

# ===== 평가손익 + 신호 결합 =====
st.subheader("📊 현황 + 매도 신호")

view = edited.dropna(subset=["ticker"]).copy()
view["ticker"] = view["ticker"].astype(str).str.strip().str.upper()

# 분석 결과와 머지
view = view.merge(summary[["ticker", "close", "action", "state",
                            "last_cross", "last_cross_date", "rsi14"]],
                  on="ticker", how="left")
view = view.merge(scores_df[["ticker", "composite"]], on="ticker", how="left")
view["종목명"] = view["ticker"].map(NAMES).fillna("-")

# 평가손익 계산
view["현재가"] = view["close"]
view["평가금액"] = view["qty"] * view["close"]
view["원금"] = view["qty"] * view["buy_price"]
view["손익"] = view["평가금액"] - view["원금"]
view["수익률(%)"] = ((view["close"] / view["buy_price"]) - 1) * 100


# 통합 신호 → "어떻게 할까" 한 줄
def holding_signal(row):
    action = row.get("action")
    rsi = row.get("rsi14")
    pnl_pct = row.get("수익률(%)")
    composite = row.get("composite")

    reasons = []
    severity = 0   # 0 보유 · 1 주의 · 2 매도

    # 강한 매도 신호
    if action == "매도":
        reasons.append("최근 30일 데드크로스 발생")
        severity = 2
    if pd.notna(rsi) and rsi >= 80:
        reasons.append(f"RSI {rsi:.0f} 극단 과매수")
        severity = max(severity, 2)
    if pd.notna(composite) and composite <= -1.0:
        reasons.append(f"펀더멘털 악화 (QVGM {composite:+.2f})")
        severity = max(severity, 2)

    # 주의 신호
    if action == "미보유" and severity < 2:
        reasons.append("추세 하락 구간")
        severity = max(severity, 1)
    if pd.notna(rsi) and rsi >= 70 and severity < 2:
        reasons.append(f"RSI {rsi:.0f} 과매수")
        severity = max(severity, 1)
    if pd.notna(pnl_pct) and pnl_pct <= -8 and severity < 2:
        reasons.append(f"매수가 대비 {pnl_pct:.1f}% (-8% 손절선 근접)")
        severity = max(severity, 1)

    if severity == 2:
        return "🔴 매도 검토", " · ".join(reasons)
    if severity == 1:
        return "🟠 주의", " · ".join(reasons)
    if action == "매수":
        return "🟢 추가 매수 가능", "골든크로스 발생"
    return "✅ 보유", "특이사항 없음"


sigs = view.apply(holding_signal, axis=1)
view["신호"] = [s[0] for s in sigs]
view["사유"] = [s[1] for s in sigs]

# ===== 요약 KPI =====
total_cost = view["원금"].sum()
total_value = view["평가금액"].sum()
total_pnl = total_value - total_cost
total_pnl_pct = (total_pnl / total_cost * 100) if total_cost > 0 else 0
n_sell = (view["신호"] == "🔴 매도 검토").sum()
n_warn = (view["신호"] == "🟠 주의").sum()

k1, k2, k3, k4, k5 = st.columns(5)
k1.metric("보유 종목 수", f"{len(view)}")
k2.metric("총 원금", f"{total_cost:,.0f}")
k3.metric("총 평가금액", f"{total_value:,.0f}")
k4.metric("총 손익", f"{total_pnl:+,.0f}", delta=f"{total_pnl_pct:+.2f}%")
k5.metric("🔴 매도 검토", f"{n_sell}", delta=f"🟠 주의 {n_warn}", delta_color="off")

# 매도 신호가 있으면 큼직히 알림
if n_sell > 0:
    sell_tickers = view[view["신호"] == "🔴 매도 검토"]["ticker"].tolist()
    st.error(f"⚠️ **매도 검토 필요**: {', '.join(sell_tickers)}")

# ===== 상세 표 =====
display = view.rename(columns={
    "ticker": "티커",
    "qty": "수량",
    "buy_price": "매수가",
    "buy_date": "매수일",
    "rsi14": "RSI",
}).copy()

st.dataframe(
    display[["신호", "티커", "종목명", "수량", "매수가", "현재가",
             "수익률(%)", "손익", "사유", "매수일",
             "action", "RSI", "composite", "last_cross_date", "notes"]].rename(
        columns={"action": "추세", "composite": "종합점수", "last_cross_date": "신호일", "notes": "메모"}
    ),
    use_container_width=True,
    hide_index=True,
    column_config={
        "수량": st.column_config.NumberColumn(format="%.8f"),
        "매수가": st.column_config.NumberColumn(format="%,.2f"),
        "현재가": st.column_config.NumberColumn(format="%,.2f"),
        "수익률(%)": st.column_config.NumberColumn(format="%+.2f"),
        "손익": st.column_config.NumberColumn(format="%+,.0f"),
        "RSI": st.column_config.NumberColumn(format="%.1f"),
        "종합점수": st.column_config.NumberColumn(
            "종합점수",
            help="저평가·품질·성장·추세·타이밍 5항목 종합. ±1.5 이상이면 극단.",
            format="%+.2f"),
    },
)

st.caption(
    "**컬럼 풀이**: 추세 = 50/200일선 상태 (매수=골든크로스, 미보유=하락추세, 매도=데드크로스). "
    "RSI = 단기 과매수/과매도 (70+ 부담, 30- 반등 기회). "
    "종합점수 = 회사 펀더 + 추세 + 타이밍 결합 (위 📖 용어 사전 참고)."
)

# ===== 자산 배분 (간단) =====
if total_value > 0:
    st.markdown("#### 자산 배분")
    view["weight"] = view["평가금액"] / total_value * 100
    fig = go.Figure(go.Pie(
        labels=[f"{r['종목명']} ({r['ticker']})" for _, r in view.iterrows()],
        values=view["평가금액"], hole=0.45,
    ))
    fig.update_layout(height=380, margin=dict(t=10, b=10, l=10, r=10))
    st.plotly_chart(fig, use_container_width=True)

st.caption(
    "**매도 신호 기준**: 데드크로스 발생, RSI ≥ 80, QVGM ≤ -1.0 중 하나만 충족해도 🔴 표시. "
    "주의 신호: 추세 미보유 / RSI 70-80 / 손실 -8% 근접. "
    "이건 *자동 매도가 아니라* 검토하라는 알림입니다."
)

# =====================================================================
# 🏛️ Core-Satellite 자산 배분 추적기
# =====================================================================
st.divider()
st.subheader("🏛️ Core-Satellite 자산 배분 추적")
st.caption(
    "**Core (시장 ETF)** + **Satellite (개별주)** + **Cash** 비중을 목표 대비 추적. "
    "장기·적립식 투자자에게 학술적으로 검증된 표준 전략 (Bogleheads). "
    "현금 비중은 직접 입력합니다 — 증권 계좌 외 보유 현금 포함."
)

ca1, ca2, ca3, ca4 = st.columns(4)
with ca1:
    target_core = st.number_input("🏛️ Core 목표 (%)", min_value=0, max_value=100, value=70, step=5)
with ca2:
    target_satellite = st.number_input("🎯 Satellite 목표 (%)", min_value=0, max_value=100, value=20, step=5)
with ca3:
    target_cash = st.number_input("💵 Cash 목표 (%)", min_value=0, max_value=100, value=10, step=5)
with ca4:
    cash_amount = st.number_input("💵 현재 보유 현금", min_value=0, value=0, step=100_000,
                                  help="MMF, CMA, 단기채권 등 즉시 사용 가능한 현금. 추가매수용 탄약.")

if target_core + target_satellite + target_cash != 100:
    st.warning(f"⚠️ 목표 비중 합계 {target_core + target_satellite + target_cash}% — 100%가 되도록 조정해주세요.")

# 분류 + 요약
core_etfs = load_core_etfs()
core_set = set(core_etfs["ticker"].astype(str))
classified = classify_holdings(view, core_etf_tickers=core_set)
price_map = dict(zip(view["ticker"], view["close"]))
alloc = allocation_summary(classified, price_map, cash_amount=cash_amount)

aa1, aa2, aa3, aa4 = st.columns(4)
aa1.metric("🏛️ Core 비중", f"{alloc['Core_pct']:.1f}%",
           delta=f"{alloc['Core_pct'] - target_core:+.1f}pp (목표 {target_core}%)",
           delta_color="off")
aa2.metric("🎯 Satellite 비중", f"{alloc['Satellite_pct']:.1f}%",
           delta=f"{alloc['Satellite_pct'] - target_satellite:+.1f}pp (목표 {target_satellite}%)",
           delta_color="off")
aa3.metric("💵 Cash 비중", f"{alloc['Cash_pct']:.1f}%",
           delta=f"{alloc['Cash_pct'] - target_cash:+.1f}pp (목표 {target_cash}%)",
           delta_color="off")
aa4.metric("💼 총 자산", f"{alloc['Total']:,.0f}",
           delta=f"Core {alloc['Core_value']:,.0f} · Sat {alloc['Satellite_value']:,.0f}",
           delta_color="off")

# 리밸런싱 액션
actions = rebalancing_actions(alloc, target_core, target_satellite, target_cash, threshold_pp=5.0)
if actions:
    st.markdown("##### ⚖️ 리밸런싱 권장 액션 (±5%p 초과)")
    action_df = pd.DataFrame(actions)
    action_df.columns = ["버킷", "현재%", "목표%", "편차pp", "액션", "금액"]
    st.dataframe(
        action_df, hide_index=True, use_container_width=True,
        column_config={
            "현재%": st.column_config.NumberColumn(format="%.1f"),
            "목표%": st.column_config.NumberColumn(format="%.1f"),
            "편차pp": st.column_config.NumberColumn(format="%+.1f"),
            "금액": st.column_config.NumberColumn(format="%,.0f"),
        },
    )
    st.caption("💡 학술적 알파: 단순 리밸런싱만으로 연 0.5~1% 추가 수익 (Vanguard 30년 연구).")
else:
    st.success("✅ 목표 배분에 ±5%p 이내. 리밸런싱 불필요.")

# Core ETF 후보 보기 (펼치기)
with st.expander("🏛️ Core ETF 후보 목록 보기 (16종)"):
    st.dataframe(
        core_etfs[["ticker", "name", "category", "asset_class", "expense_ratio", "currency", "notes"]],
        hide_index=True, use_container_width=True,
        column_config={
            "expense_ratio": st.column_config.NumberColumn("운용보수(%)", format="%.2f"),
        },
    )

# =====================================================================
# 🎯 분할매수 트리거 알림
# =====================================================================
st.divider()
st.subheader("🎯 분할매수 트리거 알림")
st.caption(
    "보유 종목 중 매수가 대비 -5% / -10% / -15% / -20% 하락 도달한 종목. "
    "**점수가 양수면 분할 추가매수 기회**, 음수면 펀더 변화 검토 신호."
)

score_map = dict(zip(scores_df["ticker"], scores_df["composite"])) if not scores_df.empty else {}
triggers = add_on_buy_triggers(view, current_price_map=price_map, score_map=score_map,
                                thresholds=(-5, -10, -15, -20))

if triggers.empty:
    st.info("📭 분할매수 트리거 도달 종목 없음. 모든 보유 종목이 매수가 대비 -5% 이내.")
else:
    triggers_disp = triggers.copy()
    triggers_disp["종목명"] = triggers_disp["ticker"].map(NAMES).fillna("-")
    triggers_disp = triggers_disp[["ticker", "종목명", "buy_price", "current_price",
                                   "drop_pct", "trigger", "score", "verdict"]].rename(
        columns={"ticker": "티커", "buy_price": "매수가", "current_price": "현재가",
                 "drop_pct": "하락률(%)", "trigger": "도달선", "score": "QVGM",
                 "verdict": "판정"}
    )
    st.dataframe(
        triggers_disp, hide_index=True, use_container_width=True,
        column_config={
            "매수가": st.column_config.NumberColumn(format="%,.2f"),
            "현재가": st.column_config.NumberColumn(format="%,.2f"),
            "하락률(%)": st.column_config.NumberColumn(format="%+.2f"),
            "도달선": st.column_config.NumberColumn(format="%d%%"),
            "QVGM": st.column_config.NumberColumn(format="%+.2f"),
        },
    )
    st.caption(
        "**룰**: 점수 ≥ +0.5 → 💎 추가매수 기회 / 0 ~ +0.5 → 🔵 분할매수 검토 / "
        "-0.5 ~ 0 → 🟠 신중 / ≤ -0.5 → 🔴 손절 검토."
    )

# =====================================================================
# 📈 DCA (월 적립식) 시뮬레이터
# =====================================================================
st.divider()
st.subheader("📈 DCA 시뮬레이터 — 월 적립식 자산 분포")
st.caption(
    "매월 일정 금액을 N년 매수했을 때 미래 자산 분포 (몬테카를로 2,000회). "
    "**월급근로자에게 자연적인 전략** — 시장 타이밍 고민 불필요. "
    "정규분포 가정이라 fat-tail 미반영 → 실제 p5는 더 낮을 수 있음."
)

ds1, ds2, ds3, ds4 = st.columns(4)
with ds1:
    dca_monthly = st.number_input("월 투자금", min_value=0, value=1_000_000,
                                  step=100_000, help="매월 일정한 금액으로 매수")
with ds2:
    dca_years = st.slider("기간 (년)", min_value=3, max_value=40, value=20)
with ds3:
    dca_return = st.slider("기대 연수익률 (%)", min_value=1, max_value=15, value=8,
                           help="S&P 500 장기 평균 약 8~10%. 채권 혼합 시 6~7%.")
with ds4:
    dca_vol = st.slider("연환산 변동성 (%)", min_value=5, max_value=40, value=18,
                        help="S&P 500 약 15~20%. 100% 주식 = 18~22%, 60/40 = 12~14%.")

if dca_monthly > 0:
    sim = dca_simulate(dca_monthly, dca_years,
                       expected_annual_return=dca_return/100,
                       annual_vol=dca_vol/100, n_sims=2000)

    sm1, sm2, sm3, sm4 = st.columns(4)
    sm1.metric("💰 총 투자 원금", f"{sim['total_invested']:,.0f}")
    sm2.metric("📊 예상 자산 (중앙값)", f"{sim['p50']:,.0f}",
               delta=f"회수배수 {sim['p50']/sim['total_invested']:.2f}x" if sim['total_invested'] > 0 else "—",
               delta_color="off")
    sm3.metric("🟢 운 좋을 때 (상위 25%)", f"{sim['p75']:,.0f}",
               delta=f"{sim['p75']/sim['total_invested']:.2f}x" if sim['total_invested'] > 0 else "—",
               delta_color="off")
    sm4.metric("🔴 운 나쁠 때 (하위 5%)", f"{sim['p5']:,.0f}",
               delta=f"{sim['p5']/sim['total_invested']:.2f}x" if sim['total_invested'] > 0 else "—",
               delta_color="off")

    if sim["loss_prob"] > 0.001:
        st.warning(f"⚠️ 원금 손실 확률 (시뮬레이션 기준): {sim['loss_prob']*100:.1f}%. "
                   f"기간이 짧을수록, 변동성이 클수록 증가.")
    else:
        st.success(f"✅ {dca_years}년 보유 시 시뮬레이션 원금 손실 확률 < 0.1%")

    # 경로 차트
    path = dca_path(dca_monthly, dca_years,
                    expected_annual_return=dca_return/100,
                    annual_vol=dca_vol/100, n_sims=500)
    fig_dca = go.Figure()
    fig_dca.add_trace(go.Scatter(
        x=path["months"]/12, y=path["p95_path"],
        mode="lines", line=dict(width=0), showlegend=False))
    fig_dca.add_trace(go.Scatter(
        x=path["months"]/12, y=path["p5_path"],
        mode="lines", line=dict(width=0), fill="tonexty",
        fillcolor="rgba(76, 175, 80, 0.2)",
        name="5~95% 구간"))
    fig_dca.add_trace(go.Scatter(
        x=path["months"]/12, y=path["p50_path"],
        mode="lines", line=dict(color="#4CAF50", width=3),
        name="중앙값 (50%)"))
    fig_dca.add_trace(go.Scatter(
        x=path["months"]/12, y=path["invested_path"],
        mode="lines", line=dict(color="#888", dash="dash", width=2),
        name="누적 원금"))
    fig_dca.update_layout(
        xaxis_title="년", yaxis_title="자산",
        height=380, margin=dict(t=20, b=10, l=10, r=10),
        legend=dict(orientation="h", yanchor="bottom", y=1.02),
    )
    st.plotly_chart(fig_dca, use_container_width=True)

    with st.expander("ℹ️ DCA 시뮬레이션 해석"):
        st.markdown(
            f"- **총 원금 {sim['total_invested']:,.0f}** 을 {dca_years}년간 매월 적립\n"
            f"- **중앙값 시나리오**: 약 **{sim['p50']:,.0f}** 으로 성장\n"
            f"- **운 좋을 때 (상위 25%)**: 약 **{sim['p75']:,.0f}**\n"
            f"- **운 나쁠 때 (하위 5%)**: 약 **{sim['p5']:,.0f}**\n"
            f"- **회수배수 평균**: {sim['return_multiple_mean']:.2f}배\n\n"
            "💡 **DCA의 가치**:\n"
            "1. 시장 타이밍 고민 불필요 — 월급일에 자동 매수\n"
            "2. 가격 하락 시 더 많은 주식 매수 — 변동성이 친구\n"
            "3. 정점 매수 회피 — FOMO 행동 자동 방어\n"
            "4. 평균적으로 lump-sum이 ~2%pa 유리하지만, 심리 안정성은 DCA 우위\n\n"
            "⚠️ **한계**: 정규분포 가정. 실제 시장은 fat-tail이라 극단 시나리오는 더 나쁠 수 있음. "
            "또 과거 평균 수익률이 미래에도 유지된다는 보장 없음 (mean-reversion 위험)."
        )

# =====================================================================
# 🎯 추천 분산 포트폴리오 — 점수×변동성 기반 자본 배분 (실험적)
# =====================================================================
st.divider()
st.subheader("🎯 추천 분산 포트폴리오 (실험적)")
st.caption(
    "QVGM 점수와 변동성을 결합해 **상위 종목에 분산 매수 비중**을 자동 계산합니다. "
    "**투자 추천이 아니라** 자본 배분 시뮬레이션. 1회성 매수 시점 기준, 리밸런싱/세금/수수료 미반영."
)

if scores_df.empty or summary.empty:
    st.info("분석 결과(summary_signals.csv)가 없어 추천 포트폴리오를 만들 수 없습니다.")
else:
    pool = scores_df.merge(
        summary[["ticker", "close"]], on="ticker", how="left"
    ).merge(
        funda[["ticker", "sector", "currency"]] if "sector" in funda.columns and "currency" in funda.columns else funda[["ticker"]],
        on="ticker", how="left",
    ).merge(
        score_input[["ticker", "ann_vol"]] if "ann_vol" in score_input.columns else score_input[["ticker"]],
        on="ticker", how="left",
    )

    # 타이밍 라벨 (과열/조정 매수 기회) — 일반인 친화적 한국어
    def _timing(row):
        oh = row.get("overheat_penalty", 0) or 0
        mr = row.get("mean_reversion_bonus", 0) or 0
        me = row.get("multi_exp_penalty", 0) or 0
        if oh <= -0.4: return "🔴 너무 올라 위험"
        if mr >= 0.30: return "💎 떨어진 우량주"
        if mr >= 0.15: return "💚 매수 검토"
        if me <= -0.30: return "⚠️ 가격이 실적보다 빨리 오름"
        if oh <= -0.20: return "🟠 살짝 비쌈"
        return ""
    if "overheat_penalty" in pool.columns:
        pool["타이밍"] = pool.apply(_timing, axis=1)
    else:
        pool["타이밍"] = ""

    col1, col2, col3 = st.columns([1, 1, 1])
    with col1:
        market = st.selectbox("시장/통화", ["KRW (한국)", "USD (미국)", "전체"], index=0,
                              help="한·미 혼합은 환율 이슈가 있어 분리 권장")
    with col2:
        capital_default = 10_000_000 if market.startswith("KRW") else (10_000 if market.startswith("USD") else 1_000_000)
        capital_step = 100_000 if market.startswith("KRW") else 100
        capital = st.number_input("총 투자 금액", min_value=0, value=capital_default,
                                  step=capital_step, help="단위는 선택한 통화")
    with col3:
        top_n = st.slider("종목 수 (Top N)", min_value=3, max_value=20, value=10)

    col4, col5, col6, col7 = st.columns([1, 1, 1, 1])
    with col4:
        method = st.selectbox(
            "가중 방식",
            ["score_x_invvol", "score", "inv_vol", "equal"],
            index=0,
            help=("score_x_invvol: 점수↑ × 변동성↓ (추천 / AQR 표준 결합) | "
                  "score: 점수만 가중 (대박 종목에 집중) | "
                  "inv_vol: 1/변동성 (위험 균등) | "
                  "equal: 1/N (단순 균등 — DeMiguel 2009 의외로 강함)"),
        )
    with col5:
        sector_cap_pct = st.slider("단일 섹터 최대 비중 (%)", min_value=20, max_value=100,
                                   value=35, step=5,
                                   help="한 섹터로 쏠림 방지. 100%면 미적용")
    with col6:
        min_score = st.number_input("최소 점수 (이 미만 제외)", value=0.0, step=0.1,
                                    help="0 이상이면 z-score 양수만 후보")
    with col7:
        exclude_overheat = st.checkbox("🔴 과열 종목 제외", value=False,
                                       help="overheat_penalty ≤ -0.4 또는 멀티플 확장 위험 종목을 후보에서 제외")

    # 통화 필터
    if "currency" in pool.columns:
        if market.startswith("KRW"):
            pool_f = pool[pool["currency"] == "KRW"].copy()
        elif market.startswith("USD"):
            pool_f = pool[pool["currency"] == "USD"].copy()
        else:
            pool_f = pool.copy()
    else:
        pool_f = pool.copy()

    # 과열 종목 제외 (체크박스)
    if exclude_overheat and "overheat_penalty" in pool_f.columns:
        before_n = len(pool_f)
        pool_f = pool_f[(pool_f["overheat_penalty"] > -0.4) &
                        (pool_f.get("multi_exp_penalty", 0).fillna(0) > -0.3)]
        removed = before_n - len(pool_f)
        if removed > 0:
            st.info(f"🔴 과열/멀티플 확장 종목 {removed}개 제외됨")

    sec_cap = None if sector_cap_pct >= 100 else sector_cap_pct / 100.0

    if pool_f.empty:
        st.warning("선택한 통화에 후보 종목이 없습니다.")
    else:
        try:
            result = build_portfolio(
                pool_f, capital=capital, top_n=top_n,
                method=method, sector_cap=sec_cap, min_score=min_score,
            )
        except Exception as e:
            st.error(f"포트폴리오 생성 실패: {e}")
            result = None

        if result and not result["portfolio"].empty:
            p = result["portfolio"].copy()
            p["종목명"] = p["ticker"].map(NAMES).fillna("-")

            invested = float(p["actual_amount"].sum())
            cash = result["cash_left"]
            cash_pct = cash / capital * 100 if capital > 0 else 0

            m1, m2, m3, m4 = st.columns(4)
            m1.metric("선정 종목 수", f"{len(p)}")
            m2.metric("실제 매수 금액", f"{invested:,.0f}", delta=f"{invested/capital*100:.1f}% 사용")
            m3.metric("잔여 현금", f"{cash:,.0f}", delta=f"{cash_pct:+.1f}%", delta_color="off")
            m4.metric("최대 비중 종목", f"{p['weight_pct'].max():.1f}%")

            st.markdown("##### 종목별 배분")
            # 타이밍 라벨 머지
            p = p.merge(pool_f[["ticker", "타이밍"]], on="ticker", how="left")
            disp = p[["ticker", "종목명", "sector", "타이밍", "score", "weight_pct",
                      "price", "shares", "actual_amount", "target_amount"]].rename(
                columns={"ticker": "티커", "sector": "섹터", "score": "점수",
                         "weight_pct": "비중%", "price": "현재가",
                         "shares": "매수수량", "actual_amount": "실제금액",
                         "target_amount": "목표금액"}
            )
            st.dataframe(
                disp, hide_index=True, use_container_width=True,
                column_config={
                    "점수": st.column_config.NumberColumn(format="%+.2f"),
                    "비중%": st.column_config.NumberColumn(format="%.2f"),
                    "현재가": st.column_config.NumberColumn(format="%,.2f"),
                    "매수수량": st.column_config.NumberColumn(format="%d"),
                    "실제금액": st.column_config.NumberColumn(format="%,.0f"),
                    "목표금액": st.column_config.NumberColumn(format="%,.0f"),
                },
            )

            if not result["sector_breakdown"].empty:
                st.markdown("##### 섹터 분포")
                sb = result["sector_breakdown"]
                fig2 = go.Figure(go.Pie(
                    labels=sb["sector"], values=sb["weight_pct"], hole=0.45,
                ))
                fig2.update_layout(height=320, margin=dict(t=10, b=10, l=10, r=10))
                st.plotly_chart(fig2, use_container_width=True)

            with st.expander("ℹ️ 이 추천을 어떻게 해석할까?"):
                st.markdown(
                    "- **점수**: QVGM v3 (z-score 결합 + 턴어라운드 보너스). 양수면 모집단 평균 위.\n"
                    "- **비중%**: 자본을 종목 사이에 어떻게 나눌지 비율. 가중 방식에 따라 다름.\n"
                    "- **매수수량**: 현재가 기준 1주 단위 매수 가능한 수량. 소수주식 미지원 가정.\n"
                    "- **잔여 현금**: 1주 단위로 매수하고 남는 돈. 비싼 종목이 많으면 커짐.\n"
                    "- **한계**:\n"
                    "  1. 점수는 *현재 시점 스냅샷* — 시장 상황 변하면 빠르게 갱신 필요\n"
                    "  2. 변동성은 최근 3개월 일별. 단기적으로 변할 수 있음\n"
                    "  3. N=40여 종목으로 만든 모델이라 통계적 신뢰도 제한적\n"
                    "  4. 후행적 검증(현재 점수로 과거 수익률 추산)이라 진정한 백테스트는 아님\n"
                    "\n이 분석은 투자 판단을 돕기 위한 의사결정 보조 자료이며, "
                    "최종 매수·매도 결정은 공식 공시, 최신 실적, 본인의 투자 기간과 "
                    "위험 감내 범위를 확인한 뒤 내려야 합니다."
                )
        elif result:
            st.warning(result.get("meta", {}).get("error", "포트폴리오를 만들 후보가 부족합니다."))
