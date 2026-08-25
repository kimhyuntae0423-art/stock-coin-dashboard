"""
매일 09:30 KST 시장 분석 카카오톡 발송.

내용: 검증된 매크로 신호(scripts/etf_recommend.py::market_regime()/macro_signals())
기반 시장 국면 해석. CLAUDE.md "자산별 검증된 신호" 표에 등재된 VIX 국면
(IC=+0.14)·수익률곡선(IC=+0.25)·달러강도(IC=+0.16)·구리금비율(IC=-0.37)만 씀.

2026-08-24 여러 차례 사용자 피드백을 거쳐 지금 형태로 정착했다 (자세한 변경
이력은 git log 참고, 여기는 "왜 이렇게 생겼는지"만 남김):
- market_regime()의 5단계 국면(bull/bear/fear/complacent/mixed) 라벨 하나로만
  뭉뚱그리면 "너무 뭉뚱그렸다"는 피드백 → breadth·SPY 1개월 모멘텀·VIX·매크로
  3개 신호(중립 아닌 것 전부, 1개로 자르지 않음)·코인 온체인 국면을 실제
  수치 그대로 3단락 에세이에 풀어씀(_outlook_paragraph1/2/3, 사용자가 문안을
  직접 확인·승인).
- "text 템플릿은 200자 한도"라는 가정으로 한때 태그 압축판/피드 템플릿을
  거쳤는데, (1) feed 템플릿은 실제로 카카오톡 채팅창 안에서 4줄로 강제
  절단되고 펼쳐볼 방법이 없었고(스크린샷으로 확인), (2) 같은 계정으로 몇
  달째 문제없이 쓰는 morning-briefing 레포가 450자 text 메시지를 안 자르고
  보내는 걸 확인 — 200자 한도 자체가 잘못된 가정이었음. text 템플릿 +
  상세 에세이 그대로가 최종 형태.
- 보유종목 매수/매도 신호(scripts/check_alerts.py)는 별도 메시지라 안 섞음.

2026-08-25: "어제도 오늘도 같은 내용이라 인사이트가 없다"는 피드백 — 매크로
신호는 원래 하루이틀 만에 잘 안 바뀌는 값들이라, 매일 오늘 스냅샷만 그대로
문장으로 바꾸면 "인사이트"가 아니라 "같은 설명 반복"이 됨. 그래서
results/market_report_state.json에 전날 국면을 기록해뒀다가 ①국면이
바뀌었는지/며칠째 이어지는지(_regime_insight_sentence) ②VIX가 최근 1년
대비 상대적으로 어느 수준인지(_vix_percentile_clause, check_alerts.py의
BTC 사이클 변화 추적과 같은 패턴)를 덧붙인다. **이 상태 파일이 실제로
저장되려면 daily-market-report.yml에 git commit/push 스텝이 있어야
하는데, 원래 없었음(2026-08-25 발견·수정)** — 없으면 매번 러너 종료와
함께 상태가 사라져서 "지속일수 추적"이 영원히 작동 안 함.

2026-08-25 (같은 날 두 번째 요청): 위 인사이트는 전부 "우리 데이터 안에서"
만든 해석(A)이라 한계가 있다 — 사용자가 "실제 뉴스 근거로 설명해주는 것도
자동으로 되냐"고 물어서, Claude API의 web_search 서버 도구로 오늘자 실제
뉴스를 검색·요약하는 4번째 단락(B)을 추가했다(_news_grounded_insight).
scripts/update_reports.py가 이미 ANTHROPIC_API_KEY로 Claude를 호출하는
전례가 있어 같은 시크릿을 재사용. ANTHROPIC_API_KEY 없거나 API 호출
실패하면 그냥 그 단락만 생략(A 3단락은 그대로 발송) — 뉴스 인사이트는
"있으면 좋은 보너스"지 실패해도 카톡 자체가 막히면 안 됨.

results/summary_signals.csv(run_analysis.py가 매일 07:00 KST에 먼저 갱신)를
그대로 재사용 — 실시간 yfinance 호출 없음.
GitHub Actions의 daily-market-report.yml 에서 실행.
"""
import json
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
from onchain import classify_regime

