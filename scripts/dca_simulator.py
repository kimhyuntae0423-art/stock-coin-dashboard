"""
DCA (Dollar Cost Averaging) 시뮬레이터 — 월 적립식 자산 분포 추정.

학술적 근거:
- DCA vs Lump-sum: 평균적으로 lump-sum이 ~2%pa 유리하지만, DCA는 정점 매수
  회피 + 심리적 안정성에서 우위 (Vanguard 2012).
- 월급근로자는 자연적으로 DCA — 시장 타이밍 고민 불필요.
- 변동성이 친구: 가격 하락 시 더 많은 주식 매수.

본 시뮬레이터는 매월 일정 금액을 매수했을 때 N년 후 자산 분포를
몬테카를로(기본 2000회)로 추정. 정규분포 가정으로 단순화 — 실제 시장은
fat-tail 있으므로 -25% percentile은 실제로 더 낮을 수 있음.
"""
from __future__ import annotations
import numpy as np


def dca_simulate(monthly_amount: float,
                 years: int,
                 expected_annual_return: float = 0.08,
                 annual_vol: float = 0.18,
                 n_sims: int = 2000,
                 seed: int | None = 42) -> dict:
    """
    Parameters
    ----------
    monthly_amount : 매월 매수 금액 (원/달러)
    years : 적립 기간 (년)
    expected_annual_return : 기대 연수익률 (S&P 500 장기 평균 ≈ 0.08~0.10)
    annual_vol : 연환산 변동성 (S&P 500 ≈ 0.15~0.20)
    n_sims : 몬테카를로 시뮬레이션 횟수
    seed : 재현성 시드

    Returns
    -------
    dict with keys:
      - total_invested: 총 투자 원금
      - mean: 시뮬레이션 평균 자산
      - p5, p25, p50, p75, p95: 백분위 자산
      - loss_prob: 원금 손실 확률 (final < total_invested)
      - return_multiple_mean: 평균 회수배수 (mean / invested)
    """
    if seed is not None:
        rng = np.random.default_rng(seed)
    else:
        rng = np.random.default_rng()

    months = int(years * 12)
    monthly_return = expected_annual_return / 12
    monthly_vol = annual_vol / np.sqrt(12)

    # 벡터화: (n_sims, months) 정규분포 수익률 행렬
    returns = rng.normal(monthly_return, monthly_vol, size=(n_sims, months))
    finals = np.zeros(n_sims)
    for i in range(n_sims):
        balance = 0.0
        for r in returns[i]:
            balance = balance * (1 + r) + monthly_amount
        finals[i] = balance

    total_invested = monthly_amount * months
    return {
        "total_invested": float(total_invested),
        "mean": float(finals.mean()),
        "median": float(np.median(finals)),
        "p5": float(np.percentile(finals, 5)),
        "p25": float(np.percentile(finals, 25)),
        "p50": float(np.percentile(finals, 50)),
        "p75": float(np.percentile(finals, 75)),
        "p95": float(np.percentile(finals, 95)),
        "loss_prob": float((finals < total_invested).mean()),
        "return_multiple_mean": float(finals.mean() / total_invested) if total_invested > 0 else 0,
        "n_sims": n_sims,
        "years": years,
        "monthly_amount": monthly_amount,
    }


def dca_path(monthly_amount: float,
             years: int,
             expected_annual_return: float = 0.08,
             annual_vol: float = 0.18,
             n_sims: int = 500,
             seed: int | None = 42) -> dict:
    """월별 자산 경로를 반환 — 차트 그리기용.

    Returns
    -------
    dict:
      - months: array of month indices [0..months]
      - p5_path, p50_path, p95_path: 각 월별 백분위 경로
      - invested_path: 누적 원금 경로
    """
    if seed is not None:
        rng = np.random.default_rng(seed)
    else:
        rng = np.random.default_rng()
    months = int(years * 12)
    monthly_return = expected_annual_return / 12
    monthly_vol = annual_vol / np.sqrt(12)

    paths = np.zeros((n_sims, months + 1))
    for i in range(n_sims):
        balance = 0.0
        for m in range(months):
            r = rng.normal(monthly_return, monthly_vol)
            balance = balance * (1 + r) + monthly_amount
            paths[i, m + 1] = balance

    p5 = np.percentile(paths, 5, axis=0)
    p50 = np.percentile(paths, 50, axis=0)
    p95 = np.percentile(paths, 95, axis=0)
    invested = np.array([monthly_amount * m for m in range(months + 1)])

    return {
        "months": np.arange(months + 1),
        "p5_path": p5,
        "p50_path": p50,
        "p95_path": p95,
        "invested_path": invested,
    }
