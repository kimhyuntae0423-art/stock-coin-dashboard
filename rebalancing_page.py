"""리밸런싱 페이지 — 코어-위성 자산배분 + 추천 포트폴리오."""
import streamlit as st
import pandas as pd
import numpy as np
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
from scripts.etf_recommend import (
    market_regime, score_etfs, tactical_alloc, enrich_with_volume,
    volume_signals, technical_signals,
)
from scripts.etf_rotation import rotation_target, PHASE_LABELS, PHASE_DESCS

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
NAMES["CASH"] = "💰 보유 현금"   # 현금 특수 행

# ── GitHub API 헬퍼 (파일 상단 정의 — 보유내역 편집·이력 트래커 공용) ──
import json as _rb_json

_RB_GH_OWNER = "kimhyuntae0423-art"
_RB_GH_REPO  = "stock-coin-dashboard"


def _rb_gh_token() -> str | None:
    for key in ("GH_PAT", "GITHUB_TOKEN"):
        try:
            return st.secrets[key]
        except Exception:
            continue
    return None


def _rb_gh_get(path: str) -> tuple[str | None, str | None]:
    """GitHub API에서 파일 내용(str)과 SHA를 반환. 없으면 (None, None)."""
    import requests as _req
    token = _rb_gh_token()
    if not token:
        return None, None
    url  = f"https://api.github.com/repos/{_RB_GH_OWNER}/{_RB_GH_REPO}/contents/{path}"
    resp = _req.get(url, headers={"Authorization": f"token {token}"}, timeout=10)
    if resp.status_code != 200:
        return None, None
    data = resp.json()
    import base64 as _b64
    content = _b64.b64decode(data["content"]).decode("utf-8")
    return content, data.get("sha")


def _rb_gh_put(path: str, content_str: str, msg: str) -> tuple[bool, str]:
    """GitHub API로 파일 커밋. (성공여부, 오류메시지) 반환."""
    import requests as _req, base64 as _b64
    token = _rb_gh_token()
    if not token:
        return False, "토큰 없음 (Streamlit Cloud secrets에 GH_PAT 미설정)"
    url     = f"https://api.github.com/repos/{_RB_GH_OWNER}/{_RB_GH_REPO}/contents/{path}"
    headers = {"Authorization": f"token {token}"}

    # 1단계: SHA 조회 (파일 업데이트에 필수)
    sha = None
    try:
        get_resp = _req.get(url, headers=headers, timeout=10)
        if get_resp.status_code == 200:
            sha = get_resp.json().get("sha")
        elif get_resp.status_code == 401:
            return False, "HTTP 401: 토큰 인증 실패 — Streamlit secrets의 GH_PAT를 확인하세요"
        elif get_resp.status_code == 403:
            return False, "HTTP 403: 토큰 권한 부족 — GH_PAT에 repo 쓰기 권한이 필요합니다"
    except Exception as ge:
        return False, f"GET 실패: {ge}"

    # 2단계: PUT으로 파일 저장
    payload = {
        "message": msg,
        "content": _b64.b64encode(content_str.encode("utf-8")).decode("ascii"),
    }
    if sha:
        payload["sha"] = sha
    try:
        resp = _req.put(url, headers=headers, json=payload, timeout=15)
        if resp.status_code in (200, 201):
            return True, ""
        # 422: SHA 충돌 → 최신 SHA 재조회 후 1회 재시도
        if resp.status_code == 422:
            try:
                sha2 = _req.get(url, headers=headers, timeout=10).json().get("sha")
                if sha2:
                    payload["sha"] = sha2
                    resp2 = _req.put(url, headers=headers, json=payload, timeout=15)
                    if resp2.status_code in (200, 201):
                        return True, ""
                    err2 = resp2.json().get("message", "") if resp2.content else ""
                    return False, f"재시도 실패 HTTP {resp2.status_code}: {err2}"
            except Exception:
                pass
        err_msg = resp.json().get("message", "") if resp.content else ""
        return False, f"HTTP {resp.status_code}: {err_msg}"
    except Exception as e:
        return False, str(e)


def _rb_load() -> list:
    content, _ = _rb_gh_get("rebalancing_history.json")
    if content is not None:
        try:
            return _rb_json.loads(content)
        except Exception:
            return []
    if _RB_HIST_FILE_PATH.exists():
        try:
            return _rb_json.loads(_RB_HIST_FILE_PATH.read_text(encoding="utf-8"))
        except Exception:
            return []
    return []


def _rb_save(hist: list) -> bool:
    """이력 저장. GitHub API 성공 시 True, 로컬만 저장 시 False."""
    json_str = _rb_json.dumps(hist, ensure_ascii=False, indent=2)
    if _rb_gh_token():
        ok, _ = _rb_gh_put("rebalancing_history.json", json_str, "data: 리밸런싱 이력 갱신")
        if ok:
            return True
    _RB_HIST_FILE_PATH.write_text(json_str, encoding="utf-8")
    return False


_RB_HIST_FILE_PATH = ROOT / "rebalancing_history.json"

# =====================================================================
# 공통 데이터 로드
# =====================================================================
st.title("⚖️ 리밸런싱")
st.caption("코어-위성 자산배분 추적 · 추천 분산 포트폴리오.")

holdings = _load_holdings()

# ── CASH 먼저 추출 (person 필터 전) ───────────────────────────────
# CASH 행은 person 필드 값에 무관하게 항상 집계
_cash_mask  = holdings["ticker"].str.upper() == "CASH"
if _cash_mask.any():
    _cr = holdings.loc[_cash_mask].copy()
    _cq = pd.to_numeric(_cr["qty"],       errors="coerce").fillna(0)
    _cb = pd.to_numeric(_cr["buy_price"], errors="coerce").fillna(1).replace(0, 1)
    cash_amount = float((_cq * _cb).sum())
else:
    cash_amount = 0.0
holdings    = holdings[~_cash_mask].copy()

all_persons = sorted([p for p in holdings["person"].unique() if p and str(p).strip()])
selected_person = st.selectbox(
    "👤 계산 대상",
    options=["전체"] + all_persons,
    index=0,
    key="rebal_person_filter",
)
if selected_person != "전체":
    holdings = holdings[holdings["person"] == selected_person].copy()

# ── 보유 내역 편집 ────────────────────────────────────────────────
_he_all_names      = [""] + sorted(set(NAMES.values()))
_he_name_to_ticker = {v: k for k, v in NAMES.items()}

if "_he_save_msg" in st.session_state:
    _msg, _ok = st.session_state.pop("_he_save_msg")
    if _ok:
        st.success(_msg)
    else:
        st.warning(_msg)

with st.expander("✏️ 보유 내역 관리 (줄 추가 · 편집 · 저장)", expanded=False):
    st.caption("새 행은 + 버튼으로 추가. 행 삭제는 체크박스 → Delete. 💰 보유 현금은 종목명에서 선택.")
    _he_full   = _load_holdings()
    if selected_person != "전체":
        _he_show   = _he_full[_he_full["person"] == selected_person].copy()
        _he_others = _he_full[_he_full["person"] != selected_person].copy()
    else:
        _he_show   = _he_full.copy()
        _he_others = pd.DataFrame()

    _he_show.insert(0, "종목명", _he_show["ticker"].map(NAMES).fillna(""))
    _he_show = _he_show.rename(columns={
        "ticker": "티커", "qty": "수량", "buy_price": "매수가", "person": "이름", "notes": "메모"
    })
    _he_disp_cols = [c for c in ["종목명","티커","수량","매수가","이름","메모"] if c in _he_show.columns]

    _he_edited = st.data_editor(
        _he_show[_he_disp_cols],
        num_rows="dynamic",
        key=f"rebal_he_{selected_person}",
        column_config={
            "종목명": st.column_config.SelectboxColumn("종목명", options=_he_all_names, width="medium"),
            "티커":   st.column_config.TextColumn("티커", width="small"),
            "수량":   st.column_config.NumberColumn("수량", format="%.8g"),
            "매수가": st.column_config.NumberColumn("매수가", format="%,.0f"),
            "이름":   st.column_config.TextColumn("이름", width="small"),
            "메모":   st.column_config.TextColumn("메모"),
        },
        use_container_width=True,
    )

    if st.button("💾 저장 & GitHub 반영", key="rebal_he_save", type="primary", use_container_width=True):
        _he_cp = _he_edited.copy()
        for _hi, _hr in _he_cp.iterrows():
            _htk = str(_hr.get("티커", "") or "").strip()
            _hnm = str(_hr.get("종목명", "") or "").strip()
            if not _htk and _hnm:
                _he_cp.at[_hi, "티커"] = _he_name_to_ticker.get(_hnm, "")

        _he_cur = _he_cp.drop(columns=["종목명"]).rename(columns={
            "티커": "ticker", "수량": "qty", "매수가": "buy_price", "이름": "person", "메모": "notes"
        })
        _he_cur["buy_date"] = ""
        _he_cur = _he_cur[
            _he_cur["ticker"].astype(str).str.strip().str.upper().isin(["", "NONE", "NAN"]) == False
        ]
        if selected_person != "전체" and not _he_others.empty:
            _he_save = pd.concat([_he_cur, _he_others], ignore_index=True)
        else:
            _he_save = _he_cur.copy()

        (ROOT / "holdings.csv").write_text(_he_save.to_csv(index=False), encoding="utf-8")
        if _rb_gh_token():
            _he_ok, _he_err = _rb_gh_put("holdings.csv", _he_save.to_csv(index=False), "data: 보유 내역 갱신")
            if _he_ok:
                st.session_state["_he_save_msg"] = ("✅ GitHub에 저장됐습니다.", True)
            else:
                st.session_state["_he_save_msg"] = (f"⚠️ 로컬 저장됨. GitHub 저장 실패 — {_he_err}", False)
        else:
            st.session_state["_he_save_msg"] = ("⚠️ GITHUB_TOKEN 미설정 — 로컬에만 저장됐습니다.", False)
        st.rerun()

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

# ── 포트폴리오 전반 인사이트 ─────────────────────────────────────
_i_cycle  = pd.read_csv(RESULTS / "cycle_metrics.csv").iloc[0].to_dict() \
            if (RESULTS / "cycle_metrics.csv").exists() else {}
_i_csumf  = RESULTS / "coin_summary.csv"
_i_csum   = pd.read_csv(_i_csumf) if _i_csumf.exists() else pd.DataFrame()

try:
    import urllib.request as _iu, json as _ij
    with _iu.urlopen("https://api.frankfurter.app/latest?from=USD&to=KRW", timeout=3) as _ir:
        _i_fx = float(_ij.loads(_ir.read())["rates"]["KRW"])
except Exception:
    _i_fx = 1380.0

_i_etf_set = set(load_core_etfs()["ticker"].astype(str))
_i_cp = {str(r["ticker"]): float(r["close"]) * _i_fx for _, r in _i_csum.iterrows()} \
        if not _i_csum.empty else {}
_i_sp = dict(zip(summary["ticker"].astype(str), summary["close"])) \
        if not summary.empty else {}

# alloc 사전 계산 — Core-Satellite 슬라이더 세션 상태로 읽기 (첫 렌더 시 기본값 사용)
target_core      = int(st.session_state.get("tgt_core_", 80))
target_satellite = int(st.session_state.get("tgt_sat_",  10))
target_cash      = int(st.session_state.get("tgt_cash_", 10))
# cash_amount는 위에서 holdings.csv CASH 티커로 읽음 (세션 상태 불필요)
new_money        = float(st.session_state.get("new_money_input", 1_000_000))

view_alloc = holdings.copy()
if not summary.empty:
    view_alloc = view_alloc.merge(summary[["ticker", "close"]], on="ticker", how="left")
else:
    view_alloc["close"] = None

core_etfs = load_core_etfs()
core_set  = set(core_etfs["ticker"].astype(str))
price_map_alloc = dict(zip(view_alloc["ticker"].str.upper(), view_alloc["close"]))
for _ct, _cp_val in _i_cp.items():
    price_map_alloc[str(_ct).upper()] = _cp_val
classified = classify_holdings(view_alloc, core_etf_tickers=core_set)
alloc = allocation_summary(classified, price_map_alloc, cash_amount=cash_amount)

_i_val = {"ETF": 0.0, "주식": 0.0, "코인": 0.0}
for _, _hr in holdings.iterrows():
    _t, _q = str(_hr["ticker"]), float(_hr["qty"])
    if "-USD" in _t:
        _i_val["코인"] += _q * _i_cp.get(_t, 0.0)
    elif _t in _i_etf_set:
        _i_val["ETF"] += _q * float(_i_sp.get(_t, 0.0))
    else:
        _i_val["주식"] += _q * float(_i_sp.get(_t, 0.0))

_i_total = sum(_i_val.values()) or 1.0
_i_pct   = {k: v / _i_total * 100 for k, v in _i_val.items()}

_i_mvrv  = float(_i_cycle.get("mvrv_z", 0.0))
_i_alt   = float(_i_cycle.get("alt_season_score", 0.0))

# 인사이트 카드 데이터 생성  (emoji, title, bg, border, badge, detail)
_i_cards = []

# 1. 코인 비중
_coin_over = _i_pct["코인"] - 15
if _coin_over > 20:
    _i_cards.append((
        "🔴", "코인 비중 과다", "#fff1f2", "#ef4444",
        f"현재 {_i_pct['코인']:.0f}% — 목표(10~15%)의 {_i_pct['코인']/15:.1f}배",
        f"전체 자산의 약 절반({_i_pct['코인']:.0f}%)이 코인 한 곳에 집중돼 있습니다. "
        f"코인은 주식 대비 변동성이 3~5배 높은 자산이라, 이 비중에서 BTC가 30% 하락하면 "
        f"포트폴리오 전체가 약 15% 이상 손실을 봅니다. "
        f"목표 10~15%는 상승 잠재력을 유지하면서도 한 번의 급락이 전체 자산을 흔들지 않도록 설계된 수준입니다. "
        f"다만 지금 당장 모두 파는 것은 저점 매도가 될 수 있습니다 — "
        f"아래 MVRV 로드맵이 트리거를 켜줄 때 그룹별로 단계적으로 줄이세요.",
    ))
elif _coin_over > 0:
    _i_cards.append((
        "🟠", "코인 비중 초과", "#fff7ed", "#f97316",
        f"현재 {_i_pct['코인']:.0f}% — 목표(15%) 대비 {_coin_over:.0f}%p 초과",
        f"목표 범위를 {_coin_over:.0f}%p 벗어나 있습니다. "
        f"아래 로드맵에서 트리거가 켜진 그룹부터 선별 정리하면 "
        f"큰 손실 없이 목표 범위 안으로 들어올 수 있습니다.",
    ))
else:
    _i_cards.append((
        "🟢", "코인 비중 양호", "#f0fdf4", "#22c55e",
        f"현재 {_i_pct['코인']:.0f}% — 목표 범위(10~15%) 이내",
        f"코인 비중이 목표 범위 안에 있습니다. "
        f"현 포지션을 유지하면서 ETF 코어 비중을 점진적으로 늘려가는 방향으로 전략을 이어가세요.",
    ))

# 2. ETF 코어 비중
if _i_pct["ETF"] < 20:
    _etf_ratio = _i_pct["주식"] / max(_i_pct["ETF"], 0.1)
    _i_cards.append((
        "🟠", "ETF 코어 비중 낮음", "#fff7ed", "#f97316",
        f"현재 {_i_pct['ETF']:.0f}% — 개별주({_i_pct['주식']:.0f}%)의 약 {_etf_ratio:.0f}분의 1 수준",
        f"코어-새틀라이트 전략에서 ETF(코어)는 포트폴리오의 닻 역할입니다. "
        f"코어가 탄탄해야 코인이나 개별주에서 손실이 와도 전체 자산이 버팁니다. "
        f"지금은 개별주({_i_pct['주식']:.0f}%)가 ETF({_i_pct['ETF']:.0f}%)보다 약 {_etf_ratio:.0f}배 커서 "
        f"위성이 코어보다 큰 역전 구조입니다. "
        f"월급이 들어올 때마다 코인이나 개별주를 추가 매수하지 말고 "
        f"S&P500 ETF(360200.KS) 적립에만 집중하세요. "
        f"이렇게만 해도 별도 매도 없이 코인 비중이 서서히 희석됩니다.",
    ))
