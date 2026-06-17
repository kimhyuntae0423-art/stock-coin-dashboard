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
_ETF_TICKERS: set = set()
if CORE_ETF_FILE.exists():
    _etf_df = pd.read_csv(CORE_ETF_FILE)
    for _, _r in _etf_df.iterrows():
        _NAME_TO_TICKER[str(_r["name"])] = str(_r["ticker"])
    _ETF_TICKERS = set(_etf_df["ticker"].astype(str).str.strip())
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

_MERGE_COLS = ["ticker", "close", "action", "state", "last_cross", "last_cross_date", "rsi14",
               "return_12m_pct", "return_1m_pct"]
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
st.caption(
    "새 행은 맨 아래 + 버튼으로 추가. 행 삭제는 체크박스 → Delete. "
    "**티커를 직접 입력**하거나, 종목명 드롭다운 선택 후 💾 저장하면 티커 자동 입력. "
    "저장 후 반드시 '✅ GitHub에 저장 완료' 메시지를 확인하세요 — 뜨지 않으면 데이터가 사라질 수 있습니다."
)

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
        "티커": st.column_config.TextColumn(
            "티커",
            width="small",
            help="직접 입력 권장. 예: 005930.KS, AAPL, BTC-USD. 종목명 선택 시 저장 후 자동 채워짐.",
        ),
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
        # session_state에 결과 보관 → rerun 후에도 메시지 표시
        st.session_state["_save_ok"] = ok
        st.session_state["_save_msg"] = msg
        st.rerun()
with sc2:
    csv_dl = edited.to_csv(index=False).encode("utf-8")
    st.download_button("📥 백업", data=csv_dl, file_name="holdings_backup.csv",
                       mime="text/csv", use_container_width=True)

# 저장 결과 메시지 — rerun 후에도 유지
if "_save_ok" in st.session_state:
    _ok = st.session_state.pop("_save_ok")
    _msg = st.session_state.pop("_save_msg", "")
    if _ok:
        st.success(f"✅ {_msg}")
    else:
        st.error(
            f"⚠️ **GitHub 동기화 실패** — 데이터가 영구 저장되지 않았습니다!\n\n"
            f"원인: {_msg}\n\n"
            "Streamlit Cloud에서는 GitHub 저장이 필요합니다. "
            "📥 백업 버튼으로 CSV를 다운로드하세요."
        )

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

# 12-1M 모멘텀 분위 — 전체 주식 유니버스 분포 기준으로 보유종목 분류
if not summary.empty and "return_12m_pct" in summary.columns and "return_1m_pct" in summary.columns:
    _all_r12 = pd.to_numeric(summary["return_12m_pct"], errors="coerce")
    _all_r1  = pd.to_numeric(summary["return_1m_pct"],  errors="coerce")
    _all_mom = (_all_r12 - _all_r1).dropna()
    _q25, _q50, _q75 = _all_mom.quantile([0.25, 0.50, 0.75])
    def _assign_mom_rank(m):
        if pd.isna(m): return None
        if m >= _q75: return "Q1"
        if m >= _q50: return "Q2"
        if m >= _q25: return "Q3"
        return "Q4"
else:
    _q25 = _q50 = _q75 = None
    def _assign_mom_rank(m): return None

view["mom_12_1"] = (
    pd.to_numeric(view.get("return_12m_pct", pd.Series(dtype=float)), errors="coerce") -
    pd.to_numeric(view.get("return_1m_pct",  pd.Series(dtype=float)), errors="coerce")
)
view["mom_rank_h"] = view["mom_12_1"].apply(_assign_mom_rank)

view["현재가"] = view["close"]
view["평가금액"] = view["qty"] * view["close"]
view["원금"] = view["qty"] * view["buy_price"]
view["손익"] = view["평가금액"] - view["원금"]
view["수익률(%)"] = ((view["close"] / view["buy_price"]) - 1) * 100


def _coin_bb(ticker: str) -> dict | None:
    """해당 코인의 현재 BB %B, RSI, state 계산. 데이터 부족시 None."""
    path = RESULTS / f"coin_{ticker}_signals.csv"
    if not path.exists():
        return None
    try:
        df = pd.read_csv(path, usecols=["Close", "rsi14", "state"]).tail(40)
    except Exception:
        return None
    df["Close"] = pd.to_numeric(df["Close"], errors="coerce")
    df["rsi14"] = pd.to_numeric(df["rsi14"], errors="coerce")
    if len(df) < 20:
        return None
    mid = df["Close"].rolling(20).mean()
    std = df["Close"].rolling(20).std()
    upper = mid + 2 * std
    lower = mid - 2 * std
    rng = (upper - lower).replace(0, float("nan"))
    pct_b_s = (df["Close"] - lower) / rng
    last = df.iloc[-1]
    pb = pct_b_s.iloc[-1]
    return {
        "pct_b": float(pb) if pd.notna(pb) else None,
        "rsi14": float(last["rsi14"]) if pd.notna(last["rsi14"]) else None,
        "state": str(last["state"]) if pd.notna(last["state"]) else None,
    }


# MVRV Z-Score 로드 — 코인 보유 신호에 사용 (cycle_metrics.csv)
_mvrv_z_now: float | None = None
_cycle_file = RESULTS / "cycle_metrics.csv"
if _cycle_file.exists():
    try:
        _raw_mvrv = pd.read_csv(_cycle_file).iloc[0].get("mvrv_z")
        _mvrv_z_now = float(_raw_mvrv) if pd.notna(_raw_mvrv) else None
    except Exception:
        pass