SUMMARY = RESULTS_DIR / "summary_signals.csv"
CYCLE_METRICS = RESULTS_DIR / "cycle_metrics.csv"
VIX_SIGNALS = RESULTS_DIR / "^VIX_signals.csv"
# 2026-08-24: "어제도 오늘도 같은 내용"이라는 피드백 — 매크로 신호 자체가
# 하루이틀 만에 잘 안 바뀌는 값들이라, 매번 오늘 스냅샷만 그대로 문장으로
# 바꾸면 "인사이트"가 아니라 "같은 설명 반복"이 된다. 그래서 전날 상태를
# 기록해뒀다가 ①국면이 바뀌었는지/며칠째 이어지는지 ②매크로 신호가 바뀌었는지
# 비교해서 "무엇이 새로운지"를 알려주는 쪽으로 바꿨다(check_alerts.py가 BTC
# 사이클 변화를 추적하는 것과 같은 패턴, CYCLE_STATE 참고).
REPORT_STATE = RESULTS_DIR / "market_report_state.json"


# market_regime()의 5단계를 "강세/약세/…" 서랍 문장 하나로 뭉뚱그리지 않고,
# breadth·SPY 1개월 모멘텀·VIX·채권 대비 강도를 실제 숫자 그대로 문장에 녹여
# 넣는다 — 2026-08-24, "국면 5개로만 나누면 너무 뭉뚱그린 것 같다"는 피드백
# 반영. 사용자가 직접 문안을 확인·승인한 스타일(2단락: ①국면+지표 실측치,
# ②매크로 신호 상세 + 균형 잡힌 결론)을 그대로 코드화.
def _bond_clause(bond_winning: bool, positive_regime: bool) -> str:
    if positive_regime:
        return (
            "다만 채권 쪽으로도 자금이 몰리는 신호가 있어서, 안전자산 선호 심리가 완전히 가시진 않았습니다."
            if bond_winning else
            "채권보다 주식 쪽으로 돈이 더 몰리고 있다는 신호까지 겹쳐서 위험자산을 선호하는 분위기가 이어지고 있습니다."
        )
    return (
        "채권 쪽으로 자금이 몰리는 안전자산 선호 심리까지 겹쳐 있습니다."
        if bond_winning else
        "다만 채권보다는 아직 주식이 선호되는 편이라 패닉 수준까지는 아닙니다."
    )


def _vix_phrase(vix_signal: str) -> str:
    """문장 중간에 자연스럽게 넣을 VIX 수준 형용구(접두어 없음)."""
    if "공포 극단" in vix_signal:
        return "극단적으로 높고"
    if "변동성 상승" in vix_signal:
        return "다소 높아진 편이고"
    if "과열 경계" in vix_signal:
        return "낮은 편이고"
    return "안정적인 수준이고"


def _vix_percentile_clause(vix: float) -> str | None:
    """오늘 VIX가 최근 1년(252거래일) 대비 어느 정도 수준인지. 절대 수치
    (15.1)만으로는 감이 잘 안 와서 상대적 위치를 덧붙임 — "인사이트가
    필요하다"는 피드백 반영. 데이터 부족하면 None(문장 생략)."""
    if not VIX_SIGNALS.exists():
        return None
    try:
        closes = pd.to_numeric(pd.read_csv(VIX_SIGNALS)["Close"], errors="coerce").dropna().tail(252)
    except Exception:
        return None
    if len(closes) < 60:
        return None
    pct = float((closes < vix).mean() * 100)
    if pct <= 50:
        return f"최근 1년 중 하위 {pct:.0f}%에 해당하는 낮은 수준이에요"
    return f"최근 1년 중 상위 {100 - pct:.0f}%에 해당하는 높은 수준이에요"