elif _i_pct["ETF"] < 40:
    _i_cards.append((
        "🔵", "ETF 코어 확대 중", "#eff6ff", "#3b82f6",
        f"현재 {_i_pct['ETF']:.0f}% — 목표(40% 이상)로 성장 중",
        f"ETF 코어 비중이 목표 방향으로 성장하고 있습니다. "
        f"꾸준한 적립을 이어가세요. "
        f"코어가 40%를 넘으면 코인·개별주에서 일시적 손실이 와도 "
        f"포트폴리오 전체가 안정적으로 버티는 구조가 됩니다.",
    ))
else:
    _i_cards.append((
        "🟢", "ETF 코어 양호", "#f0fdf4", "#22c55e",
        f"현재 {_i_pct['ETF']:.0f}% — 안정적 코어 확보",
        f"안정적인 코어 비중({_i_pct['ETF']:.0f}%)이 확보된 상태입니다. "
        f"코어가 흔들리지 않으면 위성 자산에서 일시적 손실이 와도 전체 포트폴리오가 버팁니다. "
        f"현재 전략의 방향을 유지하세요.",
    ))

# 3. 코인 사이클 (MVRV)
if _i_mvrv < 0:
    _i_cards.append((
        "💎", "코인 사이클: 극단 바닥", "#faf5ff", "#7e22ce",
        f"시장 온도 지수 {_i_mvrv:.2f} — 코인 보유자 평균이 손실 중인 바닥 구간",
        f"'코인 시장 온도 지수'는 비트코인을 가진 사람들이 평균적으로 얼마나 수익 또는 손실 상태인지를 "
        f"숫자로 보여주는 지표입니다. 현재 {_i_mvrv:.2f}는 0 아래로 내려간 상태로, "
        f"BTC를 보유한 사람 대부분이 지금 팔면 손해를 보는 구간이라는 뜻입니다. "
        f"역사상 이 구간에서 BTC를 팔았던 투자자는 대부분 후회했습니다. "
        f"불안하더라도 이 구간은 기다리는 것이 맞습니다. "
        f"오히려 여유가 있다면 BTC 소량 적립을 고려할 만한 타이밍입니다.",
    ))
elif _i_mvrv < 1.5:
    _i_cards.append((
        "🟢", "코인 사이클: 저평가 구간", "#f0fdf4", "#22c55e",
        f"시장 온도 지수 {_i_mvrv:.2f} — 아직 차가운 편 (1.5 넘으면 주의 / 2.5 넘으면 과열)",
        f"'코인 시장 온도 지수'는 BTC 보유자들이 평균적으로 얼마나 수익 상태인지를 숫자로 보여줍니다. "
        f"0에 가까울수록 '아직 달아오르지 않은 저온 구간', 2.5를 넘으면 '과열 위험 구간'입니다. "
        f"현재 {_i_mvrv:.2f}는 역사적으로 BTC 강세장이 본격 시작되기 전 바닥~초입 구간과 유사한 수준입니다. "
        f"2020년 10월, 2023년 1월에도 이와 비슷한 수치에서 이후 수배의 상승이 나왔습니다. "
        f"지금 손실이 크다고 서둘러 매도하면 상승분을 고스란히 놓치게 됩니다. "
        f"BTC·ETH 같은 주요 자산은 유지하면서, "
        f"회복 가능성이 낮은 소형 알트(TRUMP·MASK·ZETA·SAND·ID)만 "
        f"다음 반등 시 아래 로드맵에 따라 선별 정리하세요. "
        f"이 지수가 1.5를 넘어갈 때부터 매도 액션을 시작하면 됩니다.",
    ))
elif _i_mvrv < 2.5:
    _i_cards.append((
        "🟠", "코인 사이클: 과열 경계 진입", "#fff7ed", "#f97316",
        f"시장 온도 지수 {_i_mvrv:.2f} — 따뜻해지는 중, 1단계 매도 시점",
        f"'코인 시장 온도 지수'가 {_i_mvrv:.2f}로 '따뜻한 구간'에 진입했습니다. "
        f"과거 BTC 사이클에서 이 범위(1.5~2.5)는 '중간 과열' 구간에 해당합니다. "
        f"BTC는 아직 추가 상승 여지가 있었지만, "
        f"소형 알트는 이미 정점을 넘기는 경우가 많았습니다. "
        f"아래 로드맵의 Group 1·2 매도 트리거가 켜진 상태입니다. "
        f"두려움과 탐욕 모두 내려놓고 계획대로 단계적 매도를 실행할 때입니다.",
    ))
else:
    _i_cards.append((
        "🔴", "코인 사이클: 과열 구간", "#fff1f2", "#ef4444",
        f"시장 온도 지수 {_i_mvrv:.2f} — 뜨거운 구간, 역사적 고점 경계",
        f"'코인 시장 온도 지수'가 {_i_mvrv:.2f}로 '뜨거운 구간'에 들어왔습니다. "
        f"2.5 이상은 역사적으로 BTC 사이클 고점 근처에서 나타났던 수준으로, "
        f"2013·2017·2021년 사이클 모두 이 구간 이후 50~80%의 대규모 하락이 왔습니다. "
        f"지금은 '더 오를 것 같다'는 유혹이 강하게 드는 시점이지만, "
        f"바로 그 감정이 투자자를 가장 크게 망치는 함정입니다. "
        f"계획대로 코인 비중을 지금 줄이세요.",
    ))

# 4. 알트 시즌 지수
if _i_alt < 25:
    _i_cards.append((
        "🟠", "비트코인 시즌 — 알트 부진", "#fff7ed", "#f97316",
        f"알트 시즌 점수 {_i_alt:.0f}/100 — BTC 지배 장세",
        f"알트 시즌 지수는 최근 90일간 주요 알트코인 중 BTC 대비 수익률이 높은 비율로 계산됩니다. "
        f"{_i_alt:.0f}/100은 BTC가 거의 모든 알트를 앞서는 '비트코인 지배 장세'입니다. "
        f"역사적 사이클 패턴을 보면 ① BTC 선행 상승 → ② ETH로 유동성 이동 → "
        f"③ 소형 알트까지 확산 순서를 밟습니다. 지금은 첫 번째 단계입니다. "
        f"이 환경에서 알트를 추가 매수하면 BTC 대비 크게 뒤처질 가능성이 높습니다. "
        f"신규 자금은 S&P500 ETF 적립에 집중하고, "
        f"알트 시즌 점수가 50을 넘을 때를 보유 알트의 출구로 노리세요.",
    ))
elif _i_alt > 75:
    _i_cards.append((
        "💎", "알트코인 시즌 — 알트 강세", "#faf5ff", "#7e22ce",
        f"알트 시즌 점수 {_i_alt:.0f}/100 — 알트 주도 장세",
        f"알트가 BTC를 앞서는 시즌입니다. "
        f"보유 알트의 손실이 빠르게 회복되는 구간이기도 합니다. "
        f"역사적으로 알트 시즌은 수주~수개월로 길지 않습니다. "
        f"아래 로드맵의 Group 1·2 알트를 MVRV 트리거와 맞춰 지금 단계적으로 정리하세요. "
        f"기다리다 놓치는 것보다 계획대로 실행하는 게 낫습니다.",
    ))
else:
    _i_cards.append((
        "🔵", "혼조 시즌 — 선별 장세", "#eff6ff", "#3b82f6",
        f"알트 시즌 점수 {_i_alt:.0f}/100 — BTC·알트 혼조",
        f"BTC와 알트가 혼조세를 보이는 구간입니다. "
        f"특정 섹터·종목이 강세를 보이는 선별적 장세로, "
        f"포트폴리오 전반보다 개별 자산의 신호를 더 세밀하게 확인해야 합니다.",
    ))

# 전체 요약 문단
_s_coin = (
    f"코인이 포트폴리오의 {_i_pct['코인']:.0f}%를 차지해 목표(10~15%)의 {_i_pct['코인']/15:.1f}배에 달하는 불균형 상태입니다."
    if _coin_over > 20 else
    f"코인이 목표(15%)를 {_coin_over:.0f}%p 초과한 {_i_pct['코인']:.0f}%입니다."
    if _coin_over > 0 else
    f"코인 비중({_i_pct['코인']:.0f}%)이 목표 범위(10~15%) 안에 있습니다."
)
_s_mvrv = (
    f"다만 코인 시장 온도 지수({_i_mvrv:.2f})가 아직 저온 구간이라 지금 파는 것은 저점 매도가 될 수 있습니다."
    if _i_mvrv < 1.5 else
    f"코인 시장 온도 지수({_i_mvrv:.2f})가 과열 경계에 진입했으니 단계적 매도를 시작할 타이밍입니다."
    if _i_mvrv < 2.5 else
    f"코인 시장 온도 지수({_i_mvrv:.2f})가 과열 구간으로 적극적인 코인 축소가 필요합니다."
)
_s_etf = (
    f"ETF 코어({_i_pct['ETF']:.0f}%)가 아직 낮아 월급을 ETF에 꾸준히 적립하는 것이 가장 효과적인 비중 조정 수단입니다."
    if _i_pct["ETF"] < 20 else
    f"ETF 코어({_i_pct['ETF']:.0f}%)는 목표(40%)에 근접 중이며 ETF 적립을 이어가야 합니다."
    if _i_pct["ETF"] < 40 else
    f"ETF 코어({_i_pct['ETF']:.0f}%)는 안정적으로 확보된 상태입니다."
)
_s_alt = (
    f"알트 시즌 점수 {_i_alt:.0f}/100으로 BTC 주도 장세가 이어지고 있어 알트 추가 매수는 당분간 불리합니다."
    if _i_alt < 25 else
    f"알트 시즌 점수 {_i_alt:.0f}/100으로 알트 강세장이 진행 중이니 보유 알트 반등을 출구로 활용하세요."
    if _i_alt > 75 else
    f"알트 시즌 점수 {_i_alt:.0f}/100으로 BTC·알트 혼조세입니다."
)
_i_summary_text = f"{_s_coin} {_s_mvrv} {_s_etf} {_s_alt}"

# 전체 가이드 (우선순위 순)
_i_guide = [
    (
        "①", "신규 자금은 ETF 적립에만",
        f"월급이 들어올 때마다 S&P500 ETF(360200.KS)에만 넣으세요. "
        f"지금 코인·개별주에 추가 투입하면 불균형이 더 깊어집니다.",
    ),
]
if _i_mvrv < 1.5:
    _i_guide.append((
        "②", "코인 매도 — 온도 지수 1.5까지 대기",
        f"현재 온도 지수 {_i_mvrv:.2f}는 저평가 구간입니다. "
        f"손실이 크더라도 지금 파는 건 최악의 타이밍입니다. "
        f"지수가 1.5를 넘을 때 아래 로드맵의 Group 1(소형 알트)부터 정리를 시작하세요.",
    ))
elif _i_mvrv < 2.5:
    _i_guide.append((
        "②", "코인 매도 — Group 1·2 단계적 매도 시작",
        f"온도 지수 {_i_mvrv:.2f}로 1단계 트리거 활성화. "
        f"아래 로드맵에서 TRUMP·MASK·ZETA·SAND·ID부터 정리를 시작하세요.",
    ))
else:
    _i_guide.append((
        "②", "코인 비중 즉시 축소",
        f"온도 지수 {_i_mvrv:.2f}로 과열 구간입니다. 모든 그룹 매도를 지금 실행하세요.",
    ))
if _i_alt < 25:
    _i_guide.append((
        "③", "알트 추가 매수 금지",
        f"BTC 주도 장세({_i_alt:.0f}/100)에서 알트를 사면 BTC 대비 손실을 보기 쉽습니다. "
        f"알트 시즌 점수가 50을 넘을 때까지 추가 매수를 참으세요.",
    ))
elif _i_alt > 75:
    _i_guide.append((
        "③", "알트 강세장 — 출구 기회 활용",
        f"알트 강세({_i_alt:.0f}/100) 구간입니다. Group 1·2 보유 알트 반등을 출구로 활용하세요.",
    ))
else:
    _i_guide.append((
        "③", "알트 신규 매수 자제",
        f"혼조 장세({_i_alt:.0f}/100). 신규 매수는 자제하고 기존 보유분을 유지하세요.",
    ))
_i_guide.append((
    "④", "월 1회 이 탭에서 점검",
    "온도 지수와 코인 비중이 바뀌면 위 가이드도 자동으로 바뀝니다. "
    "너무 자주 확인하면 감정 매매로 이어지니 월 1회만 점검하세요.",
))

# 렌더링
st.subheader("📊 포트폴리오 전반 인사이트")

# 전체 요약 + 우선순위 액션 (하나의 박스)
_guide_rows = []
for _gi, (_gn, _gt, _gb) in enumerate(_i_guide):
    _border = "border-bottom:1px solid #e2e8f0;" if _gi < len(_i_guide) - 1 else ""
    _guide_rows.append(
        f"<div style='padding:7px 0;{_border}'>"
        f"<span style='font-weight:700;color:#1e293b'>{_gn} {_gt}</span>"
        f"<span style='color:#4b5563'> — {_gb}</span></div>"
    )
_guide_html = "".join(_guide_rows)

st.markdown(
    f"<div style='background:#f1f5f9;border-radius:8px;padding:14px 16px;margin-bottom:14px'>"
    f"<div style='font-size:12px;font-weight:600;color:#64748b;margin-bottom:6px'>📝 전체 요약</div>"
    f"<div style='font-size:13px;color:#1e293b;line-height:1.75;margin-bottom:14px'>{_i_summary_text}</div>"
    f"<div style='height:1px;background:#cbd5e1;margin-bottom:10px'></div>"
    f"<div style='font-size:12px;font-weight:600;color:#64748b;margin-bottom:4px'>🎯 우선순위 액션</div>"
    f"<div style='font-size:13px;line-height:1.7'>{_guide_html}</div>"
    f"</div>",
    unsafe_allow_html=True,
)

# 신호 상세
st.markdown(
    "<div style='font-size:12px;font-weight:600;color:#64748b;margin-bottom:6px'>"
    "▸ 신호 상세</div>",
    unsafe_allow_html=True,
)
for _emoji, _title, _bg, _bd, _badge, _detail in _i_cards:
    st.markdown(
        f"<div style='background:{_bg};border-left:3px solid {_bd};"
        f"border-radius:6px;padding:10px 14px;margin-bottom:7px'>"
        f"<div style='margin-bottom:4px'>"
        f"<span style='font-weight:700;color:{_bd}'>{_emoji} {_title}</span>"
        f"<span style='color:#6b7280;font-size:12px;margin-left:8px'>| {_badge}</span></div>"
        f"<div style='color:#374151;font-size:13px;line-height:1.65'>{_detail}</div>"
        f"</div>",
        unsafe_allow_html=True,
    )

