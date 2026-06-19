"""시장 국면 + 섹터 사이클 반영 코어 ETF 추천 — etf_page.py · rebalancing_page.py 공유 모듈."""
import pandas as pd

# ── 섹터 사이클 정의 ──────────────────────────────────────────────────────────
# (카테고리 키워드) → (대표 ETF, 비교 벤치마크, 라벨)
# 상대강도 = 대표ETF 1M - 벤치마크 1M
_SECTOR_CYCLES = [
    (["반도체"],              "SMH",  "SPY",  "반도체 사이클"),
    (["AI", "로봇"],          "AIQ",  "QQQ",  "AI 사이클"),
    (["방산"],                "ITA",  "SPY",  "방산 사이클"),
    (["우라늄"],              "URA",  "SPY",  "원자력 사이클"),
    (["구리"],                "COPX", "SPY",  "구리/원자재 사이클"),
    (["인프라"],              "PAVE", "SPY",  "인프라 사이클"),
    (["헬스케어"],            "XLV",  "SPY",  "헬스케어 사이클"),
    (["유틸리티"],            "XLU",  "SPY",  "유틸리티 사이클"),
    (["채권"],                "TLT",  "SPY",  "채권 사이클"),
    (["원자재 - 금", "금"],   "GLD",  "BND",  "금 사이클"),
    (["인도"],                "INDA", "VEU",  "인도 사이클"),
    (["일본"],                "DXJ",  "VEU",  "일본 사이클"),
    (["나스닥"],              "QQQ",  "SPY",  "나스닥 사이클"),
    (["한국 대형주"],         "069500.KS", "SPY", "코스피 사이클"),
    (["미국 대형주", "미국 전체", "글로벌"], "SPY", "VT", "글로벌 사이클"),
]


def _cycle_multiplier(rel_1m: float) -> float:
    """섹터 상대강도(1M, %p) → 사이클 배율."""
    if rel_1m >  6: return 1.25
    if rel_1m >  3: return 1.12
    if rel_1m > -3: return 1.00
    if rel_1m > -6: return 0.88
    return 0.75


def _cycle_label(rel_1m: float) -> str:
    if rel_1m >  6: return "🔥 강한 상승"
    if rel_1m >  3: return "📈 상승"
    if rel_1m > -3: return "➡️ 중립"
    if rel_1m > -6: return "📉 하락"
    return "❄️ 강한 하락"


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
    """summary_signals DataFrame → 시장 국면 반환."""
    if summary_df.empty:
        return dict(label="🔘 데이터 없음", key="mixed", desc="",
                    breadth=0, spy_1m=0, spy_12m=0, tlt_1m=0, bond_winning=False)

    latest = summary_df.sort_values("date").groupby("ticker").last().reset_index()
    breadth = (latest["state"] == "bull").mean() * 100

    def _get(t, col):
        r = latest[latest["ticker"] == t]
        return float(r[col].values[0]) if not r.empty and col in r.columns else 0.0

    spy_1m       = _get("SPY", "return_1m_pct")
    spy_12m      = _get("SPY", "return_12m_pct")
    tlt_1m       = _get("TLT", "return_1m_pct")
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


def sector_cycles(summary_df: pd.DataFrame) -> pd.DataFrame:
    """각 섹터의 사이클 상태를 계산해 DataFrame으로 반환.

    Columns: sector, indicator, benchmark, rel_1m, multiplier, cycle_label
    """
    if summary_df.empty:
        return pd.DataFrame()

    latest = summary_df.sort_values("date").groupby("ticker").last().reset_index()
    latest["ticker"] = latest["ticker"].astype(str).str.upper()

    def _r1m(t):
        r = latest[latest["ticker"] == t.upper()]
        return float(r["return_1m_pct"].values[0]) if not r.empty else None

    rows = []
    for keywords, ind, bench, lbl in _SECTOR_CYCLES:
        ind_r  = _r1m(ind)
        ben_r  = _r1m(bench)
        if ind_r is None or ben_r is None:
            continue
        rel = ind_r - ben_r
        rows.append({
            "섹터":    lbl,
            "지표ETF": ind,
            "벤치마크": bench,
            "지표 1M": ind_r,
            "벤치 1M": ben_r,
            "상대강도": rel,
            "사이클":  _cycle_label(rel),
            "_mult":   _cycle_multiplier(rel),
            "_keys":   keywords,
        })
    return pd.DataFrame(rows)


def score_etfs(etf_df: pd.DataFrame, summary_df: pd.DataFrame, regime_key: str) -> pd.DataFrame:
    """core_etfs + summary 병합 후 국면 × 섹터 사이클 반영 점수 계산.

    추가 컬럼: close, return_1m_pct, return_12m_pct, rsi14, state,
               버킷, 섹터사이클, 사이클배율, mom_score, score
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

    # 섹터 사이클 매핑 빌드
    cycles_df = sector_cycles(summary_df)

    def _get_cycle(cat: str):
        if cycles_df.empty:
            return "—", 1.0
        for _, cy in cycles_df.iterrows():
            if any(k in cat for k in cy["_keys"]):
                return cy["사이클"], cy["_mult"]
        return "—", 1.0

    valid["버킷"] = valid.apply(_risk_bucket, axis=1)
    valid[["섹터사이클", "사이클배율"]] = valid["category"].apply(
        lambda c: pd.Series(_get_cycle(str(c)))
    )

    valid["r12_rank"]  = valid["return_12m_pct"].rank(pct=True)
    valid["r1_rank"]   = valid["return_1m_pct"].rank(pct=True)
    valid["mom_score"] = (valid["r12_rank"] * 0.7 + valid["r1_rank"] * 0.3) * 100

    w = _BUCKET_WEIGHT.get(regime_key, _BUCKET_WEIGHT["mixed"])
    valid["score"] = valid.apply(
        lambda r: r["mom_score"] * w.get(r["버킷"], 1.0) * float(r["사이클배율"]),
        axis=1,
    )

    result = merged.copy()
    result = result.merge(
        valid[["ticker", "버킷", "섹터사이클", "사이클배율", "mom_score", "score"]],
        on="ticker", how="left",
    )
    return result