_REGIME_KR = {"bull": "강세", "bear": "약세", "fear": "공포", "complacent": "과열(조용함)", "mixed": "혼조"}


def _load_report_state() -> dict:
    if not REPORT_STATE.exists():
        return {}
    try:
        with open(REPORT_STATE, "r", encoding="utf-8") as f:
            return json.load(f)
    except (json.JSONDecodeError, OSError):
        return {}


def _save_report_state(state: dict) -> None:
    REPORT_STATE.parent.mkdir(parents=True, exist_ok=True)
    with open(REPORT_STATE, "w", encoding="utf-8") as f:
        json.dump(state, f, ensure_ascii=False, indent=2)


def _regime_insight_sentence(regime_key: str, prev_state: dict, today_str: str) -> tuple[str | None, dict]:
    """전날 상태와 비교해 국면이 바뀌었는지/며칠째 이어지는지 문장 하나로.
    반환: (문장 또는 None, 저장할 새 상태 dict). 같은 날 두 번 실행되면(수동
    재실행 등) streak을 중복 증가시키지 않는다."""
    if prev_state.get("date") == today_str:
        streak = prev_state.get("streak", 1)
        prev_regime_key = prev_state.get("prev_regime_key")
    else:
        prev_regime_key = prev_state.get("regime_key")
        if prev_regime_key == regime_key:
            streak = prev_state.get("streak", 1) + 1
        else:
            streak = 1

    new_state = {
        "date": today_str, "regime_key": regime_key, "streak": streak,
        "prev_regime_key": prev_regime_key,
    }

    if prev_regime_key is None:
        return None, new_state
    if prev_regime_key != regime_key:
        return (
            f"어제까지의 {_REGIME_KR.get(prev_regime_key, prev_regime_key)} 국면에서 "
            f"오늘 {_REGIME_KR.get(regime_key, regime_key)}로 바뀌었어요.",
            new_state,
        )
    if streak >= 2:
        return f"이 흐름이 {streak}일째 이어지고 있어요.", new_state
    return None, new_state


def _outlook_paragraph1(regime: dict) -> str:
    """1단락: 국면을 한 문장으로 먼저 짚고, breadth·모멘텀·VIX·채권 대비 강도를
    실제 수치와 함께 풀어씀."""
    breadth = regime.get("breadth") or 0.0
    spy_1m = regime.get("spy_1m") or 0.0
    vix = regime.get("vix")
    vix_signal = regime.get("vix_signal", "")
    bond_winning = bool(regime.get("bond_winning"))
    key = regime.get("key")

    if key == "bull":
        return (
            f"오늘 미국 증시는 뚜렷한 강세 흐름을 타고 있어요. 추적 중인 종목의 {breadth:.0f}%가 상승 추세에 올라타 있고, "
            f"대표 지수는 최근 한 달 새 {spy_1m:+.1f}% 올랐습니다. 변동성 지표(VIX)도 {vix:.1f}로 낮은 편이라 시장이 크게 "
            f"불안해하는 상황은 아니고요, {_bond_clause(bond_winning, True)}"
        )
    if key == "bear":
        return (
            f"오늘 미국 증시는 약세 국면이에요. 추적 중인 종목의 {breadth:.0f}%만 상승 추세에 있고, 대표 지수도 최근 한 달 새 "
            f"{spy_1m:+.1f}%로 힘을 못 쓰고 있습니다. 변동성 지표(VIX)는 {vix:.1f}로 {_vix_phrase(vix_signal)}, "
            f"{_bond_clause(bond_winning, False)}"
        )
    if key == "fear":
        return (
            f"오늘은 시장이 공포에 가까운 상태예요. 변동성 지표(VIX)가 {vix:.1f}까지 치솟았고, 대표 지수도 최근 한 달 새 "
            f"{spy_1m:+.1f}%로 흔들리고 있습니다. 다만 역사적으로 이런 극단적인 공포 구간은 오히려 저가에 살 기회였던 경우가 "
            f"많았어요(검증된 신호)."
        )
    if key == "complacent":
        return (
            f"오늘 시장은 너무 조용합니다. 추적 중인 종목의 {breadth:.0f}%가 상승 추세이고 변동성 지표(VIX)는 {vix:.1f}까지 "
            f"낮아져서, 다들 안심하는 분위기예요. 다만 이렇게 과도하게 잠잠할 때가 오히려 조심할 시점이라는 신호이기도 합니다."
        )
    # mixed
    return (
        f"오늘 시장은 방향을 못 정하고 있어요. 상승 추세 종목이 {breadth:.0f}%로 뚜렷한 쪽이 없고, 대표 지수도 최근 한 달 새 "
        f"{spy_1m:+.1f}%로 큰 움직임이 없습니다. 변동성 지표(VIX)는 {vix:.1f}로 {_vix_phrase(vix_signal)}."
    )


