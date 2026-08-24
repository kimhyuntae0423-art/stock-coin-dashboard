"""scripts/daily_market_report.py — 검증된 매크로 신호 기반 시장 분석 메시지.

2026-08-21: 기존엔 KOSPI/KOSDAQ/S&P/나스닥/환율/VIX/공포탐욕지수를 그냥 숫자로만
나열해서 "도움이 안 된다"는 피드백을 받고, scripts/etf_recommend.py의 검증된
market_regime()/macro_signals()를 재사용하는 해석 중심 메시지로 교체했다.

2026-08-24: 세 차례 더 다듬었다. 1차로 카카오 text 템플릿(200자 한도) 맞추려고
태그로 압축했다가 "신호 나열처럼 보인다"는 피드백에 피드형 템플릿(title+
description)으로 교체했고, 그래도 "국면 — 브레드스 67% · SPY 1M +3.7%" 식
사실 나열이라 "이해가 안 된다"는 피드백에 짧은 에세이(조각글) 한 단락으로
재작성했다. 3차로 "국면 5개로만 나누면 너무 뭉뚱그린 것 같다"는 피드백을
받아, breadth·SPY 모멘텀·VIX·매크로 3개 신호를 (1개만 고르지 않고) 실제
수치 그대로 2단락 에세이에 풀어쓰는 방식으로 다시 바꿨다(사용자가 문안을
직접 확인·승인). 이 테스트는 (title, description)이 태그 수프나 사실
나열로 되돌아가지 않으면서도, 실제 지표 수치가 문장 안에 살아있는지 고정한다.
"""
import sys
from pathlib import Path

sys.path.append(str(Path(__file__).resolve().parent.parent))
sys.path.append(str(Path(__file__).resolve().parent.parent / "scripts"))

from scripts.daily_market_report import build_message


def test_build_message_returns_title_and_essay_style_description():
    """실제 results/summary_signals.csv 기준 — 제목에 "조각글"이 있고, 본문은
    KOSPI/KOSDAQ 같은 해석 없는 원시 숫자 나열이 아니라 자연스러운 문장이어야
    한다. "브레드스"/"SPY 1M"/"IC=" 같은 압축 표기가 그대로 노출되면 안 된다."""
    title, description = build_message()
    assert "조각글" in title
    assert "KOSDAQ" not in description and "나스닥" not in description
    assert "브레드스" not in description and "SPY 1M" not in description and "IC=" not in description
    # 국면 도입 문장 중 하나는 반드시 포함(또는 데이터 없음 안내)
    assert any(k in description for k in ("강세", "약세", "공포", "조용합니다", "방향을 못", "없음"))
    # 표·나열이 아니라 문장으로 끝맺는 단락인지 — 최소 한 문장은 마침표로 끝남
    assert description.rstrip().endswith((".", "요", "다"))


def test_build_message_keeps_real_numbers_not_bucketed_labels_only():
    """2026-08-24 (3차): "국면 5개로만 나누면 너무 뭉뚱그린 것" 피드백 반영
    회귀 테스트 — breadth(%)·VIX 실제 수치가 살아있고, 최소 2단락(빈 줄로
    구분)으로 국면 설명과 매크로 상세가 분리돼 있어야 한다."""
    title, description = build_message()
    assert "%" in description  # breadth 등 실제 퍼센트 수치가 남아있어야 함
    assert "\n\n" in description  # 단락 구분(국면 단락 vs 매크로/맞춤 단락)


def test_build_message_includes_coin_paragraph():
    """2026-08-24: "코인은 아예 언급이 없다"는 피드백으로 3단락(BTC 온체인
    국면) 추가 — results/cycle_metrics.csv가 있으면 "비트코인"/"온체인" 언급이
    실제 문장 안에 있어야 한다(코인은 없다는 안내가 아니라)."""
    title, description = build_message()
    assert "비트코인" in description and "온체인" in description
