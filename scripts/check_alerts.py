"""
보유 종목 매도/주의 신호 점검 후 카카오 알림 발송.

GitHub Actions의 매일 자동 갱신 마지막 단계에서 실행.
환경변수 KAKAO_* 가 설정돼 있을 때만 알림 발송, 아니면 콘솔에만 출력.
"""
import os
import sys
from pathlib import Path
import pandas as pd

# kakao_notify를 어느 cwd에서든 import 가능하도록
_SCRIPTS_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(_SCRIPTS_DIR))

ROOT = _SCRIPTS_DIR.parent
HOLDINGS = ROOT / "holdings.csv"
SUMMARY = ROOT / "results" / "summary_signals.csv"
COIN_SUMMARY = ROOT / "results" / "coin_summary.csv"


def load_signals() -> pd.DataFrame:
    """주식 + 코인 summary 합쳐서 반환."""
    dfs = []
    if SUMMARY.exists():
        dfs.append(pd.read_csv(SUMMARY))
    if COIN_SUMMARY.exists():
        dfs.append(pd.read_csv(COIN_SUMMARY))
    return pd.concat(dfs, ignore_index=True) if dfs else pd.DataFrame()


def severity_for_holding(row, sig_row) -> tuple[int, list[str]]:
    """단일 보유종목의 위험도(0=보유 / 1=주의 / 2=매도 검토) 와 사유 리스트."""
    severity = 0
    reasons: list[str] = []

    action = sig_row.get("action")
    rsi = sig_row.get("rsi14")
    close = sig_row.get("close")
    buy_price = row.get("buy_price")

    # 매도 검토 신호 (severity 2)
    if action == "매도":
        severity = 2
        reasons.append("데드크로스 발생")
    if pd.notna(rsi) and rsi >= 80:
        severity = max(severity, 2)
        reasons.append(f"RSI {rsi:.0f} 극단 과매수")

    # 주의 신호 (severity 1)
    if severity < 2:
        if action == "미보유":
            severity = max(severity, 1)
            reasons.append("추세 미보유 구간")
        if pd.notna(rsi) and 70 <= rsi < 80:
            severity = max(severity, 1)
            reasons.append(f"RSI {rsi:.0f} 과매수")

    # 손익 기반 (severity 1) — 매수가 있을 때만
    if severity < 2 and pd.notna(buy_price) and pd.notna(close) and buy_price > 0:
        pnl_pct = (close / buy_price - 1) * 100
        if pnl_pct <= -8:
            severity = max(severity, 1)
            reasons.append(f"손익 {pnl_pct:+.1f}% (-8% 손절선 근접)")

    return severity, reasons


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

    alerts: list[dict] = []
    for _, row in h.dropna(subset=["ticker"]).iterrows():
        ticker = str(row["ticker"]).strip().upper()
        s = signals[signals["ticker"] == ticker]
        if s.empty:
            continue
        s = s.iloc[0]
        severity, reasons = severity_for_holding(row, s)
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


def build_message(alerts: list[dict]) -> str | None:
    """카카오 200자 한도 내 메시지 조립."""
    if not alerts:
        return None
    high = [a for a in alerts if a["severity"] == 2]
    warn = [a for a in alerts if a["severity"] == 1]

    parts = []
    if high:
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
    msg = build_message(alerts)

    if msg is None:
        print("✓ 알림 없음 — 보유 종목 모두 정상")
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
