"""scripts/daily_market_report.py — 검증된 매크로 신호 기반 시장 분석 메시지.

2026-08-21: 기존엔 KOSPI/KOSDAQ/S&P/나스닥/환율/VIX/공포탐욕지수를 그냥 숫자로만
나열해서 "도움이 안 된다"는 피드백을 받고, scripts/etf_recommend.py의 검증된
market_regime()/macro_signals()를 재사용하는 해석 중심 메시지로 교체했다.

2026-08-24: 하루 동안 여러 차례 오갔다 — text(200자로 추정) → feed(title+
description, 문장형 에세이) → text(200자로 재압축) → 다시 text(제한 없음, 상세
에세이). "text 템플릿은 200자 한도"라는 가정 자체가 틀렸다는 게 최종적으로
드러났다: (1) feed 템플릿은 실제로 카카오톡 채팅창 안에서 4줄로 강제 절단되고
펼쳐볼 방법이 없었음(스크린샷으로 확인), (2) 같은 계정으로 몇 달째 문제없이
쓰는 morning-briefing 레포(briefing-cloud.py)가 450자짜리 text 메시지를 전혀
안 자르고 보내는 걸 확인. 그래서 kakao_notify._text_template()의 인위적
200자 컷도 제거하고, breadth·SPY 모멘텀·VIX·매크로 3개 신호·코인 온체인
국면을 실제 수치 그대로 3단락 에세이(_outlook_paragraph1/2/3, 사용자가 직접
확인·승인)로 build_message()가 그대로 반환하도록 최종 정착했다.
이 테스트는 KOSPI/KOSDAQ 원시 나열이나 브레드스/SPY 1M/IC= 같은 압축
코드명으로 되돌아가지 않으면서, 실제 국면·코인 언급이 살아있는지 고정한다.
"""
import sys
from pathlib import Path

sys.path.append(str(Path(__file__).resolve().parent.parent))
sys.path.append(str(Path(__file__).resolve().parent.parent / "scripts"))

from scripts.daily_market_report import build_message


def test_build_message_has_no_raw_index_dump_or_compressed_jargon():
    """KOSPI/KOSDAQ 같은 해석 없는 원시 숫자 나열이나, "브레드스"/"SPY 1M"/
    "IC=" 같은 내부 코드명이 그대로 노출되면 안 된다."""
    msg = build_message()
    assert "KOSDAQ" not in msg and "나스닥" not in msg
    assert "브레드스" not in msg and "SPY 1M" not in msg and "IC=" not in msg


def test_build_message_includes_regime_and_coin_mentions():
    """국면 라벨(강세/약세/공포/과열/혼조) 중 하나와, 코인(비트코인) 언급이
    둘 다 포함돼야 한다 — 2026-08-24 "코인은 아예 언급이 없다"는 피드백 반영."""
    msg = build_message()
    assert any(k in msg for k in ("강세", "약세", "공포", "과열", "혼조", "없음"))
    assert "비트코인" in msg


def test_build_message_is_paragraph_essay_not_truncated():
    """2단락 이상(제목 포함 빈 줄로 구분)의 실제 문장 에세이여야 하고, 문장이
    마침표 없이 도중에 잘려있으면 안 된다(과거 200자 컷의 흔적 "…" 금지)."""
    msg = build_message()
    assert msg.count("\n\n") >= 2
    assert not msg.rstrip().endswith("…")


def test_news_grounded_insight_skips_without_oauth_token(monkeypatch):
    """2026-08-25: 뉴스 근거 인사이트(B)는 CLAUDE_CODE_OAUTH_TOKEN(claude
    setup-token으로 발급하는 구독 기반 토큰) 없으면 claude CLI를 호출하지도
    않고 조용히 None을 반환해야 한다 — 실패해도 나머지 3단락 발송을 막으면 안 됨."""
    from scripts.daily_market_report import _news_grounded_insight

    monkeypatch.delenv("CLAUDE_CODE_OAUTH_TOKEN", raising=False)
    result = _news_grounded_insight({"key": "bull", "vix": 15.0}, {})
    assert result is None


def test_news_grounded_insight_falls_back_on_subprocess_failure(monkeypatch):
    """claude CLI 서브프로세스 호출이 실패해도(타임아웃, CLI 미설치 등)
    예외가 전파되지 않고 None을 반환해야 한다."""
    import subprocess
    from scripts.daily_market_report import _news_grounded_insight

    monkeypatch.setenv("CLAUDE_CODE_OAUTH_TOKEN", "dummy-token")

    def _boom(*args, **kwargs):
        raise FileNotFoundError("claude: command not found")

    monkeypatch.setattr(subprocess, "run", _boom)
    result = _news_grounded_insight({"key": "bull", "vix": 15.0}, {})
    assert result is None


