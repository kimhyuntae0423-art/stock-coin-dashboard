"""
보유 종목 매도/주의 신호 + BTC MVRV 국면(regime) 변경 + 보유 코인 추세(MA50/MA200) 전환 점검 후 카카오 알림 발송.

GitHub Actions의 매일 자동 갱신 마지막 단계에서 실행.
환경변수 KAKAO_* 가 설정돼 있을 때만 알림 발송, 아니면 콘솔에만 출력.

BTC 국면 정의는 scripts/onchain.py::classify_regime()이 SSOT (0/1.5/2.5 경계,
deep_value/accumulation/bull/top) — 대시보드(portfolio_page.py 등)와 완전히
동일한 기준을 쓴다. 예전엔 이 파일 안에만 있던 별도 임계값(0/2/4/6, NUPL·Pi
Cycle 포함, 백테스트 근거 없음)을 써서 대시보드와 다른 국면을 카톡으로
보내던 불일치가 있었음(2026-08-21 발견·수정, ARCHITECTURE.md 38행 참고).

국면이 변경된 날만 카톡 푸시 (스팸 방지).
"""
import json
import os
import sys
from pathlib import Path
import pandas as pd

# kakao_notify를 어느 cwd에서든 import 가능하도록, ROOT도 추가해서
# crypto_analysis.py 내부의 "from scripts.onchain import ..." 절대 임포트가
# 풀리게 함(2026-07-22, coin_alt_stoploss_status 도입하며 추가).
_SCRIPTS_DIR = Path(__file__).resolve().parent
ROOT = _SCRIPTS_DIR.parent
sys.path.insert(0, str(_SCRIPTS_DIR))
sys.path.insert(0, str(ROOT))

from crypto_analysis import coin_alt_stoploss_status, COIN_EXIT_GROUPS
from onchain import classify_regime, REGIME_LABEL_KR
from config import NAMES_FILE, COIN_NAMES_FILE
HOLDINGS = ROOT / "holdings.csv"
SUMMARY = ROOT / "results" / "summary_signals.csv"
COIN_SUMMARY = ROOT / "results" / "coin_summary.csv"
CYCLE_METRICS = ROOT / "results" / "cycle_metrics.csv"
CYCLE_STATE = ROOT / "results" / "cycle_alert_state.json"
TREND_STATE = ROOT / "results" / "coin_trend_alert_state.json"
_RESULTS = ROOT / "results"


def load_names() -> dict:
    """티커→한글명 매핑. portfolio_page.py::load_names()와 동일 패턴(SSOT: names.csv/coin_names.csv)."""
    names: dict = {}
    for path in (NAMES_FILE, COIN_NAMES_FILE):
        if path.exists():
            df = pd.read_csv(path)
            names.update(dict(zip(df["ticker"], df["name"])))
    return names


NAMES = load_names()


def load_signals() -> pd.DataFrame:
    """주식 + 코인 summary 합쳐서 반환."""
    dfs = []
    if SUMMARY.exists():
        dfs.append(pd.read_csv(SUMMARY))
    if COIN_SUMMARY.exists():
        dfs.append(pd.read_csv(COIN_SUMMARY))
    return pd.concat(dfs, ignore_index=True) if dfs else pd.DataFrame()