def holding_signal(row):
    ticker = str(row.get("ticker", ""))
    is_coin = "-USD" in ticker
    is_etf = ticker in _ETF_TICKERS
    mom_rank_h = row.get("mom_rank_h")
    action = row.get("action")
    rsi = row.get("rsi14")
    pnl_pct = row.get("수익률(%)")

    # ── ETF: 리밸런싱으로 관리 — 손실 기반 신호 없음 ──────────────
    if is_etf:
        if mom_rank_h == "Q1":
            return "🟢 리밸런싱 적기", "12-1M 모멘텀 상위 25%(Q1) — ETF 비중 확대 또는 유지"
        if mom_rank_h == "Q4":
            return "🟠 비중 점검", "12-1M 모멘텀 하위 25%(Q4) — 리밸런싱 시 목표 비중 재확인"
        if mom_rank_h == "Q2":
            return "🟢 보유 양호", "ETF 추세 유지 중 — 리밸런싱 스케줄로 관리"
        return "🔵 보유", "ETF — 리밸런싱으로 관리 (개별 매도 신호 없음)"

    # ── 코인: BTC는 MVRV 순수 적용, 알트는 MVRV + 개별 손실 병행 ──
    if is_coin:
        is_btc = ticker == "BTC-USD"
        if _mvrv_z_now is not None:
            z = _mvrv_z_now

            if is_btc:
                # BTC BB 모멘텀 확인 — MVRV 경보 없을 때만 추가 표시
                btc_bb = _coin_bb("BTC-USD")
                btc_pb = btc_bb["pct_b"] if btc_bb else None
                btc_rsi = btc_bb["rsi14"] if btc_bb else None
                btc_momentum = (
                    btc_pb is not None and btc_rsi is not None
                    and btc_pb > 1.0 and btc_rsi > 70
                )
                if z < 0:
                    return "💎 비중 확대 기회", f"MVRV Z-Score {z:.2f} — 역사적 바닥 근접 (BTC 100% 구간, 백테스트 검증)"
                elif z < 1.5:
                    suffix = f" · BB 모멘텀 강화(%B {btc_pb:.2f}, RSI {btc_rsi:.0f}, 백테스트 +23%, 81%)" if btc_momentum else ""
                    return "🟢 보유 양호", f"MVRV Z-Score {z:.2f} — 저평가 구간 (BTC 75% 구간){suffix}"
                elif z < 2.5:
                    return "🟠 중립~과열 경계", f"MVRV Z-Score {z:.2f} — 과열 진입 전 (BTC 45% 구간)"
                else:
                    return "🔴 비중 축소", f"MVRV Z-Score {z:.2f} — 과열 구간 (BTC 20% 목표, 백테스트 검증)"

            # 알트코인: BB + 손익 복합 신호
            cycle_ctx = f"MVRV Z {z:.2f}({'축적' if z < 1.5 else '과열 경계' if z < 2.5 else '과열'})"
            bb = _coin_bb(ticker)
            pct_b = bb["pct_b"] if bb else None
            rsi_bb = bb["rsi14"] if bb else None
            state_bb = bb["state"] if bb else None

            # 신호1. BB 매도: %B>1 + RSI>70 (백테스트 -11.7%, 27% 승률)
            if pct_b is not None and rsi_bb is not None and pct_b > 1.0 and rsi_bb > 70:
                return (
                    "🔴 매도 검토",
                    f"BB 상단 이탈(%B {pct_b:.2f}) + RSI {rsi_bb:.0f}"
                    f" — 과열 매도 신호 (백테스트 -11.7%, 27%). {cycle_ctx}",
                )

            # 신호2. 추세 반전 조기 경보: bull + %B<0.2 (백테스트 -18.2%, 8%)
            if pct_b is not None and state_bb == "bull" and pct_b < 0.2:
                return (
                    "🟠 추세 반전 경보",
                    f"MA 추세 bull이나 BB 하단(%B {pct_b:.2f})"
                    f" — 추세 전환 조기 경보 (백테스트 -18.2%, 8%). {cycle_ctx}",
                )

            # 신호3. 손익 기반 — %B<0+RSI<30이면 등급 완화
            is_bounce = (
                pct_b is not None and rsi_bb is not None
                and pct_b < 0.0 and rsi_bb < 30
            )
            if pd.notna(pnl_pct):
                if pnl_pct <= -40:
                    if is_bounce:
                        return (
                            "🟠 주의 (반등 후보)",
                            f"{pnl_pct:.1f}% 손실 심각 — 단, BB 하단+RSI 과매도"
                            f"(%B {pct_b:.2f}, RSI {rsi_bb:.0f}) 반등 후보 구간. {cycle_ctx}",
                        )
                    return "🔴 매도 검토", f"{pnl_pct:.1f}% 손실 — 알트 개별 하락 심각. {cycle_ctx}"
                elif pnl_pct <= -20:
                    if is_bounce:
                        return (
                            "🔵 반등 후보",
                            f"{pnl_pct:.1f}% 손실 — BB 하단+RSI 과매도"
                            f"(%B {pct_b:.2f}, RSI {rsi_bb:.0f}) 반등 후보 구간 (57% 승률). {cycle_ctx}",
                        )
                    return "🟠 주의", f"{pnl_pct:.1f}% 손실 — 알트 하락 주의. {cycle_ctx}"

            # 손실 없거나 -20% 이내: BB 반등 후보 or MVRV 기반
            if is_bounce:
                return (
                    "🔵 반등 후보",
                    f"BB 하단 이탈+RSI 과매도(%B {pct_b:.2f}, RSI {rsi_bb:.0f})"
                    f" — 평균회귀 반등 후보 (백테스트 +21.4%, 57%). {cycle_ctx}",
                )
            if z < 0:
                return "💎 비중 확대 기회", f"MVRV Z-Score {z:.2f} — 역사적 바닥 근접"
            elif z < 1.5:
                return "🟢 보유 양호", f"MVRV Z-Score {z:.2f} — 저평가 구간"
            elif z < 2.5:
                return "🟠 중립~과열 경계", f"MVRV Z-Score {z:.2f} — 과열 진입 전"
            else:
                return "🔴 비중 축소", f"MVRV Z-Score {z:.2f} — 과열 구간"
        return "🔵 보유", "MVRV 데이터 없음 — 코인 탭에서 온체인 지표 확인 권장"

    # ── 개별주: 매도 검토 / 주의 / 긍정 ──────────────────────────
    reasons = []
    severity = 0
    _heavy = pd.notna(pnl_pct) and pnl_pct <= -20
    _mild  = pd.notna(pnl_pct) and -20 < pnl_pct <= -8

    # ─ 큰 손실 (≥ -20%) ──────────────────────────────────────────
    if _heavy:
        if mom_rank_h == "Q1":
            # 손실 크지만 추세 살아있음 — 즉각 판단 유예
            return (
                "🟠 신호 충돌",
                f"📉 매수가 대비 {pnl_pct:.1f}% 손실. "
                f"📈 단, 12-1M 모멘텀 Q1(상위 25%) — 추세는 살아있음. 직접 판단 필요."
            )
        if mom_rank_h == "Q4":
            reasons.append(
                f"매수가 대비 {pnl_pct:.1f}% 손실 + 모멘텀 하위 25%(Q4) — 추세·논거 이중 훼손"
            )
        else:
            reasons.append(
                f"매수가 대비 {pnl_pct:.1f}% 손실 — 매도 검토 (논거 재확인 후 보유 여부 판단)"
            )
        severity = 2

    # ─ 경미한 손실 (-8 ~ -20%) ────────────────────────────────────
    elif _mild:
        reasons.append(f"매수가 대비 {pnl_pct:.1f}% 손실 — 손절 기준선 이탈, 논거 유지 중인지 점검")
        severity = max(severity, 1)

    # ─ 모멘텀 악화 (Q4) — 큰 손실과 중복되지 않을 때만 추가 ──────
    if mom_rank_h == "Q4" and not _heavy:
        reasons.append("12-1M 모멘텀 하위 25%(Q4) — 추세 약화 (백테스트: Q4 연 +17.7%)")
        severity = max(severity, 1)

    # ─ 데드크로스 — 보조 참고 ────────────────────────────────────
    if action in ("매도", "미보유"):
        reasons.append("데드크로스/하락추세 — 보조 참고 (50.8% 적중, 단독 신뢰도 낮음)")
        severity = max(severity, 1)

    # ─ RSI 극단 과매수 ────────────────────────────────────────────
    if pd.notna(rsi) and rsi >= 80:
        reasons.append(f"RSI {rsi:.0f} — 극단 과매수. 강한 추세에서는 계속 오를 수 있음")
        severity = max(severity, 1)

    if severity == 2:
        return "🔴 매도 검토", " · ".join(reasons)
    if severity == 1:
        return "🟠 주의", " · ".join(reasons)

    if mom_rank_h == "Q1":
        return "🟢 추가 매수 가능", "12-1M 모멘텀 상위 25%(Q1) — 백테스트 연 +45.9%, 분할 매수 적기"
    if mom_rank_h == "Q2":
        return "🟢 보유 양호", "12-1M 모멘텀 중상위(Q2) — 추세 유지 중"
    return "🔵 보유", "특이사항 없음"


