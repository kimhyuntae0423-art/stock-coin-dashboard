"""
주식 종합 평가 — 학술적으로 검증된 팩터를 결합 (QVMGT + Quality Composite).

근거 (학술/실증):
- Value · Quality · Momentum은 30년 이상 일관 초과수익 (Fama-French, AQR, MSCI)
- Piotroski F-Score (1996): 상위 종목 시장 대비 연 +13.4% (1976~1996)
- Magic Formula (Greenblatt): 1988~2004 미국 연 +23.8%
- 12-1 모멘텀 (Jegadeesh-Titman 1993): 50년간 거의 모든 시장에서 작동
- 52주 고가 근접도 (George-Hwang 2004): 12M 모멘텀보다 일관된 우위
- AQR Z-score 결합 방식: 절대 임계값 대신 cross-sectional z-score로 안정성↑

v3 (2026-05): Z-score 결합 + Quality Composite + 12-1 모멘텀 + 52주 고가
v2: Forward PER · 턴어라운드 보너스 · 밸류 트랩 패널티 (legacy)
"""
from __future__ import annotations
import pandas as pd
import numpy as np


# ============================================================
# v2 (Legacy) — 절대 임계값 등급 점수 (대시보드 호환 목적)
# ============================================================
def _per_bucket(per):
    if per is None or pd.isna(per) or per <= 0:
        return None
    if per < 10: return 2
    if per < 15: return 1
    if per < 25: return 0
    if per < 40: return -1
    return -2


def score_value(per, pbr, forward_per=None):
    per_s = _per_bucket(per)
    fper_s = _per_bucket(forward_per)
    pbr_s = None
    if pbr is not None and not pd.isna(pbr) and pbr > 0:
        if pbr < 1: pbr_s = 2
        elif pbr < 2: pbr_s = 1
        elif pbr < 4: pbr_s = 0
        elif pbr < 6: pbr_s = -1
        else: pbr_s = -2
    valid = [s for s in (per_s, pbr_s, fper_s) if s is not None]
    if not valid: return None
    return round(sum(valid) / len(valid))


def score_quality(roe_pct, profit_margin_pct):
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


def score_momentum(return_12m_pct, state):
    ret_s = trend_s = 0
    if return_12m_pct is not None and not pd.isna(return_12m_pct):
        if return_12m_pct >= 40: ret_s = 2
        elif return_12m_pct >= 15: ret_s = 1
        elif return_12m_pct >= 0: ret_s = 0
        elif return_12m_pct >= -20: ret_s = -1
        else: ret_s = -2
    if state == "bull": trend_s = 1
    elif state == "bear": trend_s = -1
    return round((ret_s + trend_s) / 2)


def score_technical(rsi):
    if rsi is None or pd.isna(rsi): return 0
    if rsi <= 30: return 2
    if rsi <= 45: return 1
    if rsi <= 60: return 0
    if rsi <= 70: return -1
    return -2


def score_growth(rev_growth_pct, eps_growth_pct):
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


def turnaround_bonus(per, forward_per, eps_growth_q_pct, earnings_growth_yoy_pct):
    """실적 가속/턴어라운드 보너스. 상한 +0.3 (이전 +0.5에서 축소).
    이유: 모멘텀 추종 방지 우선 — 강세 종목의 보너스가 페널티를 상쇄하지 않도록.
    """
    bonus = 0.0
    if (per is not None and not pd.isna(per) and per > 0
            and forward_per is not None and not pd.isna(forward_per) and forward_per > 0):
        ratio = forward_per / per
        if ratio <= 0.5: bonus = max(bonus, 0.3)
        elif ratio <= 0.65: bonus = max(bonus, 0.2)
    signals = []
    if eps_growth_q_pct is not None and not pd.isna(eps_growth_q_pct):
        signals.append(eps_growth_q_pct)
    if earnings_growth_yoy_pct is not None and not pd.isna(earnings_growth_yoy_pct):
        signals.append(earnings_growth_yoy_pct)
    if signals:
        best = max(signals)
        if best >= 100: bonus = max(bonus, 0.3)
        elif best >= 50: bonus = max(bonus, 0.2)
    return bonus


