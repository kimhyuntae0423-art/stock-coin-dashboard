"""포트폴리오 페이지 — 보유 종목 + 매수가 추적 + 매도 신호 알림."""
import base64
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
from scripts.asset_allocation import add_on_buy_triggers

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

with st.expander("📖 용어 사전", expanded=False):
    st.markdown("""
**🚦 타이밍 라벨**
- 🔴 **너무 올라 위험**: 단기 과매수 — 분할매수 권장
- 🟠 **살짝 비쌈**: 약한 단기 과열 신호
- ⚠️ **가격이 실적보다 빨리 오름**: 1년 가격 상승률이 실적 성장률을 30%p+ 초과
- 💎 **떨어진 우량주**: 펀더 좋고 + 추세 살아있고 + 최근 조정 — 좋은 진입 기회
- 💚 **매수 검토**: 약한 매수 기회 신호

**📊 점수** = -3 ~ +3 사이의 종합 평가. 0이 평균. +1 이상이면 매수 우호, -1 이하면 매도 우호.
    """)

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

sc1, sc2, sc3 = st.columns([1, 1, 4])
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
with sc3:
    uploaded = st.file_uploader("📤 CSV 복원", type=["csv"], key="restore_csv",
                                label_visibility="collapsed")
    if uploaded is not None:
        try:
            restored = pd.read_csv(uploaded)
            for col in ["qty", "buy_price"]:
                if col in restored.columns:
                    restored[col] = pd.to_numeric(restored[col], errors="coerce").fillna(0.0)
            _save_holdings(restored)
            _push_to_github(restored)
            st.success(f"✅ {len(restored)}개 복원 완료!")
        except Exception as e:
            st.error(f"복원 실패: {e}")

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
        reasons.append("최근 30일 데드크로스 발생")
        severity = 2
    if pd.notna(rsi) and rsi >= 80:
        reasons.append(f"RSI {rsi:.0f} 극단 과매수")
        severity = max(severity, 2)
    if pd.notna(composite) and composite <= -1.0:
        reasons.append(f"펀더멘털 악화 (QVGM {composite:+.2f})")
        severity = max(severity, 2)
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

total_cost = view["원금"].sum()
total_value = view["평가금액"].sum()
total_pnl = total_value - total_cost
total_pnl_pct = (total_pnl / total_cost * 100) if total_cost > 0 else 0
n_sell = (view["신호"] == "🔴 매도 검토").sum()
n_warn = (view["신호"] == "🟠 주의").sum()

k1, k2, k3, k4, k5, k6 = st.columns(6)
k1.metric("보유 종목 수", f"{len(view)}")
k2.metric("총 원금", f"{total_cost:,.0f}원")
k3.metric("총 평가금액", f"{total_value:,.0f}원")
k4.metric("총 손익", f"{total_pnl:+,.0f}원", delta=f"{total_pnl_pct:+.2f}%")
k5.metric("🔴 매도 검토", f"{n_sell}", delta=f"🟠 주의 {n_warn}", delta_color="off")
k6.metric("USD/KRW", f"{_get_usdkrw():,.0f}", help="코인 현재가 환산에 사용된 환율 (1시간 캐시)")

if n_sell > 0:
    sell_tickers = view[view["신호"] == "🔴 매도 검토"]["ticker"].tolist()
    st.error(f"⚠️ **매도 검토 필요**: {', '.join(sell_tickers)}")

display = view.rename(columns={
    "ticker": "티커", "qty": "수량", "buy_price": "매수가",
    "buy_date": "매수일", "rsi14": "RSI",
}).copy()

st.dataframe(
    display[["신호", "티커", "종목명", "수량", "매수가", "현재가",
             "평가금액", "수익률(%)", "손익", "사유", "매수일",
             "action", "RSI", "composite", "last_cross_date", "notes"]].rename(
        columns={"action": "추세", "composite": "종합점수",
                 "last_cross_date": "신호일", "notes": "메모"}
    ),
    use_container_width=True,
    hide_index=True,
    column_config={
        "수량": st.column_config.NumberColumn(format="%.8f"),
        "매수가": st.column_config.NumberColumn(format="%,.0f"),
        "현재가": st.column_config.NumberColumn(format="%,.0f"),
        "평가금액": st.column_config.NumberColumn(format="%,.0f"),
        "수익률(%)": st.column_config.NumberColumn(format="%+.2f"),
        "손익": st.column_config.NumberColumn(format="%+,.0f"),
        "RSI": st.column_config.NumberColumn(format="%.1f"),
        "종합점수": st.column_config.NumberColumn(format="%+.2f"),
    },
)
st.caption(
    "**컬럼 풀이**: 추세 = 50/200일선 상태. RSI 70+ 부담, 30- 반등 기회. "
    "종합점수 = 회사 펀더 + 추세 + 타이밍 결합."
)

# 파이차트
if total_value > 0:
    st.markdown("#### 자산 배분")
    view["weight"] = view["평가금액"] / total_value * 100
    fig_pie = go.Figure(go.Pie(
        labels=[f"{r['종목명']} ({r['ticker']})" for _, r in view.iterrows()],
        values=view["평가금액"], hole=0.45,
    ))
    fig_pie.update_layout(height=380, margin=dict(t=10, b=10, l=10, r=10))
    st.plotly_chart(fig_pie, use_container_width=True)

st.caption(
    "**매도 신호 기준**: 데드크로스 발생, RSI ≥ 80, QVGM ≤ -1.0 중 하나만 충족해도 🔴 표시."
)

st.divider()

# ── 분할매수 트리거 알림 ─────────────────────────────────────────
st.subheader("🎯 분할매수 트리거 알림")
st.caption(
    "보유 종목 중 매수가 대비 -5% / -10% / -15% / -20% 하락 도달한 종목. "
    "**점수가 양수면 분할 추가매수 기회**, 음수면 펀더 변화 검토 신호."
)

price_map = dict(zip(view["ticker"], view["close"]))
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
                 "drop_pct": "하락률(%)", "trigger": "도달선", "score": "QVGM", "verdict": "판정"}
    )
    st.dataframe(
        triggers_disp, hide_index=True, use_container_width=True,
        column_config={
            "매수가": st.column_config.NumberColumn(format="%,.2f"),
            "현재가": st.column_config.NumberColumn(format="%,.2f"),
            "하락률(%)": st.column_config.NumberColumn(format="%+.2f"),
            "QVGM": st.column_config.NumberColumn(format="%+.2f"),
        },
    )
    st.caption(
        "**룰**: 점수 ≥ +0.5 → 💎 추가매수 기회 / 0 ~ +0.5 → 🔵 분할매수 검토 / "
        "-0.5 ~ 0 → 🟠 신중 / ≤ -0.5 → 🔴 손절 검토."
    )