sigs = view.apply(holding_signal, axis=1)
view["신호"] = [s[0] for s in sigs]
view["사유"] = [s[1] for s in sigs]

total_cost = view["원금"].sum()
total_value = view["평가금액"].sum()
total_pnl = total_value - total_cost
total_pnl_pct = (total_pnl / total_cost * 100) if total_cost > 0 else 0
n_sell = view["신호"].str.contains("🔴", na=False).sum()
n_warn = view["신호"].str.contains("🟠", na=False).sum()

k1, k2, k3, k4, k5, k6 = st.columns(6)
k1.metric("보유 종목 수", f"{len(view)}")
k2.metric("총 원금", f"{total_cost:,.0f}원")
k3.metric("총 손익", f"{total_pnl:+,.0f}원", delta=f"{total_pnl_pct:+.2f}%")
k4.metric("총 평가금액", f"{total_value:,.0f}원")
k5.metric("🔴 매도 검토", f"{n_sell}")
k6.metric("USD/KRW", f"{_get_usdkrw():,.0f}", help="코인 현재가 환산에 사용된 환율 (1시간 캐시)")

if n_sell > 0:
    sell_tickers = view[view["신호"].str.contains("🔴", na=False)]["ticker"].tolist()
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
        "사유": st.column_config.TextColumn("사유", width="large"),
    },
)
# ──────────────────────────────────────────────────────────────────────
# 신호 표시 정의 (단일 소스)
# 신호 종류·조건이 바뀌면 이 리스트만 수정 → 범례 카드·배경색이 자동 반영
# ──────────────────────────────────────────────────────────────────────
_SIGNAL_DISPLAY = [
    {
        "emoji": "🟢",
        "label": "추가 매수 / 보유 양호",
        "card_bg": "#f0fdf4", "card_border": "#22c55e", "card_color": "#15803d",
        "live_bg": "#e8f5e9", "live_bd": "#43a047",
        "items_html": (
            "📈 개별주: 모멘텀 Q1~Q2<br>"
            "📦 ETF: 리밸런싱 적기 (Q1)<br>"
            "🪙 BTC: MVRV &lt; 1.5 저평가<br>"
            "🪙 BTC: BB 모멘텀 강화(%B&gt;1+RSI70)"
        ),
        "caption": "모멘텀 Q1 시 🟢",
    },
    {
        "emoji": "🔵",
        "label": "보유 / 반등 후보",
        "card_bg": "#eff6ff", "card_border": "#3b82f6", "card_color": "#1d4ed8",
        "live_bg": "#eff6ff", "live_bd": "#3b82f6",
        "items_html": (
            "특이 신호 없음 → 보유 유지<br>"
            "📦 ETF: 리밸런싱으로 관리<br>"
            "🪙 코인: MVRV 데이터 없음<br>"
            "🪙 알트: BB하단+RSI과매도<br>"
            "&nbsp;&nbsp;(%B&lt;0+RSI&lt;30, 반등 후보 57%)"
        ),
        "caption": None,
    },
    {
        "emoji": "🟠",
        "label": "주의 / 경보",
        "card_bg": "#fff7ed", "card_border": "#f97316", "card_color": "#c2410c",
        "live_bg": "#fff3e0", "live_bd": "#fb8c00",
        "items_html": (
            "📈 개별주: -8~-20% 손실·Q4·RSI 80+<br>"
            "&nbsp;&nbsp;또는 -20% + Q1(추세 살아있음)<br>"
            "📦 ETF: Q4 비중 점검<br>"
            "🪙 코인: MVRV 1.5~2.5<br>"
            "🪙 알트: BB추세반전 경보<br>"
            "&nbsp;&nbsp;(bull+%B&lt;0.2, -18.2% 백테스트)"
        ),
        "caption": "-20%+Q1은 🟠 신호 충돌",
    },
    {
        "emoji": "🔴",
        "label": "매도 검토",
        "card_bg": "#fff1f2", "card_border": "#ef4444", "card_color": "#b91c1c",
        "live_bg": "#ffebee", "live_bd": "#e53935",
        "items_html": (
            "📈 개별주: -20% 이상 손실<br>"
            "&nbsp;&nbsp;(Q4이면 추세도 악화)<br>"
            "🪙 BTC: MVRV &gt; 2.5 과열<br>"
            "🪙 알트: BB상단이탈(%B&gt;1+RSI70)<br>"
            "&nbsp;&nbsp;또는 -40% 손실<br>"
            "📦 ETF: 해당 없음"
        ),
        "caption": "-20% 이상 손실 시 🔴 매도 검토",
    },
    {
        "emoji": "💎",
        "label": "비중 확대 기회",
        "card_bg": "#faf5ff", "card_border": "#a855f7", "card_color": "#7e22ce",
        "live_bg": "#e8f5e9", "live_bd": "#43a047",
        "items_html": (
            "🪙 코인 전용<br>"
            "MVRV &lt; 0 — 역사적 바닥<br>"
            "BTC 100% 구간 (백테스트)"
        ),
        "caption": None,
    },
]
# emoji → live 배경색 빠른 조회 (상세 카드 배경에 사용)
_SIGNAL_LIVE = {d["emoji"]: (d["live_bg"], d["live_bd"]) for d in _SIGNAL_DISPLAY}