def value_trap_penalty(value_score, state, return_12m_pct, rsi):
    if value_score is None or value_score < 1: return 0.0
    if state != "bear": return 0.0
    if return_12m_pct is None or pd.isna(return_12m_pct) or return_12m_pct >= 0: return 0.0
    if rsi is not None and not pd.isna(rsi) and rsi >= 50: return 0.0
    return -0.5


def overheat_penalty(rsi, high52_ratio) -> float:
    """단기 과열·정점 페널티 — 사용자 행동 방어 (FOMO 매수 방지).

    "최근 많이 오른 종목을 더 좋게 보는 인지편향"이 정점 매수 + 평균회귀
    손실로 이어지는 패턴을 시스템에서 자동으로 깎아줌.

    조건 (최대 -0.6):
    - RSI ≥ 75 또는 52주 고가 ≥ 97% → 단기 정점 부근
    - RSI ≥ 70 또는 52주 고가 ≥ 93% → 매수 부담 구간
    - RSI ≥ 65 또는 52주 고가 ≥ 88% → 약한 경고
    """
    p = 0.0
    if rsi is not None and not pd.isna(rsi):
        if rsi >= 75:
            p = min(p, -0.5)
        elif rsi >= 70:
            p = min(p, -0.3)
        elif rsi >= 65:
            p = min(p, -0.15)
    if high52_ratio is not None and not pd.isna(high52_ratio):
        if high52_ratio >= 0.97:
            p = min(p, -0.4)
        elif high52_ratio >= 0.93:
            p = min(p, -0.25)
        elif high52_ratio >= 0.88:
            p = min(p, -0.10)
    return p


def mean_reversion_bonus(state, high52_ratio, rsi, return_12m_pct,
                          quality_z=None, value_z=None) -> float:
    """조정 받은 우량주 보너스 — "덜 올랐지만 미래에 오를 종목" 발굴.

    학술적 근거: Quality + Value + Short-term Pullback 조합은 De Bondt-Thaler 1985
    이후 평균회귀 효과의 표준 추출 방식. AQR, MSCI Quality-at-Reasonable-Price.

    조건:
    - 추세는 살아있음 (state == 'bull')
    - 52주 고가 대비 60~85% 구간 (단기 조정 진행 중, 추세 파괴는 아님)
    - RSI 30~55 → 과매도 회복 단계
    - 펀더가 평균 이상 (quality_z + value_z >= 0)
    """
    if state != "bull":
        return 0.0
    if high52_ratio is None or pd.isna(high52_ratio):
        return 0.0
    if not (0.60 <= high52_ratio <= 0.85):
        return 0.0
    if rsi is None or pd.isna(rsi):
        return 0.0

    # 펀더 최소 조건 — 평균 이하면 보너스 안 줌 (그냥 빠지는 종목과 구분)
    funda_sum = 0.0
    if quality_z is not None and not pd.isna(quality_z):
        funda_sum += quality_z
    if value_z is not None and not pd.isna(value_z):
        funda_sum += value_z
    if funda_sum < 0:
        return 0.0

    # RSI 구간별 강도
    if 30 <= rsi <= 50:
        return 0.35  # 과매도에서 회복 단계 — 가장 강한 매수 기회
    if 50 < rsi <= 60:
        return 0.20  # 회복 중기
    if 60 < rsi <= 65:
        return 0.10  # 회복 후기 — 약한 보너스
    return 0.0


