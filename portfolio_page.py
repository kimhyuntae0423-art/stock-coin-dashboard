"""포트폴리오 페이지 — 보유 종목 + 매수가 추적 + 매도 신호 알림."""
import base64
import json
import requests
import streamlit as st
import pandas as pd
import plotly.graph_objects as go
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parent
sys.path.append(str(ROOT))
from scripts.stock_score import rank_stocks
from scripts.factor_calc import enrich_price_factors

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
    rows = []
    if CORE_ETF_FILE.exists():
        etf_df = pd.read_csv(CORE_ETF_FILE)
        for _, r in etf_df.iterrows():
            t = str(r["ticker"])
            name = str(r["name"])
            cur = str(r.get("currency", ""))
            tag = "국내 ETF" if cur == "KRW" else "해외 ETF"
            rows.append((f"{name}  ({t}) · {tag}", t))
    if COIN_NAMES_FILE.exists():
        coin_df = pd.read_csv(COIN_NAMES_FILE)
        for _, r in coin_df.iterrows():
            t = str(r["ticker"])
            rows.append((f"{r['name']}  ({t}) · 코인", t))
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

# 종목명 → 티커 역방향 매핑 (테이블 첫 열 자동완성용)
_NAME_TO_TICKER: dict[str, str] = {}
if CORE_ETF_FILE.exists():
    _etf_df = pd.read_csv(CORE_ETF_FILE)
    for _, _r in _etf_df.iterrows():
        _NAME_TO_TICKER[str(_r["name"])] = str(_r["ticker"])
_NAME_TO_TICKER.update({v: k for k, v in NAMES.items()})
_ALL_NAMES = [""] + sorted(_NAME_TO_TICKER.keys())


@st.cache_data(ttl=3600)
def _get_usdkrw() -> float:
    try:
        import yfinance as yf
        rate = yf.Ticker("USDKRW=X").fast_info.get("lastPrice")
        if rate and rate > 100:
            return float(rate)
    except Exception:
        pass
    return 1380.0
ASSET_LABEL_TO_TICKER = {label: ticker for label, ticker in ASSET_OPTIONS}
ASSET_LABELS = [label for label, _ in ASSET_OPTIONS]


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


def _save_holdings(df: pd.DataFrame):
    df.to_csv(HOLDINGS_FILE, index=False, encoding="utf-8")


_GH_REPO = "kimhyuntae0423-art/stock-coin-dashboard"
_GH_FILE = "holdings.csv"


def _push_to_github(df: pd.DataFrame) -> tuple[bool, str]:
    token = st.secrets.get("GITHUB_TOKEN", "")
    if not token:
        return False, "Streamlit secrets에 GITHUB_TOKEN이 없습니다."
    headers = {
        "Authorization": f"token {token}",
        "Accept": "application/vnd.github.v3+json",
    }
    api_url = f"https://api.github.com/repos/{_GH_REPO}/contents/{_GH_FILE}"
    resp = requests.get(api_url, headers=headers)
    if resp.status_code != 200:
        return False, f"GitHub 파일 조회 실패: {resp.status_code}"
    sha = resp.json()["sha"]
    content = df.to_csv(index=False)
    encoded = base64.b64encode(content.encode("utf-8")).decode("utf-8")
    payload = {
        "message": f"update: holdings.csv ({pd.Timestamp.now().strftime('%Y-%m-%d %H:%M')})",
        "content": encoded,
        "sha": sha,
    }
    put_resp = requests.put(api_url, headers=headers, json=payload)
    if put_resp.status_code in (200, 201):
        return True, "GitHub에 저장 완료! 영구 보존됩니다."
    return False, f"GitHub 저장 실패: {put_resp.status_code}"


# =====================================================================
# 공통 데이터 로드
# =====================================================================
st.title("💼 보유 종목")
st.caption("장기 분할매수 포트폴리오 추적. 매수 내역 입력 → 수익률·비중·매도신호 자동 계산.")

holdings = _load_holdings()