# 범례 카드 — _SIGNAL_DISPLAY에서 자동 생성
_cards_html = "<div style='display:flex; gap:8px; margin-top:16px; margin-bottom:8px; flex-wrap:wrap'>"
for _sd in _SIGNAL_DISPLAY:
    _cards_html += (
        f"<div style='flex:1; min-width:148px; background:{_sd['card_bg']};"
        f"border-left:4px solid {_sd['card_border']};border-radius:6px;padding:10px 12px'>"
        f"<div style='font-size:13px;font-weight:700;color:{_sd['card_color']};margin-bottom:4px'>"
        f"{_sd['emoji']} {_sd['label']}</div>"
        f"<div style='font-size:11px;color:#555;line-height:1.6'>{_sd['items_html']}</div>"
        f"</div>"
    )
_cards_html += "</div>"
st.markdown(_cards_html, unsafe_allow_html=True)

# 파이차트
if total_value > 0:
    st.markdown("#### 자산 배분")
    view["weight"] = view["평가금액"] / total_value * 100
    fig_pie = go.Figure(go.Pie(
        labels=[f"{r['종목명']} ({r['ticker']})" for _, r in view.iterrows()],
        values=view["평가금액"], hole=0.45,
    ))
    fig_pie.update_layout(
        height=520,
        margin=dict(t=10, b=10, l=10, r=280),
        legend=dict(font=dict(size=17), x=1.02, y=0.5, xanchor="left", yanchor="middle"),
    )
    st.plotly_chart(fig_pie, use_container_width=True)

# 캡션 — _SIGNAL_DISPLAY caption 필드에서 자동 생성
_caption_parts = [
    f"{_sd['emoji']} {_sd['caption']}"
    for _sd in _SIGNAL_DISPLAY if _sd.get("caption")
]
st.caption(
    "**신호 기준**: " + " · ".join(_caption_parts) + " | "
    "📦 ETF — 손실 신호 없음, 리밸런싱으로 관리 | "
    "🪙 BTC — MVRV Z-Score 구간 기반 (0/1.5/2.5) | "
    "🪙 알트 — BB(%B) 복합 신호 (범례 참고). "
    "골든크로스(50.8%)·RSI70+(45%)는 주신호 제외."
)