_MACRO_SENTENCE: dict[tuple[str, str], tuple[str, str]] = {
    # (macro key, 부분 문자열 매치) -> (극성 warn/support, 문장)
    ("경기신호", "과열"): ("warn", "구리 가격이 금값 대비 유독 비싸지는 흐름이 나타나고 있는데, 이건 이 프로젝트가 검증한 신호 중 가장 신뢰도가 높은 지표라 지금의 상승세가 이미 과열 국면에 가까워졌을 가능성을 보여줍니다."),
    ("경기신호", "저점"): ("support", "구리 가격이 금값 대비 저평가되는 흐름이 나타나고 있는데, 이건 경기 회복 초기에 흔히 보이는 신호라 앞으로가 기대되는 구간입니다."),
    ("곡선신호", "안전자산선호"): ("warn", "채권 시장에서도 안전자산을 선호하는 분위기가 감지되고 있어서, 지금 흐름이 계속될지는 조금 더 지켜봐야 합니다."),
    ("곡선신호", "위험자산선호"): ("support", "채권 시장 흐름도 위험자산을 선호하는 쪽이라, 지금 분위기와 방향이 맞아떨어집니다."),
    ("달러강도", "강달러"): ("support", "달러도 강세를 보이고 있어서 이 흐름을 뒷받침하고 있습니다."),
    ("달러강도", "약달러"): ("warn", "달러는 약세인데, 이 역시 과거 패턴상 주식 수익률엔 그다지 좋은 신호가 아니었어요."),
}
_MACRO_PRIORITY = ["경기신호", "곡선신호", "달러강도"]


def _cross_signal_insight(regime_key: str, macro: dict, breadth: float) -> str | None:
    """2026-08-25: "신호값 자체 말고 왜 이런 신호가 떴는지, 애널리스트 아티클처럼
    알고 싶다"는 피드백 — 지표를 하나씩 나열만 하지 말고 서로 엮어서 "그래서
    지금 이런 조합이 왜 나타나는지"를 추론한다. 단, 이건 확인된 사실이 아니라
    지표 조합에 대한 해석(추측)이라는 걸 명시("~일 수 있어요" 톤 유지,
    CLAUDE.md 절대원칙 3 "데이터 ≠ 의견" · 절대원칙 4 "모르는 숫자는 만들지
    않는다" — 실제 오늘자 뉴스로 확인된 원인이 아니라 데이터 패턴 간 논리적
    개연성만 제시)."""
    def has(key: str, sub: str) -> bool:
        val = macro.get(key)
        return val is not None and sub in val

    if has("경기신호", "과열") and has("달러강도", "약달러"):
        return "구리 과열과 약달러가 동시에 나타난 걸 보면, 달러가 약해지면서 원자재 가격을 밀어올리는 흐름일 가능성이 있어요."
    if regime_key == "bull" and has("경기신호", "과열"):
        return "실물경기 지표(구리)가 금융시장보다 먼저 과열 신호를 보내는 건, 전형적으로 경기 확장 국면 후반부에 나타나는 패턴이에요."
    if regime_key in ("bull", "complacent") and has("곡선신호", "안전자산선호"):
        return "주가는 오르는데 채권 시장은 이미 안전자산을 선호하는 신호를 보내는 괴리가 있어요 — 두 시장 중 하나가 아직 반응을 덜 했을 수 있습니다."
    if regime_key == "fear" and has("경기신호", "저점"):
        return "시장 심리는 공포에 질려 있는데 실물경기 지표는 오히려 회복 초기 신호를 보내는, 흔치 않은 조합이에요."
    if regime_key == "complacent" and breadth is not None and breadth >= 70:
        return "변동성은 낮고 대부분 종목이 오르는 전형적인 낙관 국면인데, 역사적으로 이런 안정감이 오래가지 않았던 경우가 많았습니다."
    return None


