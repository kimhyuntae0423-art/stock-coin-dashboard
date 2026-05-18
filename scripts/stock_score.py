"""
주식 종합 평가 — 학술적으로 검증된 4개 팩터를 결합 (QVM + Technical).

근거:
- 가치(Value) · 품질(Quality) · 모멘텀(Momentum)은 30년 이상 학술 연구에서 일관되게
  초과수익을 보인 핵심 팩터들 (Fama-French, AQR, MSCI factor research)
- Piotroski F-Score (9점 척도) 상위 종목들은 시장을 연 13.4% 초과한 백테스트 (1976~1996)
- Magic Formula (Greenblatt): 이익수익률 + 자본수익률 결합으로 연 30%+ 보고
- 12개월 모멘텀(Jegadeesh-Titman 1993)은 2024년에도 최고 성과 팩터

본 모듈은 각 팩터를 -2(나쁨) ~ +2(좋음)로 점수화하고, 평균을 종합 점수로 사용.
"""
import pandas as pd


# ---------- 1. Value Score ----------
def score_value(per, pbr) -> int:
    """PER + PBR을 결합한 가치 점수. 낮을수록(저평가) 좋음."""
    per_s = pbr_s = None

    if per is not None and not pd.isna(per) and per > 0:
        if per < 10: per_s = 2
        elif per < 15: per_s = 1
        elif per < 25: per_s = 0
        elif per < 40: per_s = -1
        else: per_s = -2

    if pbr is not None and not pd.isna(pbr) and pbr > 0:
        if pbr < 1: pbr_s = 2
        elif pbr < 2: pbr_s = 1
        elif pbr < 4: pbr_s = 0
        elif pbr < 6: pbr_s = -1
        else: pbr_s = -2

    valid = [s for s in (per_s, pbr_s) if s is not None]
    if not valid: return None
    return round(sum(valid) / len(valid))


# ---------- 2. Quality Score ----------
def score_quality(roe_pct, profit_margin_pct) -> int:
    """ROE + 영업이익률 = 품질 점수. 높을수록 좋음."""
    roe_s = pm_s = None

    if roe_pct is not None and not pd.isna(roe_pct):
        if roe_pct >= 25: roe_s = 2
        elif roe_pct >= 15: roe_s = 1
        elif roe_pct >= 8: roe_s = 0
        elif roe_pct >= 0: roe_s = -1
        else: roe_s = -2

    if profit_margin_pct is not None and not pd.isna(profit_margin_pct):
        if profit_margin_pct >= 25: pm_s = 2
        elif profit_margin_pct >= 15: pm_s = 1
        elif profit_margin_pct >= 5: pm_s = 0
        elif profit_margin_pct >= 0: pm_s = -1
        else: pm_s = -2

    valid = [s for s in (roe_s, pm_s) if s is not None]
    if not valid: return None
    return round(sum(valid) / len(valid))


# ---------- 3. Momentum Score ----------
def score_momentum(return_12m_pct, state) -> int:
    """12개월 수익률 + 추세 상태 = 모멘텀 점수."""
    ret_s = trend_s = 0

    if return_12m_pct is not None and not pd.isna(return_12m_pct):
        if return_12m_pct >= 40: ret_s = 2
        elif return_12m_pct >= 15: ret_s = 1
        elif return_12m_pct >= 0: ret_s = 0
        elif return_12m_pct >= -20: ret_s = -1
        else: ret_s = -2

    if state == "bull":
        trend_s = 1
    elif state == "bear":
        trend_s = -1

    # 평균
    return round((ret_s + trend_s) / 2)


# ---------- 4. Technical Score (RSI 기반) ----------
def score_technical(rsi) -> int:
    """RSI 기반 진입 타이밍 점수.
    - 과매수: 매수 부담
    - 과매도: 반등 가능성"""
    if rsi is None or pd.isna(rsi):
        return 0
    if rsi <= 30: return 2     # 과매도 — 매수 기회
    if rsi <= 45: return 1
    if rsi <= 60: return 0
    if rsi <= 70: return -1
    return -2                  # 과매수


# ---------- 5. Growth Score (성장성) ----------
def score_growth(rev_growth_pct, eps_growth_pct) -> int:
    """매출/EPS YoY 성장률 평균.
    근거: Growth는 QVM의 G — 매출·이익이 빠르게 늘면 PER이 높아도 정당화될 수 있음."""
    rev_s = eps_s = None

    if rev_growth_pct is not None and not pd.isna(rev_growth_pct):
        if rev_growth_pct >= 25: rev_s = 2
        elif rev_growth_pct >= 10: rev_s = 1
        elif rev_growth_pct >= 0: rev_s = 0
        elif rev_growth_pct >= -10: rev_s = -1
        else: rev_s = -2

    if eps_growth_pct is not None and not pd.isna(eps_growth_pct):
        if eps_growth_pct >= 30: eps_s = 2
        elif eps_growth_pct >= 10: eps_s = 1
        elif eps_growth_pct >= 0: eps_s = 0
        elif eps_growth_pct >= -15: eps_s = -1
        else: eps_s = -2

    valid = [s for s in (rev_s, eps_s) if s is not None]
    if not valid: return None
    return round(sum(valid) / len(valid))


# ---------- 종합 점수 + 추천 ----------
def composite_stock_score(value, quality, momentum, technical, growth=None) -> dict:
    """5개 팩터(QVGMT) 평균. None인 팩터는 제외."""
    scores = {
        "가치": value, "품질": quality, "성장": growth,
        "모멘텀": momentum, "기술적": technical,
    }
    valid = {k: v for k, v in scores.items() if v is not None}
    if not valid:
        return {"avg": 0, "label": "데이터 없음", "scores": scores}
    avg = sum(valid.values()) / len(valid)

    if avg >= 1.5:
        label = "🟢🟢 강한 매수 (모든 팩터 우호)"
    elif avg >= 0.5:
        label = "🟢 매수 우호"
    elif avg > -0.5:
        label = "🔵 중립"
    elif avg > -1.5:
        label = "🟠 매도 우호"
    else:
        label = "🔴🔴 매수 자제"

    return {"avg": round(avg, 2), "label": label, "scores": scores}


def rank_stocks(stocks_df: pd.DataFrame) -> pd.DataFrame:
    """
    stocks_df: ticker, per, pbr, roe_pct, profit_margin_pct,
               revenue_growth_yoy_pct, earnings_growth_yoy_pct,
               return_12m_pct, state, rsi14 컬럼 필요.
    반환: 추천 점수 컬럼 + 정렬된 DataFrame
    """
    rows = []
    for _, r in stocks_df.iterrows():
        v = score_value(r.get("per"), r.get("pbr"))
        q = score_quality(r.get("roe_pct"), r.get("profit_margin_pct"))
        g = score_growth(r.get("revenue_growth_yoy_pct"), r.get("earnings_growth_yoy_pct"))
        m = score_momentum(r.get("return_12m_pct"), r.get("state"))
        t = score_technical(r.get("rsi14"))
        comp = composite_stock_score(v, q, m, t, growth=g)
        rows.append({
            "ticker": r["ticker"],
            "value_score": v,
            "quality_score": q,
            "growth_score": g,
            "momentum_score": m,
            "technical_score": t,
            "composite": comp["avg"],
        })
    out = pd.DataFrame(rows)
    return out.sort_values("composite", ascending=False).reset_index(drop=True)
