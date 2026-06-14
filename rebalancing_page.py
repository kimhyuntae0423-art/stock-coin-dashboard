"""리밸런싱 페이지 — Core-Satellite 자산배분 + DCA 시뮬레이터 + 추천 포트폴리오."""
import streamlit as st
import pandas as pd
import plotly.graph_objects as go
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parent
sys.path.append(str(ROOT))
from scripts.stock_score import rank_stocks
from scripts.factor_calc import enrich_price_factors
from scripts.asset_allocation import (
    load_core_etfs, classify_holdings, allocation_summary,
    rebalancing_actions,
)
from scripts.dca_simulator import dca_simulate, dca_path
from scripts.portfolio_builder import build_portfolio

RESULTS = ROOT / "results"
HOLDINGS_FILE = ROOT / "holdings.csv"
NAMES_FILE = ROOT / "names.csv"
COIN_NAMES_FILE = ROOT / "coin_names.csv"


def _load_names() -> dict:
    names: dict = {}
    for path in (NAMES_FILE, COIN_NAMES_FILE):
        if path.exists():
            df = pd.read_csv(path)
            names.update(dict(zip(df["ticker"], df["name"])))
    return names


def _load_holdings() -> pd.DataFrame:
    empty = pd.DataFrame({
        "ticker": pd.Series(dtype="str"),
        "qty": pd.Series(dtype="float64"),
        "buy_price": pd.Series(dtype="float64"),
        "buy_date": pd.Series(dtype="str"),
        "notes": pd.Series(dtype="str"),
        "person": pd.Series(dtype="str"),
    })
    if not HOLDINGS_FILE.exists() or HOLDINGS_FILE.stat().st_size < 10:
        return empty
    df = pd.read_csv(HOLDINGS_FILE)
    for col in ["qty", "buy_price"]:
        if col in df.columns:
            df[col] = pd.to_numeric(df[col], errors="coerce").fillna(0.0)
    if "person" not in df.columns:
        df["person"] = ""
    df["person"] = df["person"].fillna("")
    return df


NAMES = _load_names()

# =====================================================================
# 공통 데이터 로드
# =====================================================================
st.title("⚖️ 리밸런싱")
st.caption("Core-Satellite 자산배분 추적 · DCA 시뮬레이터 · 추천 분산 포트폴리오.")

holdings = _load_holdings()

all_persons = sorted([p for p in holdings["person"].unique() if p and str(p).strip()])
selected_person = st.selectbox(
    "👤 계산 대상",
    options=["전체"] + all_persons,
    index=0,
    key="rebal_person_filter",
)
if selected_person != "전체":
    holdings = holdings[holdings["person"] == selected_person].copy()

summary_file = RESULTS / "summary_signals.csv"
funda_file = RESULTS / "fundamentals.csv"
summary = pd.read_csv(summary_file) if summary_file.exists() else pd.DataFrame()
funda = pd.read_csv(funda_file) if funda_file.exists() else pd.DataFrame(columns=["ticker"])

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
    score_input = pd.DataFrame()
    scores_df = pd.DataFrame(columns=["ticker", "composite"])

# ── Core-Satellite 자산 배분 추적기 ─────────────────────────────
st.subheader("🏛️ Core-Satellite 자산 배분 추적")
st.caption(
    "**Core (시장 ETF)** + **Satellite (개별주)** + **Cash** 비중을 목표 대비 추적. "
    "현금 비중은 직접 입력합니다."
)

view_alloc = holdings.copy()
if not summary.empty:
    view_alloc = view_alloc.merge(
        summary[["ticker", "close"]], on="ticker", how="left"
    )
else:
    view_alloc["close"] = None

ca1, ca2, ca3, ca4 = st.columns(4)
with ca1:
    target_core = st.number_input("🏛️ Core 목표 (%)", min_value=0, max_value=100, value=70, step=5)
with ca2:
    target_satellite = st.number_input("🎯 Satellite 목표 (%)", min_value=0, max_value=100, value=20, step=5)