summary_file = RESULTS / "summary_signals.csv"
funda_file = RESULTS / "fundamentals.csv"
coin_summary_file = RESULTS / "coin_summary.csv"
summary = pd.read_csv(summary_file) if summary_file.exists() else pd.DataFrame()
funda = pd.read_csv(funda_file) if funda_file.exists() else pd.DataFrame(columns=["ticker"])

_MERGE_COLS = ["ticker", "close", "action", "state", "last_cross", "last_cross_date", "rsi14"]
if coin_summary_file.exists():
    coin_sum = pd.read_csv(coin_summary_file)
    usdkrw = _get_usdkrw()
    coin_sum["close"] = coin_sum["close"] * usdkrw
    coin_sum = coin_sum.rename(columns={"regime": "state"})
    for col in _MERGE_COLS:
        if col not in coin_sum.columns:
            coin_sum[col] = None
    combined_summary = pd.concat(
        [summary[_MERGE_COLS] if not summary.empty else pd.DataFrame(columns=_MERGE_COLS),
         coin_sum[_MERGE_COLS]],
        ignore_index=True,
    )
else:
    combined_summary = summary

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

# ── 사람 필터 ────────────────────────────────────────────────────
all_persons = sorted([p for p in holdings["person"].unique() if p and str(p).strip()])
person_options = ["전체"] + all_persons
selected_person = st.selectbox(
    "👤 보기/계산 대상",
    options=person_options,
    index=0,
    help="선택한 사람의 보유종목만 표시하고 계산합니다.",
    key="person_filter",
)

# ── 보유 내역 추가 / 편집 ────────────────────────────────────────


st.subheader("✏️ 보유 내역 추가 / 편집")
st.caption("새 행 맨 아래 추가, 행 삭제는 체크박스 → Delete. 종목명 선택 시 저장할 때 티커 자동 입력.")

_edit_cols = ["ticker", "qty", "buy_price", "person", "notes"]
_edit_df = holdings[_edit_cols].copy() if all(c in holdings.columns for c in _edit_cols) else holdings[["ticker", "qty", "buy_price"]].copy()
_edit_df["ticker"] = _edit_df["ticker"].fillna("").astype(str)
_edit_df["qty"] = pd.to_numeric(_edit_df["qty"], errors="coerce").fillna(0.0)
_edit_df["buy_price"] = pd.to_numeric(_edit_df["buy_price"], errors="coerce").fillna(0.0)
_edit_df["person"] = _edit_df["person"].fillna("").astype(str) if "person" in _edit_df.columns else ""
_edit_df["notes"] = _edit_df["notes"].fillna("").astype(str) if "notes" in _edit_df.columns else ""
# 종목명 열 추가 (첫 열)
_edit_df.insert(0, "종목명", _edit_df["ticker"].map(NAMES).fillna(""))
_edit_df = _edit_df.rename(columns={"ticker": "티커", "qty": "수량", "buy_price": "매수가", "person": "이름", "notes": "메모"})

# 선택한 사람만 편집 테이블에 표시
if selected_person != "전체":
    _edit_df_show = _edit_df[_edit_df["이름"] == selected_person].copy()
    _others = holdings[holdings["person"] != selected_person].copy()
else:
    _edit_df_show = _edit_df.copy()
    _others = None

edited_partial = st.data_editor(
    _edit_df_show,
    num_rows="dynamic",
    use_container_width=True,
    key=f"holdings_editor_{selected_person}",
    column_config={
        "종목명": st.column_config.SelectboxColumn(
            "종목명 검색",
            options=_ALL_NAMES,
            help="이름 선택 → 저장 시 티커 자동 입력",
            width="medium",
        ),
        "티커": st.column_config.TextColumn("티커", width="small"),
        "수량": st.column_config.NumberColumn("수량", format="%.8g"),
        "매수가": st.column_config.NumberColumn("매수가", format="%,.0f"),
        "이름": st.column_config.TextColumn("이름", width="small"),
        "메모": st.column_config.TextColumn("메모"),
    },
)