st.divider()
st.subheader("💼 보유 현황")
_h_regime = market_regime(summary)
_h_vix    = _h_regime.get("vix")
_h_vsig   = _h_regime.get("vix_signal", "")
if not holdings.empty:
    # portfolio_page.py와 동일한 방식으로 가격 합산 (주식 + 코인 KRW 변환)
    _ph_parts = []
    if not summary.empty:
        _ph_parts.append(summary[["ticker", "close"]].copy())
    if not _i_csum.empty:
        _ph_coin = _i_csum[["ticker", "close"]].copy()
        _ph_coin["close"] = _ph_coin["close"] * _i_fx
        _ph_parts.append(_ph_coin)
    _ph_prices = pd.concat(_ph_parts, ignore_index=True) if _ph_parts else pd.DataFrame(columns=["ticker", "close"])
    _ph_prices["ticker"] = _ph_prices["ticker"].astype(str).str.upper()

    _ph_view = holdings.copy()
    _ph_view["ticker"] = _ph_view["ticker"].astype(str).str.strip().str.upper()
    _ph_view = _ph_view.merge(_ph_prices, on="ticker", how="left")
    _ph_view["종목명"] = _ph_view["ticker"].map(NAMES).fillna(_ph_view["ticker"])
    _ph_view["평가금액"] = pd.to_numeric(_ph_view["qty"], errors="coerce") * pd.to_numeric(_ph_view["close"], errors="coerce")
    _ph_view["수익률(%)"] = (pd.to_numeric(_ph_view["close"], errors="coerce") / pd.to_numeric(_ph_view["buy_price"], errors="coerce") - 1) * 100
    _ph_view = _ph_view.dropna(subset=["평가금액"])
    _ph_view = _ph_view[_ph_view["평가금액"] > 0].copy()

    if not _ph_view.empty:
        _core_upper = {x.upper() for x in core_set}
        _ph_view["카테고리"] = _ph_view["ticker"].apply(
            lambda t: "코인" if "-USD" in t else ("코어 ETF" if t in _core_upper else "개별주")
        )
        _ph_view["버킷"] = _ph_view["카테고리"].map(
            {"코어 ETF": "🏛️ 코어", "개별주": "🎯 위성", "코인": "🎯 위성"}
        )
        _ph_total = _ph_view["평가금액"].sum()
        _ph_sorted = _ph_view.sort_values("평가금액", ascending=False)

        # 범례 라벨: [코어 ETF] 종목명  or  [개별주] 종목명  or  [코인] 종목명
        _pie_labels = [
            f"[{r['카테고리']}] {r['종목명']}  {r['수익률(%)']:+.1f}%"
            for _, r in _ph_sorted.iterrows()
        ]
        _pie_custom = [
            [r["종목명"], r["수익률(%)"], r["평가금액"], r["평가금액"]/_ph_total*100, r["카테고리"]]
            for _, r in _ph_sorted.iterrows()
        ]

        _fig_pie = go.Figure(go.Pie(
            labels=_pie_labels,
            values=_ph_sorted["평가금액"],
            customdata=_pie_custom,
            hole=0.42,
            hovertemplate="<b>%{customdata[0]}</b><br>카테고리: %{customdata[4]}<br>평가금액: %{customdata[2]:,.0f}원<br>수익률: %{customdata[1]:+.1f}%<br>비중: %{customdata[3]:.1f}%<extra></extra>",
            textinfo="percent",
            textfont=dict(size=11),
            showlegend=True,
        ))
        _fig_pie.update_layout(
            height=500,
            margin=dict(t=10, b=10, l=10, r=10),
            legend=dict(
                font=dict(size=11),
                x=1.01, y=0.5,
                xanchor="left", yanchor="middle",
                tracegroupgap=0,
            ),
            paper_bgcolor="rgba(0,0,0,0)",
        )
        st.plotly_chart(_fig_pie, use_container_width=True)

        _cat_order = {"코어 ETF": 0, "개별주": 1, "코인": 2}
        _tbl = _ph_sorted.copy()
        _tbl["_co"] = _tbl["카테고리"].map(_cat_order)
        _tbl = _tbl.sort_values(["_co", "평가금액"], ascending=[True, False]).drop(columns=["_co", "버킷"])
        _tbl["수량"]    = pd.to_numeric(_tbl["qty"], errors="coerce")
        _tbl["매수가"]  = pd.to_numeric(_tbl["buy_price"], errors="coerce")
        _tbl["현재가"]  = pd.to_numeric(_tbl["close"], errors="coerce")
        _tbl["원금"]    = _tbl["수량"] * _tbl["매수가"]
        _tbl["손익"]    = _tbl["평가금액"] - _tbl["원금"]
        _tbl["비중(%)"] = _tbl["평가금액"] / _ph_total * 100

        # ── 백테스트 기반 신호 추가 ─────────────────────────────────────────
        _res_dir = ROOT / "results"
        _vsigs, _tsigs = [], []
        for _tk in _tbl["ticker"]:
            _vsigs.append(volume_signals(str(_tk), _res_dir))
            _tsigs.append(technical_signals(str(_tk), _res_dir))

        # 1M 수익률 룩업 (summary_signals에서)
        _sum_latest = summary.sort_values("date").groupby("ticker").last().reset_index()
        _sum_latest["ticker"] = _sum_latest["ticker"].astype(str).str.upper()
        _ret1m_map = dict(zip(_sum_latest["ticker"], _sum_latest.get("return_1m_pct", pd.Series(dtype=float))))

        def _overheat_lbl(t, v):
            ma  = t.get("ma_score", 0) or 0
            bb  = t.get("bb_pct",   0.5) or 0.5
            vol = v.get("vol_ratio", 1.0) or 1.0
            if ma == 3 and bb > 0.85:
                return "⚠️ 과열" if vol < 1.3 else "🌡️ 과열+거래량"
            if ma >= 2 and bb > 0.7:
                return "🌡️ 상단근접"
            if ma <= 1 or bb < 0.3:
                return "❄️ 하단지지"
            return "➡️ 보통"

        def _action(row, t, v):
            ret      = float(row.get("수익률(%)") or 0)
            ret_1m   = float(_ret1m_map.get(str(row.get("ticker","")).upper()) or 0)
            vol_r    = float(v.get("vol_ratio") or 1.0)
            ma       = t.get("ma_score", 0) or 0
            bb       = float(t.get("bb_pct") or 0.5)
            overheat = ma == 3 and bb > 0.85
            vix_fear = _h_vix and _h_vix > 25

            # 백테스트 인사이트 우선순위 적용
            if overheat and ret > 20 and ret_1m < 0:
                return "⚠️ 분할매도 검토"   # 과열+모멘텀 꺾임
            if overheat and ret > 30:
                return "🌡️ 차익실현 고려"   # 과열+고수익
            if vix_fear and ret < -10:
                return "🔥 역발상 추가매수"  # VIX 극단 + 손실 = 매수 기회 (IC=0.14)
            if vol_r >= 1.4 and bb < 0.4:
                return "📈 거래량+저점 주목" # 거래량 급증 + 하단 = 매집 신호
            if ma <= 1 and ret < -15:
                return "❄️ 추세 약세 관망"
            return "✅ 유지"

        _tbl["과열신호"]  = [_overheat_lbl(t, v) for t, v in zip(_tsigs, _vsigs)]
        _tbl["거래량신호"] = [v.get("vol_label", "—") for v in _vsigs]
        _tbl["OBV추세"]   = [v.get("obv_slope") for v in _vsigs]
        _tbl["액션"]      = [_action(r, t, v)
                             for (_, r), t, v in zip(_tbl.iterrows(), _tsigs, _vsigs)]

        _tbl_show = _tbl[["카테고리", "종목명", "ticker", "수량", "매수가", "현재가",
                           "원금", "평가금액", "손익", "수익률(%)", "비중(%)",
                           "과열신호", "거래량신호", "OBV추세", "액션"]].copy()
        st.dataframe(
            _tbl_show, hide_index=True, use_container_width=True,
            column_config={
                "카테고리":   st.column_config.TextColumn("카테고리"),
                "종목명":     st.column_config.TextColumn("종목명"),
                "ticker":     st.column_config.TextColumn("티커"),
                "수량":       st.column_config.NumberColumn("수량", format="%.4f"),
                "매수가":     st.column_config.NumberColumn("매수가", format="%,.0f"),
                "현재가":     st.column_config.NumberColumn("현재가", format="%,.0f"),
                "원금":       st.column_config.NumberColumn("원금", format="%,.0f"),
                "평가금액":   st.column_config.NumberColumn("평가금액", format="%,.0f"),
                "손익":       st.column_config.NumberColumn("손익", format="%+,.0f"),
                "수익률(%)":  st.column_config.NumberColumn("수익률(%)", format="%+.2f"),
                "비중(%)":    st.column_config.NumberColumn("비중(%)", format="%.1f"),
                "과열신호":   st.column_config.TextColumn("과열신호",
                              help="MA=3+BB>0.85 = 과열(IC 역방향 확인). 과열일수록 향후 수익 낮은 경향"),
                "거래량신호": st.column_config.TextColumn("거래량",
                              help="거래량비율(IC=+0.04). 급증=기관 개입 추정"),
                "OBV추세":    st.column_config.NumberColumn("OBV(%)", format="%+.1f",
                              help="10일 OBV 변화율. 양수=매집, 음수=분배"),
                "액션":       st.column_config.TextColumn("백테스트 액션",
                              help="VIX·과열·거래량 신호 기반 행동 제안. 최종 결정은 직접 판단"),
            },
        )

        # ── 보유 종목 종합 분석 익스팬더 ────────────────────────────────────────
        with st.expander("📊 보유 종목 종합 분석", expanded=False):
            _an_summary = summary.sort_values("date").groupby("ticker").last().reset_index()
            _an_summary["ticker"] = _an_summary["ticker"].astype(str).str.upper()
            try:
                _an_coins = pd.read_csv(ROOT / "results" / "coin_summary.csv")
                _an_coins["ticker"] = _an_coins["ticker"].astype(str).str.upper()
            except Exception:
                _an_coins = pd.DataFrame()
            _an_fx = _i_fx  # 코인 KRW 환율

            _an_h = _tbl.copy()  # 이미 정렬된 보유 종목 (위에서 계산)

            # ── 한국주식 / ETF 분석 ──────────────────────────────────────────────
            _an_ks = _an_h[~_an_h["ticker"].str.contains("-USD", na=False)].copy()
            if not _an_ks.empty:
                st.markdown("#### 🇰🇷 한국주식 / ETF")

                _an_rows = []
                for _, r in _an_ks.iterrows():
                    tk   = str(r["ticker"]).upper()
                    vsig = volume_signals(tk, _res_dir)
                    tsig = technical_signals(tk, _res_dir)
                    smr  = _an_summary[_an_summary["ticker"] == tk]

                    state  = smr.iloc[0]["state"] if not smr.empty else "—"
                    r1m    = float(smr.iloc[0]["return_1m_pct"])  if not smr.empty and pd.notna(smr.iloc[0]["return_1m_pct"])  else None
                    r12m   = float(smr.iloc[0]["return_12m_pct"]) if not smr.empty and pd.notna(smr.iloc[0]["return_12m_pct"]) else None
                    rsi    = float(smr.iloc[0]["rsi14"])           if not smr.empty and pd.notna(smr.iloc[0]["rsi14"])          else None

                    ret   = float(r.get("수익률(%)") or 0)
                    ma    = tsig.get("ma_score", 0) or 0
                    bb    = float(tsig.get("bb_pct") or 0.5)
                    vol_r = float(vsig.get("vol_ratio") or 1.0)
                    vol_l = vsig.get("vol_label", "—")
                    ovheat = ma == 3 and bb > 0.85

                    # 액션 결정
                    if state == "bear":
                        if ret < -20:
                            action = "🔴 추세 역전 + 손실 — 포지션 재검토"
                        elif ret < 0:
                            action = "🔴 하락추세 — 추가매수 보류"
                        else:
                            action = "⚠️ 하락추세 — 차익실현 고려"
                    elif ovheat and ret > 30:
                        action = "🌡️ 과열 + 고수익 — 분할 차익실현"
                    elif ovheat and r1m is not None and r1m < 0:
                        action = "⚠️ 과열 + 모멘텀 꺾임 — 분할매도 검토"
                    elif "다이버전스" in vol_l and ret > 15:
                        action = "⚠️ 가격↑ 거래량↓ — 상승 지속력 주의"
                    elif bb < 0.2 and state == "bull":
                        action = "❄️ 하단 지지 구간 — 분할매수 검토"
                    elif vol_r >= 1.4 and state == "bull":
                        action = "📈 거래량 급증 — 추세 강세"
                    else:
                        action = "✅ 유지"

                    # 기술 등급
                    if state == "bear":
                        grade = "🔴 약세"
                    elif ovheat:
                        grade = "🌡️ 과열"
                    elif ma >= 2 and bb > 0.5:
                        grade = "🟢 강세"
                    else:
                        grade = "🟡 중립"

                    _an_rows.append({
                        "티커":     tk,
                        "종목명":   r.get("종목명", tk),
                        "수익률(%)": ret,
                        "추세":     f"{'🟢' if state=='bull' else '🔴'} {state}",
                        "1개월(%)":  r1m,
                        "12개월(%)": r12m,
                        "RSI":      rsi,
                        "기술등급":  grade,
                        "거래량":   vol_l,
                        "분석액션":  action,
                    })

                _an_ks_df = pd.DataFrame(_an_rows)
                # 기술등급 정렬: 약세 → 과열 → 중립 → 강세
                _grade_order = {"🔴 약세": 0, "🌡️ 과열": 1, "🟡 중립": 2, "🟢 강세": 3}
                _an_ks_df["_g"] = _an_ks_df["기술등급"].map(_grade_order).fillna(9)
                _an_ks_df = _an_ks_df.sort_values("_g").drop(columns=["_g"])

                st.dataframe(
                    _an_ks_df,
                    hide_index=True, use_container_width=True,
                    column_config={
                        "티커":      st.column_config.TextColumn("티커"),
                        "종목명":    st.column_config.TextColumn("종목명"),
                        "수익률(%)": st.column_config.NumberColumn("보유수익(%)", format="%+.1f"),
                        "추세":      st.column_config.TextColumn("추세"),
                        "1개월(%)":  st.column_config.NumberColumn("1개월(%)", format="%+.1f",
                                     help="한국 개별주 모멘텀 IC=0.065 (방향 맞으나 통계 미검증 — 참고용)"),
                        "12개월(%)": st.column_config.NumberColumn("12개월(%)", format="%+.1f",
                                     help="한국 개별주 모멘텀 IC=0.065 (방향 맞으나 통계 미검증 — 참고용)"),
                        "RSI":       st.column_config.NumberColumn("RSI", format="%.0f",
                                     help="70↑ 과열 / 30↓ 침체. 역방향 신호로 활용"),
                        "기술등급":  st.column_config.TextColumn("기술등급",
                                     help="추세+과열 복합 판단"),
                        "거래량":    st.column_config.TextColumn("거래량신호"),
                        "분석액션":  st.column_config.TextColumn("분석 액션",
                                     help="과열(IC 역방향 검증) + 추세(bear=손절 검토) 기반. 최종 결정은 직접 판단"),
                    },
                )
                st.caption("한국 개별주 모멘텀은 IC=0.065 — 방향은 맞으나 데이터 부족으로 통계 미검증. 과열·추세 신호 위주로 판단하세요.")

                # 긴급 알림
                _bear_holds = _an_ks_df[_an_ks_df["분석액션"].str.startswith("🔴", na=False)]
                _hot_holds  = _an_ks_df[_an_ks_df["분석액션"].str.startswith("🌡️", na=False)]
                if not _bear_holds.empty:
                    st.error(f"🔴 하락추세: {', '.join(_bear_holds['티커'])} — 추세 전환 확인 전 추가매수 자제 (bear추세 = 향후 수익 낮은 경향)")
                if not _hot_holds.empty:
                    st.warning(f"🌡️ 과열 차익실현 구간: {', '.join(_hot_holds['티커'])} — BB·MA 역방향 IC 검증됨, 일부 실현 고려")

            # ── 코인 분석 ────────────────────────────────────────────────────────
            _an_cu = _an_h[_an_h["ticker"].str.contains("-USD", na=False)].copy()
            if not _an_cu.empty and not _an_coins.empty:
                st.markdown("#### 🪙 코인")

                _coin_rows = []
                for _, r in _an_cu.iterrows():
                    tk  = str(r["ticker"]).upper()
                    row = _an_coins[_an_coins["ticker"] == tk]
                    if row.empty:
                        continue
                    cr   = row.iloc[0]
                    ret  = float(r.get("수익률(%)") or 0)
                    reg  = str(cr.get("regime", "—"))
                    r90  = float(cr.get("return_90d_pct") or 0)
                    rsi  = float(cr.get("rsi14") or 50)
                    act_c = str(cr.get("action", "—"))

                    # 코인 액션 판단
                    if ret < -80:
                        coin_action = "🔴 -80% 이상 손실 — 회복 불확실, 정리 검토"
                    elif ret < -60:
                        coin_action = "⚠️ 깊은 손실 — 핵심 코인 외 정리 고려"
                    elif ret < -30 and rsi < 35:
                        coin_action = "❄️ 누적 손실 + RSI 침체 — 분할 물타기 or 관망"
                    elif reg == "accumulation" and rsi < 40 and ret > -20:
                        coin_action = "📥 매집 국면 + RSI 침체 — 분할매수 고려"
                    elif reg == "accumulation":
                        coin_action = "📥 매집 국면 — 관망 유지"
                    else:
                        coin_action = "✅ 유지"

                    _coin_rows.append({
                        "티커":       tk,
                        "보유수익(%)": ret,
                        "코인국면":    reg,
                        "90d(%)":     r90,
                        "RSI":        rsi,
                        "코인액션":    act_c,
                        "분석액션":    coin_action,
                    })

                if _coin_rows:
                    _an_cu_df = pd.DataFrame(_coin_rows).sort_values("보유수익(%)")
                    st.dataframe(
                        _an_cu_df,
                        hide_index=True, use_container_width=True,
                        column_config={
                            "티커":        st.column_config.TextColumn("티커"),
                            "보유수익(%)": st.column_config.NumberColumn("보유수익(%)", format="%+.1f"),
                            "코인국면":    st.column_config.TextColumn("국면"),
                            "90d(%)":      st.column_config.NumberColumn("90일(%)", format="%+.1f"),
                            "RSI":         st.column_config.NumberColumn("RSI", format="%.0f"),
                            "코인액션":    st.column_config.TextColumn("코인신호"),
                            "분석액션":    st.column_config.TextColumn("분석 액션"),
                        },
                    )

                    # 심각한 손실 코인 경보
                    _deep_loss = _an_cu_df[_an_cu_df["보유수익(%)"] < -60]
                    _accum_ok  = _an_cu_df[
                        (_an_cu_df["코인국면"] == "accumulation") & (_an_cu_df["보유수익(%)"] > -30)
                    ]
                    if not _deep_loss.empty:
                        st.error(
                            f"🔴 60% 이상 손실 코인 {len(_deep_loss)}종: "
                            f"{', '.join(_deep_loss['티커'].tolist())} — "
                            "원금 회복에 각각 150~900% 상승 필요. 포지션 재검토 권장"
                        )
                    if not _accum_ok.empty:
                        st.info(
                            f"📥 매집 국면 + 손실 소폭: {', '.join(_accum_ok['티커'].tolist())} — "
                            "분할매수 검토 가능 구간 (단, 코인 변동성 유의)"
                        )

            st.caption(
                "분석 기준: 기술 신호(백테스트 IC 검증) + 코인 온체인 국면. "
                "최종 매수·매도 결정은 공식 공시·실적·본인 위험 감내 범위 확인 후 내리세요."
            )

