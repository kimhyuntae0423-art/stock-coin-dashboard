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

2026-08-25: 위 "국면 변경 시만" 방지는 BTC 사이클/코인 추세 전환 알림에만
있었고, 정작 제일 자주 뜨는 개별 종목 손익/데드크로스 "매도 검토·주의"
알림엔 이 dedup이 없었다 — 손실 구간이 그대로 유지되기만 해도 파이프라인이
돌 때마다(매일 07:00 KST + 코드 푸시 시에도 daily-update.yml이 다시 돎)
매번 같은 내용을 다시 보냈다("하루에 여러 번 받아서 피곤하다" 피드백).
그래서 results/holding_alert_state.json에 로트(ticker+person+buy_price)별
마지막 발송 severity를 저장해뒀다가, severity가 실제로 바뀔 때만(예: 주의→
매도 검토, 매도 검토→회복) 다시 보내도록 통일했다(_dedup_holding_alert).
"""
import json
import os
import re
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
HOLDING_ALERT_STATE = ROOT / "results" / "holding_alert_state.json"
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


def _load_holding_alert_state() -> dict:
    if not HOLDING_ALERT_STATE.exists():
        return {}
    try:
        with open(HOLDING_ALERT_STATE, "r", encoding="utf-8") as f:
            return json.load(f)
    except (json.JSONDecodeError, OSError):
        return {}


def _save_holding_alert_state(state: dict) -> None:
    HOLDING_ALERT_STATE.parent.mkdir(parents=True, exist_ok=True)
    with open(HOLDING_ALERT_STATE, "w", encoding="utf-8") as f:
        json.dump(state, f, ensure_ascii=False, indent=2)


def _dedup_holding_alert(severity: int, prev_severity: int | None) -> bool:
    """이 로트를 이번에 알림 목록에 넣어야 하는지. severity 0(정상 복귀)은
    애초에 알림 대상이 아니라 항상 False — 상태 저장 여부는 check()가
    별도로 처리(이번 실행에 severity 0인 로트는 new_state에서 자연히
    빠지므로, 나중에 다시 severity>0이 되면 "새로 걸린 것"으로 재발송됨)."""
    if severity == 0:
        return False
    return prev_severity != severity


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

    prev_state = _load_holding_alert_state()
    new_state: dict = {}
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
        if severity == 0:
            continue
        # 로트(같은 티커라도 계좌·매수가가 다르면 손익률이 달라 별도 추적 필요)별 키
        key = f"{ticker}|{row.get('person', '')}|{row.get('buy_price', '')}"
        new_state[key] = severity
        if _dedup_holding_alert(severity, prev_state.get(key)):
            alerts.append({
                "ticker": ticker,
                "severity": severity,
                "reasons": reasons,
                "close": s.get("close"),
                "rsi": s.get("rsi14"),
                "action": s.get("action"),
            })
    _save_holding_alert_state(new_state)
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


# 2026-08-24: 글자수는 더 이상 문제가 아님이 확인됐지만(200자 한도는 잘못된
# 가정이었음, 위 커밋 참고) — 종목마다 전체 사유 문장을 그대로 쓰니 "너무
# 보기 힘들다"는 피드백을 받음. 문제는 길이가 아니라 시각적 스캔이 안 되는
# 것 — 종목명 뒤에 긴 문장이 줄줄이 붙어 어디가 핵심(손익%)인지 안 보이고,
# 특히 "데드크로스…" 같은 설명은 여러 종목에 토씨 하나 안 틀리고 반복돼서
# 같은 문장을 몇 번이나 읽게 됨. 그래서 ① 손익%를 줄 맨 앞으로 빼서 한눈에
# 스캔되게 하고 ② 사유는 짧은 태그로 압축하고 ③ 반복되는 태그의 설명은
# 메시지 끝에 한 번만 각주로 붙인다(같은 문장 반복 제거 = "요약").
_PCT_RE = re.compile(r"[-+]\d+\.\d+%")

# (사유 문장에 포함된 부분 문자열, 짧은 설명 구절, 구절 안 전문용어 각주 —
# 각주 없으면 None). 2026-08-24: 태그 한 단어("데드크로스")까지 압축했더니
# "왜 파는지 이유를 더 풀어써달라"는 피드백 — 완전한 문장은 아니어도 "왜"가
# 담긴 짧은 구절로 되돌림.
_MVRV_FOOTNOTE = "온체인 지표(MVRV)=코인 보유자들의 평균 매수가 대비 지금 가격이 얼마나 비싼지 보는 지표. 과열 구간은 역사적으로 고점 근처였음"
_REASON_TAG_RULES: list[tuple[str, str, str | None]] = [
    ("손절 검증 구간", "손절 구간 진입, 매도 권장", "손절권장=개별 코인 손실이 -20%~-40% 구간이면 통계적으로 매도가 유리(19종목·10,940건 백테스트, 승률 70~74%)"),
    ("데드라인 도달", "로드맵 데드라인 도달, 전량 매도 권장", "로드맵데드라인=손실이 -40%보다 깊어 매도해도 통계적 이점은 없지만, 2027년 말까지 회복 안 되면 정리하기로 정한 기한"),
    ("온체인 지표가 '과열'", "온체인 지표(MVRV) 과열 구간", _MVRV_FOOTNOTE),
    ("온체인 지표가 '중립~과열'", "온체인 지표 과열 진입 전 주의", _MVRV_FOOTNOTE),
    ("손실이 커서", "손실 커서 계속 들고 갈지 재검토 필요", None),
    ("손절 기준선", "손절 기준선(-8%) 이탈", None),
    ("데드크로스", "데드크로스(하락 전환 신호)", "데드크로스=단기 평균선이 장기 평균선 아래로 내려간 하락 신호, 적중률 50.8%로 단독 신뢰도는 낮음"),
    ("RSI(상대강도지수)", "RSI 단기 과매수", "RSI=주가가 최근 얼마나 빨리 올랐는지 보는 지표. 과매수여도 강한 상승세에선 계속 오를 수 있어 주의"),
]
_MAX_ALERT_ITEMS = 6  # 한꺼번에 너무 많이 뜨면 "요약"이 아니라 "나열"이 됨(2026-08-24 실제로 겪음)


def _alert_label_pct_phrases(alert: dict) -> tuple[str, str, tuple[str, ...], list[str]]:
    """alert 하나에서 (라벨, 손익%, 사유 구절 튜플, 사용된 각주 substr 목록)을 뽑는다."""
    label = NAMES.get(alert["ticker"], alert["ticker"])
    reasons_text = " ".join(alert["reasons"])
    m = _PCT_RE.search(reasons_text)
    pct = m.group() if m else ""

    phrases: list[str] = []
    footnote_keys: list[str] = []
    for reason in alert["reasons"]:
        for substr, phrase, footnote in _REASON_TAG_RULES:
            if substr in reason and phrase not in phrases:
                phrases.append(phrase)
                if footnote:
                    footnote_keys.append(substr)
                break
    return label, pct, tuple(phrases), footnote_keys


def _render_phrase_groups(alerts: list[dict]) -> list[str]:
    """alerts를 사유 구절이 완전히 같은 종목끼리 묶어서 "📌 설명 / · 종목 %"
    형태로 렌더링(2026-08-24, "중복 설명 한 번만 쓰고 해당되는 거 밑에
    나열해달라"는 요청 반영) — 항목이 하나뿐이어도 같은 형태로 통일해서
    코인 1건짜리도 주식 여러 건짜리와 시각적으로 같은 구조가 되게 한다.
    각주(전문용어 뜻)는 이 그룹 바로 아래에 붙일 수 있게 별도로 반환."""
    groups: dict[tuple[str, ...], list[tuple[str, str]]] = {}
    order: list[tuple[str, ...]] = []
    footnotes: dict[str, str] = {}
    for a in alerts:
        label, pct, phrases, footnote_keys = _alert_label_pct_phrases(a)
        for k in footnote_keys:
            footnotes[k] = next(fn for s, _, fn in _REASON_TAG_RULES if s == k)
        if phrases not in groups:
            groups[phrases] = []
            order.append(phrases)
        groups[phrases].append((label, pct))

    lines: list[str] = []
    for phrases in order:
        items = groups[phrases]
        if not phrases:
            lines.append("📌 특이 사유 없음")
        else:
            # 사유가 여러 개면 쉼표로 욱여넣지 않고 한 줄씩 풀어써서(2026-08-24,
            # "이유를 좀더 이쁘게" 요청) 읽을 때 문장이 아니라 나열이라는 게
            # 눈에 보이게 함 — 첫 사유는 📌, 그 다음부터는 들여쓴 "+".
            lines.append(f"📌 {phrases[0]}")
            lines.extend(f"   + {p}" for p in phrases[1:])
        lines.extend(f"  · {label} {pct}" for label, pct in items)
    lines.extend(f"ℹ️ {text}" for text in footnotes.values())
    return lines


def _render_alert_group(alerts: list[dict], budget: int) -> tuple[list[str], int]:
    """alerts를 최대 budget개까지, 코인/주식으로 먼저 나눠서 렌더링한다
    (2026-08-24, "코인하고 주식하고 크게 두 개로 구분하고 각각 설명을
    달아달라"는 요청 반영 — 둘은 판단 근거 자체가 다름: 코인은 온체인 국면·
    손절 로드맵, 주식은 손익·데드크로스). 각주도 전체 메시지 끝이 아니라
    해당 코인/주식 섹션 바로 아래 붙인다("코인은 코인 밑에" 요청 반영).
    두 섹션 사이엔 빈 줄을 하나 넣는다("코인하고 주식 사이에 한 줄 띄워달라").
    반환: (렌더된 줄 목록, 생략된 종목 수)."""
    truncated = alerts[:budget]
    coins = [a for a in truncated if "-USD" in a["ticker"]]
    stocks = [a for a in truncated if "-USD" not in a["ticker"]]

    lines: list[str] = []
    if coins:
        lines.append("🪙 코인")
        lines.extend(_render_phrase_groups(coins))
    if stocks:
        if coins:
            lines.append("")
        lines.append("📈 주식")
        lines.extend(_render_phrase_groups(stocks))

    return lines, max(0, len(alerts) - budget)


def build_message(alerts: list[dict], cycle: dict | None = None) -> str | None:
    """카카오 text 템플릿(kakao_notify.send_to_self())용 메시지. 종목당
    "📌 사유 설명 / · 종목 손익%"으로 묶어 쓰고, 코인·주식 섹션 바로 아래에
    그 섹션에서 쓰인 전문용어 각주를 붙인다."""
    if not alerts and not cycle:
        return None

    high = [a for a in (alerts or []) if a["severity"] == 2]
    warn = [a for a in (alerts or []) if a["severity"] == 1]

    lines: list[str] = []
    if cycle:
        lines.append(format_cycle_alert(cycle))

    budget = _MAX_ALERT_ITEMS
    omitted_total = 0
    if high:
        lines.append(f"🔴 매도 검토 ({len(high)}건)")
        rendered, omitted = _render_alert_group(high, budget)
        lines.extend(rendered)
        budget = max(0, budget - len(high))
        omitted_total += omitted
    if warn:
        lines.append(f"🟠 주의 ({len(warn)}건)")
        rendered, omitted = _render_alert_group(warn, budget)
        lines.extend(rendered)
        omitted_total += omitted
    if omitted_total:
        lines.append(f"+ {omitted_total}건 더 — 대시보드에서 전체 확인")

    return "\n".join(lines)


def build_trend_message(trend_flips: list[dict]) -> str | None:
    """추세 전환 알림 — 매도 검토와 한 메시지에 같이 넣으면 뒤로 밀려 조용히
    잘려나가는 문제가 있어서(2026-08-21 발견) 별도 메시지로 분리 발송한다."""
    if not trend_flips:
        return None
    lines = [f"🔄 보유 코인 추세 전환 ({len(trend_flips)}건)"] + format_trend_flips(trend_flips)
    return "\n".join(lines)


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
        print(f"=== 발송할 메시지 ({label}) ===")
        print(m)
        print(f"(길이: {len(m)}자)")
        print("====================")
        if has_kakao:
            try:
                from kakao_notify import send_to_self
                send_to_self(m)
                print("✓ 카카오톡 발송 완료")
            except Exception as e:
                print(f"✗ 카카오 발송 실패: {e}")
                exit_code = 1
        else:
            print("ℹ KAKAO_REST_API_KEY / KAKAO_REFRESH_TOKEN 미설정 — 실제 발송 스킵")
    return exit_code


if __name__ == "__main__":
    sys.exit(main())