def severity_for_holding(
    row, sig_row, mvrv_z=None, is_etf: bool = False, is_coin: bool = False,
    usdkrw: float = 1380.0,
) -> tuple[int, list[str]]:
    """단일 보유종목의 위험도(0=보유 / 1=논거 재검토 / 2=비중 축소(코인)) 와 사유 리스트.

    자산 유형별 신호 기준 (백테스트 검증):
      ETF  → 리밸런싱으로 관리, 알림 없음
      코인 → scripts/crypto_analysis.py의 온체인 국면(MVRV) 기준 — rebalancing_page.py
             "보유 현황" 표와 완전히 같은 판단(coin_holdings_action_text() 동일 로직)
      개별주 → 손실(-8%/-20%) + 데드크로스 + RSI 80+ (모두 1수준, 2수준 없음)

    usdkrw: 코인 손익 계산용 환율. sig_row["close"]는 coin_summary.csv 기준
    USD, row["buy_price"]는 holdings.csv 기준 KRW라 변환 없이 나누면 항상
    -100%에 가까운 값이 나오던 버그가 있었음(2026-07-22 발견 — 이 버그 때문에
    카카오 알림이 보유 코인 전부에 "🔴 매도 검토"를 보내고 있었음).

    2026-08-24: 알트코인에 "BB(%B)>1 + RSI>70 → 매도" 신호가 따로 있었는데, 이
    신호 자체가 백테스트 승률 27%(동전던지기보다 나쁨 — CLAUDE.md "검증 실패"
    표에 코인 RSI 과매수 신호가 이미 등재돼 있던 것과 같은 부류)였고,
    rebalancing_page.py의 "보유 현황" 표(coin_holdings_action_text() 기준)와도
    무관하게 따로 동작해서 — 같은 코인이 카톡에선 "매도 검토", 대시보드에선
    "매수 우호"로 동시에 뜨는 걸 실제로 확인함(사용자 목격, 예: ENS/XRP/SOL 등
    6종목이 매집(accumulation) 구간이라 대시보드는 "매수"인데 카톡은 BB 신호로
    "매도 검토"를 보내고 있었음). BB 신호 전체 제거하고 대시보드와 같은 온체인
    국면 판단만 쓰도록 통일. G1·G2 개별손실 손절 로드맵(19종목 백테스트 근거)은
    대시보드와 동일하게 그대로 최우선 유지.
    """
    # ── ETF: 리밸런싱으로 관리 — 알림 불필요 ──────────────────────
    if is_etf:
        return 0, []

    # ── 코인: 대시보드와 동일하게 온체인 국면(MVRV) 하나로 판단 ────
    if is_coin:
        ticker_str = str(row.get("ticker", "")).strip().upper()
        is_btc = ticker_str == "BTC-USD"
        buy_price = row.get("buy_price")
        close = sig_row.get("close")
        if close is not None and pd.notna(close):
            close = float(close) * usdkrw  # USD -> KRW

        regime = classify_regime(float(mvrv_z))["regime"] if (mvrv_z is not None and pd.notna(mvrv_z)) else "unknown"
        label = REGIME_LABEL_KR.get(regime, regime)  # 바닥권/매집/중립~과열/과열/미확인

        # G1·G2(출구 전략 대상 알트)는 개별손실 로드맵이 온체인 국면보다 우선
        # (대시보드 coin_holdings_action_with_stoploss()와 동일 우선순위).
        if not is_btc and pd.notna(buy_price) and pd.notna(close) and float(buy_price) > 0:
            pnl_pct = (float(close) / float(buy_price) - 1) * 100
            if pnl_pct < 0 and (
                ticker_str in COIN_EXIT_GROUPS["G1"] or ticker_str in COIN_EXIT_GROUPS["G2"]
            ):
                alt_status, alt_reason = coin_alt_stoploss_status(pnl_pct)
                if alt_status == "sell":
                    return 2, [alt_reason]
                return 0, []  # "wait"/None(아직 손절 검증 구간 진입 전) — 알림 불필요

        # 온체인 국면 판단 — rebalancing_page.py "보유 현황" 표와 동일 기준
        if regime == "top":
            return 2, [f"온체인 지표가 '{label}' 구간이에요 — 비중을 줄이는 걸 검토해보세요 (백테스트 검증)"]
        elif regime == "bull":
            return 1, [f"온체인 지표가 '{label}' 구간으로 넘어가는 중이에요 — 과열 전 주의 단계입니다"]
        return 0, []

    # ── 개별주: 매도 검토 + 주의 ─────────────────────────────────
    severity = 0
    reasons: list[str] = []

    action = sig_row.get("action")
    rsi = sig_row.get("rsi14")
    close = sig_row.get("close")
    buy_price = row.get("buy_price")

    # 손익 기반
    if pd.notna(buy_price) and pd.notna(close) and buy_price > 0:
        pnl_pct = (close / buy_price - 1) * 100
        if pnl_pct <= -20:
            severity = 2  # 개별주 -20% = 🔴 (ETF와 다름 — 기업 thesis 훼손 가능)
            reasons.append(f"매수가 대비 {pnl_pct:+.1f}% — 손실이 커서 계속 들고 갈 이유가 맞는지 다시 확인해보세요")
        elif pnl_pct <= -8:
            severity = max(severity, 1)
            reasons.append(f"매수가 대비 {pnl_pct:+.1f}% — 손절 기준선(-8%)을 넘었어요")

    # 데드크로스 — 보조 참고 (적중률 50.8%, 단독 신뢰도 낮음)
    if action in ("매도", "미보유"):
        severity = max(severity, 1)
        reasons.append("단기 이동평균이 장기 이동평균 아래로 내려간 하락 신호(데드크로스) — 참고용, 적중률 50.8%로 높지 않음")

    # RSI 80+ — severity 1 (RSI 70+ 적중률 45%, 단독 신뢰도 낮음)
    if pd.notna(rsi) and rsi >= 80:
        severity = max(severity, 1)
        reasons.append(f"RSI(상대강도지수) {rsi:.0f} — 단기 과매수 신호예요 (강한 상승 흐름에선 계속 오를 수도 있어요)")

    return severity, reasons