def multiple_expansion_penalty(return_12m_pct, earnings_growth_yoy_pct,
                               eps_growth_q_pct=None) -> float:
    """가격 상승이 실적 성장을 크게 초과하면 페널티 — 멀티플 확장 위험 인지.

    예: SK하이닉스 12M +820% vs EPS YoY +397% → 초과 +423%p → -0.5

    초과폭(가격증가 - EPS증가):
    - ≥ 150%p → -0.5
    - 75~150%p → -0.3
    - 30~75%p → -0.15
    - 그 외 → 0

    실적 성장 데이터 결측 시 분기 EPS 성장률로 대체. 그것도 없으면 0.
    """
    if return_12m_pct is None or pd.isna(return_12m_pct):
        return 0.0
    eps_g = None
    if earnings_growth_yoy_pct is not None and not pd.isna(earnings_growth_yoy_pct):
        eps_g = earnings_growth_yoy_pct
    elif eps_growth_q_pct is not None and not pd.isna(eps_growth_q_pct):
        eps_g = eps_growth_q_pct
    if eps_g is None:
        return 0.0
    excess = return_12m_pct - eps_g
    if excess >= 150: return -0.5
    if excess >= 75:  return -0.3
    if excess >= 30:  return -0.15
    return 0.0


# ============================================================
# v3 — Z-score 결합 (AQR 방식) + Piotroski 부분 + 시계열 모멘텀
# ============================================================

def quality_composite(row) -> int:
    """가용 데이터로 만든 Piotroski 정신의 부분 품질 점수(0~7).

    원본 Piotroski 9개 중 우리가 직접 만들 수 있는 건 ROE 양수 1개뿐이므로,
    가용 지표(ROE, profit margin, 성장률 등)로 7개 이진 체크를 구성.
    """
    score = 0
    roe = row.get("roe_pct"); pm = row.get("profit_margin_pct")
    rev = row.get("revenue_growth_yoy_pct"); eps = row.get("earnings_growth_yoy_pct")
    eps_q = row.get("eps_growth_q_pct")
    per = row.get("per"); fper = row.get("forward_per")

    if roe is not None and not pd.isna(roe) and roe > 0: score += 1
    if roe is not None and not pd.isna(roe) and roe >= 15: score += 1
    if pm is not None and not pd.isna(pm) and pm >= 5: score += 1
    if rev is not None and not pd.isna(rev) and rev > 0: score += 1
    if eps is not None and not pd.isna(eps) and eps > 0: score += 1
    if eps_q is not None and not pd.isna(eps_q) and eps_q > 0: score += 1
    # forward PER이 현재 PER보다 낮으면(실적 개선 기대) +1
    if (per is not None and not pd.isna(per) and per > 0 and
            fper is not None and not pd.isna(fper) and fper > 0 and fper < per):
        score += 1
    return score


def _zscore(series: pd.Series) -> pd.Series:
    """cross-sectional z-score. NaN은 평균(0)으로 처리. winsorize ±3σ."""
    s = pd.to_numeric(series, errors="coerce")
    mean = s.mean()
    std = s.std(ddof=0)
    if std == 0 or pd.isna(std):
        return pd.Series(0.0, index=series.index)
    z = (s - mean) / std
    z = z.clip(-3.0, 3.0)  # winsorize
    return z.fillna(0.0)


def _composite_label_v3(z: float) -> str:
    """z-score 결합 점수에 대한 라벨. ±1σ 임계."""
    if z >= 1.0: return "🟢🟢 강한 매수 (상위 16%)"
    if z >= 0.5: return "🟢 매수 우호"
    if z > -0.5: return "🔵 중립"
    if z > -1.0: return "🟠 매도 우호"
    return "🔴🔴 매수 자제 (하위 16%)"