# 종목명으로 티커 자동 파생 (티커가 비어 있고 종목명이 선택된 경우)
edited_partial = edited_partial.copy()
for idx, row in edited_partial.iterrows():
    if (not str(row.get("티커", "")).strip()) and str(row.get("종목명", "")).strip():
        derived = _NAME_TO_TICKER.get(str(row["종목명"]), "")
        if derived:
            edited_partial.at[idx, "티커"] = derived

edited_cur = edited_partial.drop(columns=["종목명"]).rename(
    columns={"티커": "ticker", "수량": "qty", "매수가": "buy_price", "이름": "person", "메모": "notes"}
)
edited_cur["buy_date"] = ""

# 다른 사람 데이터 합쳐서 전체 저장용 DataFrame 구성
if selected_person != "전체" and _others is not None and not _others.empty:
    edited = pd.concat([edited_cur, _others], ignore_index=True)
else:
    edited = edited_cur.copy()
    if selected_person == "전체" and "buy_date" in holdings.columns and len(holdings) == len(edited):
        edited["buy_date"] = holdings["buy_date"].values

# 현황 계산용은 현재 편집 대상만
holdings_view = edited_cur.copy()

sc1, sc2 = st.columns([1, 1])
with sc1:
    if st.button("💾 저장", type="primary", use_container_width=True):
        _save_holdings(edited)
        ok, msg = _push_to_github(edited)
        if ok:
            st.success(msg)
        else:
            st.warning(f"로컬 저장 완료. GitHub 동기화 실패: {msg}")
        st.rerun()
with sc2:
    csv_dl = edited.to_csv(index=False).encode("utf-8")
    st.download_button("📥 백업", data=csv_dl, file_name="holdings_backup.csv",
                       mime="text/csv", use_container_width=True)

if edited.empty or edited["ticker"].dropna().empty:
    st.info("보유 종목이 없습니다. 위 표에 추가해보세요.")
    st.stop()

st.divider()

# ── 현황 + 매도 신호 ─────────────────────────────────────────────
label_suffix = f" — {selected_person}" if selected_person != "전체" else " — 전체"
st.subheader(f"📊 현황 + 매도 신호{label_suffix}")

view = holdings_view.dropna(subset=["ticker"]).copy()
view = view[view["ticker"].astype(str).str.strip() != ""].copy()
view["ticker"] = view["ticker"].astype(str).str.strip().str.upper()

if not combined_summary.empty:
    view = view.merge(combined_summary[_MERGE_COLS], on="ticker", how="left")
else:
    for c in ["close", "action", "state", "last_cross", "last_cross_date", "rsi14"]:
        view[c] = None

view = view.merge(scores_df[["ticker", "composite"]], on="ticker", how="left")
view["종목명"] = view["ticker"].map(NAMES).fillna("-")
view["현재가"] = view["close"]
view["평가금액"] = view["qty"] * view["close"]
view["원금"] = view["qty"] * view["buy_price"]
view["손익"] = view["평가금액"] - view["원금"]
view["수익률(%)"] = ((view["close"] / view["buy_price"]) - 1) * 100


def holding_signal(row):
    action = row.get("action")
    rsi = row.get("rsi14")
    pnl_pct = row.get("수익률(%)")
    composite = row.get("composite")
    reasons = []
    severity = 0
    if action == "매도":
        reasons.append("단기(50일)선이 장기(200일)선 아래로 내려옴 → 하락 추세 전환 신호")
        severity = 2
    if pd.notna(rsi) and rsi >= 80:
        reasons.append(f"RSI {rsi:.0f} — 단기 급등으로 과매수 구간, 조정 가능성 높음")
        severity = max(severity, 2)
    if action == "미보유" and severity < 2:
        reasons.append("단기(50일)선이 장기(200일)선 아래 — 추세 하락 구간, 반등 확인 후 매수 권장")
        severity = max(severity, 1)
    if pd.notna(rsi) and rsi >= 70 and severity < 2:
        reasons.append(f"RSI {rsi:.0f} — 단기 과열 구간, 추가 상승 여력 제한적")
        severity = max(severity, 1)
    if pd.notna(pnl_pct) and pnl_pct <= -20:
        reasons.append(f"매수가 대비 {pnl_pct:.1f}% 하락 — 손절 기준선(-8%) 크게 이탈, 매도 검토 필요")
        severity = max(severity, 2)
    elif pd.notna(pnl_pct) and pnl_pct <= -8 and severity < 2:
        reasons.append(f"매수가 대비 {pnl_pct:.1f}% 하락 — 손절 기준선(-8%) 이탈, 추가 하락 시 대응 필요")
        severity = max(severity, 1)
    if severity == 2:
        return "🔴 매도 검토", " · ".join(reasons)
    if severity == 1:
        return "🟠 주의", " · ".join(reasons)
    if action == "매수":
        return "🟢 추가 매수 가능", "단기(50일)선이 장기(200일)선 위로 올라옴 → 상승 추세 확인, 분할 매수 적기"
    return "🔵 보유", "특이사항 없음"


