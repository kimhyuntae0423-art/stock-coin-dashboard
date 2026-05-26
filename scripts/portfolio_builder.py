"""
분산 포트폴리오 구성 — 점수 + 변동성 + 섹터 제약을 결합.

학술/실무 근거:
- Equal Weight (1/N): DeMiguel et al. 2009 — 복잡한 최적화보다 잘 작동
- Inverse Volatility / Risk Parity: AQR · BlackRock 표준. 변동성 큰 종목 비중↓
- Score-weighted: 알파 시그널을 자본 효율적으로 활용
- Score × InvVol: 위 둘의 결합. "강한 종목 + 안정적인 종목"에 자본 집중

본 모듈은 1회성 매수 추천을 위한 가중치를 계산.
리밸런싱·세제·거래비용은 다루지 않음 (의사결정 보조 목적).
"""
from __future__ import annotations
import pandas as pd
import numpy as np


def _score_to_strength(score: float) -> float:
    """composite z-score를 양의 weight strength로 변환.

    z-score는 음수가 가능하므로 0 미만은 0으로 클리핑.
    추가로 +1 offset을 줘서 0 근처도 약한 비중은 받게 함 (디폴트는 미사용).
    """
    if score is None or pd.isna(score):
        return 0.0
    return max(0.0, float(score))  # 음수 점수 종목은 제외


def _normalize_to_sum_one(weights: pd.Series) -> pd.Series:
    total = weights.sum()
    if total <= 0:
        # 모두 0인 경우 균등 분배
        return pd.Series(1.0 / len(weights), index=weights.index)
    return weights / total


def _apply_sector_cap(weights: pd.Series, sectors: pd.Series, cap: float) -> pd.Series:
    """단일 섹터 비중이 cap을 넘으면 해당 섹터를 cap까지로 깎고 잔여 비중을 다른 섹터에 재배분.

    cap=0.35: 한 섹터 최대 35%. 초과분은 다른 섹터의 종목들에 비례 재분배.
    수렴할 때까지 최대 5회 반복(섹터가 여럿이 동시에 cap에 닿으면 단순 1패스로 부족).
    """
    if cap is None or cap >= 1.0 or len(weights) == 0:
        return weights
    w = weights.copy()
    sec = sectors.fillna("Unknown")
    for _ in range(5):
        sec_sum = w.groupby(sec).sum()
        over = sec_sum[sec_sum > cap + 1e-9]
        if over.empty:
            break
        for sname, total in over.items():
            mask = (sec == sname)
            # 해당 섹터 종목 비중을 cap에 맞춰 균등 축소
            w.loc[mask] = w.loc[mask] * (cap / total)
        # 잔여 비중을 cap 미만 섹터에 비례 재배분
        deficit = 1.0 - w.sum()
        if deficit <= 1e-9:
            break
        # cap에 닿지 않은 종목만 후보
        sec_sum2 = w.groupby(sec).sum()
        ok_sectors = sec_sum2[sec_sum2 < cap - 1e-9].index
        candidate_mask = sec.isin(ok_sectors)
        if not candidate_mask.any():
            break
        base = w.loc[candidate_mask].sum()
        if base <= 0:
            break
        w.loc[candidate_mask] = w.loc[candidate_mask] * (1 + deficit / base)
    return w / w.sum()  # 최종 정규화


