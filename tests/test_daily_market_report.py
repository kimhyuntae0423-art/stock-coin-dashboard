"""scripts/daily_market_report.py — 검증된 매크로 신호 기반 시장 분석 메시지.

2026-08-21: 기존엔 KOSPI/KOSDAQ/S&P/나스닥/환율/VIX/공포탐욕지수를 그냥 숫자로만
나열해서 "도움이 안 된다"는 피드백을 받고, scripts/etf_recommend.py의 검증된
market_regime()/macro_signals()를 재사용하는 해석 중심 메시지로 교체했다.
이 테스트는 메시지가 카카오 200자 한도 안에 들어오고, 핵심 섹션이 빠지지
않는지 고정한다.
"""
import sys
from pathlib import Path

sys.path.append(str(Path(__file__).resolve().parent.parent))
sys.path.append(str(Path(__file__).resolve().parent.parent / "scripts"))

from scripts.daily_market_report import _short, build_message


def test_short_strips_parenthetical_explanation_and_spaces():
    assert _short("⚠️ 과열 경계 (향후 수익 저조 경향)") == "⚠️과열경계"
    assert _short("➡️ 중립") == "➡️중립"
    assert _short("약달러 (향후 수익 저조 경향)") == "약달러"


def test_build_message_fits_kakao_limit_and_has_no_raw_index_dump():
    """실제 results/summary_signals.csv 기준 — 200자 한도 안, KOSPI/KOSDAQ 같은
    해석 없는 원시 숫자 나열이 아니라 국면 해석 문구가 포함돼야 한다."""
    msg = build_message()
    assert len(msg) <= 195
    assert "시장 분석" in msg
    assert "KOSDAQ" not in msg and "나스닥" not in msg
    # 국면 라벨(강세/약세/혼조/공포/과열) 중 하나는 반드시 포함
    assert any(k in msg for k in ("강세", "약세", "혼조", "공포", "과열", "데이터 없음"))