with ca3:
    target_cash = st.number_input("💵 Cash 목표 (%)", min_value=0, max_value=100, value=10, step=5)
with ca4:
    cash_amount = st.number_input("💵 현재 보유 현금", min_value=0, value=0, step=100_000,
                                  help="MMF, CMA 등 즉시 사용 가능한 현금.")

if target_core + target_satellite + target_cash != 100:
    st.warning(f"⚠️ 목표 비중 합계 {target_core + target_satellite + target_cash}% — 100%가 되도록 조정해주세요.")

core_etfs = load_core_etfs()
core_set = set(core_etfs["ticker"].astype(str))
price_map_alloc = dict(zip(view_alloc["ticker"], view_alloc["close"]))
classified = classify_holdings(view_alloc, core_etf_tickers=core_set)
alloc = allocation_summary(classified, price_map_alloc, cash_amount=cash_amount)

aa1, aa2, aa3, aa4 = st.columns(4)
aa1.metric("🏛️ Core 비중", f"{alloc['Core_pct']:.1f}%",
           delta=f"{alloc['Core_pct'] - target_core:+.1f}pp (목표 {target_core}%)", delta_color="off")
aa2.metric("🎯 Satellite 비중", f"{alloc['Satellite_pct']:.1f}%",
           delta=f"{alloc['Satellite_pct'] - target_satellite:+.1f}pp (목표 {target_satellite}%)", delta_color="off")
aa3.metric("💵 Cash 비중", f"{alloc['Cash_pct']:.1f}%",
           delta=f"{alloc['Cash_pct'] - target_cash:+.1f}pp (목표 {target_cash}%)", delta_color="off")
aa4.metric("💼 총 자산", f"{alloc['Total']:,.0f}",
           delta=f"Core {alloc['Core_value']:,.0f} · Sat {alloc['Satellite_value']:,.0f}", delta_color="off")

actions_alloc = rebalancing_actions(alloc, target_core, target_satellite, target_cash, threshold_pp=5.0)
if actions_alloc:
    st.markdown("##### ⚖️ 리밸런싱 권장 액션 (±5%p 초과)")
    action_df = pd.DataFrame(actions_alloc)
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
    st.caption("💡 단순 리밸런싱만으로 연 0.5~1% 추가 수익 (Vanguard 30년 연구).")
else:
    st.success("✅ 목표 배분에 ±5%p 이내. 리밸런싱 불필요.")

with st.expander("🏛️ Core ETF 후보 목록 보기"):
    st.dataframe(
        core_etfs[["ticker", "name", "category", "asset_class", "expense_ratio", "currency", "notes"]],
        hide_index=True, use_container_width=True,
        column_config={"expense_ratio": st.column_config.NumberColumn("운용보수(%)", format="%.2f")},
    )

st.divider()

# ── 신규자금 리밸런싱 계획 ────────────────────────────────────────
st.subheader("💰 신규자금으로 리밸런싱")
st.caption(
    "현재 보유 포트폴리오 + 신규 투자금을 합산해, 목표 배분에 가장 빠르게 근접하는 "
    "**매수 전용** 계획입니다. 기존 종목은 그대로 유지합니다."
)

new_money = st.number_input("추가 투자할 금액", min_value=0, value=1_000_000, step=100_000, key="new_money_input")