def _outlook_paragraph2(macro: dict, regime_key: str, breadth: float | None = None) -> str:
    """2단락: 매크로 선행지표 3개를 중립 아닌 것만 전부(1개로 자르지 않음)
    풀어쓰고, 국면과 macro가 같은 방향인지 엇갈리는지로 균형 잡힌 결론을 냄.
    가능하면 신호 조합에 대한 해석(_cross_signal_insight)도 덧붙임."""
    parts: list[str] = []
    polarities: list[str] = []
    for key in _MACRO_PRIORITY:
        val = macro.get(key)
        if val is None or "중립" in val:
            continue
        for (mkey, sub), (polarity, sentence) in _MACRO_SENTENCE.items():
            if mkey == key and sub in val:
                parts.append(sentence)
                polarities.append(polarity)
                break

    if not parts:
        return "매크로 선행 지표들은 오늘 특별한 경고 신호 없이 중립적입니다."

    positive_regime = regime_key in ("bull", "complacent")
    negative_regime = regime_key in ("bear", "fear")
    has_warn = "warn" in polarities
    has_support = "support" in polarities

    if positive_regime and has_warn:
        closing = "그러니 지금 분위기를 그대로 믿고 따라가기보다는, 한 박자 쉬어가는 마음으로 지켜볼 시점에 가깝습니다."
    elif positive_regime:
        closing = "매크로 신호들도 대체로 지금 흐름을 뒷받침하고 있어 당분간은 이 분위기가 이어질 가능성이 있습니다."
    elif negative_regime and has_support:
        closing = "다만 매크로 신호 일부는 회복 조짐을 보이고 있어 마냥 비관적이지만은 않습니다."
    elif negative_regime:
        closing = "매크로 신호도 같은 방향을 가리키고 있어 당분간 조심스러운 흐름이 이어질 수 있습니다."
    else:
        closing = "매크로 신호까지 겹쳐 있어 당장은 방향을 예단하기보다 지켜보는 쪽이 안전합니다."

    insight = _cross_signal_insight(regime_key, macro, breadth)
    insight_clause = f" 굳이 해석을 붙이자면, {insight}" if insight else ""

    return "매크로 선행 지표를 조금 더 짚어보면, " + " ".join(parts) + " " + closing + insight_clause


# 코인(BTC) 국면별 도입 문장 — scripts/onchain.py::classify_regime()이 SSOT
# (0/1.5/2.5 경계). 대시보드 전체(rebalancing_page.py 등)와 같은 기준.
_COIN_REGIME_SENTENCE = {
    "deep_value": "비트코인은 지금 바닥권에 가까운 상태예요. 온체인 지표(MVRV — 지금 가격이 보유자들 평균 매수가 대비 얼마나 비싼지 보여주는 지표)가 {z:.2f}로, 역사적으로 저점 부근에서 나타나는 수준입니다.",
    "accumulation": "비트코인은 지금 매집 구간에 가까운 상태예요. 온체인 지표(MVRV)가 {z:.2f}로, 아직 크게 부풀려지지 않은 저평가 구간으로 볼 수 있습니다.",
    "bull": "비트코인은 지금 중립~과열 경계 구간이에요. 온체인 지표(MVRV)가 {z:.2f}로 예전보다 꽤 올라와 있어서, 과열 진입 전 단계로 봐야 합니다.",
    "top": "비트코인은 지금 과열 구간에 가까운 상태예요. 온체인 지표(MVRV)가 {z:.2f}로, 보유자들 평균 매수가 대비 가격이 많이 부풀려져 있습니다.",
}

