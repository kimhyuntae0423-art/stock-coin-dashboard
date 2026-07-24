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
from scripts.config import (
    DEFAULT_TARGET_CORE, DEFAULT_TARGET_SATELLITE, DEFAULT_TARGET_CASH,
    KEY_TARGET_CORE, KEY_TARGET_SATELLITE, KEY_TARGET_CASH,
    RESULTS_DIR as RESULTS, HOLDINGS_FILE, NAMES_FILE, COIN_NAMES_FILE,
)
from scripts.etf_recommend import (
    market_regime, score_etfs, tactical_alloc, enrich_with_volume,
    volume_signals, technical_signals,
)
from scripts.etf_rotation import rotation_target
from scripts.holdings_io import parse_buy_dates, format_buy_dates
from scripts.onchain import classify_regime, REGIME_LABEL_KR
from scripts.crypto_analysis import (
    coin_holdings_action_text, coin_rebalance_insight, COIN_EXIT_GROUPS,
    ALT_STOPLOSS_RECOVERY_PCT, coin_alt_stoploss_status,
    coin_holdings_action_with_stoploss, coin_rebalance_insight_with_stoploss,
)


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


_SNAP_FILE = "holdings_snapshots.json"


def _snap_load() -> list:
    raw, _ = _rb_gh_get(_SNAP_FILE)
    if raw:
        try:
            return _rb_json.loads(raw)
        except Exception:
            return []
    _p = ROOT / _SNAP_FILE
    if _p.exists():
        try:
            return _rb_json.loads(_p.read_text(encoding="utf-8"))
        except Exception:
            return []
    return []


def _snap_key(entry: dict) -> tuple:
    # 예전엔 "month"(YYYY-MM) 단위로만 저장했는데(2026-07-23 신설), 리밸런싱을
    # 직접 날짜로 기록하는 사용자 습관에 맞춰 "date"(YYYY-MM-DD 또는 그 이하
    # 정밀도) + "person"으로 키를 세분화(2026-07-24) — 옛 항목은 "date" 필드가
    # 없으므로 "month"로 폴백해서 그대로 읽힘(마이그레이션 불필요).
    return (entry.get("date") or entry.get("month") or ""), entry.get("person", "전체")


def _snap_upsert(snaps: list, entry: dict) -> list:
    """같은 (date, person)이 있으면 교체, 없으면 추가. 최신순 정렬."""
    key = _snap_key(entry)
    snaps = [s for s in snaps if _snap_key(s) != key]
    snaps.append(entry)
    return sorted(snaps, key=lambda x: _snap_key(x)[0], reverse=True)


def _snap_save(snaps: list) -> bool:
    json_str = _rb_json.dumps(snaps, ensure_ascii=False, indent=2)
    ok, _ = _rb_gh_put(_SNAP_FILE, json_str, "data: 비중 스냅샷 갱신")
    if not ok:
        (ROOT / _SNAP_FILE).write_text(json_str, encoding="utf-8")
    return ok


def _compute_role_alloc_snapshot(holdings_df, core_etfs_df, stock_price_map, coin_price_map_krw):
    """비중 스냅샷 집계(VOO/SCHD/SOXX/TLT/GLD 역할 + 코인 + 현금, 개별주는
    집계 제외)를 _rot_df(리밸런싱 추천표, 페이지 하단 "🎯 리밸런싱 실행"
    섹션에서만 계산되고 new_money=0이면 아예 안 만들어짐)에 기대지 않고
    holdings_df만으로 독립 계산 — "보유 내역 관리" 저장 시 자동 스냅샷용
    (2026-07-24 신설, 이후 수동 스냅샷 버튼은 중복이라 제거하고 이 경로만 남음).
    반환: (비중% dict, 금액(원) dict, 총자산)."""
    role_map = dict(zip(core_etfs_df["ticker"].astype(str).str.upper(), core_etfs_df["rotation_role"].astype(str)))
    role_val: dict = {}
    coin_val = 0.0
    cash_val = 0.0
    total = 0.0
    for _, r in holdings_df.iterrows():
        tk  = str(r.get("ticker", "")).strip().upper()
        qty = float(r.get("qty") or 0)
        if not tk:
            continue
        if tk == "CASH":
            val = qty * float(r.get("buy_price") or 1)
            cash_val += val
        elif "-USD" in tk:
            px = coin_price_map_krw.get(tk)
            if px is None:
                continue
            val = qty * float(px)
            coin_val += val
        else:
            px = stock_price_map.get(tk)
            if px is None:
                continue
            val = qty * float(px)
            role = role_map.get(tk)
            if role in ("VOO", "SCHD", "SOXX", "TLT", "GLD"):
                role_val[role] = role_val.get(role, 0.0) + val
        total += val
    if total <= 0:
        return {}, {}, 0.0
    amounts = dict(role_val)
    amounts["coin"] = coin_val
    amounts["cash"] = cash_val
    pcts = {role: round(v / total * 100, 1) for role, v in amounts.items()}
    return pcts, amounts, total

# =====================================================================
# 공통 데이터 로드
# =====================================================================
st.title("⚖️ 리밸런싱")
st.caption("코어-위성 자산배분 추적 · 추천 분산 포트폴리오.")

holdings = _load_holdings()

# ── CASH 먼저 추출 (person 필터 전) ───────────────────────────────
_cash_row_mask = holdings["ticker"].str.upper() == "CASH"
_cash_rows     = holdings.loc[_cash_row_mask].copy()
holdings       = holdings[~_cash_row_mask].copy()

all_persons = sorted([p for p in holdings["person"].unique() if p and str(p).strip()])
selected_person = st.selectbox(
    "👤 계산 대상",
    options=["전체"] + all_persons,
    index=0,
    key="rebal_person_filter",
)

# CASH 합계 — 선택된 사람 기준(전체면 전체 합산). 2026-07-21: 이전엔 person 필드 값에
# 무관하게 항상 전체 합산이라 "김보라"를 선택해도 김현태 현금까지 섞여 나오던 버그.
_cr = _cash_rows if selected_person == "전체" else _cash_rows[_cash_rows["person"] == selected_person]
if not _cr.empty:
    _cq = pd.to_numeric(_cr["qty"],       errors="coerce").fillna(0)
    _cb = pd.to_numeric(_cr["buy_price"], errors="coerce").fillna(1).replace(0, 1)
    cash_amount = float((_cq * _cb).sum())
else:
    cash_amount = 0.0

if selected_person != "전체":
    holdings = holdings[holdings["person"] == selected_person].copy()

summary_file = RESULTS / "summary_signals.csv"
funda_file = RESULTS / "fundamentals.csv"
summary = pd.read_csv(summary_file) if summary_file.exists() else pd.DataFrame()
funda = pd.read_csv(funda_file) if funda_file.exists() else pd.DataFrame(columns=["ticker"])

# "배분 현황 & 리밸런싱" 상단 요약(목표/총자산)이 페이지 맨 위로 옮겨오면서
# 여기서 먼저 계산 — "보유 현황" 섹션도 같은 변수를 재사용(2026-07-23,
# 이전엔 "보유 현황"에서만 계산해서 중복 호출이었음).
_h_regime = market_regime(summary)
_h_vix    = _h_regime.get("vix")
_h_vsig   = _h_regime.get("vix_signal", "")

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

# cash_amount는 위에서 holdings.csv CASH 티커로 읽음 (세션 상태 불필요)
# 아래 위젯(new_money_input) 기본값(2,000,000)과 일치시킴 — 새 세션 첫 로드 시
# 이 폴백(1,000,000)과 위젯 기본값이 달라서 "신규자금분" 등이 잠깐 어긋나던
# 문제(재검증 발견, 2026-07-22). 위젯이 렌더되고 나면 session_state가 실제
# 위젯값으로 채워져 이후엔 문제 없었지만, 첫 렌더 순간엔 그대로 노출됐음.
new_money        = float(st.session_state.get("new_money_input", 2_000_000))

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

st.subheader("📊 배분 현황 & 리밸런싱")

ic1, ic2, ic3 = st.columns(3)
with ic1:
    target_core = st.number_input("🏛️ 코어 목표 (%)", min_value=0, max_value=100,
                                   value=DEFAULT_TARGET_CORE, step=5, key=KEY_TARGET_CORE)
with ic2:
    target_satellite = st.number_input("🎯 위성 목표 (%)", min_value=0, max_value=100,
                                        value=DEFAULT_TARGET_SATELLITE, step=5, key=KEY_TARGET_SATELLITE)
with ic3:
    target_cash = st.number_input("💵 현금 목표 (%)", min_value=0, max_value=100,
                                   value=DEFAULT_TARGET_CASH, step=5, key=KEY_TARGET_CASH)