CYCLE_TEMPLATES = {
    "deep_value":   "🟢 BTC 바닥권 — 적극 매수 구간 (100% 목표, 백테스트 검증)",
    "accumulation": "📊 BTC 매집 — 저평가 구간 (75% 목표)",
    "bull":         "🟠 BTC 중립~과열 경계 (45% 목표)",
    "top":          "🚨 BTC 과열 — 비중 축소 검토 (20% 목표, 백테스트 검증)",
}


def _load_prev_stage() -> str | None:
    if not CYCLE_STATE.exists():
        return None
    try:
        with open(CYCLE_STATE, "r", encoding="utf-8") as f:
            return json.load(f).get("stage")
    except (json.JSONDecodeError, OSError):
        return None


def _save_state(stage: str, prev: str | None, mvrv_z) -> None:
    CYCLE_STATE.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "stage": stage,
        "prev_stage": prev,
        "mvrv_z": float(mvrv_z) if pd.notna(mvrv_z) else None,
    }
    with open(CYCLE_STATE, "w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False, indent=2)


def check_cycle() -> dict | None:
    """BTC MVRV 국면(regime) 변경 감지. 대시보드(portfolio_page.py 등)와 동일하게
    scripts/onchain.py::classify_regime()을 SSOT로 사용 — 예전엔 이 파일 안에만
    있던 별도 임계값(0/2/4/6, classify_cycle_stage)을 써서 대시보드와 다른 국면을
    카톡으로 보내던 불일치가 있었음(2026-08-21 발견, ARCHITECTURE.md 38행 참고).
    변경 시만 dict 반환, 없으면 None."""
    if not CYCLE_METRICS.exists():
        return None
    try:
        df = pd.read_csv(CYCLE_METRICS)
    except pd.errors.EmptyDataError:
        return None
    if df.empty:
        return None

    mvrv_z = df.iloc[0].get("mvrv_z")
    if pd.isna(mvrv_z):
        return None
    mvrv_z = float(mvrv_z)
    current = classify_regime(mvrv_z)["regime"]

    prev = _load_prev_stage()
    if prev == current:
        return None  # 변경 없음 → 알림 스킵

    _save_state(current, prev, mvrv_z)
    return {"stage": current, "prev_stage": prev, "mvrv_z": mvrv_z}


def format_cycle_alert(cycle: dict) -> str:
    head = CYCLE_TEMPLATES.get(cycle["stage"], REGIME_LABEL_KR.get(cycle["stage"], cycle["stage"]))
    mvrv_z = cycle.get("mvrv_z")
    if mvrv_z is not None and pd.notna(mvrv_z):
        head += f" (Z={mvrv_z:.2f})"
    prev = cycle.get("prev_stage")
    if prev:
        head += f" [from {REGIME_LABEL_KR.get(prev, prev)}]"
    return head


def check() -> list[dict]:
    """보유 중인 종목 중 신호 트리거된 항목 리스트."""
    if not HOLDINGS.exists():
        return []
    try:
        h = pd.read_csv(HOLDINGS)
    except pd.errors.EmptyDataError:
        return []
    if h.empty or h["ticker"].dropna().empty:
        return []

    signals = load_signals()
    if signals.empty:
        return []

    # MVRV Z-Score — 코인 신호 판정에 사용
    _mvrv_z: float | None = None
    if CYCLE_METRICS.exists():
        try:
            _raw = pd.read_csv(CYCLE_METRICS).iloc[0].get("mvrv_z")
            _mvrv_z = float(_raw) if pd.notna(_raw) else None
        except Exception:
            pass

    # USD/KRW 환율 — 코인 손익(신호3) 계산에 필요(rebalancing_page.py와 동일 패턴)
    try:
        import urllib.request as _ur
        with _ur.urlopen("https://api.frankfurter.app/latest?from=USD&to=KRW", timeout=4) as _r:
            _usdkrw = float(json.loads(_r.read())["rates"]["KRW"])
    except Exception:
        _usdkrw = 1380.0

    # ETF 티커 목록
    _etf_file = ROOT / "core_etfs.csv"
    _etf_tickers: set = (
        set(pd.read_csv(_etf_file)["ticker"].astype(str).str.strip())
        if _etf_file.exists() else set()
    )

    alerts: list[dict] = []
    for _, row in h.dropna(subset=["ticker"]).iterrows():
        ticker = str(row["ticker"]).strip().upper()
        is_coin = "-USD" in ticker
        is_etf = ticker in _etf_tickers
        s = signals[signals["ticker"] == ticker]
        if s.empty:
            continue
        s = s.iloc[0]
        severity, reasons = severity_for_holding(
            row, s, mvrv_z=_mvrv_z, is_etf=is_etf, is_coin=is_coin, usdkrw=_usdkrw,
        )
        if severity > 0:
            alerts.append({
                "ticker": ticker,
                "severity": severity,
                "reasons": reasons,
                "close": s.get("close"),
                "rsi": s.get("rsi14"),
                "action": s.get("action"),
            })
    return alerts


def check_trend_flip() -> list[dict]:
    """보유 코인의 MA50/MA200 추세(state) 전환(bear↔bull) 감지.
    골든/데드크로스 자체는 백테스트 검증된 예측 신호가 아니므로(CLAUDE.md
    참고) 매매 권고가 아닌 '참고 정보'로만 표시한다. 전환된 종목만 반환
    (스팸 방지, check_cycle()과 같은 패턴)."""
    if not HOLDINGS.exists():
        return []
    try:
        h = pd.read_csv(HOLDINGS)
    except pd.errors.EmptyDataError:
        return []
    if h.empty or h["ticker"].dropna().empty:
        return []

    tickers = sorted({
        str(t).strip().upper() for t in h["ticker"].dropna()
        if "-USD" in str(t).upper()
    })
    if not tickers:
        return []

    prev_states: dict = {}
    if TREND_STATE.exists():
        try:
            with open(TREND_STATE, "r", encoding="utf-8") as f:
                prev_states = json.load(f)
        except (json.JSONDecodeError, OSError):
            prev_states = {}

    flips: list[dict] = []
    current_states = dict(prev_states)
    for ticker in tickers:
        path = _RESULTS / f"coin_{ticker}_signals.csv"
        if not path.exists():
            continue
        try:
            state = pd.read_csv(path, usecols=["state"]).iloc[-1]["state"]
        except Exception:
            continue
        if pd.isna(state):
            continue
        state = str(state)
        prev = prev_states.get(ticker)
        current_states[ticker] = state
        if prev is not None and prev != state:
            flips.append({"ticker": ticker, "from": prev, "to": state})

    TREND_STATE.parent.mkdir(parents=True, exist_ok=True)
    with open(TREND_STATE, "w", encoding="utf-8") as f:
        json.dump(current_states, f, ensure_ascii=False, indent=2)
    return flips


def format_trend_flips(flips: list[dict]) -> list[str]:
    lines = []
    for flip in flips:
        label = NAMES.get(flip["ticker"], flip["ticker"])
        arrow = "📈" if flip["to"] == "bull" else "📉"
        lines.append(
            f"{arrow} {label}({flip['ticker']}): 추세 전환 {flip['from']}→{flip['to']}"
            f" (MA50/MA200 참고용, 단독 신뢰도 낮음)"
        )
    return lines


# 피드 템플릿도 무한정 길어지면 "간단 요약 보고서"가 아니라 다시 나열이 되므로
# (2026-08-24, 실제로 보유 코인이 한꺼번에 과열 신호를 받은 날 12건이 뜬 것
# 확인) 종목 단위로 최대 이 개수까지만 보여주고 나머지는 건수만 알림.
_MAX_ALERT_ITEMS = 5


def _render_alert_group(alerts: list[dict], budget: int) -> tuple[list[str], int]:
    """alerts를 최대 budget개까지 "종목명(티커)\n  · 이유" 블록으로 렌더링.
    반환: (렌더된 줄 목록, 생략된 종목 수)."""
    lines: list[str] = []
    for a in alerts[:budget]:
        label = NAMES.get(a["ticker"], a["ticker"])
        lines.append(f"{label}({a['ticker']})")
        lines.extend(f"  · {reason}" for reason in a["reasons"])
    return lines, max(0, len(alerts) - budget)


def build_message(alerts: list[dict], cycle: dict | None = None) -> tuple[str, str] | None:
    """(title, description) 반환 — kakao_notify.send_feed_to_self()용 피드 템플릿.

    2026-08-24: 예전엔 "· 종목명(티커): 이유1, 이유2"를 한 줄에 다 욱여넣어서
    "신호 나열처럼 보인다"는 피드백을 받음 — 종목마다 줄을 나누고, 제목에서
    가장 급한 등급(매도 검토 > 주의)을 먼저 알려주는 보고서 형태로 교체.
    피드 템플릿은 text 템플릿의 200자 한도보다 훨씬 여유롭지만, 그렇다고
    전부 나열하면 다시 "보고서"가 아니라 "목록"이 되므로 종목당 개수는 제한."""
    if not alerts and not cycle:
        return None

    high = [a for a in (alerts or []) if a["severity"] == 2]
    warn = [a for a in (alerts or []) if a["severity"] == 1]

    if high:
        title = f"🔴 보유 종목 점검 — 매도 검토 {len(high)}건"
    elif warn:
        title = f"🟠 보유 종목 점검 — 주의 {len(warn)}건"
    else:
        title = "📊 BTC 사이클 알림"

    parts: list[str] = []
    if cycle:
        parts.append(format_cycle_alert(cycle))

    budget = _MAX_ALERT_ITEMS
    omitted_total = 0
    if high:
        if parts:
            parts.append("")
        parts.append("🔴 매도 검토")
        lines, omitted = _render_alert_group(high, budget)
        parts.extend(lines)
        budget = max(0, budget - len(high))
        omitted_total += omitted
    if warn:
        if parts:
            parts.append("")
        parts.append("🟠 주의")
        lines, omitted = _render_alert_group(warn, budget)
        parts.extend(lines)
        omitted_total += omitted
    if omitted_total:
        parts.append("")
        parts.append(f"+ {omitted_total}건 더 — 대시보드에서 전체 확인")

    return title, "\n".join(parts)


def build_trend_message(trend_flips: list[dict]) -> tuple[str, str] | None:
    """추세 전환 알림 — 매도 검토와 한 메시지에 같이 넣으면 뒤로 밀려 조용히
    잘려나가는 문제가 있어서(2026-08-21 발견) 별도 메시지로 분리 발송한다."""
    if not trend_flips:
        return None
    title = f"🔄 보유 코인 추세 전환 {len(trend_flips)}건"
    return title, "\n".join(format_trend_flips(trend_flips))


def main():
    alerts = check()
    cycle = check_cycle()
    trend_flips = check_trend_flip()
    msg = build_message(alerts, cycle)
    trend_msg = build_trend_message(trend_flips)

    if msg is None and trend_msg is None:
        print("✓ 알림 없음 — 보유 종목 정상 + BTC 사이클/추세 변경 없음")
        return 0

    has_kakao = bool(os.environ.get("KAKAO_REST_API_KEY") and os.environ.get("KAKAO_REFRESH_TOKEN"))
    exit_code = 0
    for label, m in (("매도/주의/사이클", msg), ("추세 전환", trend_msg)):
        if m is None:
            continue
        title, description = m
        print(f"=== 발송할 메시지 ({label}) ===")
        print(f"[제목] {title}")
        print(description)
        print("====================")
        if has_kakao:
            try:
                from kakao_notify import send_feed_to_self
                send_feed_to_self(title, description)
                print("✓ 카카오톡 발송 완료")
            except Exception as e:
                print(f"✗ 카카오 발송 실패: {e}")
                exit_code = 1
        else:
            print("ℹ KAKAO_REST_API_KEY / KAKAO_REFRESH_TOKEN 미설정 — 실제 발송 스킵")
    return exit_code


if __name__ == "__main__":
    sys.exit(main())