sigs = view.apply(holding_signal, axis=1)
view["신호"] = [s[0] for s in sigs]
view["사유"] = [s[1] for s in sigs]

total_cost = view["원금"].sum()
total_value = view["평가금액"].sum()
total_pnl = total_value - total_cost
total_pnl_pct = (total_pnl / total_cost * 100) if total_cost > 0 else 0
n_sell = (view["신호"] == "🔴 매도 검토").sum()
n_warn = (view["신호"] == "🟠 주의").sum()

k1, k2, k3, k4, k5, k6 = st.columns(6)
k1.metric("보유 종목 수", f"{len(view)}")
k2.metric("총 원금", f"{total_cost:,.0f}원")
k3.metric("총 손익", f"{total_pnl:+,.0f}원", delta=f"{total_pnl_pct:+.2f}%")
k4.metric("총 평가금액", f"{total_value:,.0f}원")
k5.metric("🔴 매도 검토", f"{n_sell}")
k6.metric("USD/KRW", f"{_get_usdkrw():,.0f}", help="코인 현재가 환산에 사용된 환율 (1시간 캐시)")

if n_sell > 0:
    sell_tickers = view[view["신호"] == "🔴 매도 검토"]["ticker"].tolist()
    st.error(f"⚠️ **매도 검토 필요**: {', '.join(sell_tickers)}")

display = view.rename(columns={
    "ticker": "티커", "qty": "수량", "buy_price": "매수가", "rsi14": "RSI(과열)",
    "days_since_cross": "추세일수",
}).copy()

# 코인 여부 판별 (티커에 -USD 포함)
def _qty_fmt(row):
    return f"{row['수량']:.8f}" if "-USD" in str(row["티커"]) else f"{int(round(row['수량'])):,}"
display["수량"] = display.apply(_qty_fmt, axis=1)
display["action"] = display["action"].map({"매수": "상승추세", "미보유": "하락추세"}).fillna(display["action"])

def _cross_date_label(row):
    d = row.get("last_cross_date")
    n = row.get("추세일수")
    if pd.isna(d) or not d:
        return "-"
    try:
        n = int(n) if pd.notna(n) else 0
        return f"{d} ({n}일째)"
    except Exception:
        return str(d)
display["last_cross_date"] = display.apply(_cross_date_label, axis=1)

def _rsi_label(v):
    if pd.isna(v):
        return "-"
    v = float(v)
    if v >= 70:
        return f"{v:.1f} (과열)"
    if v <= 30:
        return f"{v:.1f} (과매도)"
    return f"{v:.1f} (정상)"
display["RSI(과열)"] = display["RSI(과열)"].apply(_rsi_label)

# 신호에서 동그라미만 추출
display["신호"] = display["신호"].str.extract(r"^(\S)")[0]

_display_cols = ["신호", "종목명", "수량", "매수가", "현재가",
                 "원금", "손익", "평가금액", "수익률(%)", "사유"]
display_table = display[_display_cols].copy()

for _col in ["매수가", "현재가"]:
    display_table[_col] = display_table[_col].apply(
        lambda x: f"{x:,.0f}" if pd.notna(x) and isinstance(x, (int, float)) else ""
    )