st.divider()
st.subheader("📊 배분 현황 & 리밸런싱")

ic1, ic2, ic3 = st.columns(3)
with ic1:
    target_core = st.number_input("🏛️ 코어 목표 (%)", min_value=0, max_value=100, value=80, step=5, key="tgt_core_")
with ic2:
    target_satellite = st.number_input("🎯 위성 목표 (%)", min_value=0, max_value=100, value=10, step=5, key="tgt_sat_")
with ic3:
    target_cash = st.number_input("💵 현금 목표 (%)", min_value=0, max_value=100, value=10, step=5, key="tgt_cash_")
if target_core + target_satellite + target_cash != 100:
    st.warning(f"⚠️ 목표 비중 합계 {target_core + target_satellite + target_cash}% — 100%가 되도록 조정해주세요.")

aa1, aa2, aa3, aa4 = st.columns(4)
with aa1:
    st.metric("💼 총 자산", f"{alloc['Total']:,.0f}원")
    st.caption(f"보유 현금 {cash_amount:,.0f}원 포함 · CASH 행 관리")
aa2.metric("🏛️ 코어", f"{alloc['Core_pct']:.1f}%",
           delta=f"{alloc['Core_pct'] - target_core:+.1f}pp (목표 {target_core}%)", delta_color="off")
aa3.metric("🎯 위성", f"{alloc['Satellite_pct']:.1f}%",
           delta=f"{alloc['Satellite_pct'] - target_satellite:+.1f}pp (목표 {target_satellite}%)", delta_color="off")
with aa4:
    st.metric("💵 현금", f"{alloc['Cash_pct']:.1f}%",
              delta=f"{alloc['Cash_pct'] - target_cash:+.1f}pp (목표 {target_cash}%)", delta_color="off")
    st.caption(f"보유 현금: {cash_amount:,.0f}원")

if _h_vix:
    if _h_vix > 25:
        st.success(f"🔥 VIX {_h_vix:.0f} — {_h_vsig}  ·  백테스트 검증: 지금이 역발상 매수 타이밍 (IC=0.14)")
    elif _h_vix < 13:
        st.warning(f"🌡️ VIX {_h_vix:.0f} — {_h_vsig}  ·  과열 경계, 신규 매수 신중")
    else:
        st.info(f"VIX {_h_vix:.0f} — {_h_vsig}")

actions_alloc = rebalancing_actions(alloc, target_core, target_satellite, target_cash, threshold_pp=5.0)
if not actions_alloc:
    st.success("✅ 목표 배분에 ±5%p 이내. 리밸런싱 불필요.")

core_buy = sat_buy = cash_res = 0
if new_money > 0 and alloc["Total"] > 0:
    total_after = alloc["Total"] + new_money
    core_deficit  = max(0.0, total_after * target_core      / 100 - alloc["Core_value"])
    sat_deficit   = max(0.0, total_after * target_satellite / 100 - alloc["Satellite_value"])
    cash_deficit  = max(0.0, total_after * target_cash      / 100 - cash_amount)
    total_deficit = core_deficit + sat_deficit + cash_deficit
    if total_deficit > 0:
        scale    = min(1.0, new_money / total_deficit)
        core_buy = round(core_deficit * scale)
        sat_buy  = round(sat_deficit  * scale)
        cash_res = new_money - core_buy - sat_buy
    else:
        core_buy = sat_buy = 0
        cash_res = new_money

st.markdown("""
<style>
div[data-testid="stNumberInput"]:has(input[aria-label="추가 투자할 금액 (원)"]) [data-baseweb="input"] {
    border: none !important; background: transparent !important; box-shadow: none !important;
}
div[data-testid="stNumberInput"]:has(input[aria-label="추가 투자할 금액 (원)"]) input {
    font-size: 1.875rem !important; font-weight: 700 !important; font-family: inherit !important;
    padding: 0 !important; line-height: 1.2 !important; color: rgb(49,51,63) !important;
}
div[data-testid="stNumberInput"]:has(input[aria-label="추가 투자할 금액 (원)"]) button {
    display: none !important;
}
</style>
""", unsafe_allow_html=True)
mc1, mc2, mc3, mc4 = st.columns(4)
with mc1:
    new_money = st.number_input("추가 투자할 금액 (원)", min_value=0, value=2_000_000,
                                step=100_000, key="new_money_input")
mc2.metric("🏛️ 코어 매수", f"{core_buy:,.0f}원")
mc3.metric("🎯 위성 매수", f"{sat_buy:,.0f}원")
mc4.metric("💵 현금 유보", f"{cash_res:,.0f}원")

if new_money > 0 and alloc["Total"] > 0:
    total_after = alloc["Total"] + new_money
    new_core_pct = (alloc["Core_value"] + core_buy) / total_after * 100
    new_sat_pct  = (alloc["Satellite_value"] + sat_buy) / total_after * 100
    new_cash_pct = (cash_amount + cash_res) / total_after * 100
    st.caption(
        f"매수 후 예상 배분: 코어 **{new_core_pct:.1f}%** / 위성 **{new_sat_pct:.1f}%** / 현금 **{new_cash_pct:.1f}%** "
        f"(목표: {target_core}% / {target_satellite}% / {target_cash}%)"
    )