if new_money > 0 and alloc["Total"] > 0:
    total_after = alloc["Total"] + new_money

    core_deficit  = max(0.0, total_after * target_core       / 100 - alloc["Core_value"])
    sat_deficit   = max(0.0, total_after * target_satellite  / 100 - alloc["Satellite_value"])
    cash_deficit  = max(0.0, total_after * target_cash       / 100 - cash_amount)

    total_deficit = core_deficit + sat_deficit + cash_deficit
    if total_deficit > 0:
        scale    = min(1.0, new_money / total_deficit)
        core_buy = round(core_deficit * scale)
        sat_buy  = round(sat_deficit  * scale)
        cash_res = new_money - core_buy - sat_buy
    else:
        core_buy = sat_buy = 0
        cash_res = new_money

    mc1, mc2, mc3 = st.columns(3)
    mc1.metric("🏛️ Core 매수", f"{core_buy:,.0f}")
    mc2.metric("🎯 Satellite 매수", f"{sat_buy:,.0f}")
    mc3.metric("💵 현금 유보", f"{cash_res:,.0f}")

    new_core_pct = (alloc["Core_value"] + core_buy) / total_after * 100
    new_sat_pct  = (alloc["Satellite_value"] + sat_buy) / total_after * 100
    new_cash_pct = (cash_amount + cash_res) / total_after * 100
    st.caption(
        f"매수 후 예상 배분: Core **{new_core_pct:.1f}%** / Satellite **{new_sat_pct:.1f}%** / Cash **{new_cash_pct:.1f}%** "
        f"(목표: {target_core}% / {target_satellite}% / {target_cash}%)"
    )

    # Core 매수 후보
    if core_buy > 0:
        st.markdown("##### 🏛️ Core ETF 매수 후보")
        _core_show = core_etfs.copy()
        _price_map_c = dict(zip(summary["ticker"].astype(str).str.upper(), summary["close"])) if not summary.empty else {}
        _core_show["현재가"] = _core_show["ticker"].astype(str).str.upper().map(_price_map_c)
        _core_show = _core_show[_core_show["현재가"].notna()].copy()  # 현재가 없으면 제외
        if not _core_show.empty:
            _core_show["균등배분"] = round(core_buy / len(_core_show))
            _core_show["수량(균등)"] = (_core_show["균등배분"] / _core_show["현재가"]).apply(
                lambda x: int(x) if pd.notna(x) and x > 0 else 0
            )
            st.dataframe(
                _core_show[["ticker", "name", "category", "expense_ratio", "currency", "현재가", "균등배분", "수량(균등)"]],
                hide_index=True, use_container_width=True,
                column_config={
                    "expense_ratio": st.column_config.NumberColumn("운용보수(%)", format="%.2f"),
                    "현재가": st.column_config.NumberColumn(format="%,.0f"),
                    "균등배분": st.column_config.NumberColumn(format="%,.0f"),
                },
            )
        else:
            st.info("분석 데이터(summary_signals.csv)에 Core ETF 현재가 없음. GitHub Actions 갱신 후 확인하세요.")

    # Satellite 매수 후보
    if sat_buy > 0:
        st.markdown("##### 🎯 Satellite 매수 후보")
        _STOCK_THRESHOLD = 1.0  # QVGM ≥ +1.0 (상위 ~16%) 일 때만 개별주 추천

        _sat_stocks = pd.DataFrame()
        if not scores_df.empty:
            _sat_pool = scores_df.copy()
            if not summary.empty:
                _sat_pool = _sat_pool.merge(summary[["ticker", "close"]], on="ticker", how="left")
            _sat_stocks = _sat_pool[_sat_pool["composite"] >= _STOCK_THRESHOLD].head(10).copy()

        if not _sat_stocks.empty:
            st.caption(f"QVGM ≥ +{_STOCK_THRESHOLD} 개별주가 있어 개별주를 추천합니다.")
            _sat_stocks["종목명"] = _sat_stocks["ticker"].map(NAMES).fillna("-")
            n_sat = max(len(_sat_stocks), 1)
            _sat_stocks["균등배분"] = round(sat_buy / n_sat)
            st.dataframe(
                _sat_stocks[["ticker", "종목명", "composite", "균등배분"]].rename(
                    columns={"ticker": "티커", "composite": "QVGM점수", "균등배분": "배분금액"}
                ),
                hide_index=True, use_container_width=True,
                column_config={
                    "QVGM점수": st.column_config.NumberColumn(format="%+.2f"),
                    "배분금액": st.column_config.NumberColumn(format="%,.0f"),
                },
            )
        else:
            st.caption(f"QVGM +{_STOCK_THRESHOLD} 이상 개별주 없음 → 섹터/테마 ETF를 추천합니다.")
            _sector_etfs = core_etfs[
                core_etfs["category"].str.contains("섹터|테마", na=False)
            ].copy()
            if not summary.empty:
                _pm = dict(zip(summary["ticker"].astype(str).str.upper(), summary["close"]))
                _sector_etfs["현재가"] = _sector_etfs["ticker"].astype(str).str.upper().map(_pm)
            if not _sector_etfs.empty:
                n_etf = max(len(_sector_etfs), 1)
                _sector_etfs["균등배분"] = round(sat_buy / n_etf)
                st.dataframe(
                    _sector_etfs[["ticker", "name", "category", "expense_ratio", "currency", "균등배분"]],
                    hide_index=True, use_container_width=True,
                    column_config={
                        "expense_ratio": st.column_config.NumberColumn("운용보수(%)", format="%.2f"),
                        "균등배분": st.column_config.NumberColumn(format="%,.0f"),
                    },
                )
            else:
                st.info("섹터/테마 ETF 데이터 없음. core_etfs.csv를 확인하세요.")
