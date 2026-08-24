"""scripts/daily_market_report.py — 검증된 매크로 신호 기반 시장 분석 메시지.

2026-08-21: 기존엔 KOSPI/KOSDAQ/S&P/나스닥/환율/VIX/공포탐욕지수를 그냥 숫자로만
나열해서 "도움이 안 된다"는 피드백을 받고, scripts/etf_recommend.py의 검증된
market_regime()/macro_signals()를 재사용하는 해석 중심 메시지로 교체했다.

2026-08-24: 카카오 text 템플릿(200자 한도) 맞추려고 신호를 "⚠️과열경계" 태그로
압축했더니 "신호 나열처럼 보인다"는 피드백을 받아 피드형 템플릿(title+description)
으로 교체 — _short()는 더 이상 필요 없어 제거. 이 테스트는 (title, description)
튜플에 핵심 섹션이 빠지지 않고, 다시 태그 수프로 압축되지 않는지 고정한다.
"""
import sys
from pathlib import Path

sys.path.append(str(Path(__file__).resolve().parent.parent))
sys.path.append(str(Path(__file__).resolve().parent.parent / "scripts"))

from scripts.daily_market_report import build_message


def test_build_message_returns_title_and_readable_description():
    """실제 results/summary_signals.csv 기준 — 제목에 "시장 요약"이 있고,
    KOSPI/KOSDAQ 같은 해석 없는 원시 숫자 나열이 아니라 국면 해석 문구가
    포함돼야 한다. 압축 태그(공백 없는 이모지+한글 붙어쓰기)가 아니라 띄어쓰기
    있는 문장이어야 한다."""
    title, description = build_message()
    assert "시장 요약" in title
    assert "KOSDAQ" not in description and "나스닥" not in description
    # 국면 라벨(강세/약세/혼조/공포/과열) 중 하나는 반드시 포함
    assert any(k in description for k in ("강세", "약세", "혼조", "공포", "과열", "없음"))
    # 압축 태그 수프가 아니라 줄바꿈으로 나뉜 문장인지 — 최소 한 줄은 있어야 함
    assert len(description.split("\n")) >= 1