# ── 데이터 계산 ──────────────────────────────────────────────────────────
    _e_regime = market_regime(summary)
    _e_scored = score_etfs(core_etfs, summary, _e_regime["key"])
    _e_scored = enrich_with_volume(_e_scored, ROOT / "results")
    _e_alloc  = tactical_alloc(_e_scored, core_buy if core_buy > 0 else 1,
                               regime=_e_regime)
    _vix  = _e_regime.get("vix")
    _vsig = _e_regime.get("vix_signal", "—")

    _held_map: dict = {}
    _ranked = pd.DataFrame()
    if not _e_alloc.empty:
        if not holdings.empty:
            _h = holdings.copy()
            _h["ticker"] = _h["ticker"].astype(str).str.upper()
            _h = _h.merge(
                summary.sort_values("date").groupby("ticker").last()
                       .reset_index()[["ticker", "close"]].assign(
                           ticker=lambda d: d["ticker"].astype(str).str.upper()),
                on="ticker", how="left",
            )
            _h["보유금액"] = pd.to_numeric(_h["qty"], errors="coerce") * \
                              pd.to_numeric(_h["close"], errors="coerce")
            _h["수익률(%)"] = (pd.to_numeric(_h["close"], errors="coerce") /
                                pd.to_numeric(_h["buy_price"], errors="coerce") - 1) * 100
            _h_core = _h[_h["ticker"].isin(_e_alloc["ticker"].astype(str).str.upper())]
            _h_total = _h_core["보유금액"].sum()
            for _, _hr in _h_core.iterrows():
                _held_map[str(_hr["ticker"]).upper()] = {
                    "보유금액":    float(_hr["보유금액"] or 0),
                    "수익률(%)":   float(_hr.get("수익률(%)") or 0),
                    "현재비중(%)": float(_hr["보유금액"] / _h_total * 100) if _h_total > 0 else 0,
                }

        _ranked = _e_alloc.dropna(subset=["score"]).copy()
        _ranked = _ranked.reset_index(drop=True)
        _ranked["순위"] = range(1, len(_ranked) + 1)
        _ranked["ticker_u"] = _ranked["ticker"].astype(str).str.upper()
        _ranked["보유"] = _ranked["ticker_u"].apply(
            lambda t: "✅ 보유" if t in _held_map else "—"
        )
        _ranked["수익률(%)"] = _ranked["ticker_u"].apply(
            lambda t: _held_map[t]["수익률(%)"] if t in _held_map else None
        )
        _ranked["현재비중(%)"] = _ranked["ticker_u"].apply(
            lambda t: _held_map[t]["현재비중(%)"] if t in _held_map else 0.0
        )
        _ranked["전술비중(%)"] = _ranked["전술비중"].fillna(0) * 100
        _ranked["비중차이(%p)"] = _ranked["전술비중(%)"] - _ranked["현재비중(%)"]
        if core_buy > 0:
            _ranked["추천금액(원)"] = (_ranked["전술비중"] * core_buy).round(0)
            _ranked["추천수량"] = (_ranked["추천금액(원)"] / _ranked["close"]).apply(
                lambda x: int(x) if pd.notna(x) and x > 0 else 0
            )
        _ranked["배율"] = _ranked["사이클배율"].apply(
            lambda x: f"×{float(x):.2f}" if pd.notna(x) else "×1.00"
        )

        def _reb_action(row):
            ticker   = str(row["ticker_u"])
            held     = ticker in _held_map
            diff     = float(row["비중차이(%p)"])
            sig      = str(row.get("전환신호", ""))
            overheat = str(row.get("과열신호", ""))
            vol      = str(row.get("거래량신호", ""))
            ret      = float(row.get("수익률(%)") or 0)
            if held:
                if "과열+전환" in sig or ("⚠️ 과열" in overheat and "전환 주의" in sig):
                    return "🚨 즉시 축소"
                if "전환 주의" in sig or "모멘텀 둔화" in sig:
                    return "📉 비중 축소"
                if "⚠️ 과열" in overheat and ret > 25:
                    return "🌡️ 차익실현"
                if diff > 5 and "매집" in vol:
                    return "🚀 적극 추가매수"
                if diff > 3:
                    return "📈 추가매수"
                if diff < -5:
                    return "📉 비중 축소"
                return "✅ 유지"
            else:
                if "전환 주의" in sig or "❄️ 약세" == sig:
                    return "⛔ 매수 보류"
                if row.get("전술비중(%)") or 0 > 3 and "🔥" in sig:
                    return "🆕 신규매수 적극"
                if (row.get("전술비중(%)") or 0) > 2:
                    return "🆕 신규매수 검토"
                return "— 관망"

        _ranked["리밸런싱"] = _ranked.apply(_reb_action, axis=1)

    # ── 코어 ETF 로테이션 가이드 ──────────────────────────────────────────────
    st.markdown("---")
    if _e_alloc.empty:
        st.info("현재가 데이터 없음.")
    else:
        _spy_1m  = _e_regime.get("spy_1m",  0)
        _spy_12m = _e_regime.get("spy_12m", 0)
        _rot_df, _phase = rotation_target(_vix or 18.0, _spy_1m, _spy_12m, _e_scored, regime_dict=_e_regime)
        _rot_df = _rot_df[~_rot_df["US ETF"].str.upper().isin(["COPX", "XLV"])].reset_index(drop=True)

        _phase_label = PHASE_LABELS.get(_phase, _phase)
        _phase_desc  = PHASE_DESCS.get(_phase, "")
        if _phase == "fear":
            st.error(f"**{_phase_label}** — {_phase_desc}")
        elif _phase == "overheated":
            st.warning(f"**{_phase_label}** — {_phase_desc}")
        elif _phase == "recovery":
            st.info(f"**{_phase_label}** — {_phase_desc}")
        else:
            st.success(f"**{_phase_label}** — {_phase_desc}")

        # 총 보유금액 (역할 합산 전 기준 — 비중 분모)
        _total_held = sum(v.get("보유금액", 0) for v in _held_map.values()) or 1.0

        # 동일 역할 ETF 자동 인식: core_etfs rotation_role로 역할별 보유금액 합산
        if "rotation_role" in core_etfs.columns and _held_map:
            _role_map_dict = (
                core_etfs[["ticker", "rotation_role"]]
                .dropna(subset=["rotation_role"])
                .assign(ticker=lambda d: d["ticker"].astype(str).str.upper(),
                        rotation_role=lambda d: d["rotation_role"].astype(str).str.upper())
                .query("rotation_role != '' and rotation_role != 'NAN'")
                .set_index("ticker")["rotation_role"]
                .to_dict()
            )
            _role_amounts: dict = {}
            for _t, _role in _role_map_dict.items():
                if _t in _held_map:
                    _role_amounts[_role] = _role_amounts.get(_role, 0.0) + _held_map[_t]["보유금액"]
            for _role, _amt in _role_amounts.items():
                _held_map[_role] = {
                    "보유금액":    _amt,
                    "수익률(%)":   0.0,
                    "현재비중(%)": round(_amt / _total_held * 100, 1),
                }

        # 현재비중 = 역할별 보유가치 / 총자산 (KR ETF 포함, 분모 = alloc Total)
        _rot_total_pre = max(alloc.get("Total", 1), 1)
        _role_현재가치: dict = {}
        if not holdings.empty and not summary.empty:
            _rh2 = holdings.copy()
            _rh2["ticker"] = _rh2["ticker"].astype(str).str.upper()
            _rl2 = (summary.sort_values("date").groupby("ticker").last()
                    .reset_index()[["ticker","close"]]
                    .assign(ticker=lambda d: d["ticker"].astype(str).str.upper()))
            _rh2 = _rh2.merge(_rl2, on="ticker", how="left")
            _rh2["cur_val"] = (pd.to_numeric(_rh2["qty"], errors="coerce") *
                               pd.to_numeric(_rh2["close"], errors="coerce"))
            if "rotation_role" in core_etfs.columns:
                _rrole_map = (core_etfs[["ticker","rotation_role"]]
                              .dropna(subset=["rotation_role"])
                              .assign(ticker=lambda d: d["ticker"].astype(str).str.upper(),
                                      rotation_role=lambda d: d["rotation_role"].astype(str).str.upper())
                              .set_index("ticker")["rotation_role"].to_dict())
                for _, _rhr in _rh2.iterrows():
                    _rtk2  = str(_rhr["ticker"]).upper()
                    _rval2 = float(_rhr.get("cur_val") or 0)
                    _rrole2 = _rrole_map.get(_rtk2, "")
                    if _rrole2 and _rval2 > 0:
                        _role_현재가치[_rrole2] = _role_현재가치.get(_rrole2, 0) + _rval2
        _rot_df["현재비중(%)"] = _rot_df["US ETF"].apply(
            lambda t: round(_role_현재가치.get(str(t).upper(), 0) / _rot_total_pre * 100, 1)
        )
        # 기본비중·목표비중 → 전체 포트폴리오 대비(코어 목표비중 반영)
        _rot_df["기본비중(%)"] = (_rot_df["기본비중(%)"] * target_core / 100).round(1)
        _rot_df["목표비중(%)"] = (_rot_df["목표비중(%)"] * target_core / 100).round(1)
        _rot_df["차이(%p)"] = (_rot_df["목표비중(%)"] - _rot_df["현재비중(%)"]).round(1)

        # 코인 행 추가 — holdings 실제 보유 코인 각각
        _rot_total  = max(alloc.get("Total", 1), 1)
        _btc_target = float(target_satellite)  # 코인은 위성 버킷 — 위성 목표비중 연동
        _coin_rows  = []
        if not holdings.empty:
            for _, _chr in holdings.iterrows():
                _ctk  = str(_chr["ticker"]).upper()
                if "-USD" not in _ctk:
                    continue
                _cqty = float(_chr.get("qty") or 0)
                _cprc = _i_cp.get(str(_chr["ticker"]), 0)
                _cval = _cqty * _cprc
                _c현재 = round(_cval / _rot_total * 100, 1)
                _cname = NAMES.get(_ctk, _ctk.replace("-USD", ""))
                if _ctk == "BTC-USD":
                    _coin_rows.append({
                        "역할": "BTC", "US ETF": "BTC-USD", "ISA(원화)": "—", "계좌": "코인",
                        "기본비중(%)": _btc_target, "목표비중(%)": _btc_target,
                        "현재비중(%)": _c현재, "차이(%p)": round(_btc_target - _c현재, 1),
                        "설명": "비트코인 — 4년 사이클", "가이드비중(%)": None,
                    })
                else:
                    _coin_rows.append({
                        "역할": f"알트 ({_cname})", "US ETF": _ctk, "ISA(원화)": "—", "계좌": "코인",
                        "기본비중(%)": 0.0, "목표비중(%)": 0.0,
                        "현재비중(%)": _c현재, "차이(%p)": round(-_c현재, 1),
                        "설명": "알트코인 — BTC 전환 대기", "가이드비중(%)": None,
                    })
        if _coin_rows:
            _rot_df = pd.concat([_rot_df, pd.DataFrame(_coin_rows)], ignore_index=True)

        # 현금 행 추가 (target_cash 연동)
        _cash_현재 = round(cash_amount / _rot_total * 100, 1)
        _cash_row = pd.DataFrame([{
            "역할": "현금", "US ETF": "CASH", "ISA(원화)": "—", "계좌": "현금",
            "기본비중(%)": float(target_cash), "목표비중(%)": float(target_cash),
            "현재비중(%)": _cash_현재, "차이(%p)": round(float(target_cash) - _cash_현재, 1),
            "설명": "폭락 시 추가매수 탄약", "가이드비중(%)": None,
        }])
        _rot_df = pd.concat([_rot_df, _cash_row], ignore_index=True)

        # 현재금액 = 현재비중% × 현재총자산
        _rot_df["현재금액(원)"] = (_rot_df["현재비중(%)"] / 100 * _rot_total).round(0).astype("Int64")
        # _raw_need: 과/부족 판단용 내부 컬럼 (표 미표시) — 목표비중 대비 현재 차이(KRW)
        _rot_df["_raw_need"] = ((_rot_df["목표비중(%)"] - _rot_df["현재비중(%)"]) / 100 * _rot_total).round(0).astype("Int64")

        # ── 인사이트 기반 조정 ────────────────────────────────────────
        # ETF 신호 맵: _e_scored(백테스트 복합신호) 기반 — raw summary 재조회 없음
        _sig_map: dict = {}
        if not _e_scored.empty:
            _esc = _e_scored.copy()
            _esc["ticker"] = _esc["ticker"].astype(str).str.upper()
            for _, _sr in _esc.iterrows():
                _sig_map[str(_sr["ticker"])] = {
                    "rsi":   float(_sr.get("rsi14") or 50),
                    "ret1m": float(_sr.get("return_1m_pct") or 0),
                    "score": float(_sr.get("score") or 100),
                }
        # 코인 신호 맵: ticker → {rsi, ret90d, action}
        _csig_map: dict = {}
        if not _i_csum.empty:
            _csl = _i_csum.copy()
            _csl["ticker"] = _csl["ticker"].astype(str).str.upper()
            for _, _cr in _csl.iterrows():
                _csig_map[str(_cr["ticker"])] = {
                    "rsi":    float(_cr.get("rsi14") or 50),
                    "ret90d": float(_cr.get("return_90d_pct") or 0),
                    "action": str(_cr.get("action") or ""),
                    "regime": str(_cr.get("regime") or ""),
                }
        # 역할 → 구성 티커 맵
        _role_to_tks: dict = {}
        if "rotation_role" in core_etfs.columns:
            for _, _cer in core_etfs.iterrows():
                _ctk3  = str(_cer.get("ticker","")).strip().upper()
                _crole3 = str(_cer.get("rotation_role","")).strip().upper()
                if _ctk3 and _crole3 and _crole3 != "NAN":
                    _role_to_tks.setdefault(_crole3, []).append(_ctk3)

        # VIX 국면 (백테스트 검증, IC=0.14) — ETF 인사이트 핵심 드라이버
        _vix_key = _e_regime.get("key", "mixed")   # fear/complacent/bull/bear/mixed
        _vix_val = _e_regime.get("vix")

        def _get_role_signal(us_etf: str, account: str):
            """역할/코인별 신호 반환 — 검증된 지표만 사용.

            Returns: (rsi, ret, is_coin, regime, vix_key, action, avg_score)
              - 코인: action = coin_backtest 액션(매수/보유/매도), avg_score = 0
              - ETF:  action = "", avg_score = 역할 구성 티커 평균 score
            """
            _uk = str(us_etf).upper()
            if account == "코인" or "-USD" in _uk:
                _cs = _csig_map.get(_uk, {})
                return (float(_cs.get("rsi", 50)), float(_cs.get("ret90d", 0)),
                        True, str(_cs.get("regime", "")), "",
                        str(_cs.get("action", "")), 0.0)
            _tks = _role_to_tks.get(_uk, [])
            if not _tks:
                return 50.0, 0.0, False, "", _vix_key, "", 100.0
            _rsis   = [_sig_map[t]["rsi"]   for t in _tks if t in _sig_map]
            _rets   = [_sig_map[t]["ret1m"] for t in _tks if t in _sig_map]
            _scores = [_sig_map[t]["score"] for t in _tks if t in _sig_map]
            _avg_sc = sum(_scores)/len(_scores) if _scores else 100.0
            return (sum(_rsis)/len(_rsis) if _rsis else 50.0,
                    sum(_rets)/len(_rets) if _rets else 0.0,
                    False, "", _vix_key, "", _avg_sc)

        # regime 한글 레이블 (coin_backtest 검증 기준)
        _REGIME_KR = {
            "accumulation": "매집",
            "markup":       "상승",
            "distribution": "배분",
            "markdown":     "하락",
        }
        # VIX 국면 한글 레이블 (etf_recommend 검증 기준)
        _VIX_KR = {
            "fear":       "공포 극단",
            "bear":       "약세 구간",
            "mixed":      "혼조",
            "bull":       "강세 구간",
            "complacent": "과열 경계",
        }

        # ── 패스 1: 인사이트 텍스트 생성 ──────────────────────────────────────
        # 추가금액은 무조건 new_money 배분 — 인사이트는 참고 텍스트만
        _buy_eligible: list = []  # 부족한 행(차이(%p)>0) 여부 — 추가금액 배분 대상
        _insights: list = []

        for _, _rr in _rot_df.iterrows():
            _raw  = int(_rr.get("_raw_need") or 0)
            _uk   = str(_rr.get("US ETF", "")).upper()
            _acct = str(_rr.get("계좌", ""))
            _insight = ""

            # 현금 행 — 신호 없음
            if _acct == "현금" or _uk == "CASH":
                _buy_eligible.append(False)
                _insights.append("")
                continue

            # 부족한 행만 추가금액 배분 대상
            _eligible = _raw > 5000

            _rsi_v, _ret_v, _is_coin, _regime_v, _vix_k, _action_v, _avg_score = _get_role_signal(_uk, _acct)
            _regime_kr = _REGIME_KR.get(_regime_v, "")
            _vix_kr    = _VIX_KR.get(_vix_k, "혼조")
            # ETF score → 액션 레이블 (백테스트 복합점수 기반)
            _score_label = ("📈 매수 강세" if _avg_score > 108 else
                            "🟢 매수 우호" if _avg_score > 100 else
                            "🔵 중립"      if _avg_score > 92  else "📉 매수 약화")

            _diff_pp = round(float(_rr.get("차이(%p)") or 0), 1)

            if _is_coin:
                # 코인: regime(coin_backtest ✅) + RSI<30(58% ✅)
                _rsi_str = f"RSI {_rsi_v:.0f}"
                _act_prefix = f"[백테스트 액션: {_action_v}]  " if _action_v else ""
                _0 = f"비중 {_diff_pp:+.1f}%p, 추가금액 0(달성)"
                _b = f"비중 {_diff_pp:+.1f}%p 부족"
                _o = f"비중 {abs(_diff_pp):.1f}%p 초과"
                if _raw < -5000:  # 비중 초과
                    if _regime_v == "accumulation":
                        _insight = _act_prefix + f"🟡 매집({_rsi_str}) — 바닥권, 매도 보류. {_o}"
                    elif _regime_v == "distribution":
                        _insight = _act_prefix + f"🔴 배분({_rsi_str}) — 고점 경계, 익절 고려. {_o}"
                    elif _regime_v == "markup":
                        _insight = _act_prefix + f"🟢 상승({_rsi_str}) — 추세 강함, 점진 축소. {_o}"
                    elif _rsi_v < 30:
                        _insight = _act_prefix + f"🟡 과매도({_rsi_str}, 58%) — 저점 매도 위험, 보류. {_o}"
                    else:
                        _insight = _act_prefix + f"🔵 {_regime_kr}({_rsi_str}) — 축소 고려. {_o}"
                elif _raw > 5000:  # 비중 부족
                    if _regime_v == "accumulation" and _rsi_v < 30:
                        _insight = _act_prefix + f"🎯 매집+과매도({_rsi_str}, 58%) — 최적 진입. {_b} → 적극 매수"
                    elif _regime_v == "accumulation":
                        _insight = _act_prefix + f"🟢 매집({_rsi_str}) — 바닥 형성. {_b} → 분할 매수"
                    elif _regime_v == "distribution":
                        _insight = _act_prefix + f"🔴 배분({_rsi_str}) — 고점 위험, 매수 보류. {_b}"
                    elif _regime_v == "markdown":
                        _insight = _act_prefix + f"⚠️ 하락({_rsi_str}) — 추세 약함. {_b} → 소량 분할만"
                    elif _rsi_v < 30:
                        _insight = _act_prefix + f"🎯 과매도({_rsi_str}, 58%) — 반등 확률 높음. {_b} → 매수"
                    else:
                        _insight = _act_prefix + f"🔵 {_regime_kr}({_rsi_str}). {_b} → 매수"
                else:  # 비중 균형
                    if _regime_v in ("accumulation", "markup"):
                        _icon = "🟢"
                        _insight = _act_prefix + f"{_icon} {_regime_kr}({_rsi_str}) — 매수 신호 우호적. {_0}"
                    elif _regime_v == "distribution":
                        _insight = _act_prefix + f"🔴 배분({_rsi_str}) — 매도 고려. {_0}"
                    elif _regime_v:
                        _insight = _act_prefix + f"🔵 {_regime_kr}({_rsi_str}). {_0}"
            else:
                # ETF: VIX 국면(IC=0.14 ✅) + RSI<30(58% ✅) + 백테스트 복합점수
                _vix_str = f"VIX {_vix_val:.0f}" if _vix_val else _vix_kr
                _rsi_str = f"RSI {_rsi_v:.0f}"
                _sc_pfx  = f"[{_score_label} {_avg_score:.0f}pt]  "
                _0 = f"비중 {_diff_pp:+.1f}%p, 추가금액 0(달성)"
                _b = f"비중 {_diff_pp:+.1f}%p 부족"
                _o = f"비중 {abs(_diff_pp):.1f}%p 초과"
                if _raw < -5000:  # 비중 초과
                    if _vix_k == "fear":
                        _insight = _sc_pfx + f"🔥 공포극단({_vix_str}) — 저점 매도 위험, 보류. {_o}"
                    elif _rsi_v < 30:
                        _insight = _sc_pfx + f"🟡 과매도({_rsi_str}, 58%) — 반등 가능, 매도 보류. {_o}"
                    elif _vix_k == "complacent":
                        _insight = _sc_pfx + f"🌡️ 과열({_vix_str}, {_rsi_str}) — 차익실현 고려. {_o}"
                    else:
                        _insight = _sc_pfx + f"🔵 {_vix_kr}({_vix_str}, {_rsi_str}) — 축소 고려. {_o}"
                elif _raw > 5000:  # 비중 부족
                    if _vix_k == "fear":
                        _insight = _sc_pfx + f"🔥 공포극단({_vix_str}) — 역발상 매수 타이밍(IC=0.14). {_b}"
                    elif _rsi_v < 30:
                        _insight = _sc_pfx + f"🎯 과매도({_rsi_str}, 58%)+{_vix_kr} — 이중 신호. {_b} → 적극 매수"
                    elif _vix_k == "complacent":
                        _insight = _sc_pfx + f"🌡️ 과열({_vix_str}, {_rsi_str}) — 고점 주의. {_b} → 소량만"
                    elif _vix_k == "bear":
                        _insight = _sc_pfx + f"⚠️ 약세({_vix_str}, {_rsi_str}) — 하락 압력. {_b} → 분할 매수"
                    else:
                        _insight = _sc_pfx + f"🟢 {_vix_kr}({_vix_str}, {_rsi_str}). {_b} → 매수"
                else:  # 비중 균형
                    if _vix_k in ("fear", "bear"):
                        _insight = _sc_pfx + f"🟢 {_vix_kr}({_vix_str}, {_rsi_str}) — 매수 신호 우호적. {_0}"
                    elif _vix_k == "complacent":
                        _insight = _sc_pfx + f"🌡️ 과열({_vix_str}, {_rsi_str}) — 고점 주의. {_0}"
                    else:
                        _insight = _sc_pfx + f"🔵 {_vix_kr}({_vix_str}, {_rsi_str}). {_0}"

            _buy_eligible.append(_eligible)
            _insights.append(_insight)

        _rot_df["인사이트"] = _insights

        # ── 행 버킷 분류 ──────────────────────────────────────────────────────
        def _row_bucket(row):
            _acct = str(row.get("계좌", ""))
            _us   = str(row.get("US ETF", ""))
            if _acct == "현금" or _us == "CASH":
                return "cash"
            elif _acct == "코인" or "-USD" in _us:
                return "satellite"
            return "core"

        _buckets = [_row_bucket(_rot_df.iloc[i]) for i in range(len(_rot_df))]

        # ── 추가금액 배분: new_money를 부족한 행에 비례 배분 ──────────────────
        # 매도는 인사이트 텍스트 참고 — 추가금액은 항상 0 이상
        _bucket_budgets = {"core": core_buy, "satellite": sat_buy, "cash": cash_res}
        _bucket_def = {"core": [], "satellite": [], "cash": []}
        for i in range(len(_rot_df)):
            if _buy_eligible[i]:
                _d = max(0, float(_rot_df.iloc[i]["_raw_need"] or 0))
                _bucket_def[_buckets[i]].append((i, _d))

        _buy_amts = [0] * len(_rot_df)
        for _bkt, _rows in _bucket_def.items():
            _tot = sum(d for _, d in _rows) or 1.0
            _bud = _bucket_budgets[_bkt]
            for _idx, _d in _rows:
                _buy_amts[_idx] = round(_d / _tot * _bud)

        # 현금 행에 cash_res 직접 배정 → 합계가 정확히 new_money
        for _ci in range(len(_rot_df)):
            if str(_rot_df.iloc[_ci].get("US ETF", "")).upper() == "CASH":
                _buy_amts[_ci] = cash_res
                break

        _rot_df["추가금액(원)"] = _buy_amts
        # 목표금액 = 현재금액 + 추가금액 (항등식 — 항상 일치)
        _rot_df["목표금액(원)"] = (_rot_df["현재금액(원)"].astype(float) +
                                   _rot_df["추가금액(원)"].astype(float)).round(0).astype("Int64")
        _rot_df.drop(columns=["_raw_need"], inplace=True)

        # 합계 행
        _rot_total_sum  = int(_rot_df["현재금액(원)"].sum())
        _rot_add_sum    = int(_rot_df["추가금액(원)"].sum())
        _rot_target_sum = _rot_total_sum + _rot_add_sum
        _rot_sum = pd.DataFrame([{
            "역할": "합계", "US ETF": "", "ISA(원화)": "", "계좌": "",
            "기본비중(%)": round(_rot_df["기본비중(%)"].sum(), 1),
            "목표비중(%)": float(target_core + target_satellite + target_cash),
            "현재비중(%)": 100.0,
            "차이(%p)":   round(float(target_core + target_satellite + target_cash) - 100.0, 1),
            "현재금액(원)": _rot_total_sum,
            "추가금액(원)": _rot_add_sum,
            "목표금액(원)": _rot_target_sum,
            "인사이트": "", "설명": "", "가이드비중(%)": None,
        }])
        _rot_df = pd.concat([_rot_df, _rot_sum], ignore_index=True)

        # 합계 행 강조 스타일
        _disp_cols = ["역할", "US ETF", "ISA(원화)", "계좌",
                      "목표비중(%)", "현재비중(%)", "차이(%p)",
                      "목표금액(원)", "현재금액(원)", "추가금액(원)", "인사이트"]
        _rot_disp = _rot_df[_disp_cols].copy()
        def _style_sum_row(df):
            styles = pd.DataFrame("", index=df.index, columns=df.columns)
            styles.iloc[-1] = "background-color: #1e3a5f; font-weight: bold; color: #e2e8f0"
            return styles
        st.dataframe(
            _rot_disp.style.apply(_style_sum_row, axis=None),
            hide_index=True, use_container_width=True,
            column_config={
                "역할":        st.column_config.TextColumn("역할",        width="small"),
                "US ETF":     st.column_config.TextColumn("US ETF",      width="small"),
                "ISA(원화)":  st.column_config.TextColumn("ISA(원화)",   width="medium",
                               help="ISA 계좌에서 매수할 국내 상장 ETF. '—'이면 ISA 불가(세금 22%)."),
                "계좌":        st.column_config.TextColumn("계좌",        width="small"),
                "목표비중(%)": st.column_config.NumberColumn("목표비중(%)", format="%.1f%%", width="small",
                                help="VIX 국면 기반 전략 목표 비중"),
                "현재비중(%)": st.column_config.NumberColumn("현재비중(%)", format="%.1f%%", width="small"),
                "차이(%p)":    st.column_config.NumberColumn("차이(%p)",  format="%+.1f",  width="small",
                                help="목표비중 − 현재비중. 양수=부족(매수), 음수=초과(매도)"),
                "현재금액(원)": st.column_config.NumberColumn("현재금액", format="%,d", width="small"),
                "추가금액(원)": st.column_config.NumberColumn("추가금액", format="%,d", width="small",
                                help="오늘 추가 투자금에서 이 역할에 배분되는 금액"),
                "목표금액(원)": st.column_config.NumberColumn("목표금액", format="%,d", width="small",
                                help="현재금액 + 추가금액"),
                "인사이트":    st.column_config.TextColumn("신호 & 행동 가이드", width="large"),
            },
        )
        st.caption("목표금액 = 현재금액 + 추가금액.  추가금액 = 인사이트 반영 후 오늘 실행할 매수/매도 금액.")

        # US 역할 → 실제 보유 ETF 이름 역방향 맵 (표시용)
        _role_to_held_kr: dict = {}
        if "rotation_role" in core_etfs.columns and _held_map:
            _rm = (
                core_etfs[["ticker", "rotation_role", "name", "notes"]]
                .dropna(subset=["rotation_role"])
                .assign(ticker=lambda d: d["ticker"].astype(str).str.upper(),
                        rotation_role=lambda d: d["rotation_role"].astype(str).str.upper())
                .query("rotation_role != '' and rotation_role != 'NAN'")
            )
            for _, _row in _rm.iterrows():
                if _row["ticker"] in _held_map:
                    _notes_str = str(_row.get("notes", ""))
                    _tag = " ★사용자편입" if "★사용자편입" in _notes_str else ""
                    _role_to_held_kr.setdefault(_row["rotation_role"], []).append(
                        f"{_row['name']}{_tag}"
                    )

        _guide_df = _rot_df[_rot_df["가이드"] == True].copy()
        _r_buy  = _guide_df[_guide_df["차이(%p)"] >  3].sort_values("차이(%p)", ascending=False)
        _r_sell = _guide_df[_guide_df["차이(%p)"] < -3].sort_values("차이(%p)")
        _rc1, _rc2 = st.columns(2)
        with _rc1:
            if not _r_buy.empty:
                st.success("**확대 필요** (+3%p↑)")
                for _, _rr in _r_buy.iterrows():
                    _isa_txt = _rr["ISA(원화)"].split("\n")[0]
                    _held_kr = _role_to_held_kr.get(_rr["US ETF"].upper(), [])
                    _held_str = f" — 보유: {', '.join(_held_kr)}" if _held_kr else ""
                    st.markdown(f"- **{_rr['US ETF']}** / ISA: {_isa_txt}{_held_str} `+{_rr['차이(%p)']:.1f}%p`")
            else:
                st.success("확대 필요 역할 없음")
        with _rc2:
            if not _r_sell.empty:
                st.warning("**축소 필요** (−3%p↓)")
                for _, _rr in _r_sell.iterrows():
                    _held_kr = _role_to_held_kr.get(_rr["US ETF"].upper(), [])
                    _held_str = f" ({', '.join(_held_kr)})" if _held_kr else ""
                    st.markdown(f"- **{_rr['US ETF']}**{_held_str} `{_rr['차이(%p)']:.1f}%p`")
            else:
                st.warning("축소 필요 역할 없음")

        # ── 점진적 매도 계획 (3개월 분할) ───────────────────────────────────
        _SELL_MONTHS = 3
        _this_month_proceeds = 0.0

        if not _r_sell.empty:
            _sell_name_list = []
            for _, _rr in _r_sell.iterrows():
                _kr = _role_to_held_kr.get(_rr["US ETF"].upper(), [_rr["US ETF"]])
                _sell_name_list.append(_kr[0] if _kr else _rr["US ETF"])
            st.markdown(f"**1단계 — 매도** ({', '.join(_sell_name_list)} 비중 초과 · 3개월 분할)")
            _r_sell_disp = _r_sell.copy()
            _r_sell_disp["보유 ETF"] = _r_sell_disp["US ETF"].apply(
                lambda u: ", ".join(_role_to_held_kr.get(u.upper(), [u]))
            )
            _r_sell_disp["총 초과금(원)"] = (
                _r_sell_disp["차이(%p)"].abs() / 100 * _total_held
            ).round(0)
            _r_sell_disp["1차(이번 달)"] = (_r_sell_disp["총 초과금(원)"] / _SELL_MONTHS).round(0)
            _r_sell_disp["2차(다음 달)"] = _r_sell_disp["1차(이번 달)"]
            _r_sell_disp["3차(그 다음)"] = (
                _r_sell_disp["총 초과금(원)"] - _r_sell_disp["1차(이번 달)"] * 2
            ).round(0)
            st.dataframe(
                _r_sell_disp[["역할", "보유 ETF", "차이(%p)", "총 초과금(원)", "1차(이번 달)", "2차(다음 달)", "3차(그 다음)"]],
                hide_index=True, use_container_width=True,
                column_config={
                    "차이(%p)":       st.column_config.NumberColumn(format="%+.1f"),
                    "총 초과금(원)":  st.column_config.NumberColumn(format="%,.0f"),
                    "1차(이번 달)":   st.column_config.NumberColumn(format="%,.0f"),
                    "2차(다음 달)":   st.column_config.NumberColumn(format="%,.0f"),
                    "3차(그 다음)":   st.column_config.NumberColumn(format="%,.0f"),
                },
            )
            _this_month_proceeds = float(_r_sell_disp["1차(이번 달)"].sum())

        # ── 매수 배분 (신규 투입 + 이번 달 판돈) ─────────────────────────────
        _total_deploy = core_buy + _this_month_proceeds
        if _total_deploy > 0:
            _sell_roles_upper = set(_r_sell["US ETF"].str.upper()) if not _r_sell.empty else set()
            _buy_guide = _guide_df[~_guide_df["US ETF"].str.upper().isin(_sell_roles_upper)].copy()

            if not _buy_guide.empty:
                _w_sum = _buy_guide["가이드비중(%)"].sum() or 1.0
                _buy_guide["배분비중(%)"] = (_buy_guide["가이드비중(%)"] / _w_sum * 100).round(1)
                _buy_guide["추천금액(원)"] = (_buy_guide["배분비중(%)"] / 100 * _total_deploy).round(0)

                if _this_month_proceeds > 0 and core_buy > 0:
                    _step_label = "2단계 — 판돈 재배분"
                    _fund_desc = (
                        f"신규 투입 {core_buy:,.0f}원  +  1차 판돈 {_this_month_proceeds:,.0f}원"
                        f"  =  합계 **{_total_deploy:,.0f}원** 을 비중 부족 역할에 재배분"
                    )
                elif _this_month_proceeds > 0:
                    _step_label = "2단계 — 판돈 재배분"
                    _fund_desc = (
                        f"1차 판돈 {_this_month_proceeds:,.0f}원을 비중 부족 역할에 재배분"
                        f" (매도 역할 제외)"
                    )
                else:
                    _step_label = "이번 매수 배분"
                    _fund_desc = ""

                st.markdown(f"**{_step_label}**")
                if _fund_desc:
                    st.caption(_fund_desc)
                _buy_disp = _buy_guide[["역할", "US ETF", "ISA(원화)", "배분비중(%)", "추천금액(원)"]].copy()
                _total_row = pd.DataFrame([{
                    "역할": "합계",
                    "US ETF": "",
                    "ISA(원화)": "",
                    "배분비중(%)": round(_buy_disp["배분비중(%)"].sum(), 1),
                    "추천금액(원)": _buy_disp["추천금액(원)"].sum(),
                }])
                _buy_disp = pd.concat([_buy_disp, _total_row], ignore_index=True)
                st.dataframe(
                    _buy_disp,
                    hide_index=True, use_container_width=True,
                    column_config={
                        "배분비중(%)": st.column_config.NumberColumn("배분비중(%)", format="%.1f"),
                        "추천금액(원)": st.column_config.NumberColumn(format="%,.0f"),
                    },
                )
        st.caption(
            "목표비중 = VIX 경기국면 기본비중 × H15 상대저점 tilt(±20%).  "
            "차이(%p) ±3%p 이내는 리밸런싱 생략 권장."
        )

    # ── 코어 ETF 매수 후보 (순위 테이블만) ──────────────────────────────────
    with st.expander("🏛️ 코어 ETF 매수 후보 — 종합 순위", expanded=False):
        st.caption(f"시장 국면: **{_e_regime['label']}** — {_e_regime['desc']}")
        if _vix:
            if _vix > 25:
                st.success(f"🔥 VIX {_vix:.0f} — {_vsig}  ·  공격 버킷 오버웨이트 적용 (IC=0.14 검증)")
            elif _vix < 13:
                st.warning(f"🌡️ VIX {_vix:.0f} — {_vsig}  ·  공격 버킷 언더웨이트 적용")
            else:
                st.info(f"VIX {_vix:.0f} — {_vsig}")
        if _e_alloc.empty:
            st.info("현재가 데이터 없음.")
        elif not _ranked.empty:
            _urgent  = _ranked[_ranked["리밸런싱"].str.startswith("🚨", na=False)]
            _new_buy = _ranked[_ranked["리밸런싱"].str.startswith("🆕", na=False)]
            if not _urgent.empty:
                st.error(f"🚨 즉시 조치 필요: {', '.join(_urgent['ticker'].tolist())}")
            if not _new_buy.empty:
                st.success(f"🆕 신규매수 후보: {', '.join(_new_buy['ticker'].tolist())}")

            _show_cols = ["순위", "보유", "ticker", "name", "섹터사이클",
                          "전환신호", "과열신호", "거래량신호",
                          "return_1m_pct", "return_12m_pct", "수익률(%)",
                          "현재비중(%)", "전술비중(%)", "비중차이(%p)",
                          "배율", "score", "리밸런싱"]
            if core_buy > 0:
                _show_cols += ["추천금액(원)", "추천수량"]
            _disp = _ranked[[c for c in _show_cols if c in _ranked.columns]].copy()
            st.dataframe(
                _disp, hide_index=True, use_container_width=True,
                column_config={
                    "순위":          st.column_config.NumberColumn("순위", format="%d"),
                    "보유":          st.column_config.TextColumn("보유"),
                    "ticker":        st.column_config.TextColumn("티커"),
                    "name":          st.column_config.TextColumn("종목명"),
                    "섹터사이클":    st.column_config.TextColumn("사이클"),
                    "전환신호":      st.column_config.TextColumn("전환신호"),
                    "과열신호":      st.column_config.TextColumn("과열",
                                    help="MA·BB 기반. 과열 = 향후 수익 낮은 경향 (IC 역방향 검증)"),
                    "거래량신호":    st.column_config.TextColumn("거래량",
                                    help="IC=+0.04 검증. 급증=기관 개입 추정"),
                    "return_1m_pct": st.column_config.NumberColumn("1개월(%)", format="%+.2f"),
                    "return_12m_pct":st.column_config.NumberColumn("12개월(%)", format="%+.2f"),
                    "수익률(%)":     st.column_config.NumberColumn("보유수익(%)", format="%+.2f"),
                    "현재비중(%)":   st.column_config.NumberColumn("현재비중(%)", format="%.1f"),
                    "전술비중(%)":   st.column_config.NumberColumn("전술비중(%)", format="%.1f"),
                    "비중차이(%p)":  st.column_config.NumberColumn("차이(%p)", format="%+.1f",
                                    help="전술비중 - 현재비중. (+)=추가매수 필요, (-)=비중 과다"),
                    "배율":          st.column_config.TextColumn("사이클배율"),
                    "score":         st.column_config.ProgressColumn("배분점수",
                                    format="%.0f", min_value=0, max_value=180),
                    "리밸런싱":      st.column_config.TextColumn("리밸런싱 액션"),
                    "추천금액(원)":  st.column_config.NumberColumn("추천금액(원)", format="%,.0f"),
                    "추천수량":      st.column_config.NumberColumn("추천수량"),
                },
            )
            st.caption(
                "배분점수 = 섹터사이클배율 × VIX국면배율.  "
                "비중차이(+)=전술 대비 언더웨이트 → 추가매수. 최종 결정은 직접 판단."
            )

    with st.expander("🎯 위성 매수 후보"):
        if sat_buy > 0:
            _STOCK_THRESHOLD = 1.5
            _sat_stocks = pd.DataFrame()
            if not scores_df.empty:
                _sat_pool = scores_df.copy()
                if not summary.empty:
                    _sat_pool = _sat_pool.merge(summary[["ticker", "close"]], on="ticker", how="left")
                _mask = _sat_pool["composite"] >= _STOCK_THRESHOLD
                if "z_quality" in _sat_pool.columns:
                    _mask &= _sat_pool["z_quality"] > 0
                _sat_stocks = _sat_pool[_mask].head(10).copy()

            if not _sat_stocks.empty:
                _sat_stocks["종목명"] = _sat_stocks["ticker"].map(NAMES).fillna("-")
                n_sat = max(len(_sat_stocks), 1)
                _sat_stocks["균등배분"] = round(sat_buy / n_sat)
                st.dataframe(
                    _sat_stocks[["ticker", "종목명", "composite", "균등배분"]].rename(
                        columns={"ticker": "티커", "composite": "QVGM점수", "균등배분": "배분금액(원)"}
                    ),
                    hide_index=True, use_container_width=True,
                    column_config={
                        "QVGM점수": st.column_config.NumberColumn(format="%+.2f"),
                        "배분금액(원)": st.column_config.NumberColumn(format="%,.0f"),
                    },
                )
            else:
                st.caption(f"QVGM +{_STOCK_THRESHOLD} 이상 개별주 없음 → 섹터/테마 ETF")
                _sector_etfs = core_etfs[core_etfs["category"].str.contains("섹터|테마", na=False)].copy()
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
                    st.info("섹터/테마 ETF 데이터 없음.")
        else:
            st.info("위성 배분이 없습니다.")