_totals = {c: "" for c in display_table.columns}
_totals["종목명"] = "합계"
_totals["원금"] = total_cost
_totals["손익"] = total_pnl
_totals["평가금액"] = total_value
_totals["수익률(%)"] = total_pnl_pct
display_table = pd.concat([display_table, pd.DataFrame([_totals])], ignore_index=True)

st.dataframe(
    display_table,
    use_container_width=True,
    hide_index=True,
    column_config={
        "신호": st.column_config.TextColumn("신호", width="small"),
        "수량": st.column_config.TextColumn("수량"),
        "매수가": st.column_config.TextColumn("매수가"),
        "현재가": st.column_config.TextColumn("현재가"),
        "원금": st.column_config.NumberColumn(format="%,.0f"),
        "평가금액": st.column_config.NumberColumn(format="%,.0f"),
        "수익률(%)": st.column_config.NumberColumn(format="%+.2f"),
        "손익": st.column_config.NumberColumn(format="%+,.0f"),
    },
)
st.caption(
    "🟢 추가 매수 가능 · 🔵 보유 · 🟠 주의 · 🔴 매도 검토  |  "
    "**추세**: 50일 평균선이 200일 평균선 위면 상승세, 아래면 하락세  |  "
    "**RSI**: 70 이상 과열, 30 이하 낙폭 과다"
)

# 파이차트
if total_value > 0:
    st.markdown("#### 자산 배분")
    view["weight"] = view["평가금액"] / total_value * 100
    fig_pie = go.Figure(go.Pie(
        labels=[f"{r['종목명']} ({r['ticker']})" for _, r in view.iterrows()],
        values=view["평가금액"], hole=0.45,
    ))
    fig_pie.update_layout(
        height=480,
        margin=dict(t=10, b=10, l=10, r=200),
        legend=dict(font=dict(size=14), x=1.02, y=0.5, xanchor="left", yanchor="middle"),
    )
    st.plotly_chart(fig_pie, use_container_width=True)

st.caption(
    "**매도 신호 기준**: 데드크로스 발생, RSI ≥ 80, QVGM ≤ -1.0 중 하나만 충족해도 🔴 표시."
)

# =====================================================================
# 자산별 상세 리포트
# =====================================================================
st.divider()
st.subheader("📋 자산별 상세 리포트")

_cycle_file = RESULTS / "cycle_metrics.csv"
_cycle = pd.read_csv(_cycle_file).iloc[0] if _cycle_file.exists() else None

_reports_file = ROOT / "asset_reports.json"
_reports = json.loads(_reports_file.read_text(encoding="utf-8")) if _reports_file.exists() else {}

_OPINION_COLOR = {"positive": "green", "caution": "orange", "negative": "red"}

