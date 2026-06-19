"""시장 국면 판단 + 코어 ETF 추천 점수 계산 — etf_page.py · rebalancing_page.py 공유 모듈."""
import pandas as pd


def _risk_bucket(row: pd.Series) -> str:
    cat = str(row.get("category", ""))
    asc = str(row.get("asset_class", ""))
    if asc == "bond" or "채권" in cat:
        return "방어"
    if asc == "commodity" or "원자재" in cat:
        return "대안"
    if any(k in cat for k in ["유틸리티", "헬스케어", "현금"]):
        return "방어"
    if any(k in cat for k in ["나스닥", "반도체", "AI", "방산", "테마", "우라늄", "구리", "인프라"]):
        return "공격"
    return "핵심"


_BUCKET_WEIGHT = {
    "bull":  {"공격": 1.30, "핵심": 1.10, "대안": 0.90, "방어": 0.70},
    "mixed": {"공격": 1.00, "핵심": 1.00, "대안": 1.00, "방어": 1.00},
    "bear":  {"공격": 0.70, "핵심": 0.90, "대안": 1.20, "방어": 1.30},
}


def market_regime(summary_df: pd.DataFrame) -> dict:
    """summary_signals DataFrame으로 시장 국면 반환.

    Returns dict with keys:
        label, key("bull"|"mixed"|"bear"), desc,
        breadth, spy_1m, spy_12m, tlt_1m, bond_winning
    """
    if summary_df.empty:
        return dict(label="🔘 데이터 없음", key="mixed", desc="",
                    breadth=0, spy_1m=0, spy_12m=0, tlt_1m=0, bond_winning=False)

    latest = summary_df.sort_values("date").groupby("ticker").last().reset_index()
    breadth = (latest["state"] == "bull").mean() * 100

    def _get(t, col):
        r = latest[latest["ticker"] == t]
        return float(r[col].values[0]) if not r.empty and col in r.columns else 0.0

    spy_1m  = _get("SPY", "return_1m_pct")
    spy_12m = _get("SPY", "return_12m_pct")
    tlt_1m  = _get("TLT", "return_1m_pct")
    bond_winning = tlt_1m > spy_1m

    if breadth >= 55 and spy_1m >= 0 and not bond_winning:
        label = "🟢 강세 (Risk-On)"
        key   = "bull"
        desc  = f"시장 브레드스 {breadth:.0f}% · SPY 1M {spy_1m:+.1f}% · 주식 > 채권"
    elif breadth <= 40 or spy_1m <= -5 or (bond_winning and spy_1m < 0):
        label = "🔴 약세 (Risk-Off)"
        key   = "bear"
        desc  = f"시장 브레드스 {breadth:.0f}% · SPY 1M {spy_1m:+.1f}% · {'채권 > 주식' if bond_winning else '낙폭 과대'}"
    else:
        label = "🟡 혼조"
        key   = "mixed"
        desc  = f"시장 브레드스 {breadth:.0f}% · SPY 1M {spy_1m:+.1f}% · 방향성 불명확"

    return dict(label=label, key=key, desc=desc,
                breadth=breadth, spy_1m=spy_1m, spy_12m=spy_12m,
                tlt_1m=tlt_1m, bond_winning=bond_winning)


def score_etfs(etf_df: pd.DataFrame, summary_df: pd.DataFrame, regime_key: str) -> pd.DataFrame:
    """core_etfs + summary 병합 후 국면 반영 점수 계산.

    Returns DataFrame with added columns:
        close, return_1m_pct, return_12m_pct, rsi14, state,
        버킷, mom_score, score
    """
    if summary_df.empty or etf_df.empty:
        return etf_df.copy()

    sig = summary_df.sort_values("date").groupby("ticker").last().reset_index()
    sig["ticker"] = sig["ticker"].astype(str).str.upper()

    base = etf_df.copy()
    base["ticker"] = base["ticker"].astype(str).str.upper()

    merged = base.merge(
        sig[["ticker", "close", "return_1m_pct", "return_12m_pct", "rsi14", "state"]],
        on="ticker", how="left",
    )

    valid = merged.dropna(subset=["close"]).copy()
    if valid.empty:
        return merged

    valid["버킷"]      = valid.apply(_risk_bucket, axis=1)
    valid["r12_rank"]  = valid["return_12m_pct"].rank(pct=True)
    valid["r1_rank"]   = valid["return_1m_pct"].rank(pct=True)
    valid["mom_score"] = (valid["r12_rank"] * 0.7 + valid["r1_rank"] * 0.3) * 100
    w = _BUCKET_WEIGHT.get(regime_key, _BUCKET_WEIGHT["mixed"])
    valid["score"] = valid.apply(lambda r: r["mom_score"] * w.get(r["버킷"], 1.0), axis=1)

    # 데이터 없는 행도 포함해서 반환 (score NaN)
    result = merged.copy()
    result = result.merge(
        valid[["ticker", "버킷", "mom_score", "score"]],
        on="ticker", how="left",
    )
    return result