if target_core + target_satellite + target_cash != 100:
    st.warning(f"⚠️ 목표 비중 합계 {target_core + target_satellite + target_cash}% — 100%가 되도록 조정해주세요.")

aa1, aa2, aa3, aa4 = st.columns(4)
with aa1:
    st.metric("💼 총 자산", f"{alloc['Total']:,.0f}원")
    st.caption(f"보유 현금 {cash_amount:,.0f}원 포함 · CASH 행 관리")
with aa2:
    st.metric("🏛️ 코어", f"{alloc['Core_value']:,.0f}원 ({alloc['Core_pct']:.1f}%)",
              delta=f"{alloc['Core_pct'] - target_core:+.1f}pp (목표 {target_core}%)", delta_color="off")
with aa3:
    st.metric("🎯 위성", f"{alloc['Satellite_value']:,.0f}원 ({alloc['Satellite_pct']:.1f}%)",
              delta=f"{alloc['Satellite_pct'] - target_satellite:+.1f}pp (목표 {target_satellite}%)", delta_color="off")
with aa4:
    st.metric("💵 현금", f"{cash_amount:,.0f}원 ({alloc['Cash_pct']:.1f}%)",
              delta=f"{alloc['Cash_pct'] - target_cash:+.1f}pp (목표 {target_cash}%)", delta_color="off")

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

    if "buy_date" in _he_show.columns:
        _he_show["buy_date"] = parse_buy_dates(_he_show["buy_date"])
    else:
        _he_show["buy_date"] = None
    _he_show.insert(0, "종목명", _he_show["ticker"].map(NAMES).fillna(""))
    _he_show = _he_show.rename(columns={
        "ticker": "티커", "qty": "수량", "buy_price": "평균단가", "buy_date": "일자", "person": "이름", "notes": "메모"
    })
    _he_disp_cols = [c for c in ["종목명","티커","수량","평균단가","일자","이름","메모"] if c in _he_show.columns]

    # data_editor의 셀 편집이 버튼 클릭과 같은 타이밍에 아직 커밋 안 된 상태로
    # 저장 로직이 읽어가는 경우가 있어(Streamlit의 널리 알려진 동작) 수량을
    # 수정하고 바로 저장을 눌렀는데 반영이 안 되는 문제가 있었음(2026-07-23
    # 사용자 보고). st.form으로 감싸면 폼 안의 모든 위젯 값이 제출 시점에
    # 한번에 확정되어 이 경합이 사라짐.
    with st.form(key=f"rebal_he_form_{selected_person}"):
        _he_edited = st.data_editor(
            _he_show[_he_disp_cols],
            num_rows="dynamic",
            key=f"rebal_he_{selected_person}",
            column_config={
                "종목명":   st.column_config.SelectboxColumn("종목명", options=_he_all_names, width="medium"),
                "티커":     st.column_config.TextColumn("티커", width="small"),
                "수량":     st.column_config.NumberColumn("수량", format="%.8g"),
                "평균단가": st.column_config.NumberColumn("평균단가", format="%,.0f"),
                "일자":     st.column_config.DateColumn("일자", format="YYYY-MM-DD"),
                "이름":     st.column_config.TextColumn("이름", width="small"),
                "메모":     st.column_config.TextColumn("메모"),
            },
            use_container_width=True,
        )
        _he_submitted = st.form_submit_button(
            "💾 저장 & GitHub 반영", type="primary", use_container_width=True
        )

    if _he_submitted:
        _he_cp = _he_edited.copy()
        for _hi, _hr in _he_cp.iterrows():
            _htk = str(_hr.get("티커", "") or "").strip()
            _hnm = str(_hr.get("종목명", "") or "").strip()
            if not _htk and _hnm:
                _he_cp.at[_hi, "티커"] = _he_name_to_ticker.get(_hnm, "")

        _he_cur = _he_cp.drop(columns=["종목명"]).rename(columns={
            "티커": "ticker", "수량": "qty", "평균단가": "buy_price", "일자": "buy_date", "이름": "person", "메모": "notes"
        })
        _he_cur["buy_date"] = format_buy_dates(_he_cur["buy_date"])
        _he_cur = _he_cur[
            _he_cur["ticker"].astype(str).str.strip().str.upper().isin(["", "NONE", "NAN"]) == False
        ]
        if selected_person != "전체" and not _he_others.empty:
            _he_save = pd.concat([_he_cur, _he_others], ignore_index=True)
        else:
            _he_save = _he_cur.copy()

        (ROOT / "holdings.csv").write_text(_he_save.to_csv(index=False), encoding="utf-8")

        # 보유 내역 저장과 동시에 오늘 날짜 스냅샷도 자동 갱신 — 예전엔 "지금 비중
        # 저장" 버튼을 따로 눌러야만 "비중 변화 이력"에 반영돼서, 방금 여기서
        # 리밸런싱하고 저장해도 이력 표엔 안 뜨는 게 당연한 동작인데 사용자 입장에선
        # "왜 안 떠?"로 보였음(2026-07-24 피드백). 이제 저장할 때마다 오늘 날짜
        # 스냅샷을 최신 상태로 덮어씀(_snap_upsert가 (date,person) 단위 upsert라
        # 같은 날 여러 번 저장해도 안전 — 마지막 상태로만 남음). _he_cur는 현재
        # person 필터가 보여주는 범위 그대로(전체 선택 시 이미 전체, 특정 사람
        # 선택 시 그 사람 행만 — CASH 행 포함) — "지금 비중 저장" 버튼과 동일하게
        # selected_person을 그대로 태그(2026-07-24, "대상이 왜 전체냐" 피드백으로
        # _he_save/"전체" 고정에서 변경 — _he_save는 파일 저장용 병합본이라 스냅샷
        # 범위엔 안 맞았음).
        from datetime import date as _he_date_cls
        _stock_price_map = dict(zip(summary["ticker"].astype(str).str.upper(), summary["close"])) if not summary.empty else {}
        _coin_price_map  = {str(k).upper(): v for k, v in _i_cp.items()}
        _snap_pct_auto, _snap_amt_auto, _snap_total_auto = _compute_role_alloc_snapshot(
            _he_cur, core_etfs, _stock_price_map, _coin_price_map
        )
        _snap_msg_suffix = ""
        if _snap_total_auto > 0:
            _snap_date_now = _he_date_cls.today().strftime("%Y-%m-%d")
            _snap_save(_snap_upsert(_snap_load(), {
                "date": _snap_date_now, "person": selected_person,
                "total": int(round(_snap_total_auto)),
                "alloc": _snap_pct_auto,
                "alloc_amount": {k: int(round(v)) for k, v in _snap_amt_auto.items()},
            }))
            _snap_msg_suffix = f" · {_snap_date_now} 스냅샷도 갱신됨"

        if _rb_gh_token():
            _he_ok, _he_err = _rb_gh_put("holdings.csv", _he_save.to_csv(index=False), "data: 보유 내역 갱신")
            if _he_ok:
                st.session_state["_he_save_msg"] = (f"✅ GitHub에 저장됐습니다.{_snap_msg_suffix}", True)
            else:
                st.session_state["_he_save_msg"] = (f"⚠️ 로컬 저장됨. GitHub 저장 실패 — {_he_err}{_snap_msg_suffix}", False)
        else:
            st.session_state["_he_save_msg"] = (f"⚠️ GITHUB_TOKEN 미설정 — 로컬에만 저장됐습니다.{_snap_msg_suffix}", False)
        st.rerun()

st.divider()

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

# 3. 코인 사이클 (MVRV) — 경계값(0/1.5/2.5)은 scripts.onchain.classify_regime()이 SSOT.
# 문구 자체는 이 페이지 전용 서술이라 그대로 두고, 조건만 그 함수로 통일(2026-07-22) —
# 이 파일 안에서만 같은 0/1.5/2.5 경계가 7곳에 따로 박혀있던 걸 정리.
_i_regime = classify_regime(_i_mvrv)["regime"]
if _i_regime == "deep_value":
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
elif _i_regime == "accumulation":
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
elif _i_regime == "bull":
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
    if _i_regime in ("deep_value", "accumulation") else
    f"코인 시장 온도 지수({_i_mvrv:.2f})가 과열 경계에 진입했으니 단계적 매도를 시작할 타이밍입니다."
    if _i_regime == "bull" else
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
if _i_regime in ("deep_value", "accumulation"):
    _i_guide.append((
        "②", "코인 매도 — 온도 지수 1.5까지 대기",
        f"현재 온도 지수 {_i_mvrv:.2f}는 저평가 구간입니다. "
        f"손실이 크더라도 지금 파는 건 최악의 타이밍입니다. "
        f"지수가 1.5를 넘을 때 아래 로드맵의 Group 1(소형 알트)부터 정리를 시작하세요.",
    ))
