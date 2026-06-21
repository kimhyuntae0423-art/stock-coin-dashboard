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

# =====================================================================
# 공통 데이터 로드
# =====================================================================
st.title("⚖️ 리밸런싱")
st.caption("코어-위성 자산배분 추적 · 추천 분산 포트폴리오.")

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
target_core      = int(st.session_state.get("tgt_core_", 70))
target_satellite = int(st.session_state.get("tgt_sat_",  20))
target_cash      = int(st.session_state.get("tgt_cash_", 10))
cash_amount      = float(st.session_state.get("cash_amt_", 0))
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

ic1, ic2, ic3, ic4, ic5 = st.columns(5)
with ic1:
    target_core = st.number_input("🏛️ 코어 목표 (%)", min_value=0, max_value=100, value=70, step=5, key="tgt_core_")
with ic2:
    target_satellite = st.number_input("🎯 위성 목표 (%)", min_value=0, max_value=100, value=20, step=5, key="tgt_sat_")
with ic3:
    target_cash = st.number_input("💵 현금 목표 (%)", min_value=0, max_value=100, value=10, step=5, key="tgt_cash_")
with ic4:
    cash_amount = st.number_input("💵 현재 보유 현금", min_value=0, value=0, step=100_000,
                                  help="MMF, CMA 등 즉시 사용 가능한 현금.", key="cash_amt_")
with ic5:
    new_money = st.number_input("💰 추가 투자할 금액 (원)", min_value=0, value=1_000_000,
                                step=100_000, key="new_money_input")

if target_core + target_satellite + target_cash != 100:
    st.warning(f"⚠️ 목표 비중 합계 {target_core + target_satellite + target_cash}% — 100%가 되도록 조정해주세요.")

aa1, aa2, aa3, aa4 = st.columns(4)
aa1.metric("🏛️ 코어", f"{alloc['Core_pct']:.1f}%",
           delta=f"{alloc['Core_pct'] - target_core:+.1f}pp (목표 {target_core}%)", delta_color="off")
aa2.metric("🎯 위성", f"{alloc['Satellite_pct']:.1f}%",
           delta=f"{alloc['Satellite_pct'] - target_satellite:+.1f}pp (목표 {target_satellite}%)", delta_color="off")
aa3.metric("💵 현금", f"{alloc['Cash_pct']:.1f}%",
           delta=f"{alloc['Cash_pct'] - target_cash:+.1f}pp (목표 {target_cash}%)", delta_color="off")