# =====================================================================
# 자산별 상세 리포트
# =====================================================================
st.divider()
st.subheader("📋 자산별 상세 리포트")

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

        # ── 현재 신호 (매일 자동 갱신) ────────────────────────────
        _sig_text = str(row.get("신호", ""))
        # _SIGNAL_LIVE에서 배경색 자동 조회 — 신호 추가 시 _SIGNAL_DISPLAY만 수정하면 됨
        _live_bg, _live_bd = "#fff3e0", "#fb8c00"  # default: 주의(주황)
        for _emoji, (_bg, _bd) in _SIGNAL_LIVE.items():
            if _emoji in _sig_text:
                _live_bg, _live_bd = _bg, _bd
                break
        st.markdown(
            f"<div style='background:{_live_bg};border-left:4px solid {_live_bd};"
            f"padding:12px 16px;border-radius:4px;margin-bottom:8px'>"
            f"<b>📡 현재 신호 (매일 자동 갱신)</b>: {_sig_text} — {row.get('사유','')}</div>",
            unsafe_allow_html=True,
        )

        _rpt = _reports.get(ticker)
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
                for _c in ["close", "ma50", "ma200"]:
                    if _c in sig_df.columns:
                        sig_df[_c] = sig_df[_c] * usdkrw
                buy_line = row["buy_price"]
            else:
                buy_line = row["buy_price"]

            # BB 계산 (차트 + 핵심 지표 공통 사용)
            _bb_mid_line  = sig_df["close"].rolling(20).mean()
            _bb_std_line  = sig_df["close"].rolling(20).std()
            _bb_upper_line = _bb_mid_line + 2 * _bb_std_line
            _bb_lower_line = _bb_mid_line - 2 * _bb_std_line
            _bb_range_line = (_bb_upper_line - _bb_lower_line).replace(0, float("nan"))
            _pct_b_series  = (sig_df["close"] - _bb_lower_line) / _bb_range_line
            _pct_b_now = float(_pct_b_series.iloc[-1]) if pd.notna(_pct_b_series.iloc[-1]) else None
            _bw_series = (_bb_range_line / _bb_mid_line.replace(0, float("nan"))).dropna()
            _bw_now = float(_bw_series.iloc[-1]) if len(_bw_series) > 0 else None
            _bw_squeeze = (
                _bw_now is not None and len(_bw_series) >= 20
                and _bw_now <= float(_bw_series.quantile(0.20))
            )

            fig_detail = go.Figure()

            # ── 1. 배경 구역: MA50>MA200=초록(상승), MA50<MA200=연빨강(하락) ──
            if "ma50" in sig_df.columns and "ma200" in sig_df.columns:
                _ma_ok = sig_df["ma50"].notna() & sig_df["ma200"].notna()
                _df_ma = sig_df[_ma_ok].reset_index(drop=True)
                if not _df_ma.empty:
                    _is_bull_zone = (_df_ma["ma50"] > _df_ma["ma200"]).tolist()
                    _dates_zone   = _df_ma["date"].tolist()
                    _prev, _zstart = _is_bull_zone[0], _dates_zone[0]
                    for _zi in range(1, len(_is_bull_zone)):
                        if _is_bull_zone[_zi] != _prev:
                            _zcolor = "rgba(34,197,94,0.08)" if _prev else "rgba(239,68,68,0.06)"
                            fig_detail.add_vrect(x0=_zstart, x1=_dates_zone[_zi],
                                                 fillcolor=_zcolor, layer="below", line_width=0)
                            _prev, _zstart = _is_bull_zone[_zi], _dates_zone[_zi]
                    _zcolor = "rgba(34,197,94,0.08)" if _prev else "rgba(239,68,68,0.06)"
                    fig_detail.add_vrect(x0=_zstart, x1=_dates_zone[-1],
                                         fillcolor=_zcolor, layer="below", line_width=0)

            # ── 2. BB 밴드 (먼저 그려야 가격선이 위에 표시됨) ──────────
            fig_detail.add_trace(go.Scatter(
                x=sig_df["date"], y=_bb_upper_line,
                name="BB 상단(2σ)",
                line=dict(color="rgba(120,120,200,0.5)", width=1, dash="dot"),
                showlegend=True))
            fig_detail.add_trace(go.Scatter(
                x=sig_df["date"], y=_bb_lower_line,
                name="BB 하단(2σ)",
                line=dict(color="rgba(120,120,200,0.5)", width=1, dash="dot"),
                fill="tonexty", fillcolor="rgba(120,120,200,0.05)",
                showlegend=True))

            # ── 3. MA50 / MA200 (핵심 2선만 유지, 주간 평균 제거) ──────
            for _mc, _mn, _mcol in [
                ("ma50",  "50일선 (중기추세)",  "#2CA02C"),
                ("ma200", "200일선 (장기추세)", "#D62728"),
            ]:
                if _mc in sig_df.columns:
                    fig_detail.add_trace(go.Scatter(
                        x=sig_df["date"], y=sig_df[_mc], name=_mn,
                        line=dict(color=_mcol, width=1.2), opacity=0.8))

            # ── 4. 가격선 (맨 위에) ──────────────────────────────────
            fig_detail.add_trace(go.Scatter(
                x=sig_df["date"], y=sig_df["close"], name="현재가격",
                line=dict(color="#4C9BE8", width=2)))

            # ── 5. 이벤트 마커 ────────────────────────────────────────
            # 골든크로스 / 데드크로스
            if "ma50" in sig_df.columns and "ma200" in sig_df.columns:
                _cross_diff = (sig_df["ma50"] - sig_df["ma200"]).fillna(0)
                _cross_ev   = (_cross_diff > 0).astype(int).diff().fillna(0)
                _golden_df  = sig_df[_cross_ev > 0]
                _dead_df    = sig_df[_cross_ev < 0]
                if not _golden_df.empty:
                    fig_detail.add_trace(go.Scatter(
                        x=_golden_df["date"], y=_golden_df["close"],
                        mode="markers+text", name="상승 전환 (골든크로스)",
                        marker=dict(symbol="triangle-up", size=14, color="#16a34a",
                                    line=dict(color="white", width=1.5)),
                        text=["📈 상승전환"] * len(_golden_df),
                        textposition="top center",
                        textfont=dict(size=9, color="#16a34a")))
                if not _dead_df.empty:
                    fig_detail.add_trace(go.Scatter(
                        x=_dead_df["date"], y=_dead_df["close"],
                        mode="markers+text", name="하락 전환 (데드크로스)",
                        marker=dict(symbol="triangle-down", size=14, color="#dc2626",
                                    line=dict(color="white", width=1.5)),
                        text=["📉 하락전환"] * len(_dead_df),
                        textposition="bottom center",
                        textfont=dict(size=9, color="#dc2626")))

            # BB 이탈 — 에피소드 첫날만 마킹
            _ep_below = (_pct_b_series < 0) & ~(_pct_b_series < 0).shift(1).fillna(False)
            _ep_above = (_pct_b_series > 1.0) & ~(_pct_b_series > 1.0).shift(1).fillna(False)
            _bb_below_ev = sig_df[_ep_below]
            _bb_above_ev = sig_df[_ep_above]
            if not _bb_below_ev.empty:
                fig_detail.add_trace(go.Scatter(
                    x=_bb_below_ev["date"],
                    y=_bb_lower_line[_bb_below_ev.index],
                    mode="markers+text", name="BB 하단 이탈 — 반등 후보",
                    marker=dict(symbol="circle", size=10, color="#3b82f6",
                                line=dict(color="white", width=1.5)),
                    text=["🔵"] * len(_bb_below_ev),
                    textposition="bottom center",
                    textfont=dict(size=11)))
            if not _bb_above_ev.empty:
                fig_detail.add_trace(go.Scatter(
                    x=_bb_above_ev["date"],
                    y=_bb_upper_line[_bb_above_ev.index],
                    mode="markers+text", name="BB 상단 이탈 — 과열",
                    marker=dict(symbol="circle", size=10, color="#ef4444",
                                line=dict(color="white", width=1.5)),
                    text=["🔴"] * len(_bb_above_ev),
                    textposition="top center",
                    textfont=dict(size=11)))

            # ── 6. 내 매수가 + 현재 BB 위치 annotation ───────────────
            fig_detail.add_hline(
                y=buy_line, line_dash="dash", line_color="#E377C2",
                annotation_text=f"내 매수가 {buy_line:,.0f}",
                annotation_position="bottom right")

            if _pct_b_now is not None:
                _pb_label = (
                    "⬇ BB 하단 이탈" if _pct_b_now < 0 else
                    "⬆ BB 상단 이탈" if _pct_b_now > 1.0 else
                    f"BB {_pct_b_now:.0%} 위치"
                )
                _last = sig_df.iloc[-1]
                fig_detail.add_annotation(
                    x=_last["date"], y=_last["close"],
                    text=f"<b>현재</b><br>{_pb_label}",
                    showarrow=True, arrowhead=2, arrowcolor="#4C9BE8",
                    bgcolor="white", bordercolor="#4C9BE8", borderpad=4,
                    font=dict(size=10, color="#1e40af"),
                    xanchor="left", yanchor="middle", ax=25, ay=0)

            fig_detail.update_layout(
                height=340, margin=dict(t=10, b=30, l=10, r=10),
                legend=dict(orientation="h", y=-0.3, font=dict(size=11)),
                xaxis_rangeslider_visible=False,
                yaxis_tickformat=",",
                plot_bgcolor="white",
                xaxis=dict(showgrid=True, gridcolor="rgba(0,0,0,0.05)"),
                yaxis=dict(showgrid=True, gridcolor="rgba(0,0,0,0.05)"),
            )
            st.plotly_chart(fig_detail, use_container_width=True)
            st.caption(
                "📌 **차트 보는 법**: "
                "🟦 파란선=내 주식 현재 가격 / "
                "🟢 초록선=50일 평균(중기) · 🔴 빨간선=200일 평균(장기) — **초록이 빨간 위**면 상승추세, 아래면 하락추세 / "
                "🔵 점선 띠=볼린저밴드(BB) — 가격 변동 정상 범위 / "
                "🟩 초록 배경=상승 추세 구간 · 🟥 분홍 배경=하락 추세 구간 / "
                "📈▲=상승 전환 시점 · 📉▼=하락 전환 시점 · 🔵●=BB 하단 이탈(반등 후보) · 🔴●=BB 상단 이탈(과열)"
            )

            # ── 핵심 지표 (쉬운 설명) ──────────────────────────────
            st.markdown("**📊 핵심 지표**")
            latest = sig_df.iloc[-1]
            cols = sig_df.columns.tolist()
            ind1, ind2, ind3, ind4 = st.columns(4)

            rsi = latest.get("rsi14")
            if pd.notna(rsi):
                if rsi >= 70:
                    rsi_tag = ("🔥 과열 (RSI 70+ 코인 적중률 45% — 참고만)" if is_coin
                               else "🔥 과열 — 단기 조정 주의")
                elif rsi <= 30:
                    rsi_tag = "🟢 낙폭 과다 — 반등 가능"
                else:
                    rsi_tag = "✅ 정상 구간"
                ind1.metric(
                    "과열 온도계 (RSI)",
                    f"{rsi:.0f} / 100",
                    delta=rsi_tag,
                    delta_color="off",
                    help="0~100 사이 숫자. 70 이상이면 단기 과열(조정 가능), 30 이하면 낙폭 과다(반등 가능). 코인은 RSI 70+ 적중률 45%(동전던지기 이하) — 단독 신호 신뢰도 낮음.",
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
            elif _bw_now is not None:
                # MACD 없을 때(코인 등) — BB 밴드폭(스퀴즈) 표시
                if _bw_squeeze:
                    bw_tag, bw_dc = "🔔 스퀴즈 — 큰 움직임 전조", "off"
                else:
                    bw_tag, bw_dc = "변동성 정상", "off"
                ind3.metric(
                    "변동성 (BB 밴드폭)",
                    f"{_bw_now:.1%}",
                    delta=bw_tag,
                    delta_color=bw_dc,
                    help="볼린저밴드 폭이 좁아지면 '스퀴즈' — 곧 큰 움직임(상승 또는 하락) 가능. 방향은 알 수 없음. "
                         "백테스트: 스퀴즈 후 90일 ENS +20%, BTC +16%.",
                )

            # BB %B — 항상 직접 계산 (bb_pct 컬럼 불필요)
            if _pct_b_now is not None:
                if _pct_b_now > 1.0:
                    bb_tag = "🔴 상단 이탈 — 알트 매도 신호"
                    bb_dc = "inverse"
                elif _pct_b_now > 0.8:
                    bb_tag = "🟠 상단 근접 — 단기 비쌈"
                    bb_dc = "inverse"
                elif _pct_b_now < 0.0:
                    bb_tag = "🔵 하단 이탈 — 반등 후보"
                    bb_dc = "normal"
                elif _pct_b_now < 0.2:
                    bb_tag = "🟡 하단 근접 — 저렴 구간"
                    bb_dc = "normal"
                else:
                    bb_tag = "중간 구간"
                    bb_dc = "off"
                _pb_display = (f"{_pct_b_now:.0%}" if 0.0 <= _pct_b_now <= 1.0
                               else f"{_pct_b_now:+.2f}")
                ind4.metric(
                    "가격 위치 (BB %B)",
                    _pb_display,
                    delta=bb_tag,
                    delta_color=bb_dc,
                    help="볼린저밴드(2σ) 안에서 현재 가격 위치. 0%=밴드 바닥, 100%=밴드 천장. "
                         "0% 미만=하단 이탈(반등 후보 57%), 100% 초과=상단 이탈(알트 -11.7% 백테스트).",
                )

        # ── 통합 분석 리포트 ────────────────────────────────────────
        st.markdown("---")
        _rpt_updated = _rpt.get("updated", "") if _rpt else ""
        _title_suffix = f"리서치 {_rpt_updated} + 실시간 기술 지표" if _rpt_updated else "실시간 기술 지표"
        st.markdown(f"**📊 종합 분석 리포트** · {_title_suffix}")

        if _rpt and _rpt.get("summary"):
            st.markdown(
                f"<div style='background:#f1f5f9;border-radius:6px;padding:10px 14px;"
                f"font-size:0.92em;margin-bottom:8px;color:#334155'>"
                f"💬 {_rpt['summary']}</div>",
                unsafe_allow_html=True,
            )

        _bull_items: list[tuple[str, str]] = []
        _bear_items: list[tuple[str, str]] = []

        if _rpt and _rpt.get("bull"):
            _bull_items.append(("📝", _rpt["bull"]))
        if _rpt and _rpt.get("bear"):
            _bear_items.append(("📝", _rpt["bear"]))

        _latest = sig_df.iloc[-1] if not sig_df.empty else None
        if _latest is not None:
            _ma50_v  = float(_latest["ma50"])  if pd.notna(_latest.get("ma50"))  else None
            _ma200_v = float(_latest["ma200"]) if pd.notna(_latest.get("ma200")) else None
            if _ma50_v and _ma200_v and _ma200_v > 0:
                _spd = (_ma50_v / _ma200_v - 1) * 100
                if _spd > 0:
                    _bull_items.append(("📊",
                        f"최근 50일 평균이 200일 평균보다 {_spd:.1f}% 높습니다. "
                        f"단기 흐름이 장기 흐름 위에 있어 전반적으로 상승 구간입니다."))
                else:
                    _bear_items.append(("📊",
                        f"최근 50일 평균이 200일 평균보다 {abs(_spd):.1f}% 낮습니다. "
                        f"단기 흐름이 장기 흐름 아래로 내려온 상태로, 하락 추세가 지속 중입니다."))

            _rsi_v = _latest.get("rsi14")
            if pd.notna(_rsi_v):
                _rsi_v = float(_rsi_v)
                if _rsi_v >= 70:
                    _bear_items.append(("📊",
                        f"RSI가 {_rsi_v:.0f}으로 과열 구간(70+)에 진입했습니다. "
                        f"단기간에 너무 많이 올랐다는 신호로, 숨 고르기(조정)가 올 수 있습니다."))
                elif _rsi_v <= 30:
                    _bull_items.append(("📊",
                        f"RSI가 {_rsi_v:.0f}으로 낙폭 과다 구간(30 이하)입니다. "
                        f"단기간에 너무 많이 내렸다는 신호로, 기술적 반등이 나올 수 있습니다."))
                elif _rsi_v >= 50:
                    _bull_items.append(("📊",
                        f"RSI {_rsi_v:.0f} — 과열도 과매도도 아닌 적정 구간입니다. "
                        f"현재 매수 세력이 매도 세력보다 조금 우세한 상태입니다."))
                else:
                    _bear_items.append(("📊",
                        f"RSI {_rsi_v:.0f} — 중립 구간이지만 50 아래입니다. "
                        f"매도 세력이 소폭 우세한 상태로, 방향 확인이 필요합니다."))

            if "macd_hist" in sig_df.columns:
                _mh_v = _latest.get("macd_hist")
                if pd.notna(_mh_v):
                    if float(_mh_v) > 0:
                        _bull_items.append(("📊",
                            "오르는 속도가 점점 빨라지고 있습니다(MACD 양수). "
                            "지금 당장 팔기보다 조금 더 추세를 지켜볼 만한 상황입니다."))
                    else:
                        _bear_items.append(("📊",
                            "오르는 속도가 둔화되거나 내리는 힘이 강해지고 있습니다(MACD 음수). "
                            "추세가 꺾이기 시작할 수 있어 주의가 필요합니다."))

        if _pct_b_now is not None:
            if _pct_b_now > 1.0:
                _bear_items.append(("📊",
                    f"가격이 볼린저밴드 상단을 뚫고 올라간 상태입니다(BB %B {_pct_b_now:+.2f}). "
                    f"알트코인 백테스트 기준 이 구간 이후 90일 평균 -11.7% — 단기 고점 가능성 있습니다."))
            elif _pct_b_now > 0.8:
                _bear_items.append(("📊",
                    f"가격이 볼린저밴드 상단 근처({_pct_b_now:.0%})에 있습니다. "
                    f"정상 변동 범위의 꼭대기에 가까워졌다는 의미로, 단기 조정이 올 수 있습니다."))
            elif _pct_b_now < 0:
                _bull_items.append(("📊",
                    f"가격이 볼린저밴드 하단을 이탈한 상태입니다(BB %B {_pct_b_now:+.2f}). "
                    f"정상 범위를 아래로 벗어날 만큼 많이 내렸다는 뜻으로, 백테스트 기준 반등 확률 57%입니다."))
            elif _pct_b_now < 0.2:
                _bull_items.append(("📊",
                    f"가격이 볼린저밴드 하단 근처({_pct_b_now:.0%})에 있습니다. "
                    f"정상 변동 범위의 바닥 쪽에 위치한 상태로, 상대적으로 저렴한 구간입니다."))
            else:
                _bull_items.append(("📊",
                    f"가격이 볼린저밴드 중간({_pct_b_now:.0%})에 있습니다. "
                    f"너무 과열되지도, 과매도되지도 않은 안정적인 위치입니다."))

        if _bw_squeeze:
            _bear_items.append(("📊",
                "볼린저밴드 폭이 최근 들어 매우 좁아졌습니다(스퀴즈). "
                "변동성이 크게 수축된 상태로, 곧 위아래 한 방향으로 큰 움직임이 나올 수 있습니다. "
                "방향은 예측하기 어려우므로 주시가 필요합니다."))

        _rc1, _rc2 = st.columns(2)
        with _rc1:
            st.markdown("**📈 강세 근거**")
            for _ico, _txt in _bull_items:
                st.markdown(
                    f"<div style='font-size:0.9em;padding:2px 0'>{_ico} {_txt}</div>",
                    unsafe_allow_html=True)
            if not _bull_items:
                st.markdown("<div style='font-size:0.9em;color:#9ca3af'>—</div>",
                            unsafe_allow_html=True)
        with _rc2:
            st.markdown("**📉 약세 근거 / 틀릴 조건**")
            for _ico, _txt in _bear_items:
                st.markdown(
                    f"<div style='font-size:0.9em;padding:2px 0'>{_ico} {_txt}</div>",
                    unsafe_allow_html=True)
            if not _bear_items:
                st.markdown("<div style='font-size:0.9em;color:#9ca3af'>—</div>",
                            unsafe_allow_html=True)

        _foot: list[str] = [f"자동 신호: {_sig_text} — {row.get('사유','')}"]
        if _rpt_updated:
            _foot.append(f"리서치 노트 {_rpt_updated} 기준")
        _src_list = _rpt.get("sources", []) if _rpt else []
        if _src_list:
            _foot.append("출처: " + "  ·  ".join(
                f"[{_s['title']}]({_s['url']})" for _s in _src_list))
        st.caption("  |  ".join(_foot))

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
                if mvrv < 0:
                    mvrv_tag = "🟢 역사적 바닥 근접 (BTC 100% 구간)"
                elif mvrv < 1.5:
                    mvrv_tag = "🟢 저평가 (BTC 75% 구간)"
                elif mvrv < 2.5:
                    mvrv_tag = "🟠 중립~과열 경계 (BTC 45% 구간)"
                else:
                    mvrv_tag = "🔴 과열 — 비중 축소 구간 (BTC 20%)"
                oc1.metric(
                    "거품 온도계 (MVRV)",
                    f"{mvrv:.2f}",
                    delta=mvrv_tag,
                    delta_color="off",
                    help="BTC 전체 보유자의 평균 수익률. 백테스트 검증 구간: <0=바닥(BTC 100%), 0~1.5=저평가(75%), 1.5~2.5=과열 경계(45%), >2.5=과열(20%).",
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

        # ── 코인 공통: MVRV + regime + 90일 수익률 ─────────────────
        elif is_coin:
            if _mvrv_z_now is not None:
                _z = _mvrv_z_now
                if _z < 0:
                    _mz_lbl = "🟢 역사적 바닥 근접 (BTC 100% 구간)"
                elif _z < 1.5:
                    _mz_lbl = "🟢 저평가 (BTC 75% 구간)"
                elif _z < 2.5:
                    _mz_lbl = "🟠 과열 경계 (BTC 45% 구간)"
                else:
                    _mz_lbl = "🔴 과열 (BTC 20% 구간)"
                st.info(
                    f"**BTC MVRV Z-Score {_z:.2f}** → {_mz_lbl}  \n"
                    "포트폴리오 신호의 근거. 코인 탭에서 전체 온체인 지표 확인 가능."
                )
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