elif new_money > 0:
    st.info("현재 보유 포트폴리오가 없습니다. 보유종목 페이지에서 먼저 종목을 추가하세요.")

st.divider()

# ── DCA 시뮬레이터 ───────────────────────────────────────────────
st.subheader("📈 DCA 시뮬레이터 — 월 적립식 자산 분포")
st.caption(
    "매월 일정 금액을 N년 매수했을 때 미래 자산 분포 (몬테카를로 2,000회). "
    "정규분포 가정이라 fat-tail 미반영."
)

ds1, ds2, ds3, ds4 = st.columns(4)
with ds1:
    dca_monthly = st.number_input("월 투자금", min_value=0, value=1_000_000, step=100_000)
with ds2:
    dca_years = st.slider("기간 (년)", min_value=3, max_value=40, value=20)
with ds3:
    dca_return = st.slider("기대 연수익률 (%)", min_value=1, max_value=15, value=8)
with ds4:
    dca_vol = st.slider("연환산 변동성 (%)", min_value=5, max_value=40, value=18)

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
        st.warning(f"⚠️ 원금 손실 확률: {sim['loss_prob']*100:.1f}%")
    else:
        st.success(f"✅ {dca_years}년 보유 시 원금 손실 확률 < 0.1%")

    path = dca_path(dca_monthly, dca_years,
                    expected_annual_return=dca_return/100,
                    annual_vol=dca_vol/100, n_sims=500)
    fig_dca = go.Figure()
    fig_dca.add_trace(go.Scatter(x=path["months"]/12, y=path["p95_path"],
                                 mode="lines", line=dict(width=0), showlegend=False))
    fig_dca.add_trace(go.Scatter(x=path["months"]/12, y=path["p5_path"],
                                 mode="lines", line=dict(width=0), fill="tonexty",
                                 fillcolor="rgba(76,175,80,0.2)", name="5~95% 구간"))
    fig_dca.add_trace(go.Scatter(x=path["months"]/12, y=path["p50_path"],
                                 mode="lines", line=dict(color="#4CAF50", width=3), name="중앙값"))
    fig_dca.add_trace(go.Scatter(x=path["months"]/12, y=path["invested_path"],
                                 mode="lines", line=dict(color="#888", dash="dash", width=2), name="누적 원금"))
    fig_dca.update_layout(xaxis_title="년", yaxis_title="자산", height=380,
                           margin=dict(t=20, b=10, l=10, r=10),
                           legend=dict(orientation="h", yanchor="bottom", y=1.02))
    st.plotly_chart(fig_dca, use_container_width=True)

st.divider()