aa4.metric("💼 총 자산", f"{alloc['Total']:,.0f}원", delta_color="off")

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
    mc1, mc2, mc3 = st.columns(3)
    mc1.metric("🏛️ 코어 매수", f"{core_buy:,.0f}원")
    mc2.metric("🎯 위성 매수", f"{sat_buy:,.0f}원")
    mc3.metric("💵 현금 유보", f"{cash_res:,.0f}원")
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

        _rot_df["현재비중(%)"] = _rot_df["US ETF"].apply(
            lambda t: round(_held_map.get(str(t).upper(), {}).get("현재비중(%)", 0.0), 1)
        )
        _rot_df["차이(%p)"] = (_rot_df["목표비중(%)"] - _rot_df["현재비중(%)"]).round(1)

        st.dataframe(
            _rot_df[["역할", "US ETF", "ISA(원화)", "계좌", "기본비중(%)", "목표비중(%)", "현재비중(%)", "차이(%p)"]],
            hide_index=True, use_container_width=True,
            column_config={
                "역할":        st.column_config.TextColumn("역할"),
                "US ETF":     st.column_config.TextColumn("US ETF"),
                "ISA(원화)":  st.column_config.TextColumn("ISA 원화 ETF",
                               help="ISA 계좌에서 매수할 국내 상장 ETF. '—'이면 ISA 불가(세금 22%)."),
                "계좌":        st.column_config.TextColumn("계좌"),
                "기본비중(%)": st.column_config.NumberColumn("기본비중(%)", format="%.1f"),
                "목표비중(%)": st.column_config.ProgressColumn(
                               "목표비중(%)", format="%.1f%%", min_value=0, max_value=50),
                "현재비중(%)": st.column_config.NumberColumn("현재비중(%)", format="%.1f"),
                "차이(%p)":    st.column_config.NumberColumn("차이(%p)", format="%+.1f",
                               help="ISA 역할만 가이드 제공. ±3%p 이내는 유지."),
            },
        )
        st.caption("⚠️ 원자재/구리·헬스케어/방어는 참고용 — ISA 불가(양도세 22%)로 가이드 제외.")

        _guide_df = _rot_df[_rot_df["가이드"] == True].copy()
        _r_buy  = _guide_df[_guide_df["차이(%p)"] >  3].sort_values("차이(%p)", ascending=False)
        _r_sell = _guide_df[_guide_df["차이(%p)"] < -3].sort_values("차이(%p)")
        _rc1, _rc2 = st.columns(2)
        with _rc1:
            if not _r_buy.empty:
                st.success("**확대 필요** (+3%p↑)")
                for _, _rr in _r_buy.iterrows():
                    _isa_txt = _rr["ISA(원화)"].split("\n")[0]
                    st.markdown(f"- **{_rr['US ETF']}** / ISA: {_isa_txt} `+{_rr['차이(%p)']:.1f}%p`")
            else:
                st.success("확대 필요 역할 없음")
        with _rc2:
            if not _r_sell.empty:
                st.warning("**축소 필요** (−3%p↓)")
                for _, _rr in _r_sell.iterrows():
                    st.markdown(f"- **{_rr['US ETF']}** `{_rr['차이(%p)']:.1f}%p`")
            else:
                st.warning("축소 필요 역할 없음")

        if core_buy > 0:
            st.markdown("**이번 매수 배분** (ISA 역할 기준)")
            _guide_df["추천금액(원)"] = (_guide_df["가이드비중(%)"] / 100 * core_buy).round(0)
            st.dataframe(
                _guide_df[["역할", "US ETF", "ISA(원화)", "가이드비중(%)", "추천금액(원)"]],
                hide_index=True, use_container_width=True,
                column_config={
                    "가이드비중(%)": st.column_config.NumberColumn("배분비중(%)", format="%.1f"),
                    "추천금액(원)":  st.column_config.NumberColumn(format="%,.0f"),
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

# ── 적립 & 리밸런싱 시뮬레이션 ──────────────────────────────────
st.subheader("📈 적립 시뮬레이션")
st.caption("강제 매도 없이 신규 자금 배분만으로 목표 비중에 점진적으로 수렴하는 경로를 보여줍니다. 확정 수익률 모형(세금·보수 미반영).")

_sc1, _sc2, _sc3, _sc4 = st.columns(4)
with _sc1:
    _sim_monthly = st.number_input("월 적립액 (원)", min_value=0, value=1_000_000,
                                   step=100_000, key="sim_monthly")
with _sc2:
    _sim_years = st.slider("기간 (년)", min_value=1, max_value=30, value=15, key="sim_years")
with _sc3:
    _sim_r_core = st.slider("코어 연수익률 (%)", min_value=0, max_value=15, value=8, key="sim_r_core")
with _sc4:
    _sim_r_sat = st.slider("위성 연수익률 (%)", min_value=-10, max_value=20, value=5, key="sim_r_sat")

_sc5, _sc6, _sc7 = st.columns(3)
with _sc5:
    _contrib_core_pct = st.slider(
        "신규 자금 → 코어 (%)", 0, 100, 100, 5, key="sim_contrib_core",
        help="월 적립액 중 코어(S&P ETF)에 넣는 비중",
    )
with _sc6:
    _contrib_cash_pct = st.slider(
        "신규 자금 → 현금 (%)", 0, 100, 0, 5, key="sim_contrib_cash",
        help="월 적립액 중 현금(MMF·CMA)으로 유보하는 비중",
    )
with _sc7:
    _sim_freq = st.selectbox(
        "강제 리밸런싱 주기",
        ["없음 (매도 안 함)", "매월", "분기", "반기", "매년"], index=0, key="sim_freq",
        help="'없음' 선택 시 신규 자금 배분만으로 비중을 조정합니다.",
    )

_contrib_sat_pct = max(0, 100 - _contrib_core_pct - _contrib_cash_pct)
if _contrib_core_pct + _contrib_cash_pct > 100:
    st.warning("코어 + 현금 합계가 100%를 초과합니다. 위성은 0%로 처리됩니다.")
else:
    st.caption(f"위성 자동 배분: {_contrib_sat_pct}%  (코어 {_contrib_core_pct}% + 현금 {_contrib_cash_pct}% + 위성 {_contrib_sat_pct}% = 100%)")

_freq_map   = {"없음 (매도 안 함)": 0, "매월": 1, "분기": 3, "반기": 6, "매년": 12}
_sim_freq_m = _freq_map[_sim_freq]

_sv_core       = float(alloc["Core_value"])
_sv_sat        = float(alloc["Satellite_value"])
_sv_cash       = float(cash_amount)
_r_c_m         = _sim_r_core / 100 / 12
_r_s_m         = _sim_r_sat  / 100 / 12
_r_x_m         = 0.02 / 12
_months_total  = _sim_years * 12
_initial_total = _sv_core + _sv_sat + _sv_cash

_xs, _cores, _sats, _cashs = [], [], [], []
_core_target_month = None  # 코어가 목표 비중 도달하는 시점

for _m in range(_months_total + 1):
    _tot = _sv_core + _sv_sat + _sv_cash
    _xs.append(_m / 12)
    _cores.append(_sv_core)
    _sats.append(_sv_sat)
    _cashs.append(_sv_cash)
    if _core_target_month is None and _tot > 0 and (_sv_core / _tot * 100) >= target_core:
        _core_target_month = _m / 12
    if _m == _months_total:
        break
    _sv_core *= (1 + _r_c_m)
    _sv_sat  *= (1 + _r_s_m)
    _sv_cash *= (1 + _r_x_m)
    _sv_core += _sim_monthly * _contrib_core_pct / 100
    _sv_sat  += _sim_monthly * _contrib_sat_pct  / 100
    _sv_cash += _sim_monthly * _contrib_cash_pct / 100
    if _sim_freq_m > 0 and (_m + 1) % _sim_freq_m == 0:
        _st = _sv_core + _sv_sat + _sv_cash
        _sv_core = _st * target_core      / 100
        _sv_sat  = _st * target_satellite / 100
        _sv_cash = _st * target_cash      / 100

_final_total    = _sv_core + _sv_sat + _sv_cash
_invested_total = _initial_total + _sim_monthly * _months_total
_invested_line  = [_initial_total + _sim_monthly * _m for _m in range(_months_total + 1)]
_totals         = [c + s + x for c, s, x in zip(_cores, _sats, _cashs)]
_core_pcts      = [c / t * 100 if t > 0 else 0 for c, t in zip(_cores, _totals)]
_sat_pcts       = [s / t * 100 if t > 0 else 0 for s, t in zip(_sats,  _totals)]
_cash_pcts      = [x / t * 100 if t > 0 else 0 for x, t in zip(_cashs, _totals)]

_tab1, _tab2 = st.tabs(["💰 자산 가치", "📊 비중 변화"])

with _tab1:
    _fig_val = go.Figure()
    _fig_val.add_trace(go.Scatter(
        x=_xs, y=_cashs, name="현금",
        stackgroup="one", fillcolor="rgba(34,197,94,0.45)",
        line=dict(width=0), mode="none",
    ))
    _fig_val.add_trace(go.Scatter(
        x=_xs, y=_sats, name="위성",
        stackgroup="one", fillcolor="rgba(249,115,22,0.45)",
        line=dict(width=0), mode="none",
    ))
    _fig_val.add_trace(go.Scatter(
        x=_xs, y=_cores, name="코어",
        stackgroup="one", fillcolor="rgba(59,130,246,0.45)",
        line=dict(width=0), mode="none",
    ))
    _fig_val.add_trace(go.Scatter(
        x=_xs, y=_invested_line, name="누적 원금",
        line=dict(color="#94a3b8", width=2, dash="dash"), mode="lines",
    ))
    _fig_val.update_layout(
        height=380, margin=dict(t=20, b=20, l=10, r=10),
        xaxis=dict(title="년", showgrid=True, gridcolor="rgba(0,0,0,0.06)", dtick=1),
        yaxis=dict(title="자산 (원)", tickformat=",d", showgrid=True, gridcolor="rgba(0,0,0,0.06)"),
        legend=dict(orientation="h", yanchor="bottom", y=1.02, x=0),
        paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(0,0,0,0)",
        hovermode="x unified",
    )
    st.plotly_chart(_fig_val, use_container_width=True)

with _tab2:
    _fig_pct = go.Figure()
    _fig_pct.add_trace(go.Scatter(
        x=_xs, y=_cash_pcts, name="현금",
        stackgroup="one", fillcolor="rgba(34,197,94,0.45)",
        line=dict(width=0), mode="none",
    ))
    _fig_pct.add_trace(go.Scatter(
        x=_xs, y=_sat_pcts, name="위성",
        stackgroup="one", fillcolor="rgba(249,115,22,0.45)",
        line=dict(width=0), mode="none",
    ))
    _fig_pct.add_trace(go.Scatter(
        x=_xs, y=_core_pcts, name="코어",
        stackgroup="one", fillcolor="rgba(59,130,246,0.45)",
        line=dict(width=0), mode="none",
    ))
    # 목표 비중 점선
    _fig_pct.add_hline(y=target_core, line_dash="dot", line_color="#3b82f6", line_width=1.5,
                       annotation_text=f"코어 목표 {target_core}%", annotation_position="right")
    _fig_pct.add_hline(y=100 - target_core, line_dash="dot", line_color="#f97316", line_width=1,
                       annotation_text=f"위성+현금 목표 {100 - target_core}%", annotation_position="right")
    # 목표 도달 세로선
    if _core_target_month is not None:
        _fig_pct.add_vline(x=_core_target_month, line_dash="dash", line_color="#3b82f6", line_width=1.5,
                           annotation_text=f"코어 목표 도달\n{_core_target_month:.1f}년", annotation_position="top left")
    _fig_pct.update_layout(
        height=380, margin=dict(t=20, b=20, l=10, r=10),
        xaxis=dict(title="년", showgrid=True, gridcolor="rgba(0,0,0,0.06)", dtick=1),
        yaxis=dict(title="비중 (%)", range=[0, 100], showgrid=True, gridcolor="rgba(0,0,0,0.06)"),
        legend=dict(orientation="h", yanchor="bottom", y=1.02, x=0),
        paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(0,0,0,0)",
        hovermode="x unified",
    )
    st.plotly_chart(_fig_pct, use_container_width=True)
    if _core_target_month is not None:
        st.success(f"✅ 현재 설정대로면 약 **{_core_target_month:.1f}년** 후 코어 비중이 목표({target_core}%)에 도달합니다. (강제 매도 없음)")
    else:
        st.warning(f"⚠️ {_sim_years}년 내에 코어 목표 비중({target_core}%)에 도달하지 못합니다. 기간을 늘리거나 월 적립액을 높여보세요.")

_multiple = _final_total / _invested_total if _invested_total > 0 else 0
_net_gain = _final_total - _invested_total
_cagr     = (_final_total / max(_initial_total, 1)) ** (1 / _sim_years) - 1 if _sim_years > 0 else 0

_sm1, _sm2, _sm3, _sm4 = st.columns(4)
_sm1.metric("💰 누적 투자 원금",   f"{_invested_total:,.0f}원")
_sm2.metric("📈 최종 예상 자산",   f"{_final_total:,.0f}원",
            delta=f"+{_net_gain:,.0f}원", delta_color="normal")
_sm3.metric("✖️ 원금 회수 배수",   f"{_multiple:.2f}x")
_sm4.metric("📊 포트폴리오 CAGR",  f"{_cagr*100:.1f}%",
            help="초기 자산 기준 연평균 복합 수익률")

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
