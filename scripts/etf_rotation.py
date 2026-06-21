"""
코어 ETF 로테이션 — 7역할 사이클 기반 배분.

경기 국면(VIX + 시장 모멘텀)으로 역할별 비중을 결정하고,
H15(상대적 저점)으로 미세 조정한다.

guide=True  : ISA 계좌 매수 가능 → 리밸런싱 가이드 제공
guide=False : ISA 불가(세금 이슈) → 테이블 표시만, 가이드 제외
"""
from __future__ import annotations
import pandas as pd

# ── 7역할 코어 정의 (SHY 제거 — 현금은 외부 CMA/파킹으로 관리) ─────────────
CORE_ROLES = [
    {
        "role":    "미국 주식",
        "us":      "VOO",
        "kr":      "360750.KS",
        "kr_name": "TIGER 미국S&P500",
        "desc":    "S&P500 지수 추종. 경기 회복~확장기 핵심.",
        "guide":   True,
        "weights": {"fear": 0.20, "recovery": 0.35, "expansion": 0.42, "overheated": 0.32},
    },
    {
        "role":    "배당/가치",
        "us":      "SCHD",
        "kr":      "314250.KS",
        "kr_name": "KODEX 미국배당귀족",
        "desc":    "고배당 우량주. 확장 후반~침체 전환기 방어.",
        "guide":   True,
        "weights": {"fear": 0.17, "recovery": 0.09, "expansion": 0.11, "overheated": 0.23},
    },
    {
        "role":    "성장/반도체",
        "us":      "SOXX",
        "kr":      "469170.KS",
        "kr_name": "KODEX 미국AI테크TOP10",
        "desc":    "반도체·AI 성장. 회복 초기~확장 중기 집중.",
        "guide":   True,
        "weights": {"fear": 0.04, "recovery": 0.15, "expansion": 0.17, "overheated": 0.09},
    },
    {
        "role":    "장기 국채",
        "us":      "TLT",
        "kr":      "476760.KS",
        "kr_name": "ACE 미국30년국채액티브",
        "desc":    "미국 20년 국채. 공포·금리 하락기 최고.",
        "guide":   True,
        "weights": {"fear": 0.28, "recovery": 0.16, "expansion": 0.07, "overheated": 0.17},
    },
    {
        "role":    "금",
        "us":      "GLD",
        "kr":      "0072R0.KS",
        "kr_name": "TIGER KRX금현물",
        "desc":    "금 현물. 인플레·지정학·공포 헷지.",
        "guide":   True,
        "weights": {"fear": 0.18, "recovery": 0.11, "expansion": 0.07, "overheated": 0.13},
    },
    {
        "role":    "원자재/구리",
        "us":      "COPX",
        "kr":      None,
        "kr_name": None,
        "desc":    "구리 채굴. 경기 확장 중기, 인프라·EV 수요. ISA 불가(세금 22%).",
        "guide":   False,
        "weights": {"fear": 0.05, "recovery": 0.09, "expansion": 0.10, "overheated": 0.03},
    },
    {
        "role":    "헬스케어/방어",
        "us":      "XLV",
        "kr":      None,
        "kr_name": None,
        "desc":    "미국 헬스케어. 사이클 무관 방어. 침체 전환기. ISA 불가(세금 22%).",
        "guide":   False,
        "weights": {"fear": 0.08, "recovery": 0.05, "expansion": 0.06, "overheated": 0.03},
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
    "overheated": "VIX<13 — 방어·배당 강화. 현금(CMA/파킹)으로 다음 조정 대비.",
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
    7역할 코어 로테이션 목표 비중 계산.

    1단계: VIX 국면으로 역할별 기본 비중 결정
    2단계: H15(냉각지수)로 역할별 ±20% tilt
    3단계: 전체 합계 100% 정규화 (display용)
    4단계: guide=True 역할만 별도 100% 정규화 (가이드/금액배분용)

    Returns
    -------
    df : 역할·목표비중·가이드비중·설명 등 포함 DataFrame
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
        pctiles = [h15_pctile[t] for t in tickers if t in h15_pctile]
        tilt = (0.8 + 0.4 * (sum(pctiles) / len(pctiles))) if pctiles else 1.0

        has_isa = role["kr"] is not None
        rows.append({
            "역할":       role["role"],
            "US ETF":    role["us"],
            "ISA(원화)": f"{role['kr_name']}\n({role['kr']})" if has_isa else "—",
            "계좌":       "✅ ISA 우선" if has_isa else "⚠️ 일반계좌",
            "설명":       role["desc"],
            "가이드":     role["guide"],
            "_base_w":   base_w,
            "_raw_w":    base_w * tilt,
        })

    # 전체 정규화 (테이블 표시용 목표비중)
    total_all = sum(r["_raw_w"] for r in rows)
    # guide=True만 정규화 (리밸런싱 가이드·금액배분용)
    total_guide = sum(r["_raw_w"] for r in rows if r["가이드"])

    for r in rows:
        r["목표비중(%)"]  = round(r["_raw_w"] / total_all * 100, 1)
        r["기본비중(%)"]  = round(r["_base_w"] * 100, 1)
        r["가이드비중(%)"] = round(r["_raw_w"] / total_guide * 100, 1) if r["가이드"] else None

    df = pd.DataFrame(rows).drop(columns=["_base_w", "_raw_w"])
    return df, phase
