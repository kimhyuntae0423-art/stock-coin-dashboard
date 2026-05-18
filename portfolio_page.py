"""포트폴리오 페이지 — 보유 종목 + 매수가 추적 + 매도 신호 알림."""
import streamlit as st
import pandas as pd
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parent
sys.path.append(str(ROOT))
from scripts.stock_score import rank_stocks

RESULTS = ROOT / "results"
HOLDINGS_FILE = ROOT / "holdings.csv"
NAMES_FILE = ROOT / "names.csv"
COIN_NAMES_FILE = ROOT / "coin_names.csv"


def load_names() -> dict:
    names: dict = {}
    for path in (NAMES_FILE, COIN_NAMES_FILE):
        if path.exists():
            df = pd.read_csv(path)
            names.update(dict(zip(df["ticker"], df["name"])))
    return names


NAMES = load_names()


def label(t: str) -> str:
    return f"{t} · {NAMES[t]}" if t in NAMES else t


st.title("💼 보유 종목")
st.caption(
    "내가 매수한 종목들. 매수가 대비 현재 수익률과 **매도 신호**를 한눈에. "
    "편집은 두 가지: (1) 로컬에서 `holdings.csv` 직접 수정 후 git push (2) 아래 표에서 즉시 수정 → CSV 다운로드 → 파일 교체."
)

# ===== 데이터 로드 =====
if not HOLDINGS_FILE.exists() or HOLDINGS_FILE.stat().st_size < 50:
    holdings = pd.DataFrame(columns=["ticker", "qty", "buy_price", "buy_date", "notes"])
else:
    holdings = pd.read_csv(HOLDINGS_FILE)

# 분석 결과
summary_file = RESULTS / "summary_signals.csv"
funda_file = RESULTS / "fundamentals.csv"
summary = pd.read_csv(summary_file) if summary_file.exists() else pd.DataFrame()
funda = pd.read_csv(funda_file) if funda_file.exists() else pd.DataFrame(columns=["ticker"])

# QVGM 점수도 같이 계산
if not summary.empty and not funda.empty:
    FUNDA_COLS = ["ticker", "per", "pbr", "roe_pct", "profit_margin_pct",
                  "revenue_growth_yoy_pct", "earnings_growth_yoy_pct"]
    for col in FUNDA_COLS:
        if col not in funda.columns:
            funda[col] = None
    score_input = summary.merge(funda[FUNDA_COLS], on="ticker", how="left")
    scores_df = rank_stocks(score_input)
else:
    scores_df = pd.DataFrame(columns=["ticker", "composite"])


# ===== 편집 가능한 테이블 =====
st.subheader("✏️ 보유 종목 입력 · 편집")
st.caption("표에서 직접 수정 가능. 새 행 추가는 맨 아래 빈 행에 입력 → Enter. 저장은 우상단 '⬇️ CSV 다운로드'.")

edited = st.data_editor(
    holdings,
    num_rows="dynamic",
    use_container_width=True,
    column_config={
        "ticker": st.column_config.TextColumn("티커", help="예: AAPL, 005930.KS, BTC-USD", required=True),
        "qty": st.column_config.NumberColumn("수량", format="%.4f"),
        "buy_price": st.column_config.NumberColumn("매수가", format="%.2f"),
        "buy_date": st.column_config.TextColumn("매수일", help="YYYY-MM-DD"),
        "notes": st.column_config.TextColumn("메모"),
    },
    key="holdings_editor",
)

# 다운로드 (사용자가 git에 commit하기 위함)
csv_bytes = edited.to_csv(index=False).encode("utf-8")
st.download_button(
    "⬇️ CSV 다운로드 (홈 폴더 holdings.csv 교체용)",
    data=csv_bytes,
    file_name="holdings.csv",
    mime="text/csv",
)

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
        columns={"action": "추세", "composite": "QVGM", "last_cross_date": "신호일", "notes": "메모"}
    ),
    use_container_width=True,
    hide_index=True,
    column_config={
        "수량": st.column_config.NumberColumn(format="%.4f"),
        "매수가": st.column_config.NumberColumn(format="%,.2f"),
        "현재가": st.column_config.NumberColumn(format="%,.2f"),
        "수익률(%)": st.column_config.NumberColumn(format="%+.2f"),
        "손익": st.column_config.NumberColumn(format="%+,.0f"),
        "RSI": st.column_config.NumberColumn(format="%.1f"),
        "QVGM": st.column_config.NumberColumn(format="%+.2f"),
    },
)

# ===== 자산 배분 (간단) =====
if total_value > 0:
    st.markdown("#### 자산 배분")
    import plotly.graph_objects as go
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