elif _i_regime == "bull":
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
# _h_regime/_h_vix/_h_vsig는 페이지 상단(summary 로드 직후)에서 이미 계산됨
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

    _ticker_action_map: dict = {}   # ticker(upper) → 보유현황 액션 레이블

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
        # technical_signals/volume_signals는 results/{ticker}_signals.csv를 찾는데
        # 코인 파일명은 results/coin_{ticker}_signals.csv라 코인은 전부 빈 값({})을 받아
        # 기본값(ma_score=0 등)으로 조용히 대체되던 버그가 있었음(2026-07-20 발견) — 코인은
        # 애초에 bb_pct/macd_hist/obv 컬럼 자체가 없어서 파일명만 고쳐도 못 씀. 코인은
        # coin_summary.csv 기반 전용 로직(RSI H20 검증값·MVRV regime)으로 분리.
        _res_dir = ROOT / "results"
        _is_coin_tk = _tbl["ticker"].str.contains("-USD", na=False)
        _vsigs, _tsigs = [], []
        for _tk, _is_c in zip(_tbl["ticker"], _is_coin_tk):
            if _is_c:
                _vsigs.append({})
                _tsigs.append({})
            else:
                _vsigs.append(volume_signals(str(_tk), _res_dir))
                _tsigs.append(technical_signals(str(_tk), _res_dir))

        # 1M 수익률 룩업 (summary_signals에서)
        _sum_latest = summary.sort_values("date").groupby("ticker").last().reset_index()
        _sum_latest["ticker"] = _sum_latest["ticker"].astype(str).str.upper()
        _ret1m_map = dict(zip(_sum_latest["ticker"], _sum_latest.get("return_1m_pct", pd.Series(dtype=float))))
        _trend_map = dict(zip(_sum_latest["ticker"], _sum_latest.get("state", pd.Series(dtype=object))))
        _rsi_map   = dict(zip(_sum_latest["ticker"], _sum_latest.get("rsi14", pd.Series(dtype=float))))

        # 코인 신호 맵 (coin_summary.csv — RSI<=25 과매도만 유효, H20 검증 / MVRV regime)
        _coin_sig_map: dict = {}
        if not _i_csum.empty:
            for _, _cr in _i_csum.iterrows():
                _coin_sig_map[str(_cr["ticker"]).upper()] = {
                    "rsi": _cr.get("rsi14"), "regime": _cr.get("regime"),
                    "action": _cr.get("action"),
                }

        def _coin_overheat_lbl(rsi):
            if rsi is None or pd.isna(rsi):
                return "—"
            if rsi <= 25:
                return "❄️ 과매도(반등여지)"   # H20 검증: 적중률 51~54%
            return "➡️ 보통"

        # 코인 액션 문구는 scripts/crypto_analysis.py::coin_holdings_action_text()로 이동
        # (2026-07-22) — 같은 파일의 리밸런싱 인사이트(coin_rebalance_insight())와 짝을
        # 이뤄서 tests/test_coin_regime_consistency.py가 "같은 코인이면 두 문구의 방향이
        # 절대 안 갈린다"를 자동 검증할 수 있도록 함. 인라인으로 각자 떨어져 있으면
        # 한쪽만 고치고 잊어버리는 사고가 반복됨(실제로 있었음).
        _coin_action_lbl = coin_holdings_action_text

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

            # 백테스트 인사이트 우선순위 적용 — RSI·모멘텀 원시값을 표에서 숨긴 대신(2026-07-22)
            # 판단 근거가 된 실제 수치를 액션 문구에 그대로 풀어씀.
            if overheat and ret > 20 and ret_1m < 0:
                return f"⚠️ 분할매도 검토 (누적 +{ret:.0f}% 과열권인데 최근 1개월 {ret_1m:+.0f}%로 꺾임)"
            if overheat and ret > 30:
                return f"🌡️ 차익실현 고려 (누적 +{ret:.0f}% 과열권 — MA정배열+BB상단)"
            if vix_fear and ret < -10:
                return f"🔥 역발상 추가매수 (VIX 공포구간 + 손실 {ret:.0f}% — 역사적 반등 우위, IC=0.14)"
            if vol_r >= 1.4 and bb < 0.4:
                return f"📈 거래량+저점 주목 (거래량 평소 {vol_r:.1f}배 + BB하단권 — 매집 추정)"
            if ma <= 1 and ret < -15:
                return f"❄️ 추세 약세 관망 (하락추세 지속 + 손실 {ret:.0f}% — 전환 전 관망)"
            return f"✅ 유지 (누적 {ret:+.0f}%, 특이 신호 없음)"

        _overheat_col, _action_col = [], []
        for (_, _row), _t, _v, _is_c in zip(_tbl.iterrows(), _tsigs, _vsigs, _is_coin_tk):
            if _is_c:
                _csig = _coin_sig_map.get(str(_row["ticker"]).upper(), {})
                _overheat_col.append(_coin_overheat_lbl(_csig.get("rsi")))
                # G1·G2 개별손실 손절 로드맵이 MVRV보다 우선(사용자 확인) —
                # coin_holdings_action_with_stoploss()가 이 우선순위를 강제
                # 적용(별도 inline 체크로 두면 깜빡하는 사고가 반복돼서 함수로
                # 합침, 2026-07-22).
                _action_col.append(coin_holdings_action_with_stoploss(
                    _csig.get("action"), _csig.get("rsi"), _csig.get("regime"),
                    float(_row.get("수익률(%)") or 0), str(_row["ticker"]).upper(),
                ))
            else:
                _overheat_col.append(_overheat_lbl(_t, _v))
                _action_col.append(_action(_row, _t, _v))

        _tbl["과열신호"]  = _overheat_col
        _tbl["거래량신호"] = [("—" if is_c else v.get("vol_label", "—"))
                             for v, is_c in zip(_vsigs, _is_coin_tk)]
        _tbl["액션"]      = _action_col

        # 추세/국면·RSI·모멘텀(%) — "보유 종목 종합 분석" 익스팬더가 따로 있었으나 위와
        # 완전히 같은 값을 다른 이름으로 중복 표시하고 있어서 2026-07-20 이 표 하나로 통합.
        # 주식/ETF: state(골든·데드크로스)·summary RSI·1개월 수익률 / 코인: MVRV regime·
        # coin RSI·90일 수익률 — 자산별로 의미가 달라 컬럼 하나에 같이 담되 헬프텍스트로 구분.
        # 원문(bull/bear, accumulation 등)은 무슨 뜻인지 바로 안 와닿는다는 사용자
        # 피드백(2026-07-22) — 쉬운 한글로 표시. 코인 단어는 scripts.onchain.REGIME_LABEL_KR
        # 하나로 통일(2026-07-22) — rebalancing_page/portfolio_page가 각자 이 5단계를
        # 따로 재구현하며 다른 어휘로 갈라졌던 문제를 SSOT 하나로 정리.
        _STATE_KR = {"bull": "🟢 상승", "bear": "🔴 하락"}
        _REGIME_EMOJI_KR = {"deep_value": "🟢", "accumulation": "🔵", "bull": "🟠",
                             "top": "🔴", "unknown": "⚪"}
        _COIN_REGIME_KR = {k: f"{_REGIME_EMOJI_KR[k]} {v}" for k, v in REGIME_LABEL_KR.items()}

        def _trend_disp(tk, is_c):
            if is_c:
                s = _coin_sig_map.get(tk, {}).get("regime")
                return _COIN_REGIME_KR.get(s, str(s) if s else "—")
            s = _trend_map.get(tk)
            return _STATE_KR.get(s, str(s) if s else "—")

        def _rsi_disp(tk, is_c):
            v = _coin_sig_map.get(tk, {}).get("rsi") if is_c else _rsi_map.get(tk)
            return round(float(v), 1) if v is not None and pd.notna(v) else None

        _coin_ret90_map = {str(r["ticker"]).upper(): r.get("return_90d_pct")
                            for _, r in _i_csum.iterrows()} if not _i_csum.empty else {}

        _trend_col, _rsi_col, _mom_col = [], [], []
        for _tk, _is_c in zip(_tbl["ticker"], _is_coin_tk):
            _tk_u = str(_tk).upper()
            _trend_col.append(_trend_disp(_tk_u, _is_c))
            _rsi_col.append(_rsi_disp(_tk_u, _is_c))
            _mom_col.append(_coin_ret90_map.get(_tk_u) if _is_c else _ret1m_map.get(_tk_u))

        _tbl["추세/국면"] = _trend_col
        _tbl["RSI"]      = _rsi_col
        _tbl["모멘텀(%)"] = _mom_col

        # 리밸런싱 인사이트와 신호 통일을 위해 보유현황 액션 맵 저장
        _ticker_action_map = {
            str(r["ticker"]).upper(): str(r["액션"])
            for _, r in _tbl.iterrows()
        }

        # RSI·모멘텀(%) 원시값은 표에서 숨김(2026-07-22 사용자 요청) — 데이터 자체는 _tbl에
        # 남겨두고 화면 노출만 뺌. 대신 그 수치들이 실제로 만든 판단 근거는 "액션" 문구 안에
        # 그대로 풀어써서(_action/_coin_action_lbl) 숫자를 직접 안 봐도 이유를 알 수 있게 함.
        _tbl_show = _tbl[["카테고리", "종목명", "ticker", "수량", "매수가", "현재가",
                           "원금", "평가금액", "손익", "수익률(%)", "비중(%)",
                           "추세/국면",
                           "과열신호", "거래량신호", "액션"]].copy()
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
                "추세/국면":  st.column_config.TextColumn("추세/국면",
                              help="주식/ETF: 골든·데드크로스 기반 state. 코인: MVRV regime"),
                "과열신호":   st.column_config.TextColumn("과열신호",
                              help="주식/ETF: MA=3+BB>0.85 = 과열(IC 역방향 확인). "
                                   "코인: RSI<=25 과매도만 표시(H20 검증, 나머지는 신호 없음)"),
                "거래량신호": st.column_config.TextColumn("거래량",
                              help="거래량비율(IC=+0.04). 급증=기관 개입 추정. 코인은 데이터 없어 — 표시"),
                "액션":       st.column_config.TextColumn("백테스트 액션 (RSI·모멘텀 근거 포함)",
                              help="RSI·모멘텀(%) 원시값은 표에서 숨기고 이 문구 안에 근거로 풀어씀. "
                                   "주식/ETF: 수익률·1개월모멘텀·VIX·과열·거래량 신호 기반. "
                                   "코인: MVRV regime+RSI 기반(coin_summary.csv 동일 소스). 최종 결정은 직접 판단"),
            },
        )

        # 긴급 알림 (구 "보유 종목 종합 분석" 익스팬더에 있던 것 — 표 통합하며 같이 이동)
        # 위에서 "추세/국면"을 한글 라벨("🔴 하락" 등)로 바꿨으니 필터 조건도 그에 맞춤 —
        # 알림 문구도 티커 대신 종목명으로 표시(사용자 피드백, 2026-07-22).
        _bear_holds = _tbl_show[_tbl_show["추세/국면"].astype(str).str.contains("하락", na=False)]
        _hot_holds  = _tbl_show[_tbl_show["과열신호"].astype(str).str.contains("과열", na=False)]
        _deep_loss_coins = _tbl_show[(_tbl_show["카테고리"] == "코인") & (_tbl_show["수익률(%)"] < -60)]
        if not _bear_holds.empty:
            st.error(f"🔴 하락추세: {', '.join(_bear_holds['종목명'])} — 추세 전환 확인 전 추가매수 자제 (하락추세 = 향후 수익 낮은 경향)")
        if not _hot_holds.empty:
            st.warning(f"🌡️ 과열 신호: {', '.join(_hot_holds['종목명'])} — BB·MA 역방향 IC 검증됨, 일부 실현 고려")
        if not _deep_loss_coins.empty:
            st.error(
                f"🔴 60% 이상 손실 코인 {len(_deep_loss_coins)}종: "
                f"{', '.join(_deep_loss_coins['종목명'].tolist())} — "
                "원금 회복에 각각 150~900% 상승 필요. 포지션 재검토 권장"
            )
        _accum_ok_coins = _tbl_show[(_tbl_show["카테고리"] == "코인") & (_tbl_show["추세/국면"] == "🔵 매집")
                                     & (_tbl_show["수익률(%)"] > -30)]
        if not _accum_ok_coins.empty:
            st.info(
                f"📥 매집 국면 + 손실 소폭: {', '.join(_accum_ok_coins['종목명'].tolist())} — "
                "분할매수 검토 가능 구간 (단, 코인 변동성 유의)"
            )

