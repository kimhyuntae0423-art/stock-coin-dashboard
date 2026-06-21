"""
코어 ETF 로테이션 — 8역할 사이클 기반 배분.

경기 국면(VIX + 시장 모멘텀)으로 역할별 비중을 결정하고,
H15(상대적 저점)으로 미세 조정한다.
"""
from __future__ import annotations
import pandas as pd

# ── 8역할 코어 정의 ─────────────────────────────────────────────────────────
CORE_ROLES = [
    {
        "role": "미국 주식",
        "us":   "VOO",
        "kr":   "360750.KS",
        "desc": "S&P500 지수 추종. 경기 회복~확장기 핵심.",
        "weights": {"fear": 0.18, "recovery": 0.32, "expansion": 0.38, "overheated": 0.28},
    },
    {
        "role": "배당/가치",
        "us":   "SCHD",
        "kr":   "314250.KS",
        "desc": "고배당 우량주. 확장 후반~침체 전환기 방어.",
        "weights": {"fear": 0.15, "recovery": 0.08, "expansion": 0.10, "overheated": 0.20},
    },
    {
        "role": "성장/반도체",
        "us":   "SOXX",
        "kr":   "469170.KS",
        "desc": "반도체·AI 성장. 회복 초기~확장 중기 집중.",
        "weights": {"fear": 0.04, "recovery": 0.14, "expansion": 0.16, "overheated": 0.08},
    },
    {
        "role": "장기 국채",
        "us":   "TLT",
        "kr":   "476760.KS",
        "desc": "미국 20년 국채. 공포·금리 하락기 최고.",
        "weights": {"fear": 0.25, "recovery": 0.14, "expansion": 0.06, "overheated": 0.15},
    },
    {
        "role": "금",
        "us":   "GLD",
        "kr":   "0072R0.KS",
        "desc": "금 현물. 인플레·지정학·공포 헷지.",
        "weights": {"fear": 0.16, "recovery": 0.10, "expansion": 0.06, "overheated": 0.12},
    },
    {
        "role": "원자재/구리",
        "us":   "COPX",
        "kr":   None,
        "desc": "구리 채굴. 경기 확장 중기, 인프라·EV 수요.",
        "weights": {"fear": 0.04, "recovery": 0.08, "expansion": 0.14, "overheated": 0.05},
    },
    {
        "role": "헬스케어/방어",
        "us":   "XLV",
        "kr":   None,
        "desc": "미국 헬스케어. 사이클 무관 방어. 침체 전환기.",
        "weights": {"fear": 0.10, "recovery": 0.06, "expansion": 0.06, "overheated": 0.07},
    },
    {
        "role": "현금/단기채",
        "us":   "SHY",
        "kr":   "448290.KS",
        "desc": "단기채·CD금리. 과열기 현금 확보. 다음 매수 재원.",
        "weights": {"fear": 0.08, "recovery": 0.08, "expansion": 0.04, "overheated": 0.05},
    },
]

PHASE_LABELS = {
    "fear":       "🔥 공포",
    "recovery":   "🌱 회복",
    "expansion":  "🚀 확장",
    "overheated": "🌡️ 과열",
}

PHASE_DESCS = {
    "fear":       "VIX>25 — 채권·금 확대, 주식 축소. 공포 극단이 최고 매수 타이밍.",
    "recovery":   "VIX 20~25 — 주식 비중 회복. 성장주·반도체 선행.",
    "expansion":  "VIX 13~20 — 주식·원자재 확대. 경기 민감 섹터 집중.",
    "overheated": "VIX<13 — 방어·배당 강화, 현금 확보. 다음 조정 대비.",
}


def get_phase(vix: float, spy_1m: float, spy_12m: float) -> str:
    """VIX + 모멘텀으로 경기 국면 판단."""
    if vix > 25:
        return "fear"
    if vix < 13:
        return "overheated"
    if vix >= 20 or spy_1m < -3:
        return "recovery"
    return "expansion"


def rotation_target(
    vix: float,
    spy_1m: float,
    spy_12m: float,
    scored_df: pd.DataFrame | None = None,
) -> tuple[pd.DataFrame, str]:
    """
    8역할 코어 로테이션 목표 비중 계산.

    1단계: VIX 국면으로 역할별 기본 비중 결정
    2단계: H15(냉각지수)로 역할별 ±20% tilt
    3단계: 합계 100% 정규화

    Returns
    -------
    df : 역할·목표비중·설명 등 포함 DataFrame
    phase : "fear" | "recovery" | "expansion" | "overheated"
    """
    phase = get_phase(vix, spy_1m, spy_12m)

    # H15 분위수 맵 (ticker → 전체 중 상위 비율 0~1)
    h15_pctile: dict[str, float] = {}
    if scored_df is not None and not scored_df.empty and "냉각지수" in scored_df.columns:
        _h = scored_df[["ticker", "냉각지수"]].dropna()
        all_vals = _h["냉각지수"].values
        for _, row in _h.iterrows():
            h15_pctile[str(row["ticker"])] = float((all_vals < row["냉각지수"]).mean())

    rows = []
    for role in CORE_ROLES:
        base_w = role["weights"][phase]

        # H15 tilt: 역할 대표 ETF (US + KR 중 있는 것의 평균)
        tickers = [role["us"]] + ([role["kr"]] if role["kr"] else [])
        pctiles  = [h15_pctile[t] for t in tickers if t in h15_pctile]
        if pctiles:
            avg_pctile = sum(pctiles) / len(pctiles)
            # 상위 33%: ×1.2 / 하위 33%: ×0.8 / 중간: ×1.0
            tilt = 0.8 + 0.4 * avg_pctile
        else:
            tilt = 1.0

        rows.append({
            "역할":      role["role"],
            "US ETF":   role["us"],
            "ISA ETF":  role["kr"] or "—",
            "설명":      role["desc"],
            "_base_w":  base_w,
            "_tilt":    tilt,
            "_raw_w":   base_w * tilt,
        })

    total = sum(r["_raw_w"] for r in rows)
    for r in rows:
        r["목표비중(%)"] = round(r["_raw_w"] / total * 100, 1)
        r["기본비중(%)"] = round(r["_base_w"] * 100, 1)

    df = pd.DataFrame(rows).drop(columns=["_base_w", "_tilt", "_raw_w"])
    return df, phase