# ============================================================
# 핵심 함수
# ============================================================
def build_portfolio(
    scored_df: pd.DataFrame,
    capital: float,
    top_n: int = 10,
    method: str = "score_x_invvol",
    sector_cap: float | None = 0.35,
    price_col: str = "close",
    sector_col: str = "sector",
    vol_col: str = "ann_vol",
    score_col: str = "composite",
    min_score: float = 0.0,
) -> dict:
    """
    Parameters
    ----------
    scored_df : DataFrame
        rank_stocks() 결과 + enrich_price_factors() + fundamentals 머지된 DF.
        필수 컬럼: ticker, composite, close, sector, ann_vol.
    capital : float
        총 투자 금액 (원/달러 — 통화 동일 가정. 한·미 혼합 시 환율 변환 필요).
    top_n : int
        분산할 종목 수 상한.
    method : str
        "equal"       — 1/N 균등
        "score"       — composite 비례
        "inv_vol"     — 1/연환산변동성 비례
        "score_x_invvol" — composite × (1/vol) 결합 (디폴트)
    sector_cap : float | None
        단일 섹터 최대 비중. None이면 미적용.
    min_score : float
        이 점수 미만은 후보에서 제외 (디폴트 0 = 음수 점수 종목 제외).

    Returns
    -------
    dict with keys:
      - 'portfolio': DataFrame (ticker, sector, score, weight_pct, target_amount, price, shares, actual_amount)
      - 'cash_left': float (1주 단위 매수 후 남은 현금)
      - 'sector_breakdown': DataFrame (sector, weight_pct)
      - 'meta': dict (method, top_n, capital, sector_cap, excluded)
    """
    df = scored_df.copy()
    if score_col not in df.columns:
        raise ValueError(f"{score_col} 컬럼이 필요합니다 (rank_stocks 결과 머지 필요)")

    # 1) 후보 필터링 — 점수 > min_score & 가격/변동성 데이터 있음
    df = df[df[score_col] > min_score].copy()
    df = df.dropna(subset=[price_col])
    if df.empty:
        return {"portfolio": pd.DataFrame(), "cash_left": capital,
                "sector_breakdown": pd.DataFrame(),
                "meta": {"error": "후보 없음 (점수 > min_score 종목이 없음)"}}

    # 2) 상위 N 선정
    df = df.sort_values(score_col, ascending=False).head(top_n).reset_index(drop=True)

    # 3) 가중치 계산
    if method == "equal":
        raw_w = pd.Series(1.0, index=df.index)
    elif method == "score":
        raw_w = df[score_col].apply(_score_to_strength)
    elif method == "inv_vol":
        v = pd.to_numeric(df[vol_col], errors="coerce")
        # 변동성 결측 시 모집단 중앙값으로 대체
        v = v.fillna(v.median() if v.notna().any() else 0.3)
        raw_w = 1.0 / v.replace(0, np.nan).fillna(v.median())
    elif method == "score_x_invvol":
        v = pd.to_numeric(df[vol_col], errors="coerce")
        v = v.fillna(v.median() if v.notna().any() else 0.3).replace(0, np.nan)
        v = v.fillna(v.median())
        strength = df[score_col].apply(_score_to_strength)
        raw_w = strength / v
    else:
        raise ValueError(f"Unknown method: {method}")

    weights = _normalize_to_sum_one(raw_w)

    # 4) 섹터 캡 적용
    if sector_cap is not None and sector_col in df.columns:
        weights = _apply_sector_cap(weights, df[sector_col], sector_cap)

    df["weight_pct"] = (weights * 100).round(2).values
    df["target_amount"] = (weights * capital).round(0).values

    # 5) 1주 단위 매수 수량 계산
    px = pd.to_numeric(df[price_col], errors="coerce")
    shares = (df["target_amount"] / px).apply(lambda x: int(x) if pd.notna(x) and x >= 0 else 0)
    df["price"] = px
    df["shares"] = shares
    df["actual_amount"] = (df["shares"] * px).round(0)

    cash_left = float(capital - df["actual_amount"].sum())

    # 6) 섹터 분포
    if sector_col in df.columns:
        sec_break = (df.groupby(sector_col)["weight_pct"].sum()
                     .sort_values(ascending=False)
                     .reset_index()
                     .rename(columns={sector_col: "sector"}))
    else:
        sec_break = pd.DataFrame()

    out_cols = ["ticker", sector_col, score_col, "weight_pct", "target_amount",
                "price", "shares", "actual_amount"]
    out_cols = [c for c in out_cols if c in df.columns]
    portfolio = df[out_cols].rename(columns={score_col: "score", sector_col: "sector"})

    return {
        "portfolio": portfolio,
        "cash_left": cash_left,
        "sector_breakdown": sec_break,
        "meta": {
            "method": method,
            "top_n": top_n,
            "capital": capital,
            "sector_cap": sector_cap,
            "n_selected": len(portfolio),
        },
    }


def compare_methods(scored_df: pd.DataFrame, capital: float, top_n: int = 10,
                    sector_cap: float | None = 0.35) -> pd.DataFrame:
    """4가지 방식 결과를 같은 테이블로 비교 — 검증/시각화용."""
    methods = ["equal", "score", "inv_vol", "score_x_invvol"]
    rows = []
    for m in methods:
        r = build_portfolio(scored_df, capital=capital, top_n=top_n,
                            method=m, sector_cap=sector_cap)
        p = r["portfolio"]
        if p.empty: continue
        rows.append({
            "method": m,
            "n": len(p),
            "max_weight_pct": p["weight_pct"].max(),
            "min_weight_pct": p["weight_pct"].min(),
            "top3_concentration": p.nlargest(3, "weight_pct")["weight_pct"].sum(),
            "n_sectors": p["sector"].nunique() if "sector" in p.columns else None,
            "cash_left_pct": round(r["cash_left"] / capital * 100, 2),
        })
    return pd.DataFrame(rows)