def rank_stocks_v3(stocks_df: pd.DataFrame, apply_overlays: bool = True) -> pd.DataFrame:
    """v3: cross-sectional z-score 결합 + (선택) v2 오버레이.

    필요 컬럼:
      ticker, per, pbr, forward_per, roe_pct, profit_margin_pct,
      revenue_growth_yoy_pct, earnings_growth_yoy_pct, eps_growth_q_pct,
      return_12m_pct, state, rsi14,
      mom_12_1 (선택), high52_ratio (선택)

    apply_overlays=True (디폴트): v2의 turnaround_bonus / value_trap_penalty를
      z-score 합산 점수 위에 추가 (단위: σ). v3의 펀더-과대평가/턴어라운드-놓침
      약점을 보완.
    """
    df = stocks_df.copy()

    # ---- 1) 각 종목별 raw 팩터 계산 ----
    df["_value_raw"] = -pd.to_numeric(df.get("per"), errors="coerce")  # 낮을수록 좋음 → 부호 반전
    df["_pbr_raw"] = -pd.to_numeric(df.get("pbr"), errors="coerce")
    # ROE + Profit Margin
    roe = pd.to_numeric(df.get("roe_pct"), errors="coerce")
    pm = pd.to_numeric(df.get("profit_margin_pct"), errors="coerce")
    df["_quality_raw"] = roe.fillna(roe.mean()) + pm.fillna(pm.mean())
    # 성장: 매출+EPS YoY 평균
    rev = pd.to_numeric(df.get("revenue_growth_yoy_pct"), errors="coerce")
    eps = pd.to_numeric(df.get("earnings_growth_yoy_pct"), errors="coerce")
    df["_growth_raw"] = (rev.fillna(rev.mean()) + eps.fillna(eps.mean())) / 2
    # 모멘텀: 12-1 모멘텀 (없으면 단순 12M return으로 대체)
    mom = pd.to_numeric(df.get("mom_12_1"), errors="coerce")
    ret12 = pd.to_numeric(df.get("return_12m_pct"), errors="coerce")
    df["_mom_raw"] = mom.combine_first(ret12)
    # 단기 모멘텀: 1개월(22거래일) 수익률 — 최근 흐름 반영
    df["_mom_1m_raw"] = pd.to_numeric(df.get("return_1m_pct"), errors="coerce")
    # 추세: 52주 고가 근접도 (없으면 state로 대체)
    h52 = pd.to_numeric(df.get("high52_ratio"), errors="coerce")
    state_map = {"bull": 1.0, "bear": -1.0}
    state_num = df.get("state", pd.Series(index=df.index)).map(state_map).fillna(0.0)
    df["_trend_raw"] = h52.combine_first(state_num)
    # Quality Composite (0~7)
    df["_qc_raw"] = df.apply(quality_composite, axis=1).astype(float)

    # ---- 2) Z-score 변환 ----
    factor_cols = {
        "z_value": df["_value_raw"],
        "z_pbr": df["_pbr_raw"],
        "z_quality": df["_quality_raw"],
        "z_growth": df["_growth_raw"],
        "z_momentum": df["_mom_raw"],
        "z_mom_1m": df["_mom_1m_raw"],
        "z_trend": df["_trend_raw"],
        "z_qc": df["_qc_raw"],
    }
    for name, raw in factor_cols.items():
        df[name] = _zscore(raw)

    # ---- 3) 동일 가중 결합 (AQR 표준) ----
    # 가치 = (z_value + z_pbr) / 2 으로 통합
    # 가중치 의도: "덜 올랐지만 좋은 종목" 발굴 강화
    #   - 가치 1.3 (저평가 우대 ↑)
    #   - 품질·성장·QC·추세 1.0
    #   - 모멘텀 0.3 (과거 가격 상승률 영향 최소화)
    df["z_value_combined"] = (df["z_value"] + df["z_pbr"]) / 2
    # v3.4: 1M 단기 모멘텀 추가 (가중치 0.3) — 최근 급락 반영, 장기 전략 유지
    _W_VALUE, _W_QUAL, _W_GROW, _W_MOM, _W_MOM1M, _W_TREND, _W_QC = 1.5, 1.0, 1.0, 0.1, 0.3, 0.5, 1.0
    _W_TOTAL = _W_VALUE + _W_QUAL + _W_GROW + _W_MOM + _W_MOM1M + _W_TREND + _W_QC
    df["composite_base"] = (
        _W_VALUE * df["z_value_combined"]
        + _W_QUAL * df["z_quality"]
        + _W_GROW * df["z_growth"]
        + _W_MOM * df["z_momentum"]
        + _W_MOM1M * df["z_mom_1m"]
        + _W_TREND * df["z_trend"]
        + _W_QC * df["z_qc"]
    ) / _W_TOTAL

    # ---- 4) v2 오버레이 (선택) — 턴어라운드 보너스 + 밸류 트랩 패널티 ----
    # ---- + v3.1 신규 오버레이 — 과열 페널티 + 멀티플 확장 페널티 ----
    if apply_overlays:
        df["turnaround_bonus"] = df.apply(
            lambda r: turnaround_bonus(
                r.get("per"), r.get("forward_per"),
                r.get("eps_growth_q_pct"), r.get("earnings_growth_yoy_pct")
            ), axis=1)
        # v3에서 value_score는 z_value_combined > 1 (저평가 1σ 이상)로 정의
        df["value_trap_penalty"] = df.apply(
            lambda r: value_trap_penalty(
                value_score=2 if r["z_value_combined"] >= 1.0 else 0,
                state=r.get("state"),
                return_12m_pct=r.get("return_12m_pct"),
                rsi=r.get("rsi14"),
            ), axis=1)
        df["overheat_penalty"] = df.apply(
            lambda r: overheat_penalty(r.get("rsi14"), r.get("high52_ratio")), axis=1)
        df["multi_exp_penalty"] = df.apply(
            lambda r: multiple_expansion_penalty(
                r.get("return_12m_pct"),
                r.get("earnings_growth_yoy_pct"),
                r.get("eps_growth_q_pct"),
            ), axis=1)
        df["mean_reversion_bonus"] = df.apply(
            lambda r: mean_reversion_bonus(
                state=r.get("state"),
                high52_ratio=r.get("high52_ratio"),
                rsi=r.get("rsi14"),
                return_12m_pct=r.get("return_12m_pct"),
                quality_z=r.get("z_quality"),
                value_z=r.get("z_value_combined"),
            ), axis=1)
    else:
        df["turnaround_bonus"] = 0.0
        df["value_trap_penalty"] = 0.0
        df["overheat_penalty"] = 0.0
        df["multi_exp_penalty"] = 0.0
        df["mean_reversion_bonus"] = 0.0

    df["composite"] = (df["composite_base"]
                       + df["turnaround_bonus"]
                       + df["value_trap_penalty"]
                       + df["overheat_penalty"]
                       + df["multi_exp_penalty"]
                       + df["mean_reversion_bonus"]).round(3)
    df["composite"] = df["composite"].clip(-3.0, 3.0)
    df["label"] = df["composite"].apply(_composite_label_v3)

    cols = ["ticker", "composite", "label", "composite_base",
            "z_value_combined", "z_quality", "z_growth", "z_momentum", "z_mom_1m", "z_trend", "z_qc",
            "turnaround_bonus", "value_trap_penalty",
            "overheat_penalty", "multi_exp_penalty", "mean_reversion_bonus"]
    out = df[cols].copy()
    out["quality_composite_raw"] = df["_qc_raw"].astype(int)

    # v2 호환 alias — 기존 페이지(stocks_page.py)가 사용하는 컬럼명을 z-score 반올림으로 매핑
    def _z_to_grade(s: pd.Series) -> pd.Series:
        return s.round().clip(-2, 2).fillna(0).astype(int)
    out["value_score"] = _z_to_grade(df["z_value_combined"])
    out["quality_score"] = _z_to_grade(df["z_quality"])
    out["growth_score"] = _z_to_grade(df["z_growth"])
    out["momentum_score"] = _z_to_grade(df["z_momentum"])
    out["technical_score"] = _z_to_grade(df["z_trend"])

    return out.sort_values("composite", ascending=False).reset_index(drop=True)


# ============================================================
# 디폴트 진입점 — v3 사용. 기존 caller(stocks_page, portfolio_page) 호환 유지.
# ============================================================
def rank_stocks(stocks_df: pd.DataFrame) -> pd.DataFrame:
    """기본은 v3 (z-score 결합). composite 컬럼 + 정렬된 DataFrame 반환."""
    return rank_stocks_v3(stocks_df)
