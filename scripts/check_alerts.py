"""
보유 종목 매도/주의 신호 + BTC 사이클 단계 변경 점검 후 카카오 알림 발송.

GitHub Actions의 매일 자동 갱신 마지막 단계에서 실행.
환경변수 KAKAO_* 가 설정돼 있을 때만 알림 발송, 아니면 콘솔에만 출력.

사이클 단계 정의 (v3 포트폴리오 룰 — 2026-05-23_portfolio_v3_with_btc.md):
  peak         MVRV Z > 6  / NUPL > 0.9  / Pi > 0.95   → BTC 비중 3~5%
  euphoria     MVRV Z 4~6  / NUPL .75~.9 / Pi .85~.95  → BTC 비중 8%
  strong       MVRV Z 2~4  / NUPL .5~.75 / Pi .6~.85   → BTC 비중 12%
  accumulation MVRV Z 0~2  / NUPL 0~.5   / Pi < .6     → BTC 비중 15%
  capitulation MVRV Z < 0  / NUPL < 0                   → BTC 비중 20% (MAX)

가장 강한 신호로 보수적 판정. 단계가 변경된 날만 카톡 푸시 (스팸 방지).
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
HOLDINGS = ROOT / "holdings.csv"
SUMMARY = ROOT / "results" / "summary_signals.csv"
COIN_SUMMARY = ROOT / "results" / "coin_summary.csv"
CYCLE_METRICS = ROOT / "results" / "cycle_metrics.csv"
CYCLE_STATE = ROOT / "results" / "cycle_alert_state.json"
_RESULTS = ROOT / "results"


def _coin_bb(ticker: str) -> dict | None:
    """해당 코인의 현재 BB %B, RSI, state 계산. 데이터 부족시 None."""
    path = _RESULTS / f"coin_{ticker}_signals.csv"
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
    bb: dict | None = None, usdkrw: float = 1380.0,
) -> tuple[int, list[str]]:
    """단일 보유종목의 위험도(0=보유 / 1=논거 재검토 / 2=비중 축소(코인)) 와 사유 리스트.

    자산 유형별 신호 기준 (백테스트 검증):
      ETF  → 리밸런싱으로 관리, 알림 없음
      BTC  → MVRV Z-Score 구간 기반 (0/1.5/2.5)
      알트 → BB(%B) + 손익 복합 신호(단, 개별손실 자체의 매도판정은 G1 로드맵 기준)
      개별주 → 손실(-8%/-20%) + 데드크로스 + RSI 80+ (모두 1수준, 2수준 없음)

    usdkrw: 코인 손익 계산용 환율. sig_row["close"]는 coin_summary.csv 기준
    USD, row["buy_price"]는 holdings.csv 기준 KRW라 변환 없이 나누면 항상
    -100%에 가까운 값이 나오던 버그가 있었음(2026-07-22 발견 — 이 버그 때문에
    카카오 알림이 보유 코인 전부에 "🔴 매도 검토"를 보내고 있었음).
    """
    # ── ETF: 리밸런싱으로 관리 — 알림 불필요 ──────────────────────
    if is_etf:
        return 0, []

    # ── 코인: BTC는 MVRV 순수 적용, 알트는 MVRV + 개별 손실 병행 ──
    if is_coin:
        ticker_str = str(row.get("ticker", "")).strip().upper()
        is_btc = ticker_str == "BTC-USD"
        buy_price = row.get("buy_price")
        close = sig_row.get("close")
        if close is not None and pd.notna(close):
            close = float(close) * usdkrw  # USD -> KRW

        if is_btc:
            if mvrv_z is not None and pd.notna(mvrv_z):
                z = float(mvrv_z)
                if z >= 2.5:
                    return 2, [f"MVRV Z-Score {z:.2f} — 과열 구간 (BTC 20% 비중 목표, 백테스트 검증)"]
                elif z >= 1.5:
                    return 1, [f"MVRV Z-Score {z:.2f} — 과열 경계 (BTC 45% 구간)"]
            return 0, []

        # 알트코인: BB + 손익 복합 신호
        pct_b = bb["pct_b"] if bb else None
        rsi_bb = bb["rsi14"] if bb else None
        state_bb = bb["state"] if bb else None
        cycle_ctx = f" (MVRV Z {float(mvrv_z):.2f})" if mvrv_z is not None and pd.notna(mvrv_z) else ""

        # 신호1. BB 매도: %B>1 + RSI>70 (백테스트 -11.7%, 27% 승률)
        if pct_b is not None and rsi_bb is not None and pct_b > 1.0 and rsi_bb > 70:
            return 2, [
                f"BB 상단 이탈(%B {pct_b:.2f}) + RSI {rsi_bb:.0f}"
                f" — 알트 과열 매도 신호 (백테스트 -11.7%, 27%){cycle_ctx}"
            ]

        # 신호2. 추세 반전 조기 경보: bull + %B<0.2 (백테스트 -18.2%, 8%)
        if pct_b is not None and state_bb == "bull" and pct_b < 0.2:
            return 1, [
                f"MA 추세 bull이나 BB 하단(%B {pct_b:.2f})"
                f" — 추세 반전 조기 경보 (백테스트 -18.2%, 8%)"
            ]

        # 신호3. 손익 기반 — %B<0+RSI<30(반등 후보 구간)이면 등급 완화.
        # "-40% → 매도(severity 2)"는 백테스트 검증이 없고 코인 정리 로드맵과도
        # 무관해서, 리밸런싱 페이지의 "매수 우호"와 정반대인 카카오 알림이
        # 나가던 원인이었음(2026-07-22). G1·G2(출구 전략 대상 알트)는 실제
        # 로드맵(coin_alt_stoploss_status: 손절선 -40%, 19종목 백테스트 근거 —
        # 회복 또는 2027년 말)이 있으므로 그걸 따르고, G3(BTC·ETH·SOL, 핵심
        # 장기보유)와 로드맵 없는 코인은 severity를 1(주의)로 낮춤.
        if pd.notna(buy_price) and pd.notna(close) and float(buy_price) > 0:
            pnl_pct = (float(close) / float(buy_price) - 1) * 100
            # G1(TRUMP·MASK·ZETA·SAND·ID)은 반등후보 조건(%B<0+RSI<30) 백테스트
            # 평균 승률 25.75%(TRUMP는 0%)로 뚜렷이 실패 — 이미 손절 로드맵
            # 대상인 코인에 "반등 후보"까지 붙이면 모순이라 제외(2026-07-22,
            # portfolio_page.py와 동일 기준).
            is_bounce = (
                pct_b is not None and rsi_bb is not None
                and pct_b < 0.0 and rsi_bb < 30
                and ticker_str not in COIN_EXIT_GROUPS["G1"]
            )
            if pnl_pct < 0 and (
                ticker_str in COIN_EXIT_GROUPS["G1"] or ticker_str in COIN_EXIT_GROUPS["G2"]
            ):
                alt_status, alt_reason = coin_alt_stoploss_status(pnl_pct)
                # alt_reason이 이미 "손실 X%로/X% —"로 시작해서 앞에 pnl_pct를 또
                # 붙이면 중복 표시되던 것 수정(2026-07-22 감사에서 발견).
                if alt_status == "sell":
                    return 2, [f"{alt_reason}{cycle_ctx}"]
                return 0, []  # "wait"/None(아직 손절 검증 구간 진입 전) — 알림 불필요
            if pnl_pct <= -40:
                if is_bounce:
                    return 1, [
                        f"손익 {pnl_pct:+.1f}% 심각 — 단, BB 하단+RSI 과매도"
                        f"(%B {pct_b:.2f}, RSI {rsi_bb:.0f}) 반등 후보 구간{cycle_ctx}"
                    ]
                return 1, [
                    f"손익 {pnl_pct:+.1f}% — 개별 손실 자체는 매도 근거로 검증되지 않음, "
                    f"MVRV 국면 기준으로 판단 권장{cycle_ctx}"
                ]
            elif pnl_pct <= -20:
                if is_bounce:
                    return 0, []  # 완화 — 반등 후보 구간
                return 1, [f"손익 {pnl_pct:+.1f}% — 알트 하락 주의{cycle_ctx}"]
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
            reasons.append(f"손익 {pnl_pct:+.1f}% — 매도 검토 (투자 논거 재확인 필요)")
        elif pnl_pct <= -8:
            severity = max(severity, 1)
            reasons.append(f"손익 {pnl_pct:+.1f}% — 손절 기준선 이탈")

    # 데드크로스 — 보조 참고 (적중률 50.8%, 단독 신뢰도 낮음)
    if action in ("매도", "미보유"):
        severity = max(severity, 1)
        reasons.append("데드크로스/하락추세 — 보조 참고 (50.8% 적중)")

    # RSI 80+ — severity 1 (RSI 70+ 적중률 45%, 단독 신뢰도 낮음)
    if pd.notna(rsi) and rsi >= 80:
        severity = max(severity, 1)
        reasons.append(f"RSI {rsi:.0f} — 극단 과매수 (강한 추세에서는 계속 오를 수 있음)")

    return severity, reasons


def classify_cycle_stage(mvrv_z, nupl, pi_ratio) -> str | None:
    """세 지표 중 가장 강한 신호로 BTC 사이클 단계 판정 (보수적)."""
    stages: list[str] = []

    if pd.notna(mvrv_z):
        if mvrv_z > 6:
            stages.append("peak")
        elif mvrv_z > 4:
            stages.append("euphoria")
        elif mvrv_z > 2:
            stages.append("strong")
        elif mvrv_z >= 0:
            stages.append("accumulation")
        else:
            stages.append("capitulation")

    if pd.notna(nupl):
        if nupl > 0.9:
            stages.append("peak")
        elif nupl > 0.75:
            stages.append("euphoria")
        elif nupl > 0.5:
            stages.append("strong")
        elif nupl >= 0:
            stages.append("accumulation")
        else:
            stages.append("capitulation")

    if pd.notna(pi_ratio):
        if pi_ratio > 0.95:
            stages.append("peak")
        elif pi_ratio > 0.85:
            stages.append("euphoria")
        elif pi_ratio > 0.6:
            stages.append("strong")
        else:
            stages.append("accumulation")

    if not stages:
        return None

    # 위험·기회 시급도 우선: peak(매도) > capitulation(매수) > euphoria > strong > accumulation
    priority = {"peak": 0, "capitulation": 1, "euphoria": 2, "strong": 3, "accumulation": 4}
    return min(stages, key=lambda s: priority[s])


STAGE_TEMPLATES = {
    "peak":         "🚨 BTC 정점 위험 — 비중 3~5%로 대량 매도 룰",
    "euphoria":     "⚠️ BTC 도취 영역 — 30% 부분 익절 검토 (목표 8%)",
    "strong":       "📈 BTC 강세 — 자연 비중 상승 허용 (목표 12%)",
    "accumulation": "📊 BTC 축적/회복 — 분할매수 진행 (목표 15%)",
    "capitulation": "🟢 BTC 항복 — Cash로 적극 매수 (목표 20%)",
}


def _load_prev_stage() -> str | None:
    if not CYCLE_STATE.exists():
        return None
    try:
        with open(CYCLE_STATE, "r", encoding="utf-8") as f:
            return json.load(f).get("stage")
    except (json.JSONDecodeError, OSError):
        return None


def _save_state(stage: str, prev: str | None, metrics: dict) -> None:
    CYCLE_STATE.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "stage": stage,
        "prev_stage": prev,
        "mvrv_z": float(metrics["mvrv_z"]) if pd.notna(metrics["mvrv_z"]) else None,
        "nupl": float(metrics["nupl"]) if pd.notna(metrics["nupl"]) else None,
        "pi_ratio": float(metrics["pi_ratio"]) if pd.notna(metrics["pi_ratio"]) else None,
    }
    with open(CYCLE_STATE, "w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False, indent=2)


def check_cycle() -> dict | None:
    """BTC 사이클 단계 변경 감지. 변경 시만 dict 반환, 없으면 None."""
    if not CYCLE_METRICS.exists():
        return None
    try:
        df = pd.read_csv(CYCLE_METRICS)
    except pd.errors.EmptyDataError:
        return None
    if df.empty:
        return None

    row = df.iloc[0]
    metrics = {
        "mvrv_z": row.get("mvrv_z"),
        "nupl": row.get("nupl"),
        "pi_ratio": row.get("pi_ratio"),
    }
    current = classify_cycle_stage(**metrics)
    if current is None:
        return None

    prev = _load_prev_stage()
    if prev == current:
        return None  # 변경 없음 → 알림 스킵

    _save_state(current, prev, metrics)
    return {"stage": current, "prev_stage": prev, **metrics}


def format_cycle_alert(cycle: dict) -> str:
    head = STAGE_TEMPLATES.get(cycle["stage"], f"BTC 단계: {cycle['stage']}")
    mvrv_z = cycle.get("mvrv_z")
    if mvrv_z is not None and pd.notna(mvrv_z):
        head += f" (Z={mvrv_z:.2f})"
    prev = cycle.get("prev_stage")
    if prev:
        head += f" [from {prev}]"
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
        bb = _coin_bb(ticker) if (is_coin and not (ticker == "BTC-USD")) else None
        severity, reasons = severity_for_holding(
            row, s, mvrv_z=_mvrv_z, is_etf=is_etf, is_coin=is_coin, bb=bb, usdkrw=_usdkrw,
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


def build_message(alerts: list[dict], cycle: dict | None = None) -> str | None:
    """카카오 200자 한도 내 메시지 조립. 사이클 경보가 가장 위에 표시됨."""
    if not alerts and not cycle:
        return None

    parts: list[str] = []
    if cycle:
        parts.append(format_cycle_alert(cycle))

    high = [a for a in (alerts or []) if a["severity"] == 2]
    warn = [a for a in (alerts or []) if a["severity"] == 1]

    if high:
        if parts:
            parts.append("")
        parts.append("🔴 매도 검토")
        for a in high:
            parts.append(f"· {a['ticker']}: {', '.join(a['reasons'])}")
    if warn:
        if parts:
            parts.append("")
        parts.append("🟠 주의")
        for a in warn:
            parts.append(f"· {a['ticker']}: {', '.join(a['reasons'])}")

    msg = "\n".join(parts)
    # 200자 초과 시 잘라서 "+ N개 더"
    if len(msg) > 195:
        msg = msg[:190] + "…"
    return msg


def main():
    alerts = check()
    cycle = check_cycle()
    msg = build_message(alerts, cycle)

    if msg is None:
        print("✓ 알림 없음 — 보유 종목 정상 + BTC 사이클 단계 변경 없음")
        return 0

    print("=== 발송할 메시지 ===")
    print(msg)
    print("====================")

    if os.environ.get("KAKAO_REST_API_KEY") and os.environ.get("KAKAO_REFRESH_TOKEN"):
        try:
            from kakao_notify import send_to_self
            send_to_self(msg)
            print("✓ 카카오톡 발송 완료")
        except Exception as e:
            print(f"✗ 카카오 발송 실패: {e}")
            return 1
    else:
        print("ℹ KAKAO_REST_API_KEY / KAKAO_REFRESH_TOKEN 미설정 — 실제 발송 스킵")
    return 0


if __name__ == "__main__":
    sys.exit(main())