elif new_money > 0:
    st.info("현재 보유 포트폴리오가 없습니다. 보유종목 페이지에서 먼저 종목을 추가하세요.")

st.divider()

# ── 리밸런싱 이력 트래커 ──────────────────────────────────────────
from datetime import date as _rb_date_cls

# 세션 내 캐시 (GitHub API 매 렌더마다 호출 방지)
if "_rb_hist" not in st.session_state:
    st.session_state["_rb_hist"] = _rb_load()
_rb_hist = st.session_state["_rb_hist"]
_rb_all_names      = sorted(set(NAMES.values()))
_rb_name_to_ticker = {v: k for k, v in NAMES.items()}

_rb_phase_options = ["공포 🔥", "회복 🌱", "확장 🚀", "과열 🌡️", "기타"]
_rb_phase_map = {"fear": "공포 🔥", "recovery": "회복 🌱", "expansion": "확장 🚀", "overheated": "과열 🌡️"}
try:
    _rb_default_phase = _rb_phase_map.get(_phase, "기타")
except NameError:
    _rb_default_phase = "기타"

# 실제 국면이 바뀌었을 때만 selectbox 초기값 갱신 (세션 캐시 방지)
if st.session_state.get("_rb_tracked_phase") != _rb_default_phase:
    st.session_state["rb_f_phase"] = _rb_default_phase
    st.session_state["_rb_tracked_phase"] = _rb_default_phase