st.divider()
st.subheader("🎯 리밸런싱 실행")

actions_alloc = rebalancing_actions(alloc, target_core, target_satellite, target_cash, threshold_pp=5.0)
if not actions_alloc:
    st.success("✅ 목표 배분에 ±5%p 이내. 리밸런싱 불필요.")

def _bucket_deficits(budget):
    """budget(원)을 코어/위성/현금 부족분 비례로 배분. total_after(목표% 산정 기준
    총자산)는 항상 new_money 기준 — 판돈은 포트폴리오 안에서 자산만 바뀌는 돈이라
    총자산 자체를 늘리지 않음. budget만 new_money+판돈으로 키우면 "이번 달 실제로
    쓸 수 있는 돈"을 반영하게 된다 — 2026-07-21."""
    if budget <= 0 or alloc["Total"] <= 0:
        # 원래 로직과 동일하게 포트폴리오가 비어있으면(Total<=0) budget이 있어도
        # 전부 0 — cash_res에 budget을 흘려보내지 않는다(재검증 발견 회귀 수정).
        return 0, 0, 0
    total_after   = alloc["Total"] + new_money
    core_deficit  = max(0.0, total_after * target_core      / 100 - alloc["Core_value"])
    sat_deficit   = max(0.0, total_after * target_satellite / 100 - alloc["Satellite_value"])
    cash_deficit  = max(0.0, total_after * target_cash      / 100 - cash_amount)
    total_deficit = core_deficit + sat_deficit + cash_deficit
    if total_deficit <= 0:
        return 0, 0, budget
    scale    = min(1.0, budget / total_deficit)
    core_buy = round(core_deficit * scale)
    sat_buy  = round(sat_deficit  * scale)
    # core_buy/sat_buy 반올림 오차가 누적되면 cash_res가 미세하게 음수가 될 수
    # 있어(재검증 발견) 0 미만으로 안 내려가게 clamp — 표 합계가 항상 budget과
    # 정확히 일치하도록 보장.
    cash_res = max(0, budget - core_buy - sat_buy)
    return core_buy, sat_buy, cash_res

core_buy, sat_buy, cash_res = _bucket_deficits(new_money)

