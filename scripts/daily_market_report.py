"""
매일 09:30 KST 시장 분석 카카오톡 발송.

내용: 검증된 매크로 신호(scripts/etf_recommend.py::market_regime()/macro_signals())
기반 시장 국면 해석. 예전엔 KOSPI/KOSDAQ/S&P/나스닥/환율/VIX/공포탐욕지수를 그냥
숫자로만 나열해서 "도움이 안 된다"는 피드백을 받음(2026-08-21) — CLAUDE.md
"자산별 검증된 신호" 표에 등재된 VIX 국면(IC=+0.14)·수익률곡선(IC=+0.25)·
달러강도(IC=+0.16)·구리금비율(IC=-0.37) 해석으로 교체. CNN 공포탐욕지수는
ARCHITECTURE.md에 이미 있는 전례(2026-07-20, stocks_page VIX 기반으로 통일)와
일관되게 제거.

results/summary_signals.csv(run_analysis.py가 매일 07:00 KST에 먼저 갱신)를
그대로 재사용 — 실시간 yfinance 호출 없음.
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

import pandas as pd

_SCRIPTS_DIR = Path(__file__).resolve().parent
ROOT = _SCRIPTS_DIR.parent
sys.path.insert(0, str(_SCRIPTS_DIR))
sys.path.insert(0, str(ROOT))

from config import RESULTS_DIR
from etf_recommend import market_regime, macro_signals

SUMMARY = RESULTS_DIR / "summary_signals.csv"


def _short(label: str) -> str:
    """macro_signals()의 긴 신호 문구에서 괄호 설명 제거 + 공백 압축 (200자 한도 대응).
    예: '⚠️ 과열 경계 (향후 수익 저조 경향)' → '⚠️과열경계'"""
    return label.split(" (")[0].replace(" ", "")


def build_message() -> str:
    if not SUMMARY.exists():
        return "📊 시장 분석 — summary_signals.csv 없음 (run_analysis.py 먼저 실행 필요)"
    df = pd.read_csv(SUMMARY)
    regime = market_regime(df)
    macro = macro_signals(df)

    today = datetime.now(ZoneInfo("Asia/Seoul")).strftime("%m/%d")
    lines = [f"📊 시장 분석 {today}", f"{regime['label']} — {regime['desc']}"]

    vix = regime.get("vix")
    if vix is not None:
        lines.append(f"VIX {vix:.1f} {regime['vix_signal']}")

    macro_parts = []
    if "경기신호" in macro:
        macro_parts.append(f"구리금 {_short(macro['경기신호'])}")
    if "곡선신호" in macro:
        macro_parts.append(f"곡선 {_short(macro['곡선신호'])}")
    if "달러강도" in macro:
        macro_parts.append(f"달러 {_short(macro['달러강도'])}")
    if macro_parts:
        lines.append("🧭 " + " · ".join(macro_parts))

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
    has_local = (ROOT / "kakao_tokens.json").exists()

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