st.subheader("📋 리밸런싱 이력")

with st.expander("➕ 새 리밸런싱 기록 추가", expanded=len(_rb_hist) == 0):
    st.caption("같은 날짜의 행은 하나의 이벤트로 묶임 · + 버튼으로 행 추가 · 체크 → Delete로 삭제  |  💡 구분 = **현금** → **단가(원)**에 보유 현금(원) 입력")
    _rb_input_template = pd.DataFrame({
        "날짜":     [_rb_date_cls.today()],
        "구분":     ["매수"],
        "종목명":   [""],
        "수량":     [0.0],
        "단가(원)": [0],
        "메모":     [""],
    })
    _rb_edited = st.data_editor(
        _rb_input_template,
        num_rows="dynamic",
        key="rb_trades_editor",
        column_config={
            "날짜":  st.column_config.DateColumn("날짜", width="small"),
            "구분":  st.column_config.SelectboxColumn("구분", options=["매수", "매도", "현금"], width="small"),
            "종목명": st.column_config.SelectboxColumn("종목명", options=_rb_all_names, width="large"),
            "수량":  st.column_config.NumberColumn("수량", format="%.4g", min_value=0, width="small"),
            "단가(원)": st.column_config.NumberColumn("단가(원)", format="%,d", min_value=0, width="medium"),
            "메모": st.column_config.TextColumn("메모", width="large"),
        },
        use_container_width=True,
    )
    if st.button("💾 기록 저장 + 보유현황 반영", key="rb_save_btn", use_container_width=True):
        import io as _io
        _rb_skipped = []

        # MVRV 이력으로 날짜별 국면 자동 계산
        _mvrv_hist_f = RESULTS / "mvrv_history.csv"
        _mvrv_hist_df = pd.DataFrame()
        if _mvrv_hist_f.exists():
            try:
                _mvrv_hist_df = pd.read_csv(_mvrv_hist_f, index_col=0, parse_dates=True)
            except Exception:
                pass

        def _phase_from_date(date_str: str) -> str:
            try:
                if not _mvrv_hist_df.empty:
                    _ts = pd.Timestamp(date_str)
                    _idx = _mvrv_hist_df.index.get_indexer([_ts], method="nearest")[0]
                    _z = float(_mvrv_hist_df.iloc[_idx]["value"])
                    if _z < 0:   return "공포 🔥"
                    if _z < 2:   return "회복 🌱"
                    if _z < 5:   return "확장 🚀"
                    return "과열 🌡️"
            except Exception:
                pass
            return _rb_default_phase

        # + 버튼으로 추가한 행(현금 등)은 날짜가 NaT → 같은 이벤트로 묶이도록 채우기
        _valid_dates = _rb_edited["날짜"].dropna()
        if not _valid_dates.empty:
            _rb_edited["날짜"] = _rb_edited["날짜"].fillna(_valid_dates.mode().iloc[0])

        # 날짜 기준으로 그룹화
        _rb_edited["_date_str"]  = _rb_edited["날짜"].astype(str)
        _rb_edited["_group_key"] = _rb_edited["_date_str"]

        # holdings 로드 (한 번만)
        _h_path = ROOT / "holdings.csv"
        _h_raw, _ = _rb_gh_get("holdings.csv")
        if _h_raw:
            _hdf = pd.read_csv(_io.StringIO(_h_raw))
        elif _h_path.exists():
            _hdf = pd.read_csv(_h_path)
        else:
            _hdf = pd.DataFrame(columns=["ticker","qty","buy_price","buy_date","notes","person"])
        _hdf["ticker"]    = _hdf["ticker"].astype(str).str.strip()
        _hdf["qty"]       = pd.to_numeric(_hdf["qty"],       errors="coerce").fillna(0)
        _hdf["buy_price"] = pd.to_numeric(_hdf["buy_price"], errors="coerce").fillna(0)

        _new_events = []
        for _gkey, _grp in _rb_edited.groupby("_group_key", sort=False):
            _ev_date  = str(_grp["_date_str"].iloc[0])
            _ev_phase = _phase_from_date(_ev_date)
            _ev_memo  = str(_grp["메모"].iloc[0] or "").strip()
            # 현금 행: 구분 == "현금"인 행의 단가(원)을 보유현금으로 사용
            _cash_rows = _grp[_grp["구분"].astype(str) == "현금"]
            _ev_cash   = int(_cash_rows["단가(원)"].fillna(0).iloc[0] or 0) if not _cash_rows.empty else -1

            buys, sells = [], []
            for _, _row in _grp.iterrows():
                if str(_row.get("구분")) == "현금":
                    continue  # 현금 행은 trade 처리 제외
                _name  = str(_row.get("종목명", "") or "").strip()
                _qty   = float(_row.get("수량",   0) or 0)
                _price = float(_row.get("단가(원)", 0) or 0)
                _tk    = _rb_name_to_ticker.get(_name, "")
                if not _name or _qty <= 0:
                    continue
                if not _tk:
                    _rb_skipped.append(_name)
                    continue
                _trade = {"ticker": _tk, "qty": _qty, "unit_price": _price}
                if str(_row.get("구분")) == "매도":
                    sells.append(_trade)
                else:
                    buys.append(_trade)

            _new_events.append({
                "date": _ev_date, "phase": _ev_phase,
                "memo": _ev_memo, "buys": buys, "sells": sells,
                "cash": _ev_cash if _ev_cash >= 0 else None,
            })

            # holdings 반영
            for _t in buys:
                _tk, _qty, _up = _t["ticker"], _t["qty"], _t["unit_price"]
                _mask = _hdf["ticker"] == _tk
                if _mask.any():
                    _oq = float(_hdf.loc[_mask, "qty"].iloc[0])
                    _op = float(_hdf.loc[_mask, "buy_price"].iloc[0])
                    _nq = _oq + _qty
                    _np = (_oq * _op + _qty * _up) / _nq if _up > 0 and _nq > 0 else _op
                    _hdf.loc[_mask, "qty"]       = _nq
                    _hdf.loc[_mask, "buy_price"] = round(_np, 2)
                else:
                    _nr = {c: "" for c in _hdf.columns}
                    _nr.update({"ticker": _tk, "qty": _qty, "buy_price": _up,
                                "buy_date": _ev_date, "notes": "", "person": ""})
                    _hdf = pd.concat([_hdf, pd.DataFrame([_nr])], ignore_index=True)
            for _t in sells:
                _tk, _qty = _t["ticker"], _t["qty"]
                _mask = _hdf["ticker"] == _tk
                if _mask.any():
                    _nq = max(0, float(_hdf.loc[_mask, "qty"].iloc[0]) - _qty)
                    if _nq == 0:
                        _hdf = _hdf[~_mask].reset_index(drop=True)
                    else:
                        _hdf.loc[_mask, "qty"] = _nq

            # CASH 갱신 — 현금 행이 있을 때만 (_ev_cash >= 0)
            if _ev_cash >= 0:
                _cash_person = selected_person if selected_person != "전체" else (
                    all_persons[0] if all_persons else ""
                )
                _cash_hmask = (_hdf["ticker"].str.upper() == "CASH") & \
                              (_hdf["person"].astype(str) == _cash_person)
                if _cash_hmask.any():
                    _hdf.loc[_cash_hmask, "qty"] = _ev_cash
                else:
                    _cr = {c: "" for c in _hdf.columns}
                    _cr.update({"ticker": "CASH", "qty": _ev_cash,
                                 "buy_price": 1, "notes": "보유 현금", "person": _cash_person})
                    _hdf = pd.concat([_hdf, pd.DataFrame([_cr])], ignore_index=True)

        # 이력 저장 (최신 순으로 앞에 삽입)
        for _ev in reversed(_new_events):
            _rb_hist.insert(0, _ev)
        _rb_saved_to_gh = _rb_save(_rb_hist)
        st.session_state["_rb_hist"] = _rb_hist

        # holdings GitHub 저장
        _hdf.to_csv(_h_path, index=False)
        _h_gh_ok = False
        if _rb_gh_token():
            _h_gh_ok, _ = _rb_gh_put("holdings.csv", _hdf.to_csv(index=False), "data: 리밸런싱 후 보유현황 갱신")

        if _rb_saved_to_gh:
            _msg = f"✅ GitHub에 저장됐습니다 ({len(_new_events)}건)."
            _msg += " 보유현황도 반영됐어요." if _h_gh_ok else " (보유현황 GitHub 저장 실패 — 로컬만 반영)"
            st.success(_msg)
        else:
            st.error(
                "🚨 GitHub 저장 실패 — 앱 재시작 시 이력이 사라집니다!\n\n"
                "**해결**: Streamlit Cloud Settings → Secrets → `GH_PAT` 확인/갱신"
            )
        if _rb_skipped:
            st.warning(f"종목명을 찾지 못해 저장 제외: {', '.join(_rb_skipped)}")
        st.rerun()

_BAD_TICKERS = {"NONE", "NAN", ""}