_ALT_SEASON_CLAUSE = {
    "altcoin_season": "알트코인들이 비트코인보다 광범위하게 앞서고 있어서(알트시즌 지수 {score:.0f}), 지금은 알트코인이 더 주목받는 구간입니다.",
    "bitcoin_season": "알트코인들은 비트코인 대비 부진한 편이라(알트시즌 지수 {score:.0f}), 아직 비트코인 위주로 흐름이 이어지고 있습니다.",
    "transition": "알트코인과 비트코인 어느 한쪽으로 뚜렷하게 쏠리지 않은(알트시즌 지수 {score:.0f}) 애매한 구간이에요.",
}


def _outlook_paragraph3(cycle: dict) -> str | None:
    """3단락: 코인(BTC) 전망 — 2026-08-24, "코인은 언급이 없다"는 피드백으로
    추가. 주식 단락과 같은 스타일(국면 하나로 뭉뚱그리지 않고 실제 수치 포함).
    데이터 없으면 None 반환(문단 자체를 생략)."""
    z = cycle.get("mvrv_z")
    if z is None or pd.isna(z):
        return None
    z = float(z)
    regime = classify_regime(z)["regime"]
    sentence = _COIN_REGIME_SENTENCE.get(regime)
    if sentence is None:
        return None
    parts = [sentence.format(z=z)]

    btc_90d = cycle.get("btc_return_90d_pct")
    if btc_90d is not None and not pd.isna(btc_90d):
        btc_90d = float(btc_90d)
        verb = "부진했어요" if btc_90d < 0 else "올랐습니다"
        parts.append(f"최근 3개월 동안은 {btc_90d:+.1f}%로 {verb}.")

    alt_regime = cycle.get("alt_season_regime")
    alt_score = cycle.get("alt_season_score")
    if alt_regime in _ALT_SEASON_CLAUSE and alt_score is not None and not pd.isna(alt_score):
        parts.append(_ALT_SEASON_CLAUSE[alt_regime].format(score=float(alt_score)))

    return " ".join(parts)


# 2026-08-24: "text 템플릿은 200자 한도"라는 가정으로 여기 있던 압축 버전
# (_compact_regime_line 등, 국면 5개로 뭉뚱그리지 않으려던 상세 에세이를 다시
# 태그로 압축해버린 것)을 썼었는데, 같은 계정으로 몇 달째 문제없이 쓰고 있는
# morning-briefing 레포(briefing-cloud.py)가 450자짜리 text 메시지를 전혀
# 안 자르고 보내는 걸 확인 — 200자 한도 자체가 잘못된 가정이었음. kakao_notify.
# _text_template()의 인위적 200자 컷도 같이 제거했으므로, 이제 다시
# _outlook_paragraph1/2/3(사용자가 직접 승인한 상세 에세이)를 그대로 쓴다.


