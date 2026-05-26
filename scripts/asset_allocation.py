"""
Core-Satellite 자산 배분 추적 + 리밸런싱 액션 생성.

전략 근거 (Bogleheads + Vanguard 30년 검증):
- Core (시장 ETF): 시장 수익률 보장 + 저비용 + 행동편향 차단
- Satellite (개별주): alpha 시도 영역. 잃어도 큰 타격 없는 비중
- Cash: 시장 폭락 시 추가매수 탄약
- 정기 리밸런싱 (목표 ±5%p 이탈 시): 연 0.5~1% 추가 알파 (Vanguard 연구)
"""
from __future__ import annotations
from pathlib import Path
import pandas as pd

ROOT = Path(__file__).resolve().parent.parent
CORE_ETF_FILE = ROOT / "core_etfs.csv"


def load_core_etfs() -> pd.DataFrame:
    """Core 버킷 후보 ETF 목록 로드."""
    if not CORE_ETF_FILE.exists():
        return pd.DataFrame(columns=["ticker", "name", "category", "asset_class"])
    return pd.read_csv(CORE_ETF_FILE)


def classify_holdings(holdings_df: pd.DataFrame,
                      core_etf_tickers: set | None = None) -> pd.DataFrame:
    """holdings의 각 종목을 Core/Satellite로 분류.

    Core: core_etfs.csv 에 있는 ETF
    Satellite: 그 외 개별주
    """
    if core_etf_tickers is None:
        core_etf_tickers = set(load_core_etfs()["ticker"].astype(str))
    out = holdings_df.copy()
    if "ticker" not in out.columns:
        out["bucket"] = "Unknown"
        return out
    out["ticker"] = out["ticker"].astype(str).str.strip().str.upper()
    out["bucket"] = out["ticker"].apply(
        lambda t: "Core" if t in core_etf_tickers else "Satellite"
    )
    return out


def allocation_summary(classified_holdings: pd.DataFrame,
                       price_map: dict,
                       cash_amount: float = 0.0,
                       qty_col: str = "qty") -> dict:
    """현재 자산 배분 요약 (Core/Satellite/Cash 금액 + 비중)."""
    h = classified_holdings.copy()
    if h.empty:
        bucket_value = pd.Series(dtype=float)
    else:
        h["price"] = h["ticker"].map(price_map)
        h["value"] = pd.to_numeric(h[qty_col], errors="coerce") * pd.to_numeric(h["price"], errors="coerce")
        bucket_value = h.groupby("bucket")["value"].sum(min_count=1).fillna(0)

    core_v = float(bucket_value.get("Core", 0.0))
    sat_v = float(bucket_value.get("Satellite", 0.0))
    total = core_v + sat_v + cash_amount

    summary = {
        "Core_value": core_v,
        "Satellite_value": sat_v,
        "Cash_value": float(cash_amount),
        "Total": float(total),
        "Core_pct": (core_v / total * 100) if total > 0 else 0.0,
        "Satellite_pct": (sat_v / total * 100) if total > 0 else 0.0,
        "Cash_pct": (cash_amount / total * 100) if total > 0 else 0.0,
    }
    return summary


def deviation_from_target(summary: dict,
                          target_core: float = 70,
                          target_satellite: float = 20,
                          target_cash: float = 10) -> dict:
    """목표 비중 대비 편차 (백분율 포인트)."""
    return {
        "Core_dev": summary["Core_pct"] - target_core,
        "Satellite_dev": summary["Satellite_pct"] - target_satellite,
        "Cash_dev": summary["Cash_pct"] - target_cash,
    }


def rebalancing_actions(summary: dict,
                        target_core: float = 70,
                        target_satellite: float = 20,
                        target_cash: float = 10,
                        threshold_pp: float = 5.0) -> list[dict]:
    """리밸런싱 권장 액션 (±threshold_pp 초과 시 발동).

    Returns: list of {bucket, current_pct, target_pct, deviation_pp, action, amount}
    """
    dev = deviation_from_target(summary, target_core, target_satellite, target_cash)
    target_map = {"Core": target_core, "Satellite": target_satellite, "Cash": target_cash}
    dev_map = {"Core": dev["Core_dev"], "Satellite": dev["Satellite_dev"], "Cash": dev["Cash_dev"]}

    actions = []
    total = summary["Total"]
    for bucket in ["Core", "Satellite", "Cash"]:
        d = dev_map[bucket]
        if abs(d) < threshold_pp:
            continue
        target = target_map[bucket]
        target_value = total * target / 100
        current_value = summary[f"{bucket}_value"]
        diff = target_value - current_value
        actions.append({
            "bucket": bucket,
            "current_pct": summary[f"{bucket}_pct"],
            "target_pct": target,
            "deviation_pp": d,
            "action": "추가매수" if d < 0 else "일부매도",
            "amount": abs(diff),
        })
    return actions


def add_on_buy_triggers(holdings_df: pd.DataFrame,
                        current_price_map: dict,
                        score_map: dict | None = None,
                        thresholds: tuple = (-5, -10, -15, -20)) -> pd.DataFrame:
    """보유 종목 중 매수가 대비 일정 % 하락 도달한 종목 식별.

    분할매수 전략의 추가 진입 트리거. 단, 점수가 양수일 때만 "기회"로 분류
    (펀더 변화 없을 때만 추가매수가 합리적).
    """
    if holdings_df.empty:
        return pd.DataFrame(columns=["ticker", "buy_price", "current_price",
                                     "drop_pct", "trigger", "score", "verdict"])
    h = holdings_df.copy()
    h["ticker"] = h["ticker"].astype(str).str.strip().str.upper()
    h["current_price"] = h["ticker"].map(current_price_map)
    h["buy_price"] = pd.to_numeric(h["buy_price"], errors="coerce")
    h["drop_pct"] = ((h["current_price"] / h["buy_price"]) - 1) * 100

    if score_map is not None:
        h["score"] = h["ticker"].map(score_map)
    else:
        h["score"] = None

    def classify(row):
        d = row["drop_pct"]
        if pd.isna(d):
            return None, "데이터 부족"
        # 가장 가까운(낮은) 임계 찾기
        triggered = None
        for thr in sorted(thresholds, reverse=True):  # -5, -10, -15, -20
            if d <= thr:
                triggered = thr
        if triggered is None:
            return None, "조정 없음"

        # 점수 확인
        score = row.get("score")
        if score is None or pd.isna(score):
            verdict = f"{triggered}% 도달 (점수 확인 필요)"
        elif score >= 0.5:
            verdict = f"💎 {triggered}% 추가매수 기회 (점수 우호 유지)"
        elif score >= 0:
            verdict = f"🔵 {triggered}% 조정 — 분할매수 검토"
        elif score >= -0.5:
            verdict = f"🟠 {triggered}% — 펀더 약화, 추가매수 신중"
        else:
            verdict = f"🔴 {triggered}% — 펀더 악화, 추가매수 자제 / 손절 검토"
        return triggered, verdict

    results = h.apply(classify, axis=1)
    h["trigger"] = [r[0] for r in results]
    h["verdict"] = [r[1] for r in results]

    return h[h["trigger"].notna()][[
        "ticker", "buy_price", "current_price", "drop_pct", "trigger", "score", "verdict"
    ]].sort_values("drop_pct")