# ── 추천 분산 포트폴리오 ─────────────────────────────────────────
st.subheader("🎯 신규 자금 배분 시뮬레이터 (실험적)")
st.caption(
    "**현재 보유종목과 무관한 독립 시뮬레이션입니다.** "
    "\"만약 X원을 새로 투자한다면?\" 에 대한 QVGM 기반 가중 배분 계산. "
    "ETF는 PER/ROE 데이터가 없어 QVGM 점수≈0이므로, ETF를 포함하려면 가중 방식을 `inv_vol` 또는 `equal`로 변경하세요."
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

    # ETF는 fundamentals.csv에 없으므로 core_etfs.csv에서 currency/sector 보완
    _etf_meta = core_etfs[["ticker", "currency", "category"]].copy()
    _etf_meta["ticker"] = _etf_meta["ticker"].astype(str).str.strip().str.upper()
    _etf_meta = _etf_meta.rename(columns={"currency": "_etf_cur", "category": "_etf_sec"})
    pool["ticker"] = pool["ticker"].astype(str).str.strip().str.upper()
    pool = pool.merge(_etf_meta, on="ticker", how="left")
    if "currency" not in pool.columns:
        pool["currency"] = None
    if "sector" not in pool.columns:
        pool["sector"] = None
    pool["currency"] = pool["currency"].combine_first(pool["_etf_cur"])
    pool["sector"] = pool["sector"].combine_first(pool["_etf_sec"])
    pool.drop(columns=["_etf_cur", "_etf_sec"], inplace=True, errors="ignore")

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
    pool["타이밍"] = pool.apply(_timing, axis=1) if "overheat_penalty" in pool.columns else ""

    col1, col2, col3 = st.columns(3)
    with col1:
        market = st.selectbox("시장/통화", ["KRW (한국)", "USD (미국)", "전체"], index=0)
    with col2:
        capital_default = 10_000_000 if market.startswith("KRW") else (10_000 if market.startswith("USD") else 1_000_000)
        capital_step = 100_000 if market.startswith("KRW") else 100
        capital = st.number_input("총 투자 금액", min_value=0, value=capital_default, step=capital_step)
    with col3:
        top_n = st.slider("종목 수 (Top N)", min_value=3, max_value=20, value=10)

    col4, col5, col6, col7 = st.columns(4)
    with col4:
        method = st.selectbox("가중 방식", ["score_x_invvol", "score", "inv_vol", "equal"], index=0)
    with col5:
        sector_cap_pct = st.slider("단일 섹터 최대 비중 (%)", min_value=20, max_value=100, value=35, step=5)
    with col6:
        min_score = st.number_input("최소 점수 (이 미만 제외)", value=0.0, step=0.1)
    with col7:
        exclude_overheat = st.checkbox("🔴 과열 종목 제외", value=False)

    if "currency" in pool.columns:
        if market.startswith("KRW"):
            pool_f = pool[pool["currency"] == "KRW"].copy()
        elif market.startswith("USD"):
            pool_f = pool[pool["currency"] == "USD"].copy()
        else:
            pool_f = pool.copy()
    else:
        pool_f = pool.copy()

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
            result = build_portfolio(pool_f, capital=capital, top_n=top_n,
                                     method=method, sector_cap=sec_cap, min_score=min_score)
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

            p = p.merge(pool_f[["ticker", "타이밍"]], on="ticker", how="left")
            disp = p[["ticker", "종목명", "sector", "타이밍", "score", "weight_pct",
                       "price", "shares", "actual_amount", "target_amount"]].rename(
                columns={"ticker": "티커", "sector": "섹터", "score": "점수",
                         "weight_pct": "비중%", "price": "현재가",
                         "shares": "매수수량", "actual_amount": "실제금액", "target_amount": "목표금액"}
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
                sb = result["sector_breakdown"]
                fig2 = go.Figure(go.Pie(labels=sb["sector"], values=sb["weight_pct"], hole=0.45))
                fig2.update_layout(height=320, margin=dict(t=10, b=10, l=10, r=10))
                st.plotly_chart(fig2, use_container_width=True)

        elif result:
            st.warning(result.get("meta", {}).get("error", "포트폴리오를 만들 후보가 부족합니다."))

    st.caption(
        "이 분석은 투자 판단을 돕기 위한 의사결정 보조 자료이며, "
        "최종 매수·매도 결정은 공식 공시, 최신 실적, 본인의 투자 기간과 "
        "위험 감내 범위를 확인한 뒤 내려야 합니다."
    )
