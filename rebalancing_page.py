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
st.markdown(
    "<div style='background:#f8fafc;border:1px solid #e2e8f0;border-radius:10px;"
    "padding:16px 20px;margin-bottom:4px'>"
    "<div style='font-size:14px;font-weight:700;color:#334155;margin-bottom:10px'>"
    "📊 포트폴리오 전반 인사이트</div>",
    unsafe_allow_html=True,
)

# 전체 요약
st.markdown(
    f"<div style='background:#f1f5f9;border-radius:8px;padding:12px 15px;margin-bottom:14px'>"
    f"<div style='font-size:12px;font-weight:600;color:#64748b;margin-bottom:5px'>📝 전체 요약</div>"
    f"<div style='color:#1e293b;font-size:13px;line-height:1.75'>{_i_summary_text}</div>"
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

# 전체 가이드
st.markdown(
    "<div style='font-size:12px;font-weight:600;color:#64748b;margin-top:6px;margin-bottom:6px'>"
    "▸ 전체 가이드 (우선순위 순)</div>",
    unsafe_allow_html=True,
)
for _gn, _gt, _gb in _i_guide:
    st.markdown(
        f"<div style='background:#ffffff;border:1px solid #e2e8f0;border-radius:6px;"
        f"padding:9px 13px;margin-bottom:6px'>"
        f"<div style='font-weight:700;color:#1e293b;font-size:13px;margin-bottom:3px'>"
        f"{_gn} {_gt}</div>"
        f"<div style='color:#4b5563;font-size:13px;line-height:1.65'>{_gb}</div>"
        f"</div>",
        unsafe_allow_html=True,
    )
st.markdown("</div>", unsafe_allow_html=True)

st.divider()

# ── Core-Satellite 자산 배분 추적기 ─────────────────────────────
st.subheader("🏛️ Core-Satellite 자산 배분 추적")
st.caption(
    "**Core (시장 ETF)** + **Satellite (개별주 + 코인)** + **Cash** 비중을 목표 대비 추적. "
    "코인은 Satellite에 합산됩니다. 현금 비중은 직접 입력합니다."
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
price_map_alloc = dict(zip(view_alloc["ticker"].str.upper(), view_alloc["close"]))
# 코인은 summary_signals에 없어 close=NaN → _i_cp(coin_summary KRW 환산)로 보완
for _ct, _cp_val in _i_cp.items():
    price_map_alloc[str(_ct).upper()] = _cp_val
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
        # 장기 시장 초과수익 기대: composite ≥ +1.5(상위 7%) AND quality_z > 0(수익성 평균 이상)
        # 근거: Fama-French/AQR — Value+Quality 교차점이 장기 알파의 핵심 동인
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
            st.caption(f"QVGM ≥ +{_STOCK_THRESHOLD} & 수익성 평균 이상 — 장기 시장 초과수익 기대 종목입니다.")
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