def _news_grounded_insight(regime: dict, macro: dict) -> str | None:
    """2026-08-25: _outlook_paragraph1/2/3(A)는 전부 우리 데이터 안에서 만든
    해석이라 "왜 이런 신호가 떴는지"는 못 짚는다. 여기서는 Claude API의
    web_search 서버 도구로 오늘자 실제 뉴스를 검색해 근거를 붙인다(B).
    ANTHROPIC_API_KEY 없거나 호출 실패하면 조용히 None — 이 단락은 "있으면
    좋은 보너스"라 실패해도 나머지 3단락 발송은 막지 않는다(update_reports.py와
    같은 폴백 원칙)."""
    api_key = os.environ.get("ANTHROPIC_API_KEY")
    if not api_key:
        return None

    regime_kr = _REGIME_KR.get(regime.get("key"), regime.get("key"))
    vix = regime.get("vix")
    macro_desc = ", ".join(f"{k}={v}" for k, v in macro.items() if v and "중립" not in str(v))
    today_str = datetime.now(ZoneInfo("Asia/Seoul")).strftime("%Y-%m-%d")

    prompt = f"""오늘({today_str}) 미국 증시는 "{regime_kr}" 국면이고, 변동성 지표(VIX)는 {vix}입니다.
매크로 신호: {macro_desc or "특이사항 없음"}.

오늘자 실제 뉴스를 검색해서, 이 흐름과 관련 있어 보이는 구체적인 뉴스나 이벤트가
있다면 2~3문장으로 쉬운 말로 설명해줘. 전문 용어 없이 투자 비전문가도 이해할 수
있게 써줘. 확정적 인과관계("이것 때문에 올랐다")로 단정하지 말고 "~영향으로
보인다" 정도의 톤을 유지하고, "사라/팔아라" 같은 매매 지시는 절대 하지 마.
검색해봐도 오늘 흐름을 설명할 만한 뚜렷한 뉴스가 없으면, 억지로 지어내지 말고
"오늘 특별히 부각된 뉴스는 없어 보인다"고 솔직히 말해줘."""

    try:
        import anthropic
        client = anthropic.Anthropic(api_key=api_key)
        response = client.messages.create(
            model="claude-sonnet-5",
            max_tokens=600,
            tools=[{"type": "web_search_20260209", "name": "web_search", "max_uses": 3}],
            messages=[{"role": "user", "content": prompt}],
        )
        text = "".join(b.text for b in response.content if b.type == "text").strip()
        return text or None
    except Exception as e:
        print(f"뉴스 인사이트 생성 실패: {e} — 이 단락만 생략")
        return None


def build_message() -> str:
    """카카오 text 템플릿(kakao_notify.send_to_self())용 메시지. 3단락 에세이:
    ①미국 증시 국면+실측 지표(+전날 대비 변화/지속일수, +VIX 1년 백분위),
    ②매크로 상세+균형 결론, ③코인(BTC) 온체인 국면+알트시즌 — 전부 실제
    수치 그대로, 태그로 압축하지 않음."""
    today_kst = datetime.now(ZoneInfo("Asia/Seoul"))
    today = today_kst.strftime("%m/%d")
    today_str = today_kst.strftime("%Y-%m-%d")
    title = f"📊 오늘의 시장 조각글 {today}"

    if not SUMMARY.exists():
        return f"{title}\nsummary_signals.csv 없음 — run_analysis.py 먼저 실행 필요"

    df = pd.read_csv(SUMMARY)
    regime = market_regime(df)
    macro = macro_signals(df)

    prev_state = _load_report_state()
    insight, new_state = _regime_insight_sentence(regime["key"], prev_state, today_str)
    _save_report_state(new_state)

    para1 = _outlook_paragraph1(regime)
    vix = regime.get("vix")
    if vix is not None:
        pct_clause = _vix_percentile_clause(float(vix))
        if pct_clause:
            para1 += f" 참고로 이 변동성 수준은 {pct_clause}."
    if insight:
        para1 = insight + " " + para1

    paragraphs = [para1]
    if regime.get("vix") is not None:
        paragraphs.append(_outlook_paragraph2(macro, regime["key"], regime.get("breadth")))

    if CYCLE_METRICS.exists():
        cycle = pd.read_csv(CYCLE_METRICS).iloc[0].to_dict()
        coin_paragraph = _outlook_paragraph3(cycle)
        if coin_paragraph:
            paragraphs.append(coin_paragraph)

    news_paragraph = _news_grounded_insight(regime, macro)
    if news_paragraph:
        paragraphs.append(f"📰 {news_paragraph}")

    return title + "\n\n" + "\n\n".join(paragraphs)


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