for _, row in view.iterrows():
    ticker = str(row["ticker"])
    name = row["종목명"]
    is_coin = "-USD" in ticker
    pnl_pct = row["수익률(%)"]

    sig_filename = f"coin_{ticker}_signals.csv" if is_coin else f"{ticker}_signals.csv"
    sig_file = RESULTS / sig_filename

    header = f"{row['신호']}  |  **{name}** ({ticker})  —  {pnl_pct:+.2f}%"
    with st.expander(header, expanded=False):

        # ── 리서치 의견 ────────────────────────────────────────────
        _rpt = _reports.get(ticker)
        if _rpt:
            _otype = _rpt.get("opinion_type", "caution")
            _color = _OPINION_COLOR.get(_otype, "gray")
            st.markdown(
                f"<div style='background:{'#e8f5e9' if _otype=='positive' else ('#fff3e0' if _otype=='caution' else '#ffebee')};"
                f"border-left:4px solid {'#43a047' if _otype=='positive' else ('#fb8c00' if _otype=='caution' else '#e53935')};"
                f"padding:12px 16px;border-radius:4px;margin-bottom:8px'>"
                f"<b>종합 의견</b>: {_rpt.get('opinion','')}</div>",
                unsafe_allow_html=True,
            )
            st.markdown(_rpt.get("summary", ""))
            _bc, _brc = st.columns(2)
            with _bc:
                st.markdown("**📈 강세 근거**")
                st.success(_rpt.get("bull", "-"))
            with _brc:
                st.markdown("**📉 약세 근거 (틀릴 조건)**")
                st.error(_rpt.get("bear", "-"))
            _src = _rpt.get("sources", [])
            if _src:
                st.markdown("**출처**:  " + "  ·  ".join(
                    f"[{s['title']}]({s['url']})" for s in _src
                ))
            st.markdown(f"<small style='color:gray'>분석 기준일: {_rpt.get('updated','')}</small>",
                        unsafe_allow_html=True)
            st.divider()

        # ── 수익률 메트릭 ──────────────────────────────────────────
        m1, m2, m3, m4, m5 = st.columns(5)
        m1.metric("매수가", f"{row['buy_price']:,.0f}")
        m2.metric("현재가", f"{row['현재가']:,.0f}")
        m3.metric("원금", f"{row['원금']:,.0f}원")
        m4.metric("평가금액", f"{row['평가금액']:,.0f}원")
        m5.metric("손익", f"{row['손익']:+,.0f}원", delta=f"{pnl_pct:+.2f}%",
                  delta_color="normal" if pnl_pct >= 0 else "inverse")

        # ── 가격 차트 ──────────────────────────────────────────────
        if sig_file.exists():
            sig_df = pd.read_csv(sig_file)
            sig_df = sig_df.rename(columns={"Date": "date", "Close": "close",
                                            "High": "high", "Low": "low"})
            sig_df["date"] = pd.to_datetime(sig_df["date"])
            sig_df = sig_df.dropna(subset=["close"]).tail(365)

            if is_coin:
                for _c in ["close", "ma50", "ma200", "sma20w", "ema21w"]:
                    if _c in sig_df.columns:
                        sig_df[_c] = sig_df[_c] * usdkrw
                buy_line = row["buy_price"]
            else:
                buy_line = row["buy_price"]

            fig_detail = go.Figure()
            fig_detail.add_trace(go.Scatter(
                x=sig_df["date"], y=sig_df["close"], name="현재가격",
                line=dict(color="#4C9BE8", width=1.5)))

            ma_styles = [
                ("ma20",  "20일 평균선 (단기)",  "#FFA500"),
                ("ma50",  "50일 평균선 (중기)",  "#2CA02C"),
                ("ma200", "200일 평균선 (장기)", "#D62728"),
                ("sma20w","20주 평균선",         "#9467BD"),
                ("ema21w","21주 가중평균선",      "#8C564B"),
            ]
            for ma_col, ma_name, ma_color in ma_styles:
                if ma_col in sig_df.columns:
                    fig_detail.add_trace(go.Scatter(
                        x=sig_df["date"], y=sig_df[ma_col], name=ma_name,
                        line=dict(color=ma_color, width=1), opacity=0.75))

            fig_detail.add_hline(
                y=buy_line, line_dash="dash", line_color="#E377C2",
                annotation_text=f"내 매수가 {buy_line:,.0f}",
                annotation_position="bottom right")
            fig_detail.update_layout(
                height=300, margin=dict(t=10, b=30, l=10, r=10),
                legend=dict(orientation="h", y=-0.25),
                xaxis_rangeslider_visible=False,
                yaxis_tickformat=",")
            st.plotly_chart(fig_detail, use_container_width=True)
            st.caption(
                "📌 **차트 보는 법**: 파란선=실제 가격 / 주황·초록·빨간선=기간별 평균 가격(평균선이 우상향이면 상승 추세) / "
                "보라 점선=내가 산 가격 / **초록선(50일)이 빨간선(200일) 위**면 상승 추세, 아래면 하락 추세"
            )

            # ── 핵심 지표 (쉬운 설명) ──────────────────────────────
            st.markdown("**📊 핵심 지표**")
            latest = sig_df.iloc[-1]
            cols = sig_df.columns.tolist()
            ind1, ind2, ind3, ind4 = st.columns(4)

            rsi = latest.get("rsi14")
            if pd.notna(rsi):
                rsi_tag = "🔥 과열 — 단기 조정 주의" if rsi >= 70 else ("🟢 낙폭 과다 — 반등 가능" if rsi <= 30 else "✅ 정상 구간")
                ind1.metric(
                    "과열 온도계 (RSI)",
                    f"{rsi:.0f} / 100",
                    delta=rsi_tag,
                    delta_color="off",
                    help="0~100 사이 숫자. 70 이상이면 단기 과열(조정 가능), 30 이하면 낙폭 과다(반등 가능), 그 사이는 정상.",
                )

            ma50v = latest.get("ma50")
            ma200v = latest.get("ma200")
            if pd.notna(ma50v) and pd.notna(ma200v) and ma200v > 0:
                spread = (ma50v / ma200v - 1) * 100
                ind2.metric(
                    "추세 방향",
                    "상승 추세 ▲" if spread > 0 else "하락 추세 ▼",
                    delta=f"단기평균이 장기평균보다 {abs(spread):.1f}% {'높음' if spread > 0 else '낮음'}",
                    delta_color="normal" if spread > 0 else "inverse",
                    help="50일 평균선이 200일 평균선보다 높으면 상승 추세(골든크로스), 낮으면 하락 추세(데드크로스).",
                )

            if "macd_hist" in cols:
                mh = latest.get("macd_hist")
                if pd.notna(mh):
                    ind3.metric(
                        "상승 가속도 (MACD)",
                        "가속 중 ▲" if mh > 0 else "감속 중 ▼",
                        delta=f"{'오름세 강해지는 중' if mh > 0 else '내림세 강해지는 중'}",
                        delta_color="normal" if mh > 0 else "inverse",
                        help="양수(+)면 현재 오르는 속도가 빨라지고 있다는 뜻, 음수(-)면 내리는 속도가 빨라지고 있다는 뜻.",
                    )

            if "bb_pct" in cols:
                bb = latest.get("bb_pct")
                if pd.notna(bb):
                    if bb > 0.8:
                        bb_tag, bb_desc = "상단 근접 — 단기 비쌈", "inverse"
                    elif bb < 0.2:
                        bb_tag, bb_desc = "하단 근접 — 단기 저렴", "normal"
                    else:
                        bb_tag, bb_desc = "중간 구간 — 보통 수준", "off"
                    ind4.metric(
                        "가격 위치 (볼린저밴드)",
                        f"{bb:.0%}",
                        delta=bb_tag,
                        delta_color=bb_desc,
                        help="최근 가격 변동 범위 안에서 지금 가격이 어디 있는지. 0%=밴드 바닥(저렴), 100%=밴드 천장(비쌈), 50%=중간.",
                    )
            elif "momentum20" in cols:
                mom = latest.get("momentum20")
                if pd.notna(mom):
                    ind4.metric(
                        "20일 상승률",
                        f"{mom:+.1%}",
                        delta="오르는 중" if mom > 0 else "내리는 중",
                        delta_color="normal" if mom > 0 else "inverse",
                        help="최근 20일 동안 가격이 얼마나 올랐는지(양수) 또는 내렸는지(음수).",
                    )

        # ── 현재 신호 사유 ─────────────────────────────────────────
        st.info(f"**지금 이 신호가 뜬 이유**: {row['사유']}")

        # ── BTC 온체인 지표 ────────────────────────────────────────
        if ticker == "BTC-USD" and _cycle is not None:
            st.markdown("---")
            st.markdown("**📡 비트코인 사이클 온도계** — 블록체인 데이터로 보는 BTC 현재 국면")
            st.caption("온체인 지표는 실제 BTC 거래 데이터를 기반으로 계산합니다. 가격 차트보다 더 근본적인 시장 상태를 알려줍니다.")
            oc1, oc2, oc3, oc4 = st.columns(4)

            mvrv = _cycle.get("mvrv_z")
            nupl = _cycle.get("nupl")
            puell = _cycle.get("puell")
            pi_sma111 = _cycle.get("pi_sma111")
            pi_sma350x2 = _cycle.get("pi_sma350x2")

            if pd.notna(mvrv):
                mvrv_tag = "🔴 극단 과열 — 매도 구간" if mvrv>7 else ("🟠 과열 주의" if mvrv>3.7 else ("🟢 적정 수준" if mvrv>0 else "🟢 역사적 바닥권"))
                oc1.metric(
                    "거품 온도계 (MVRV)",
                    f"{mvrv:.2f}",
                    delta=mvrv_tag,
                    delta_color="off",
                    help="BTC 전체 보유자의 평균 수익률을 나타내는 지표. 0 이하=역사적 바닥, 3.7 이상=과열, 7 이상=극단 거품(역대 고점 직전 수준).",
                )

            if pd.notna(nupl):
                nupl_tag = "🔴 극단 탐욕" if nupl>0.75 else ("🟠 탐욕" if nupl>0.5 else ("🟡 낙관" if nupl>0.25 else ("🟢 희망(바닥권)" if nupl>0 else "🟢 항복(매수 적기)")))
                oc2.metric(
                    "투자자 심리 (NUPL)",
                    f"{nupl:.2f}",
                    delta=nupl_tag,
                    delta_color="off",
                    help="전체 BTC 투자자가 지금 얼마나 수익/손실 상태인지를 -1~1로 나타냄. 0 근처=손익분기점, 0.75 이상=극단 탐욕(팔아야 할 때), 0 이하=항복(살 때).",
                )

            if pd.notna(puell):
                puell_tag = "🟢 채굴자 수익 낮음 — 매수 적기" if puell < 0.5 else ("🔴 채굴자 수익 과열" if puell > 4 else "🟡 중립")
                oc3.metric(
                    "채굴자 수익 지표 (Puell)",
                    f"{puell:.2f}",
                    delta=puell_tag,
                    delta_color="off",
                    help="채굴자들이 지금 얼마나 수익을 내는지. 0.5 이하=채굴자 손실 중(역사적 바닥 신호), 4 이상=채굴자 과잉 수익(고점 신호).",
                )

            if pd.notna(pi_sma111) and pd.notna(pi_sma350x2):
                pi_cross = pi_sma111 > pi_sma350x2
                oc4.metric(
                    "사이클 고점 신호 (Pi Cycle)",
                    "⚠️ 교차 발생 — 고점 신호" if pi_cross else "✅ 안전 구간",
                    delta="두 평균선이 교차하면 역대 사이클 고점과 일치했음" if pi_cross else "두 평균선 미교차 — 아직 고점 아님",
                    delta_color="inverse" if pi_cross else "off",
                    help="111일 평균선이 350일×2 평균선을 돌파하면 BTC 사이클 정점 신호. 역사적으로 이 교차 직후 대폭락이 시작됐음.",
                )

            alt_score = _cycle.get("alt_season_score")
            alt_label = _cycle.get("alt_season_label", "")
            btc_r90 = _cycle.get("btc_return_90d_pct")
            st.caption(
                f"알트시즌 점수: {alt_score:.0f}/100  |  {alt_label}  |  "
                f"BTC 90일 수익률: {btc_r90:+.1f}%" if pd.notna(alt_score) and pd.notna(btc_r90)
                else ""
            )

        # ── 코인 공통: regime + 90일 수익률 ───────────────────────
        elif is_coin:
            _cs_file = RESULTS / "coin_summary.csv"
            if _cs_file.exists():
                _cs = pd.read_csv(_cs_file)
                _cs_row = _cs[_cs["ticker"] == ticker]
                if not _cs_row.empty:
                    regime = _cs_row.iloc[0].get("regime", "-")
                    r90 = _cs_row.iloc[0].get("return_90d_pct")
                    st.caption(
                        f"사이클 국면: **{regime}**  |  90일 수익률: **{r90:+.1f}%**"
                        if pd.notna(r90) else f"사이클 국면: **{regime}**"
                    )