if _rb_hist:
    # ── 이벤트 삭제 UI ──────────────────────────────────────────────
    _ev_labels = [
        f"[{i+1}] {ev.get('date','')} {ev.get('phase','')} "
        f"(매수 {len(ev.get('buys',[]))}건 · 매도 {len(ev.get('sells',[]))}건)"
        for i, ev in enumerate(_rb_hist)
    ]
    _del_sel = st.multiselect("🗑️ 삭제할 이벤트 선택 (복수 가능)", options=list(range(len(_rb_hist))),
                              format_func=lambda i: _ev_labels[i], key="rb_del_sel")
    if _del_sel and st.button("선택 이벤트 삭제", key="rb_del_btn", type="secondary"):
        _del_set = set(_del_sel)
        _rb_hist = [ev for i, ev in enumerate(_rb_hist) if i not in _del_set]
        _rb_save(_rb_hist)
        st.session_state["_rb_hist"] = _rb_hist
        st.rerun()

    # 종목별 누적 매수·매도 금액 계산
    _ticker_total_buy:  dict = {}
    _ticker_total_sell: dict = {}
    for _ev in _rb_hist:
        for _t in _ev.get("buys", []):
            _tk = str(_t.get("ticker", "")).upper()
            if _tk and _tk not in _BAD_TICKERS:
                _amt = float(_t.get("qty", 0) or 0) * float(_t.get("unit_price", 0) or 0)
                _ticker_total_buy[_tk] = _ticker_total_buy.get(_tk, 0) + _amt
        for _t in _ev.get("sells", []):
            _tk = str(_t.get("ticker", "")).upper()
            if _tk and _tk not in _BAD_TICKERS:
                _amt = float(_t.get("qty", 0) or 0) * float(_t.get("unit_price", 0) or 0)
                _ticker_total_sell[_tk] = _ticker_total_sell.get(_tk, 0) + _amt

    # ── ETF 목표비중 매핑 (_rot_df 기준, ticker → fraction 0-1) ──────
    import re as _re
    _ticker_to_목표pct: dict = {}  # rotation table 내 비중(100% 기준, CORE 내)
    try:
        if not _rot_df.empty and "목표비중(%)" in _rot_df.columns:
            for _, _rrow in _rot_df.iterrows():
                _목표w = float(_rrow.get("목표비중(%)", 0) or 0) / 100
                _us = str(_rrow.get("US ETF", "")).strip().upper()
                if _us:
                    _ticker_to_목표pct[_us] = _목표w
                _isa = str(_rrow.get("ISA(원화)", "") or "")
                _km  = _re.search(r'\(([^)]+)\)', _isa)
                if _km:
                    _ticker_to_목표pct[_km.group(1).strip().upper()] = _목표w
    except NameError:
        pass
    if not core_etfs.empty and "rotation_role" in core_etfs.columns:
        _role_to_목표w = {str(r).strip().upper(): _ticker_to_목표pct.get(str(r).strip().upper(), 0)
                          for r in core_etfs["rotation_role"].dropna().unique()}
        for _, _crow in core_etfs.iterrows():
            _ctk   = str(_crow.get("ticker", "")).strip().upper()
            _crole = str(_crow.get("rotation_role", "")).strip().upper()
            if _ctk and _crole and _ctk not in _ticker_to_목표pct:
                _w = _role_to_목표w.get(_crole, 0)
                if _w:
                    _ticker_to_목표pct[_ctk] = _w

    _alloc_total_val = alloc.get("Total", 0)
    # 실제 목표금액 = 총자산 × core비중 × role비중 (target_core로 스케일 조정)
    _core_factor = (target_core / 100) if target_core > 0 else 1.0
    _etf_목표금액 = {_tk: int(_alloc_total_val * _w * _core_factor)
                   for _tk, _w in _ticker_to_목표pct.items() if _w > 0}

    # ── 현재 보유가치 매핑 (holdings × 현재가 / 총자산) ──────────────
    # _rot_df["현재비중(%)"]는 US ETF만 포함해 분모가 틀림 → 직접 계산
    _rb_현재가치_f: dict = {}  # ticker.upper() → fraction of total portfolio
    try:
        if not holdings.empty and not summary.empty and _alloc_total_val > 0:
            _rb_h = holdings.copy()
            _rb_h["ticker"] = _rb_h["ticker"].astype(str).str.upper()
            _rb_latest = (summary.sort_values("date")
                          .groupby("ticker").last()
                          .reset_index()[["ticker", "close"]]
                          .assign(ticker=lambda d: d["ticker"].astype(str).str.upper()))
            _rb_h = _rb_h.merge(_rb_latest, on="ticker", how="left")
            _rb_h["cur_val"] = (pd.to_numeric(_rb_h["qty"], errors="coerce") *
                                pd.to_numeric(_rb_h["close"], errors="coerce"))
            for _, _rh in _rb_h.iterrows():
                _rtk  = str(_rh["ticker"]).upper()
                _rval = float(_rh.get("cur_val") or 0)
                if _rval > 0 and _rtk not in _BAD_TICKERS:
                    _rb_현재가치_f[_rtk] = _rb_현재가치_f.get(_rtk, 0) + _rval / _alloc_total_val
        # rotation_role 경유하여 US ETF 심볼에도 매핑 (역할 합산)
        if not core_etfs.empty and "rotation_role" in core_etfs.columns:
            _rb_role_val: dict = {}
            for _, _crow in core_etfs.iterrows():
                _ctk2  = str(_crow.get("ticker", "")).strip().upper()
                _crole2 = str(_crow.get("rotation_role", "")).strip().upper()
                if _ctk2 in _rb_현재가치_f and _crole2:
                    _rb_role_val[_crole2] = _rb_role_val.get(_crole2, 0) + _rb_현재가치_f[_ctk2]
            for _crole2, _rw in _rb_role_val.items():
                _rb_현재가치_f[_crole2] = _rw
    except Exception:
        pass

    _rb_table_rows = []
    for _ei, _rb_ev in enumerate(_rb_hist):
        _rb_ev_date  = _rb_ev.get("date", "")
        _rb_ev_phase = _rb_ev.get("phase", "")
        _rb_ev_memo  = _rb_ev.get("memo", "")
        _rb_ev_buys  = [b for b in _rb_ev.get("buys",  []) if str(b.get("ticker","")).upper() not in _BAD_TICKERS]
        _rb_ev_sells = [s for s in _rb_ev.get("sells", []) if str(s.get("ticker","")).upper() not in _BAD_TICKERS]
        _rb_ev_cash  = _rb_ev.get("cash")  # 보유현금 (있을 때만)

        # 이벤트 내 전체 거래금액 합계 (매수+매도) — 목표대비(%) 분모
        _ev_total_all = sum(
            float(t.get("qty", 0) or 0) * float(t.get("unit_price", 0) or 0)
            for t in _rb_ev_buys + _rb_ev_sells
        )

        _trades = [("매수", t) for t in _rb_ev_buys] + [("매도", t) for t in _rb_ev_sells]
        _first = True
        if _trades:
            for _side, _t in _trades:
                _qty   = float(_t.get("qty", 0) or 0)
                _price = float(_t.get("unit_price", 0) or 0)
                _trade_amt = _qty * _price
                _tk_upper  = str(_t.get("ticker","")).upper()
                # 누적금액: 매수=역대 누적매수, 매도=현재 시가평가
                _cur_f = _rb_현재가치_f.get(_tk_upper)
                _cumul = int(_ticker_total_buy.get(_tk_upper, 0)) if _side == "매수" \
                    else int((_cur_f or 0) * _alloc_total_val)
                # 목표대비 = 현재보유가치 / (총자산 × core목표비중 × role목표비중)
                _목표f_adj = _ticker_to_목표pct.get(_tk_upper, 0) * _core_factor
                _pct = round((_cur_f or 0) / _목표f_adj * 100, 1) \
                    if (_목표f_adj > 0 and _cur_f is not None) else None
                _rb_table_rows.append({
                    "날짜":        _rb_ev_date,
                    "국면":        _rb_ev_phase,
                    "구분":        _side,
                    "종목명":      NAMES.get(_tk_upper, _t.get("ticker","")),
                    "수량":        _qty if _qty else None,
                    "단가(원)":    int(_price) if _price else None,
                    "거래금액(원)": int(_trade_amt) if _trade_amt else None,
                    "목표대비(%)":  _pct,
                    "누적금액(원)": _cumul,
                    "메모":        _rb_ev_memo if _first else "",
                })
                _first = False
        elif _rb_ev_cash is None or _rb_ev_cash < 0:
            # 거래도 없고 현금도 없을 때만 빈 행 표시
            _rb_table_rows.append({
                "날짜": _rb_ev_date, "국면": _rb_ev_phase, "구분": "",
                "종목명": "", "수량": None, "단가(원)": None,
                "거래금액(원)": None, "목표대비(%)": None, "누적금액(원)": None,
                "메모": _rb_ev_memo,
            })
            _first = False

        # 현금 행 (저장된 경우)
        if _rb_ev_cash is not None and _rb_ev_cash >= 0:
            _cash_target = _alloc_total_val * (target_cash / 100)
            _cash_pct = round(_rb_ev_cash / _cash_target * 100, 1) if _cash_target > 0 else None
            _rb_table_rows.append({
                "날짜":        _rb_ev_date,
                "국면":        _rb_ev_phase,
                "구분":        "현금",
                "종목명":      "보유현금",
                "수량":        None,
                "단가(원)":    None,
                "거래금액(원)": int(_rb_ev_cash),
                "목표대비(%)":  _cash_pct,
                "누적금액(원)": int(_rb_ev_cash),
                "메모":        "" if not _first else _rb_ev_memo,
            })

    _rb_df = pd.DataFrame(_rb_table_rows)
    st.dataframe(
        _rb_df,
        use_container_width=True,
        hide_index=True,
        column_config={
            "날짜":        st.column_config.TextColumn("날짜",        width="small"),
            "국면":        st.column_config.TextColumn("국면",        width="small"),
            "구분":        st.column_config.TextColumn("구분",        width="small"),
            "종목명":      st.column_config.TextColumn("종목명",      width="large"),
            "수량":        st.column_config.NumberColumn("수량",      format="%.4g", width="small"),
            "단가(원)":    st.column_config.NumberColumn("단가(원)",   format="%,d",  width="medium"),
            "거래금액(원)": st.column_config.NumberColumn("거래금액(원)", format="%,d", width="medium"),
            "목표대비(%)": st.column_config.NumberColumn("목표대비(%)", format="%.1f%%", width="small"),
            "누적금액(원)": st.column_config.NumberColumn("누적금액(원)", format="%,d", width="medium"),
            "메모":        st.column_config.TextColumn("메모",        width="large"),
        },
    )
else:
    st.info("아직 기록이 없습니다. 위 폼으로 첫 번째 리밸런싱을 기록하세요.")

st.divider()

# ── 코인 비중 축소 로드맵 ─────────────────────────────────────────
st.subheader("🚪 코인 비중 축소 로드맵")
st.caption(
    "코인 비중을 목표(10~15%)까지 단계적으로 줄이는 계획입니다. "
    "MVRV Z-Score 트리거 구간에 진입하면 아래 기준대로 매도를 검토하세요."
)

# 추가 데이터 로드
_coin_sum_f = RESULTS / "coin_summary.csv"
_cycle_f    = RESULTS / "cycle_metrics.csv"
_coin_sum2  = pd.read_csv(_coin_sum_f) if _coin_sum_f.exists() else pd.DataFrame()
_cycle_row2 = pd.read_csv(_cycle_f).iloc[0].to_dict() if _cycle_f.exists() else {}

# USD/KRW 환율
try:
    import urllib.request as _ur, json as _jj
    with _ur.urlopen("https://api.frankfurter.app/latest?from=USD&to=KRW", timeout=4) as _rr:
        _usdkrw2 = float(_jj.loads(_rr.read())["rates"]["KRW"])
except Exception:
    _usdkrw2 = 1380.0

# 코인 현재가 (KRW)
_cprice2: dict = {}
if not _coin_sum2.empty:
    for _, _cr in _coin_sum2.iterrows():
        _cprice2[str(_cr["ticker"])] = float(_cr["close"]) * _usdkrw2

# MVRV
_mvrv2 = float(_cycle_row2.get("mvrv_z", 0.0))

# 포트폴리오 평가
_h_coin  = holdings[holdings["ticker"].str.contains("-USD", na=False)].copy()
_h_stock = holdings[~holdings["ticker"].str.contains("-USD", na=False)].copy()

_val_coin = sum(
    float(r["qty"]) * _cprice2.get(str(r["ticker"]), 0.0)
    for _, r in _h_coin.iterrows()
)
_pmap2 = dict(zip(summary["ticker"].astype(str), summary["close"])) if not summary.empty else {}
_val_stock = sum(
    float(r["qty"]) * float(_pmap2.get(str(r["ticker"]), 0.0))
    for _, r in _h_stock.iterrows()
)
_val_total  = _val_coin + _val_stock
_coin_ratio = _val_coin / _val_total * 100 if _val_total > 0 else 0.0

# MVRV 트리거 레벨 (0=대기 / 1=1단계 / 2=2단계 / 3=과열)
if _mvrv2 >= 2.5:
    _trigger = 3
    _mvrv_label = "🔴🔴 과열 — Group 1·2·3 전면 정리 구간"
    _mvrv_col   = "#991b1b"
elif _mvrv2 >= 2.0:
    _trigger = 2
    _mvrv_label = "🔴 2단계 트리거 — Group 1·2 잔량 전량 매도 구간"
    _mvrv_col   = "#dc2626"
elif _mvrv2 >= 1.5:
    _trigger = 1
    _mvrv_label = "🟠 1단계 트리거 — Group 1·2 50% 매도 검토 구간"
    _mvrv_col   = "#ea580c"
else:
    _trigger = 0
    _mvrv_label = "🟢 저평가 구간 — 매도 트리거 미도달, 현 포지션 유지"
    _mvrv_col   = "#16a34a"

# 상단 지표
_rc1, _rc2, _rc3, _rc4 = st.columns(4)
_rc1.metric("📡 MVRV Z-Score", f"{_mvrv2:.2f}",
            help="0~1.5: 저평가 / 1.5~2.0: 1단계 / 2.0~2.5: 2단계 / 2.5+: 과열")
_over15 = max(0.0, _coin_ratio - 15.0)
_rc2.metric("🪙 현재 코인 비중", f"{_coin_ratio:.1f}%",
            delta=f"목표 대비 +{_over15:.1f}%p 초과" if _over15 > 0 else "목표 범위 내",
            delta_color="inverse" if _over15 > 0 else "off")
_rc3.metric("🪙 코인 평가금액", f"{_val_coin:,.0f}원")
_rc4.metric("📊 전체 포트폴리오", f"{_val_total:,.0f}원")

st.markdown(
    f"<div style='background:{_mvrv_col}18;border-left:4px solid {_mvrv_col};"
    f"border-radius:6px;padding:10px 14px;margin:8px 0'>"
    f"<b style='color:{_mvrv_col}'>{_mvrv_label}</b></div>",
    unsafe_allow_html=True,
)

st.markdown("---")

# 그룹 정의 및 출구 규칙 (trigger_level, 조건, 액션)
_G1 = ["TRUMP-USD", "MASK-USD", "ZETA-USD", "SAND-USD", "ID-USD"]
_G2 = ["GAS-USD", "DOGE-USD", "ETC-USD", "ENS-USD"]
_G3 = ["BTC-USD", "ETH-USD", "SOL-USD"]

_G1_RULES = [
    (1, "MVRV Z ≥ 1.5 도달",       "50% 매도"),
    (2, "MVRV Z ≥ 2.0 도달",       "나머지 전량 매도"),
    (0, "개별 손실 -60% 이내 회복", "전량 매도 (조건 먼저 도달 시)"),
    (0, "2027년 말 데드라인",       "조건 미충족 시 전량 매도"),
]
_G2_RULES = [
    (1, "MVRV Z ≥ 1.5 도달", "GAS·ETC·DOGE 30% 매도 시작"),
    (2, "MVRV Z ≥ 2.0 도달", "GAS·ETC·DOGE 나머지 50% 매도"),
    (2, "MVRV Z ≥ 2.0 도달", "ENS 정리 시작 (ETH 타이밍에 맞춤)"),
]
_G3_RULES = [
    (3, "MVRV Z ≥ 2.5 도달",   "BTC 일부 차익 실현 고려"),
    (0, "BTC 신고점 경신 후",   "ETH·SOL 갭 메울 때 일부 정리"),
]


def _coin_roadmap_group(title, bg, border, tickers, rules, h_coin, cprice, trigger):
    group_rows, group_val = [], 0.0
    for t in tickers:
        sub = h_coin[h_coin["ticker"] == t]
        if sub.empty:
            continue
        qty     = sub["qty"].astype(float).sum()
        avg_buy = (sub["qty"].astype(float) * sub["buy_price"].astype(float)).sum() / qty
        cur     = cprice.get(t, 0.0)
        val     = qty * cur
        pnl     = (cur / avg_buy - 1) * 100 if avg_buy > 0 else 0.0
        group_rows.append({"name": t.replace("-USD", ""), "val": val, "pnl": pnl})
        group_val += val

    if not group_rows:
        return

    st.markdown(
        f"<div style='background:{bg};border-left:4px solid {border};"
        f"border-radius:6px;padding:8px 14px;margin-bottom:8px'>"
        f"<b style='color:{border}'>{title}</b>"
        f"&nbsp;&nbsp;합산 평가 <b>{group_val:,.0f}원</b></div>",
        unsafe_allow_html=True,
    )

    gcols = st.columns(len(group_rows))
    for i, row in enumerate(group_rows):
        gcols[i].metric(row["name"], f"{row['val']:,.0f}원",
                        delta=f"{row['pnl']:+.1f}%", delta_color="normal")

    for lvl, cond, action in rules:
        active = (trigger >= lvl) and (lvl > 0)
        icon   = "🔔" if active else "⏳"
        bg2    = "#fef2f2" if active else "#f9fafb"
        tc     = "#b91c1c" if active else "#374151"
        st.markdown(
            f"<div style='background:{bg2};border-radius:4px;padding:5px 12px;"
            f"margin:3px 0;font-size:13px'>"
            f"{icon} <span style='color:{tc}'><b>{cond}</b> → {action}</span></div>",
            unsafe_allow_html=True,
        )
    st.markdown("<div style='height:8px'></div>", unsafe_allow_html=True)


_coin_roadmap_group(
    "🔴 Group 1 — 출구 전략 (TRUMP · MASK · ZETA · SAND · ID)",
    "#fff1f2", "#ef4444", _G1, _G1_RULES, _h_coin, _cprice2, _trigger,
)
_coin_roadmap_group(
    "🟠 Group 2 — 조건부 축소 (GAS · DOGE · ETC · ENS)",
    "#fff7ed", "#f97316", _G2, _G2_RULES, _h_coin, _cprice2, _trigger,
)
_coin_roadmap_group(
    "🟢 Group 3 — 코어 코인 유지 (BTC · ETH · SOL)",
    "#f0fdf4", "#22c55e", _G3, _G3_RULES, _h_coin, _cprice2, _trigger,
)

# 비중 축소 시뮬레이션
st.markdown("---")
st.markdown("##### 📊 비중 축소 시뮬레이션")

_g12_val = sum(
    _h_coin[_h_coin["ticker"] == t]["qty"].astype(float).sum() * _cprice2.get(t, 0.0)
    for t in _G1 + _G2
    if not _h_coin[_h_coin["ticker"] == t].empty
)
_after_g12     = _val_coin - _g12_val
_after_g12_pct = _after_g12 / _val_total * 100 if _val_total > 0 else 0.0
_tgt_high_val  = _val_total * 0.15

_sc1, _sc2, _sc3 = st.columns(3)
_sc1.metric("현재 코인 금액", f"{_val_coin:,.0f}원",
            delta=f"{_coin_ratio:.1f}%", delta_color="off")
_sc2.metric("G1+G2 정리 후", f"{_after_g12:,.0f}원",
            delta=f"비중 {_after_g12_pct:.1f}%", delta_color="off")
_sc3.metric("추가 감소 필요", f"{max(0.0, _after_g12 - _tgt_high_val):,.0f}원",
            delta="ETH·SOL 일부 정리", delta_color="off")

if _coin_ratio <= 15:
    st.success("✅ 코인 비중이 이미 목표 범위(15%) 이내입니다.")
elif _after_g12_pct <= 15:
    st.info(f"💡 Group 1·2만 정리해도 코인 비중 {_after_g12_pct:.1f}% — 목표 범위에 들어옵니다.")
else:
    st.warning(
        f"⚠️ Group 1·2 정리 후에도 코인 비중 {_after_g12_pct:.1f}% — "
        f"목표(15%) 대비 {_after_g12_pct - 15:.1f}%p 초과. ETH·SOL 일부 정리가 추가로 필요합니다."
    )

st.caption(
    "이 분석은 투자 판단을 돕기 위한 의사결정 보조 자료이며, "
    "최종 매수·매도 결정은 공식 공시, 최신 실적, 본인의 투자 기간과 "
    "위험 감내 범위를 확인한 뒤 내려야 합니다."
)
