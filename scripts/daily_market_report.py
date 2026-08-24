"""
매일 09:30 KST 시장 분석 카카오톡 발송.

내용: 검증된 매크로 신호(scripts/etf_recommend.py::market_regime()/macro_signals())
기반 시장 국면 해석. 예전엔 KOSPI/KOSDAQ/S&P/나스닥/환율/VIX/공포탐욕지수를 그냥
숫자로만 나열해서 "도움이 안 된다"는 피드백을 받음(2026-08-21) — CLAUDE.md
"자산별 검증된 신호" 표에 등재된 VIX 국면(IC=+0.14)·수익률곡선(IC=+0.25)·
달러강도(IC=+0.16)·구리금비율(IC=-0.37) 해석으로 교체. CNN 공포탐욕지수는
ARCHITECTURE.md에 이미 있는 전례(2026-07-20, stocks_page VIX 기반으로 통일)와
일관되게 제거.

2026-08-24: 카카오 text 템플릿(200자 한도)에 맞추려고 _short()로 신호를
"⚠️과열경계" 식 태그로 압축했더니 "신호 나열처럼 보인다"는 피드백을 받음 —
피드형 템플릿(title+description, 4줄 안팎 여유)으로 바꾸고 태그 압축 없이
실제 문장으로 풀어씀. 매크로 신호는 중립이 아닌 것만(우선순위: 구리금비율
IC=-0.37 > 수익률곡선 IC=+0.25 > 달러강도 IC=+0.16 — 절대값 큰 순) 최대
1개만 골라 한 줄로 보여줌(전부 나열하면 다시 태그 수프가 됨).

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


# 매크로 신호 우선순위 — 절대 IC 큰 순(백테스트 근거는 CLAUDE.md "자산별 검증된
# 신호" 표). 전부 보여주면 다시 태그 수프가 되니 중립이 아닌 것 중 1개만 고름.
_MACRO_PRIORITY = ["경기신호", "곡선신호", "달러강도"]
_MACRO_LABEL = {"경기신호": "구리/금 비율", "곡선신호": "채권 수익률곡선", "달러강도": "달러 강도"}


def _pick_macro_sentence(macro: dict) -> str | None:
    """중립이 아닌 매크로 신호 중 우선순위가 가장 높은 것 하나를 문장으로."""
    for key in _MACRO_PRIORITY:
        val = macro.get(key)
        if val is None or "중립" in val:
            continue
        return f"{_MACRO_LABEL[key]}: {val}"
    return None


def build_message() -> tuple[str, str]:
    """(title, description) 반환 — kakao_notify.send_feed_to_self()용 피드 템플릿."""
    today = datetime.now(ZoneInfo("Asia/Seoul")).strftime("%m/%d")
    title = f"📊 오늘의 시장 요약 {today}"

    if not SUMMARY.exists():
        return title, "summary_signals.csv 없음 — run_analysis.py 먼저 실행 필요"

    df = pd.read_csv(SUMMARY)
    regime = market_regime(df)
    macro = macro_signals(df)

    lines = [f"{regime['label']} — {regime['desc']}"]

    vix = regime.get("vix")
    if vix is not None:
        lines.append(f"변동성 지수(VIX) {vix:.1f} — {regime['vix_signal']}")

    macro_sentence = _pick_macro_sentence(macro)
    if macro_sentence:
        lines.append(macro_sentence)

    return title, "\n".join(lines)


def main():
    title, description = build_message()
    print("=== 발송할 메시지 ===")
    print(f"[제목] {title}")
    print(description)
    print("====================")

    has_env = os.environ.get("KAKAO_REST_API_KEY") and os.environ.get("KAKAO_REFRESH_TOKEN")
    has_local = (ROOT / "kakao_tokens.json").exists()

    if not (has_env or has_local):
        print("ℹ 토큰 없음 — 실제 발송 스킵 (드라이런)")
        return 0

    try:
        from kakao_notify import send_feed_to_self
        send_feed_to_self(title, description)
        print("✓ 카카오톡 발송 완료")
        return 0
    except Exception as e:
        print(f"✗ 카카오 발송 실패: {e}")
        return 1


if __name__ == "__main__":
    sys.exit(main())
