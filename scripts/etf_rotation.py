"""
코어 ETF 로테이션 — 7역할 사이클 기반 배분.

개선사항:
  1. 국면 판단 통일: market_regime() key를 1차로 사용, VIX는 보조
  2. 연성 국면 전환: VIX ±2 버퍼존에서 인접 국면 가중 혼합
     → VIX 25±2 구간에서 fear↔recovery 블렌딩, 절벽 제거

guide=True  : ISA 계좌 매수 가능 → 리밸런싱 가이드 제공
guide=False : ISA 불가(세금 이슈) → 테이블 표시만, 가이드 제외
"""
from __future__ import annotations
import pandas as pd

# ── 7역할 코어 정의 ─────────────────────────────────────────────────────────
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
        "kr":      "466950.KS",
        "kr_name": "TIGER 글로벌AI액티브 ★사용자편입",
        # 원래 추천: KODEX 미국AI테크TOP10 (469170.KS) — 추세 확인 후 복귀 가능
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

# ── market_regime() key → 로테이션 국면 매핑 ────────────────────────────────
# market_regime 5단계와 rotation 4단계를 일치시켜 두 시스템 통일
_REGIME_TO_PHASE: dict[str, str] = {
    "fear":       "fear",       # VIX>30 + 시장 하락 → 공포
    "bear":       "recovery",   # risk-off이지만 패닉 수준 아님 → 회복 방어 배분
    "mixed":      "expansion",  # 방향성 불명확 → 중립(확장) 유지
    "bull":       "expansion",  # risk-on → 확장 배분
    "complacent": "overheated", # VIX<13 저공포 → 과열 경계
}


def _phase_blend(vix: float) -> dict[str, float]:
    """
    VIX 기반 연성 국면 혼합 비율 (각 임계치 ±2 VIX 버퍼).

    예시:
      VIX 27 → fear 100%
      VIX 26 → fear 75%  + recovery 25%
      VIX 25 → fear 50%  + recovery 50%
      VIX 23 → fear 0%   + recovery 100%
      VIX 21 → recovery 75% + expansion 25%

    버퍼 없이 VIX 25.1 vs 24.9로 배분이 급변하는 절벽 제거.
    """
    TRANSITIONS = [
        (25, "fear",      "recovery"),
        (20, "recovery",  "expansion"),
        (13, "expansion", "overheated"),
    ]
    B = 2.0
    for thresh, upper, lower in TRANSITIONS:
        lo, hi = thresh - B, thresh + B
        if vix > hi:
            continue
        if vix >= lo:
            alpha = (vix - lo) / (2 * B)
            return {upper: alpha, lower: 1 - alpha}
    # 순수 구간 (버퍼 밖)
    if vix >= 25: return {"fear": 1.0}
    if vix >= 20: return {"recovery": 1.0}
    if vix >= 13: return {"expansion": 1.0}
    return {"overheated": 1.0}


def get_phase(
    vix: float,
    spy_1m: float = 0,
    spy_12m: float = 0,
    regime_key: str | None = None,
) -> str:
    """
    국면 판단 — regime_key 우선, VIX fallback.

    regime_key가 있으면 market_regime() 결과를 신뢰하고 그에 맞는 국면 반환.
    없으면 기존 VIX + 모멘텀 로직 사용.
    """
    if regime_key and regime_key in _REGIME_TO_PHASE:
        return _REGIME_TO_PHASE[regime_key]
    if vix > 25: return "fear"
    if vix < 13: return "overheated"
    if vix >= 20 or spy_1m < -3: return "recovery"
    return "expansion"


def rotation_target(
    vix: float,
    spy_1m: float,
    spy_12m: float,
    scored_df: pd.DataFrame | None = None,
    regime_dict: dict | None = None,
) -> tuple[pd.DataFrame, str]:
    """
    7역할 코어 로테이션 목표 비중 계산.

    1단계: regime_dict.key → 주 국면 레이블 결정 (시스템 통일)
    2단계: VIX 연성 블렌딩 → 국면 경계 완충 (절벽 제거)
    3단계: H15(냉각지수) ±20% tilt
    4단계: 전체·가이드 정규화
    """
    regime_key = (regime_dict or {}).get("key")
    tlt_1m     = float((regime_dict or {}).get("tlt_1m") or 0)
    if regime_dict and regime_dict.get("vix") is not None:
        vix = float(regime_dict["vix"])

    phase = get_phase(vix, spy_1m, spy_12m, regime_key=regime_key)
    blend = _phase_blend(vix)

    h15_pctile: dict[str, float] = {}
    if scored_df is not None and not scored_df.empty and "냉각지수" in scored_df.columns:
        _h = scored_df[["ticker", "냉각지수"]].dropna()
        all_vals = _h["냉각지수"].values
        for _, row in _h.iterrows():
            h15_pctile[str(row["ticker"])] = float((all_vals < row["냉각지수"]).mean())

    # 금리 급등 보정 계수 (TLT 1M -3% 이하 시 작동)
    rate_sev = min(max((-tlt_1m - 3) / 7, 0.0), 1.0) if tlt_1m < -3 else 0.0

    rows = []
    for role in CORE_ROLES:
        base_w = sum(w * role["weights"].get(p, 0) for p, w in blend.items())

        # 금리 급등 시 TLT 최대 40% 감소 / GLD 최대 50% 증가
        if rate_sev > 0:
            if role["us"] == "TLT":
                base_w *= (1 - 0.40 * rate_sev)
            elif role["us"] == "GLD":
                base_w *= (1 + 0.50 * rate_sev)

        tickers = [role["us"]] + ([role["kr"]] if role["kr"] else [])
        pctiles = [h15_pctile[t] for t in tickers if t in h15_pctile]
        tilt = (0.8 + 0.4 * (sum(pctiles) / len(pctiles))) if pctiles else 1.0

        has_isa = role["kr"] is not None
        rows.append({
            "역할":        role["role"],
            "US ETF":     role["us"],
            "ISA(원화)":  f"{role['kr_name']}\n({role['kr']})" if has_isa else "—",
            "계좌":        "✅ ISA 우선" if has_isa else "⚠️ 일반계좌",
            "설명":        role["desc"],
            "가이드":      role["guide"],
            "_base_w":    base_w,
            "_raw_w":     base_w * tilt,
        })

    total_all   = sum(r["_raw_w"] for r in rows)
    total_guide = sum(r["_raw_w"] for r in rows if r["가이드"])

    for r in rows:
        r["목표비중(%)"]   = round(r["_raw_w"] / total_all   * 100, 1)
        r["기본비중(%)"]   = round(r["_base_w"]              * 100, 1)
        r["가이드비중(%)"] = round(r["_raw_w"] / total_guide * 100, 1) if r["가이드"] else None

    df = pd.DataFrame(rows).drop(columns=["_base_w", "_raw_w"])
    return df, phase