st.markdown("""
<style>
div[data-testid="stNumberInput"]:has(input[aria-label="추가 투자할 금액 (원)"]) label p {
    font-size: 14px !important; font-weight: 400 !important;
    color: rgb(49,51,63) !important; opacity: 0.6 !important; margin-bottom: 0 !important;
}
div[data-testid="stNumberInput"]:has(input[aria-label="추가 투자할 금액 (원)"]) [data-baseweb="input"] {
    border: none !important; background: transparent !important; box-shadow: none !important;
    min-height: auto !important;
}
div[data-testid="stNumberInput"]:has(input[aria-label="추가 투자할 금액 (원)"]) input {
    font-size: 2.25rem !important; font-weight: 600 !important; font-family: inherit !important;
    padding: 0 !important; height: auto !important; line-height: 1.2 !important;
    color: rgb(49,51,63) !important;
}
div[data-testid="stNumberInput"]:has(input[aria-label="추가 투자할 금액 (원)"]) button {
    display: none !important;
}
div[data-testid="stHorizontalBlock"]:has(input[aria-label="추가 투자할 금액 (원)"]) {
    align-items: flex-end;
}
</style>
""", unsafe_allow_html=True)
with st.container(border=True):
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
                if (row.get("전술비중(%)") or 0) > 3 and "🔥" in sig:
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

        # 역할 → 실보유 KR ETF 보유현황 액션 맵 (보유현황과 신호 통일)
        _role_to_kr_actions: dict = {}
        for _role3, _tlist3 in _role_to_tks.items():
            _acts3 = [_ticker_action_map[_t3] for _t3 in _tlist3 if _t3 in _ticker_action_map]
            if _acts3:
                _role_to_kr_actions[_role3] = _acts3

        # ── 단일 소스 RSI 맵 — summary_signals(보유현황과 동일) ───────────────
        # 리밸런싱 인사이트가 보유현황과 동일한 RSI를 표시하게 함
        _kr_rsi_map: dict = {}
        if not summary.empty:
            _sm_reb = (summary.sort_values("date")
                       .groupby("ticker").last().reset_index())
            _rsi_col_reb = next((c for c in ["rsi14", "rsi"] if c in _sm_reb.columns), None)
            if _rsi_col_reb:
                for _, _smr in _sm_reb.iterrows():
                    _rv = _smr.get(_rsi_col_reb)
                    if _rv is not None and pd.notna(_rv):
                        _kr_rsi_map[str(_smr["ticker"]).upper()] = float(_rv)

        # VIX 국면 (백테스트 검증, IC=0.14) — ETF 인사이트 핵심 드라이버
        _vix_key = _e_regime.get("key", "mixed")   # fear/complacent/bull/bear/mixed
        _vix_val = _e_regime.get("vix")

        def _get_role_signal(us_etf: str, account: str):
            """역할/코인별 신호 반환 — 검증된 지표만 사용.

            Returns: (rsi, ret, is_coin, regime, vix_key, action, avg_score)
              - 코인: action = coin_backtest 액션(매수/보유/매도), avg_score = 0
              - ETF:  RSI = 실보유 KR ETF 기준(보유현황과 동일 소스),
                      score = US ETF 복합점수(백테스트 검증)
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

            # 복합점수·수익률 — US ETF 기반 (백테스트 IC=0.14 검증)
            _rets   = [_sig_map[t]["ret1m"] for t in _tks if t in _sig_map]
            _scores = [_sig_map[t]["score"] for t in _tks if t in _sig_map]
            _avg_sc = sum(_scores)/len(_scores) if _scores else 100.0

            # RSI — 실보유 KR ETF 우선(보유현황과 동일 소스), 없으면 US ETF 폴백
            _kr_rsis = [_kr_rsi_map[t] for t in _tks if t in _kr_rsi_map]
            _us_rsis = [_sig_map[t]["rsi"] for t in _tks if t in _sig_map]
            _rsi = (sum(_kr_rsis) / len(_kr_rsis) if _kr_rsis else
                    sum(_us_rsis) / len(_us_rsis) if _us_rsis else 50.0)

            return (_rsi,
                    sum(_rets)/len(_rets) if _rets else 0.0,
                    False, "", _vix_key, "", _avg_sc)

        # VIX 국면 한글 레이블 (etf_recommend 검증 기준)
        _VIX_KR = {
            "fear":       "공포 극단",
            "bear":       "약세 구간",
            "mixed":      "혼조",
            "bull":       "강세 구간",
            "complacent": "과열 경계",
        }

        # G1·G2(출구 전략 대상 알트) 개별 보유분 손익% — 손절 로드맵 판정용.
        # 이 인사이트 루프가 coin_rebalance_insight()(MVRV+RSI 기준)만 보고
        # G1·G2 개별손실 손절 로드맵을 몰라서, 이미 손절선 훨씬 아래로 물려
        # "대기" 상태인 코인에도 "매수 우호"가 뜨던 것을 회의적 재검증에서 발견
        # (portfolio_page.py는 이미 이 로드맵을 반영 중이라 같은 코인에 대해
        # 두 페이지가 반대로 말하고 있었음, 2026-07-22).
        _g1g2_pnl: dict = {}
        for _t in COIN_EXIT_GROUPS["G1"] + COIN_EXIT_GROUPS["G2"]:
            _hsub = holdings[holdings["ticker"] == _t]
            if _hsub.empty:
                continue
            _qty = _hsub["qty"].astype(float).sum()
            if _qty <= 0:
                continue
            _avg_buy = (_hsub["qty"].astype(float) * _hsub["buy_price"].astype(float)).sum() / _qty
            _cur = _i_cp.get(_t)
            if _cur is None or _avg_buy <= 0:
                continue
            _g1g2_pnl[_t] = (_cur / _avg_buy - 1) * 100

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
            _vix_kr    = _VIX_KR.get(_vix_k, "혼조")
            # ETF score → 액션 레이블 (백테스트 복합점수 기반)
            _score_label = ("📈 매수 강세" if _avg_score > 108 else
                            "🟢 매수 우호" if _avg_score > 100 else
                            "🔵 중립"      if _avg_score > 92  else "📉 매수 약화")

            # 실보유 KR ETF 보유현황 액션 (보유현황쪽 신호와 통일)
            _kr_acts  = _role_to_kr_actions.get(_uk, [])
            _kr_sell  = any("차익실현" in _a or "분할매도" in _a for _a in _kr_acts)
            _kr_buy   = any("역발상 추가매수" in _a for _a in _kr_acts)
            _kr_label = next((
                _a.split("🌡️")[-1].strip() if "🌡️" in _a else
                _a.split("⚠️")[-1].strip() if "⚠️" in _a else _a
                for _a in _kr_acts if ("차익실현" in _a or "분할매도" in _a)
            ), "")

            _diff_pp = round(float(_rr.get("차이(%p)") or 0), 1)

            if _is_coin:
                # 코인: regime(coin_backtest ✅) + RSI<=25(H20 검증, 51~54% ✅). 문구 생성은
                # scripts/crypto_analysis.py::coin_rebalance_insight()로 이동(2026-07-22) —
                # "보유 현황" 표의 coin_holdings_action_text()와 짝을 이뤄서 같은 코인에
                # 대해 두 화면이 반대 방향을 말하는 사고가 다시 나지 않도록 테스트로 고정.
                # G1·G2 실보유분은 개별손실 손절 로드맵이 MVRV보다 우선(사용자 확인) —
                # coin_rebalance_insight_with_stoploss()가 이 우선순위를 강제 적용.
                _insight = coin_rebalance_insight_with_stoploss(
                    _raw, _regime_v, _rsi_v, _diff_pp, _g1g2_pnl.get(_uk), _uk,
                )
            else:
                # ETF 인사이트: 결론(액션) 먼저, 이유 뒤 — 보유현황 신호 통합
                _o = f"비중 {abs(_diff_pp):.1f}%p 초과"
                _b = f"비중 {_diff_pp:+.1f}%p 부족"

                if _raw < -5000:
                    if _vix_k == "fear":
                        _insight = f"🔥 축소 보류 — 공포 극단 구간이라 저점 매도 위험 ({_o})"
                    elif _rsi_v < 30:
                        _insight = f"🟡 매도 보류 — ETF 과매도 반등 가능 ({_o})"
                    elif _vix_k == "complacent" or _kr_sell:
                        _insight = f"🌡️ 단계적 축소 — {_o}, 과열 신호 겹침"
                    elif _kr_acts:
                        _insight = f"🔵 점진 축소 — {_o}, 기술적 이상 없으나 비중 조정 필요"
                    else:
                        _insight = f"🔵 점진 축소 — {_o}"
                elif _raw > 5000:
                    if _kr_sell:
                        _insight = f"⚠️ 매수 보류 — 보유 ETF 과열 중, 과열 해소 후 진입 ({_b})"
                    elif _kr_buy:
                        _insight = f"🔥 적극 매수 — {_b} + 보유현황 역발상 신호 이중 확인"
                    elif _vix_k == "fear":
                        _insight = f"🔥 역발상 매수 — {_b} + 공포 극단 구간, 역발상 타이밍"
                    elif _rsi_v < 30:
                        _insight = f"🎯 적극 매수 — {_b} + ETF 과매도 이중 신호"
                    elif _vix_k == "complacent":
                        _insight = f"🌡️ 소량 분할 매수 — {_b}, 시장 과열 주의"
                    elif _vix_k == "bear":
                        _insight = f"⚠️ 분할 매수 — {_b}, 약세 구간이나 비중 조정 필요"
                    else:
                        _insight = f"🟢 분할 매수 — {_b}"
                else:
                    if _kr_sell:
                        _insight = "🌡️ 차익실현 검토 — 비중 달성 + 보유 ETF 과열"
                    elif _vix_k in ("fear", "bear"):
                        _insight = "🟢 현재 유지 — 비중 달성, 매수 환경 우호적이나 추가 불필요"
                    elif _vix_k == "complacent":
                        _insight = "🌡️ 현재 유지 — 비중 달성 + 시장 과열, 신규 매수 없음"
                    else:
                        _insight = "🔵 현재 유지 — 비중 달성"

            # 인사이트 "매수 보류"면 추가금액도 0 — 인사이트↔배분 일치
            if _kr_sell and not _is_coin:
                _eligible = False

            _buy_eligible.append(_eligible)
            _insights.append(_insight)

        _rot_df["인사이트"] = _insights

        # ── 이번 달 매도 판돈(proceeds) 미리 계산 ────────────────────────────
        # "1단계 매도"/"2단계 판돈 재배분" 표시는 원래 위치(아래)에서 그대로 하되,
        # 판돈 숫자는 여기서 먼저 구해서 바로 아래 "배분 현황" 표의 추가금액에도
        # 반영한다 — 위쪽 표도 판돈을 반영해야 한다는 사용자 요청(2026-07-22).
        _guide_df = _rot_df[_rot_df["가이드"] == True]
        _r_buy  = _guide_df[_guide_df["차이(%p)"] >  3].sort_values("차이(%p)", ascending=False)
        _r_sell = _guide_df[_guide_df["차이(%p)"] < -3].sort_values("차이(%p)")
        _SELL_MONTHS = 3
        _this_month_proceeds = 0.0
        _rot_df["매도분(원)"] = 0
        if not _r_sell.empty:
            _excess_amt = _r_sell["차이(%p)"].abs() / 100 * _total_held
            _sell_amt_per_row = (_excess_amt / _SELL_MONTHS).round(0)
            _rot_df.loc[_sell_amt_per_row.index, "매도분(원)"] = _sell_amt_per_row.astype(int)
            _this_month_proceeds = float(_sell_amt_per_row.sum())

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

        # ── 추가금액 배분: 예산(budget)을 부족한 행에 비례 배분 ──────────────
        # 매도는 인사이트 텍스트 참고 — 추가금액은 항상 0 이상
        _bucket_def = {"core": [], "satellite": [], "cash": []}
        for i in range(len(_rot_df)):
            if _buy_eligible[i]:
                _d = max(0, float(_rot_df.iloc[i]["_raw_need"] or 0))
                _bucket_def[_buckets[i]].append((i, _d))

        def _distribute(bucket_budgets):
            """bucket_budgets={"core":..,"satellite":..,"cash":..}를 _bucket_def
            비례로 개별 종목에 배분. "2단계"에서 판돈을 포함한 예산으로 다시
            호출하기 위해 재사용 가능하게 뽑음 — 2026-07-21.

            개별 종목에 round()를 독립적으로 적용하면 버킷 합계가 budget과
            1~3원 어긋날 수 있음(재검증 발견, 2026-07-22) — "신규자금분/판돈분"
            처럼 두 번의 _distribute() 결과를 빼서 보여줄 때 그 오차가 그대로
            드러남. 최대잉여법(largest remainder)으로 버킷 합계가 항상 정확히
            budget과 같도록 배분."""
            amts = [0] * len(_rot_df)
            for _bkt, _rows in _bucket_def.items():
                if not _rows:
                    continue
                _tot = sum(d for _, d in _rows) or 1.0
                _bud = bucket_budgets[_bkt]
                _target = round(_bud)
                _raw = [(_idx, _d / _tot * _bud) for _idx, _d in _rows]
                _floors = [(_idx, int(_r), _r - int(_r)) for _idx, _r in _raw]
                for _idx, _f, _ in _floors:
                    amts[_idx] = _f
                _remainder = _target - sum(_f for _, _f, _ in _floors)
                _remainder = max(0, min(len(_floors), _remainder))
                _order = sorted(range(len(_floors)), key=lambda i: -_floors[i][2])
                for _k in range(_remainder):
                    amts[_floors[_order[_k]][0]] += 1
            for _ci in range(len(_rot_df)):
                if str(_rot_df.iloc[_ci].get("US ETF", "")).upper() == "CASH":
                    amts[_ci] = round(bucket_budgets["cash"])
                    break
            return amts

        # "배분 현황" 표의 추가금액은 신규투입 + 이번 달 매도 판돈까지 포함한
        # 예산으로 배분한다(사용자 요청, 2026-07-22) — core_buy/sat_buy/cash_res
        # (신규투입 단독, 969행)는 위쪽 "코어/위성 매수" 요약 메트릭과 아래
        # "코어 ETF 매수 후보"/"위성 매수 후보" 순위표에서 그대로 쓰이므로 건드리지
        # 않고, 별도 변수(core_buy_tot 등)로 계산한다.
        core_buy_tot, sat_buy_tot, cash_res_tot = _bucket_deficits(new_money + _this_month_proceeds)
        _buy_amts = _distribute({"core": core_buy_tot, "satellite": sat_buy_tot, "cash": cash_res_tot})
        _rot_df["추가금액(원)"] = _buy_amts

        # 신규자금분/판돈분을 따로 보여주고 합계도 낸다(사용자 요청, 2026-07-22) —
        # core_buy/sat_buy/cash_res(신규투입 단독, 969행)로 다시 배분해서 "추가금액(원)"
        # (신규투입+판돈 합산)과의 차이를 판돈분으로 분리.
        _rot_df["신규자금분(원)"] = _distribute({"core": core_buy, "satellite": sat_buy, "cash": cash_res})
        _rot_df["판돈분(원)"] = _rot_df["추가금액(원)"] - _rot_df["신규자금분(원)"]

        # 목표금액:
        #   비중 초과 행 → 목표비중% × 현재총자산 (현재보다 낮아 → 매도 필요량 시각화)
        #   비중 달성/부족 행 → 현재금액 + 추가금액 (이번 달 추가 후 예상금액)
        _rn_vals   = _rot_df["_raw_need"].astype(float)
        _by_weight = (_rot_df["목표비중(%)"].astype(float) / 100 * _rot_total).round(0)
        _by_alloc  = (_rot_df["현재금액(원)"].astype(float) +
                      _rot_df["추가금액(원)"].astype(float)).round(0)
        _rot_df["목표금액(원)"] = pd.Series(
            [int(_by_weight.iloc[i]) if _rn_vals.iloc[i] < -5000
             else int(_by_alloc.iloc[i])
             for i in range(len(_rot_df))]
        ).astype("Int64")

        _rot_df.drop(columns=["_raw_need"], inplace=True)

        # 합계 행
        _rot_total_sum  = int(_rot_df["현재금액(원)"].sum())
        _rot_new_sum    = int(_rot_df["신규자금분(원)"].sum())
        _rot_sell_sum   = int(_rot_df["매도분(원)"].sum())
        _rot_proceeds_sum = int(_rot_df["판돈분(원)"].sum())
        _rot_add_sum    = int(_rot_df["추가금액(원)"].sum())
        _rot_target_sum = int(_rot_df["목표금액(원)"].sum())  # 실제 목표금액 합계
        _rot_sum = pd.DataFrame([{
            "역할": "합계", "US ETF": "", "ISA(원화)": "", "계좌": "",
            "기본비중(%)": round(_rot_df["기본비중(%)"].sum(), 1),
            "목표비중(%)": float(target_core + target_satellite + target_cash),
            "현재비중(%)": 100.0,
            "차이(%p)":   round(float(target_core + target_satellite + target_cash) - 100.0, 1),
            "현재금액(원)": _rot_total_sum,
            "신규자금분(원)": _rot_new_sum,
            "매도분(원)": _rot_sell_sum,
            "판돈분(원)": _rot_proceeds_sum,
            "추가금액(원)": _rot_add_sum,
            "목표금액(원)": _rot_target_sum,
            "인사이트": "", "설명": "", "가이드비중(%)": None,
        }])
        _rot_df = pd.concat([_rot_df, _rot_sum], ignore_index=True)

        # 합계 행 강조 스타일
        # 신규자금/매도분/재배분을 각자 열로 보여주고 "합계(원)"(=추가금액(원))도
        # 같이 낸다 — 신규금액과 판돈을 뭉치지 말고 따로, 매도분도 별도 열로
        # 보여달라는 요청(2026-07-22). 매도분은 이 역할이 초과 보유라 이번 달
        # 팔아야 할 금액(1단계와 동일 수치), 재배분은 그렇게 판 판돈 중 이 역할에
        # 새로 배분되는 금액 — 초과 보유 행(_raw_need가 큰 음수)은 _buy_eligible
        # 조건(_raw_need>5000)을 못 만족해 애초에 배분 대상에서 빠지므로, 같은
        # 행에서 매도분·재배분이 동시에 0이 아닌 경우는 이 로직상 발생하지 않는다
        # (재검증 확인, 2026-07-22).
        _disp_cols = ["역할", "US ETF", "ISA(원화)", "계좌",
                      "목표비중(%)", "현재비중(%)", "차이(%p)",
                      "목표금액(원)", "현재금액(원)",
                      "신규자금분(원)", "매도분(원)", "판돈분(원)", "추가금액(원)", "인사이트"]
        _rot_disp = _rot_df[_disp_cols].rename(columns={
            "신규자금분(원)": "신규자금(원)", "판돈분(원)": "재배분(원)", "추가금액(원)": "합계(원)",
        }).copy()
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
                "신규자금(원)": st.column_config.NumberColumn("신규자금", format="%,d", width="small",
                                help="오늘 신규 투입액에서 이 역할에 배분되는 금액"),
                "매도분(원)":   st.column_config.NumberColumn("매도분", format="%,d", width="small",
                                help="이 역할이 비중 초과라 이번 달 매도 권장되는 금액 (1단계와 동일)"),
                "재배분(원)":   st.column_config.NumberColumn("재배분", format="%,d", width="small",
                                help="다른 역할을 매도해 생긴 판돈 중 이 역할에 새로 배분되는 금액"),
                "합계(원)":     st.column_config.NumberColumn("합계", format="%,d", width="small",
                                help="신규자금 + 재배분 = 오늘 실행할 매수 금액"),
                "목표금액(원)": st.column_config.NumberColumn("목표금액", format="%,d", width="small",
                                help="현재금액 + 합계"),
                "인사이트":    st.column_config.TextColumn("신호 & 행동 가이드", width="large"),
            },
        )
        st.caption("목표금액 = 현재금액 + 합계(신규자금+재배분).  매도분은 별도로 이번 달 실제 매도할 금액입니다.")

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

        # _guide_df/_r_buy/_r_sell은 위(1457행 부근)에서 이미 계산해둠 — "배분 현황"
        # 표의 추가금액에 판돈을 반영하려면 그보다 먼저 알아야 해서 앞으로 옮김.
        with st.container(border=True):
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

        # ── 1단계 — 매도 (비중 초과 · 이번 달 권장분) ────────────────────────
        # 2026-07-21: 예전엔 "2차(다음달)/3차(그다음)" 예상칸을 같이 보여줬는데,
        # 어차피 매달 재실행하면 다음 달엔 그 시점 기준으로 차이(%p)가 통째로
        # 다시 계산돼서 이 값들이 실제로 이어지는 계획이 아니었음(스냅샷 가정일
        # 뿐). 근거 없는 3개월 분할 스케줄을 그대로 보여주면 오히려 혼란만 줘서
        # "이번 달에 얼마 팔지"만 남기고 정리.
        # _SELL_MONTHS/_this_month_proceeds는 위(1457행 부근)에서 이미 계산해둠.
        if not _r_sell.empty:
            with st.container(border=True):
                st.markdown("##### 🔴 1단계 — 매도")
                _r_sell_disp = _r_sell.copy()
                _r_sell_disp["보유 ETF"] = _r_sell_disp["US ETF"].apply(
                    lambda u: ", ".join(_role_to_held_kr.get(u.upper(), [u]))
                )
                _r_sell_disp["총 초과금(원)"] = (
                    _r_sell_disp["차이(%p)"].abs() / 100 * _total_held
                ).round(0)
                _r_sell_disp["이번 달 매도 권장(원)"] = (_r_sell_disp["총 초과금(원)"] / _SELL_MONTHS).round(0)
                st.dataframe(
                    _r_sell_disp[["역할", "보유 ETF", "차이(%p)", "인사이트",
                                   "총 초과금(원)", "이번 달 매도 권장(원)"]],
                    hide_index=True, use_container_width=True,
                    column_config={
                        "차이(%p)":               st.column_config.NumberColumn(format="%+.1f", width="small"),
                        "인사이트":               st.column_config.TextColumn("신호 & 행동 가이드", width="large"),
                        "총 초과금(원)":          st.column_config.NumberColumn(format="%,.0f", width="small"),
                        "이번 달 매도 권장(원)": st.column_config.NumberColumn(format="%,.0f", width="small"),
                    },
                )

        # ── 2단계 — 판돈 포함 매수 배분 ──────────────────────────────────────
        # "신규자금분(원)"/"판돈분(원)"/"추가금액(원)"은 위 "배분 현황" 표 계산에서
        # 이미 다 구해뒀다(같은 신규자금-단독/판돈-포함 두 번 배분 결과) — 여기선
        # 그대로 재사용만 한다.
        _buy_rows = _rot_df[
            (_rot_df["추가금액(원)"].astype(float) > 0) &
            (_rot_df["US ETF"].str.upper() != "CASH") &
            (_rot_df["역할"] != "합계")
        ].copy()

        if not _buy_rows.empty or cash_res_tot > 0:
            if _this_month_proceeds > 0:
                _step_label = "2단계 — 판돈 재배분"
            else:
                _step_label = "이번 매수 배분"

            with st.container(border=True):
                st.markdown(f"##### 🟢 {_step_label}")

                _buy_disp = _buy_rows[["역할", "US ETF", "ISA(원화)", "신규자금분(원)", "판돈분(원)", "추가금액(원)", "인사이트"]].copy()
                _buy_disp = _buy_disp.rename(columns={"추가금액(원)": "합계(원)"})
                if cash_res_tot > 0:
                    _cash_disp_row = pd.DataFrame([{
                        "역할": "현금", "US ETF": "CASH", "ISA(원화)": "—",
                        "신규자금분(원)": round(cash_res), "판돈분(원)": round(cash_res_tot - cash_res),
                        "합계(원)": round(cash_res_tot),
                        "인사이트": "🔵 목표 현금비중 채우기 — 다음 조정 시 사용",
                    }])
                    _buy_disp = pd.concat([_buy_disp, _cash_disp_row], ignore_index=True)
                _total_row = pd.DataFrame([{
                    "역할": "합계", "US ETF": "", "ISA(원화)": "",
                    "신규자금분(원)": int(_buy_disp["신규자금분(원)"].astype(float).sum()),
                    "판돈분(원)":     int(_buy_disp["판돈분(원)"].astype(float).sum()),
                    "합계(원)":       int(_buy_disp["합계(원)"].astype(float).sum()),
                    "인사이트": "",
                }])
                _buy_disp = pd.concat([_buy_disp, _total_row], ignore_index=True)
                _buy_disp = _buy_disp[["역할", "US ETF", "ISA(원화)", "신규자금분(원)", "판돈분(원)", "합계(원)", "인사이트"]]
                st.dataframe(
                    _buy_disp,
                    hide_index=True, use_container_width=True,
                    column_config={
                        "신규자금분(원)": st.column_config.NumberColumn("신규자금", format="%,.0f", width="small"),
                        "판돈분(원)":     st.column_config.NumberColumn("재배분", format="%,.0f", width="small"),
                        "합계(원)":       st.column_config.NumberColumn("합계", format="%,.0f", width="small"),
                        "인사이트":       st.column_config.TextColumn("신호 & 행동 가이드", width="large"),
                    },
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
                "배분점수 = 100 × VIX국면배율 (섹터사이클·모멘텀은 예측력 없어 점수에서 제외, 표시는 참고용).  "
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

# ── 비중 변화 이력 ────────────────────────────────────────────────
st.subheader("📋 비중 변화 이력")
st.caption(
    "'보유 내역 관리'에서 저장할 때마다 그 시점 사람 필터 기준으로 자동으로 쌓입니다. "
    "같은 날짜·같은 대상으로 다시 저장하면 마지막 상태로 덮어씁니다."
)

_hist_snaps = _snap_load()
if _hist_snaps:
    _ROLE_LABELS = {
        "VOO":  "미국주식",
        "SCHD": "배당/가치",
        "SOXX": "성장/반도체",
        "TLT":  "장기국채",
        "GLD":  "금",
        "coin": "코인",
        "cash": "현금",
    }
    _hist_rows = []
    for _hs in _hist_snaps:
        _h_total = _hs.get("total", 0) or 0
        _h_amt   = _hs.get("alloc_amount", {})
        _hrow = {
            "날짜": _hs.get("date") or _hs.get("month", ""),
            "총자산": f"{int(_h_total):,}원",
        }
        for _rk, _rlabel in _ROLE_LABELS.items():
            _pct = _hs.get("alloc", {}).get(_rk)
            if _pct is None:
                _hrow[_rlabel] = None
                continue
            # alloc_amount가 없는 옛 항목(2026-07-23 이전 저장분)은 총자산×비중으로
            # 근사 — 반올림 오차가 조금 있을 수 있지만 표시용이라 문제 없음.
            _amt = _h_amt.get(_rk)
            _amt = float(_amt) if _amt is not None else _h_total * float(_pct) / 100
            _hrow[_rlabel] = f"{_amt:,.0f}원 ({float(_pct):.1f}%)"
        _hrow["대상"] = _hs.get("person", "전체")
        _hist_rows.append(_hrow)
    _hist_df = pd.DataFrame(_hist_rows)
    st.dataframe(
        _hist_df,
        use_container_width=True,
        hide_index=True,
        column_config={
            "날짜":   st.column_config.TextColumn("날짜", width="small"),
            "총자산": st.column_config.TextColumn("총자산", width="medium"),
            **{_rl: st.column_config.TextColumn(_rl, width="small")
               for _rl in _ROLE_LABELS.values()},
            "대상":        st.column_config.TextColumn("대상", width="small"),
        },
    )
else:
    st.info("아직 기록이 없습니다. 위 '보유 내역 관리'에서 저장하면 자동으로 쌓입니다.")

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
# 주의: scripts.onchain.classify_regime()(0/1.5/2.5 경계, 4단계)과 일부러 다른
# 체계다 — 이건 그 4단계 중 "bull"(1.5~2.5) 구간을 2.0에서 한 번 더 쪼개서
# Group1·2 물량을 "1.5에서 절반 매도 → 2.0에서 나머지 전량 매도"로 단계 집행하기
# 위한 실행 스케줄이라 classify_regime()으로 합치면 그 중간 단계가 사라진다.
# _mvrv2 자체는 classify_regime()이 읽는 것과 같은 cycle_metrics.csv/mvrv_z
# 값이라 숫자 소스는 이미 통일돼 있음 — 회의적 검증 에이전트가 "SSOT 미사용"으로
# 지적(2026-07-22)했지만 의도적 설계라 그대로 둠.
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
# 그룹 목록은 scripts.crypto_analysis.COIN_EXIT_GROUPS가 SSOT(2026-07-22) —
# portfolio_page.py의 개별 코인 매도 신호도 같은 그룹 정의를 참조함.
_G1 = COIN_EXIT_GROUPS["G1"]
_G2 = COIN_EXIT_GROUPS["G2"]
_G3 = COIN_EXIT_GROUPS["G3"]

# 개별손실 손절선(-40%)은 scripts.crypto_analysis.ALT_STOPLOSS_RECOVERY_PCT가
# SSOT — 19종목·10,940건 백테스트 근거(better_to_cut 70.2%). G1·G2 둘 다 적용,
# G3(BTC·ETH·SOL)는 핵심 장기보유라 제외(2026-07-22 사용자 확인).
_G1_RULES = [
    (1, "MVRV Z ≥ 1.5 도달",       "50% 매도"),
    (2, "MVRV Z ≥ 2.0 도달",       "나머지 전량 매도"),
    (0, f"개별 손실 {ALT_STOPLOSS_RECOVERY_PCT:.0f}% 이내 회복", "전량 매도 (조건 먼저 도달 시)"),
    (0, "2027년 말 데드라인",       "조건 미충족 시 전량 매도"),
]
_G2_RULES = [
    (1, "MVRV Z ≥ 1.5 도달", "GAS·ETC·DOGE·XRP 30% 매도 시작"),
    (2, "MVRV Z ≥ 2.0 도달", "GAS·ETC·DOGE·XRP 나머지 50% 매도"),
    (2, "MVRV Z ≥ 2.0 도달", "ENS 정리 시작 (ETH 타이밍에 맞춤)"),
    (0, f"개별 손실 {ALT_STOPLOSS_RECOVERY_PCT:.0f}% 이내 회복", "전량 매도 (조건 먼저 도달 시)"),
    (0, "2027년 말 데드라인",       "조건 미충족 시 전량 매도"),
]
_G3_RULES = [
    (3, "MVRV Z ≥ 2.5 도달",   "BTC 일부 차익 실현 고려"),
    (0, "BTC 신고점 경신 후",   "ETH·SOL 갭 메울 때 일부 정리"),
]


def _coin_group_rows(tickers, h_coin, cprice):
    """그룹 종목별 현황(이름/평가금액/손익%)만 계산 — 렌더링 없음. 요약 헤드라인과
    상세 카드 둘 다 같은 계산을 공유하려고 분리(2026-07-23, "로드맵 너무 복잡"
    피드백으로 요약 우선 표시 구조 도입하며 분리)."""
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
    return group_rows, group_val


def _coin_group_active_rules(group_rows, rules, trigger, apply_stoploss):
    """이 그룹에서 지금 당장 실행해야 하는(🔔) 규칙만 뽑아서 (조건→액션) 문자열
    리스트로 반환 — 요약 헤드라인용. _coin_roadmap_group()의 활성화 판정과
    완전히 동일한 로직(중복이지만 계산이 가벼워 성능 문제 없음)."""
    sl_hits = []
    if apply_stoploss:
        for r in group_rows:
            status, reason = coin_alt_stoploss_status(r["pnl"])
            if status == "sell":
                sl_hits.append(f"{r['name']}({reason})")
    active = []
    for lvl, cond, action in rules:
        if apply_stoploss and lvl == 0 and ("개별 손실" in cond or "데드라인" in cond):
            is_active = len(sl_hits) > 0
        else:
            is_active = (trigger >= lvl) and (lvl > 0)
        if is_active:
            extra = f" — {', '.join(sl_hits)}" if sl_hits and lvl == 0 else ""
            active.append(f"{cond} → {action}{extra}")
    return active


def _coin_roadmap_group(title, bg, border, group_rows, group_val, rules, trigger,
                         apply_stoploss=False):
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

    # "개별 손실 X% 이내 회복"/"데드라인" 규칙(lvl=0)은 MVRV 트리거로는 절대 안
    # 켜지므로(active = trigger>=lvl AND lvl>0), coin_alt_stoploss_status()로
    # 실제 종목별 손익%를 넣어 따로 평가한다 — 이전엔 이 두 줄이 문구만 있고
    # 실제로 계산된 적이 없어서 코인이 손절선까지 회복해도 카드가 항상 ⏳로만
    # 뜨던 버그였음(2026-07-22 발견).
    _sl_hits = []
    if apply_stoploss:
        for r in group_rows:
            status, reason = coin_alt_stoploss_status(r["pnl"])
            if status == "sell":
                _sl_hits.append(f"{r['name']}({reason})")

    for lvl, cond, action in rules:
        if apply_stoploss and lvl == 0 and ("개별 손실" in cond or "데드라인" in cond):
            active = len(_sl_hits) > 0
        else:
            active = (trigger >= lvl) and (lvl > 0)
        icon   = "🔔" if active else "⏳"
        bg2    = "#fef2f2" if active else "#f9fafb"
        tc     = "#b91c1c" if active else "#374151"
        extra  = f" — {', '.join(_sl_hits)}" if active and _sl_hits and lvl == 0 else ""
        st.markdown(
            f"<div style='background:{bg2};border-radius:4px;padding:5px 12px;"
            f"margin:3px 0;font-size:13px'>"
            f"{icon} <span style='color:{tc}'><b>{cond}</b> → {action}{extra}</span></div>",
            unsafe_allow_html=True,
        )
    st.markdown("<div style='height:8px'></div>", unsafe_allow_html=True)


_g1_rows, _g1_val = _coin_group_rows(_G1, _h_coin, _cprice2)
_g2_rows, _g2_val = _coin_group_rows(_G2, _h_coin, _cprice2)
_g3_rows, _g3_val = _coin_group_rows(_G3, _h_coin, _cprice2)

_g1_active = _coin_group_active_rules(_g1_rows, _G1_RULES, _trigger, apply_stoploss=True)
_g2_active = _coin_group_active_rules(_g2_rows, _G2_RULES, _trigger, apply_stoploss=True)
_g3_active = _coin_group_active_rules(_g3_rows, _G3_RULES, _trigger, apply_stoploss=False)
_all_active = (
    [("Group 1", a) for a in _g1_active]
    + [("Group 2", a) for a in _g2_active]
    + [("Group 3", a) for a in _g3_active]
)

# 코인 유니버스가 늘어날 때(예: XRP-USD 신규 편입) COIN_EXIT_GROUPS 어디에도
# 속하지 않으면 이 로드맵의 매도 규칙이 영구히 적용 안 된 채 조용히 빠짐 —
# 2026-07-23 감사에서 발견(크래시는 아니지만 무기한 미관리 상태로 남는 gap).
_grouped_tickers = set(_G1) | set(_G2) | set(_G3)
_ungrouped_held = sorted(set(_h_coin["ticker"]) - _grouped_tickers)
if _ungrouped_held:
    st.info(
        f"ℹ️ {', '.join(t.replace('-USD', '') for t in _ungrouped_held)}는 "
        "출구 그룹(G1/G2/G3) 미지정 — 이 로드맵의 매도 규칙이 적용되지 않습니다. "
        "직접 판단으로 관리하세요."
    )

# 요약 헤드라인 — "지금 뭘 해야 하나"만 먼저 보여줌. 그룹별 규칙 3개(각 2~5줄)를
# 전부 펼쳐놓으면 지금 실행할 게 있는지 알아내려고 매번 다 읽어야 해서 "너무
# 복잡하다"는 피드백(2026-07-23) — 활성화된 규칙만 상단에 모으고, 전체 규칙
# 표는 펼쳐보기로 내림.
if _all_active:
    st.error(f"🔔 지금 실행할 매도 {len(_all_active)}건")
    for _grp, _txt in _all_active:
        st.markdown(f"- **[{_grp}]** {_txt}")
else:
    st.success("✅ 지금 당장 실행할 매도 없음 — 전부 대기 중")

with st.expander("📋 그룹별 상세 규칙 보기 (Group 1·2·3 전체 조건표)"):
    _coin_roadmap_group(
        "🔴 Group 1 — 출구 전략 (TRUMP · MASK · ZETA · SAND · ID)",
        "#fff1f2", "#ef4444", _g1_rows, _g1_val, _G1_RULES, _trigger,
        apply_stoploss=True,
    )
    _coin_roadmap_group(
        "🟠 Group 2 — 조건부 축소 (GAS · DOGE · ETC · ENS · XRP)",
        "#fff7ed", "#f97316", _g2_rows, _g2_val, _G2_RULES, _trigger,
        apply_stoploss=True,
    )
    _coin_roadmap_group(
        "🟢 Group 3 — 코어 코인 유지 (BTC · ETH · SOL)",
        "#f0fdf4", "#22c55e", _g3_rows, _g3_val, _G3_RULES, _trigger,
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
