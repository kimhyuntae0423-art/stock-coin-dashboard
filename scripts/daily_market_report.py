"""
매일 09:30 KST 시장 요약 카카오톡 발송.

내용: 국내 지수, 미국 지수, 환율, 미국채 10y, VIX, 공포탐욕지수.
GitHub Actions의 daily-market-report.yml 에서 실행.
"""
import os
import sys
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

# Windows cp949 이모지 출력 에러 방지
if sys.platform == "win32" and hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

import yfinance as yf

_SCRIPTS_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(_SCRIPTS_DIR))

from fear_greed import fetch_cnn_fear_greed


# yfinance 티커
TICKERS = {
    "KOSPI": "^KS11",
    "KOSDAQ": "^KQ11",
    "S&P": "^GSPC",
    "나스닥": "^IXIC",
    "USD/KRW": "KRW=X",
    "US10Y": "^TNX",
    "VIX": "^VIX",
}


def fetch_quote(symbol: str) -> dict:
    """yfinance로 최근 종가와 전일 대비 변동률 조회."""
    try:
        t = yf.Ticker(symbol)
        hist = t.history(period="10d", interval="1d", auto_adjust=False)
        hist = hist.dropna(subset=["Close"])
        if len(hist) < 2:
            return {"error": "no data"}
        last = float(hist["Close"].iloc[-1])
        prev = float(hist["Close"].iloc[-2])
        change_pct = (last / prev - 1) * 100
        return {"close": last, "change_pct": change_pct}
    except Exception as e:
        return {"error": str(e)}


def _fmt_index(name: str, q: dict, decimals: int = 0) -> str:
    if "error" in q:
        return f"{name} -"
    c = q["close"]
    p = q["change_pct"]
    sign = "+" if p >= 0 else ""
    if decimals == 0:
        return f"{name} {c:,.0f} ({sign}{p:.1f}%)"
    return f"{name} {c:,.{decimals}f} ({sign}{p:.1f}%)"


def build_message() -> str:
    quotes = {name: fetch_quote(sym) for name, sym in TICKERS.items()}
    fng = fetch_cnn_fear_greed()

    today = datetime.now(ZoneInfo("Asia/Seoul")).strftime("%m/%d")

    lines = [f"📊 시장 요약 {today}"]
    lines.append("─ 국내")
    lines.append(_fmt_index("KOSPI", quotes["KOSPI"]))
    lines.append(_fmt_index("KOSDAQ", quotes["KOSDAQ"]))
    lines.append("─ 미국(전일)")
    lines.append(_fmt_index("S&P", quotes["S&P"]))
    lines.append(_fmt_index("나스닥", quotes["나스닥"]))
    lines.append("─ 매크로")

    krw = quotes["USD/KRW"]
    if "error" not in krw:
        lines.append(f"USD/KRW {krw['close']:,.1f}")

    us10 = quotes["US10Y"]
    if "error" not in us10:
        lines.append(f"US10Y {us10['close']:.2f}%")

    vix = quotes["VIX"]
    if "error" not in vix:
        lines.append(f"VIX {vix['close']:.1f}")

    if "error" not in fng:
        lines.append(f"F&G {fng['score']:.0f} ({fng['label']})")

    msg = "\n".join(lines)
    # 카카오 텍스트 메시지 한도 200자
    if len(msg) > 195:
        msg = msg[:190] + "…"
    return msg


def main():
    msg = build_message()
    print("=== 발송할 메시지 ===")
    print(msg)
    print(f"(길이: {len(msg)}자)")
    print("====================")

    has_env = os.environ.get("KAKAO_REST_API_KEY") and os.environ.get("KAKAO_REFRESH_TOKEN")
    has_local = (_SCRIPTS_DIR.parent / "kakao_tokens.json").exists()

    if not (has_env or has_local):
        print("ℹ 토큰 없음 — 실제 발송 스킵 (드라이런)")
        return 0

    try:
        from kakao_notify import send_to_self
        send_to_self(msg)
        print("✓ 카카오톡 발송 완료")
        return 0
    except Exception as e:
        print(f"✗ 카카오 발송 실패: {e}")
        return 1


if __name__ == "__main__":
    sys.exit(main())