def test_build_message_works_without_claude_oauth_token(monkeypatch):
    """OAuth 토큰이 없는 일반적인 로컬/테스트 환경에서도 build_message()는
    실제 서브프로세스 호출 없이 정상적으로 3단락 에세이를 반환해야 한다.
    2026-08-26: 뉴스 단락은 build_news_message()로 완전히 분리됐으므로
    build_message()엔 애초에 📰가 절대 안 나온다(토큰 유무 무관)."""
    monkeypatch.delenv("CLAUDE_CODE_OAUTH_TOKEN", raising=False)
    msg = build_message()
    assert "📰" not in msg


def test_build_news_message_none_without_token(monkeypatch):
    """2026-08-26: build_news_message()는 CLAUDE_CODE_OAUTH_TOKEN 없으면
    서브프로세스를 호출하지도 않고 None을 반환해야 한다."""
    from scripts.daily_market_report import build_news_message

    monkeypatch.delenv("CLAUDE_CODE_OAUTH_TOKEN", raising=False)
    assert build_news_message() is None


def test_news_grounded_insight_strips_trailing_sources_section(monkeypatch):
    """2026-08-25(실사고): 뉴스 인사이트+출처 링크를 한 메시지에 합쳐 보냈다가
    카카오의 실제(비공식) 길이 제한에 걸려 후반부가 통째로 잘려나간 사고가
    있었음(사용자가 문장 중간 "넘어서느"에서 잘렸다고 지적, 역산 결과 약
    997자 지점 — kakao_notify.py의 text[:5000]으로 올려도 그대로 잘렸으므로
    카카오 서버 자체의 실제 제한임을 확인). 뉴스 단락을 별도 메시지로
    분리했어도(build_news_message) 그 메시지 자체에 출처 목록이 다시 붙으면
    똑같이 잘릴 수 있으므로, claude CLI가 프롬프트 지시를 무시하고 출처를
    붙여도 코드에서 방어적으로 잘라내야 한다."""
    import subprocess
    from scripts.daily_market_report import _news_grounded_insight

    monkeypatch.setenv("CLAUDE_CODE_OAUTH_TOKEN", "dummy-token")

    class _FakeResult:
        stdout = "오늘은 이런 흐름이었어요.\n\nSources:\n- [기사](https://example.com/a)\n- [기사2](https://example.com/b)"

    monkeypatch.setattr(subprocess, "run", lambda *a, **k: _FakeResult())
    result = _news_grounded_insight({"key": "bull", "vix": 15.0}, {})
    assert result == "오늘은 이런 흐름이었어요."
    assert "Sources" not in result and "example.com" not in result


def test_regime_insight_detects_change_and_streak():
    """2026-08-25: "어제도 오늘도 같은 내용"이라는 피드백으로 국면 변화/지속일수
    추적을 추가했다 — 국면이 이어지면 "N일째", 바뀌면 "~에서 ~로 바뀌었다"
    문장이 나와야 하고, 같은 날 두 번 실행해도 streak이 중복 증가하면 안 된다."""
    from scripts.daily_market_report import _regime_insight_sentence

    # 첫 실행(과거 상태 없음) — 아직 비교 대상이 없으니 문장 없음
    sentence, state1 = _regime_insight_sentence("bull", {}, "2026-08-24")
    assert sentence is None
    assert state1["streak"] == 1

    # 다음날 같은 국면 지속 — "N일째" 문장
    sentence, state2 = _regime_insight_sentence("bull", state1, "2026-08-25")
    assert sentence is not None and "2일째" in sentence
    assert state2["streak"] == 2

    # 그 다음날 국면 전환 — "~에서 ~로 바뀌었다" 문장
    sentence, state3 = _regime_insight_sentence("bear", state2, "2026-08-26")
    assert sentence is not None and "강세" in sentence and "약세" in sentence
    assert state3["streak"] == 1

    # 같은 날 재실행 — streak 중복 증가 없이 같은 결과 유지
    sentence_again, state3_again = _regime_insight_sentence("bear", state3, "2026-08-26")
    assert sentence_again == sentence
    assert state3_again["streak"] == 1
