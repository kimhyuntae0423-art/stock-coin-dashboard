"""시장 국면 + 섹터 사이클 반영 코어 ETF 추천 — etf_page.py · rebalancing_page.py 공유 모듈."""
import pandas as pd
from pathlib import Path


def volume_signals(ticker: str, results_dir) -> dict:
    """개별 종목 거래량 기반 선행 지표 계산.

    Returns dict:
        vol_ratio    : 최근5일 평균거래량 / 20일 평균거래량 (>1.3 = 급증)
        obv_slope    : OBV 10일 변화율 % (양수=매집, 음수=분배)
        macd_dir     : 'up' | 'down' (MACD 히스토그램 방향)
        pv_signal    : 가격-거래량 다이버전스 요약 문자열
        vol_label    : 종합 거래량 신호 이모지+문자
    """
    results_dir = Path(results_dir)
    f = results_dir / f"{ticker}_signals.csv"
    if not f.exists():
        return {}
    try:
        df = pd.read_csv(f)
    except Exception:
        return {}
    if len(df) < 25 or "Volume" not in df.columns:
        return {}

    # 거래량 비율
    vol5  = df["Volume"].tail(5).mean()
    vol20 = df["Volume"].tail(20).mean()
    vol_ratio = round(vol5 / vol20, 2) if vol20 > 0 else 1.0

    # OBV 기울기 (10일 변화율)
    obv = df["obv"].tail(10)
    obv_base = abs(obv.iloc[0])
    obv_slope = round((obv.iloc[-1] - obv.iloc[0]) / obv_base * 100, 1) if obv_base > 0 else 0.0

    # MACD 히스토그램 방향 (최근 3일 증가/감소)
    mh = df["macd_hist"].tail(3)
    macd_dir = "up" if mh.iloc[-1] > mh.iloc[0] else "down"

    # 가격-거래량 다이버전스
    price_up = df["Close"].tail(5).iloc[-1] > df["Close"].tail(5).iloc[0]
    if price_up and vol_ratio >= 1.1:
        pv = "강세확인 (가격↑·거래량↑)"
    elif price_up and vol_ratio < 0.9:
        pv = "약세다이버전스 (가격↑·거래량↓)"
    elif not price_up and vol_ratio >= 1.1:
        pv = "분배신호 (가격↓·거래량↑)"
    else:
        pv = "추세소멸 (가격↓·거래량↓)"

    # 종합 라벨
    if vol_ratio >= 1.4 and obv_slope > 0 and macd_dir == "up":
        label = "🔥 매집 급증"
    elif vol_ratio >= 1.2 and obv_slope > 0:
        label = "📈 거래량 확대"
    elif vol_ratio < 0.8 and obv_slope < 0:
        label = "❄️ 거래량 위축"
    elif "약세다이버전스" in pv or "분배신호" in pv:
        label = "⚠️ 가격↑·거래량↓"
    else:
        label = "➡️ 보통"

    return {
        "vol_ratio": vol_ratio,
        "obv_slope": obv_slope,
        "macd_dir":  macd_dir,
        "pv_signal": pv,
        "vol_label": label,
    }


def technical_signals(ticker: str, results_dir) -> dict:
    """MA 정렬·BB위치·RSI추세 기반 기술적 선행 지표.

    Returns dict:
        ma_score   : 0~3  (ma20>ma50>ma200 정렬 점수)
        bb_pct     : 0~1  (볼린저 밴드 위치, 0=하단, 1=상단)
        bb_trend   : 'up'|'flat'|'down'  (최근 5일 bb_pct 방향)
        rsi_slope  : RSI 10일 변화율 (%p/일)
        tech_label : 종합 기술 신호 이모지
        tech_score : -1.0 ~ +1.0  (score_etfs 보정에 사용)
    """
    results_dir = Path(results_dir)
    f = results_dir / f"{ticker}_signals.csv"
    if not f.exists():
        return {}
    try:
        df = pd.read_csv(f)
    except Exception:
        return {}
    if len(df) < 25:
        return {}

    last = df.iloc[-1]
    # MA 정렬 (0~3)
    ma_score = int(last["Close"] > last["ma20"]) + \
               int(last["ma20"]  > last["ma50"]) + \
               int(last["ma50"]  > last["ma200"])

    # 볼린저 밴드 위치 및 추세
    bb = float(last.get("bb_pct", 0.5))
    bb5 = df["bb_pct"].tail(5)
    bb_trend = "up" if bb5.iloc[-1] > bb5.iloc[0] + 0.05 else \
               ("down" if bb5.iloc[-1] < bb5.iloc[0] - 0.05 else "flat")

    # RSI 추세 (10일 기울기)
    rsi10 = df["rsi14"].tail(10)
    rsi_slope = round((rsi10.iloc[-1] - rsi10.iloc[0]) / 10, 2)

    # 기술 점수 (-1 ~ +1)
    score = (ma_score / 3 - 0.5) * 0.6          # MA 기여: -0.3 ~ +0.3
    score += (bb - 0.5) * 0.2                    # BB 기여: -0.1 ~ +0.1
    score += max(-0.1, min(0.1, rsi_slope / 10)) # RSI slope 기여
    score = max(-1.0, min(1.0, score))

    # 라벨
    if ma_score == 3 and rsi_slope > 0:
        label = "🟢 기술 강세"
    elif ma_score >= 2 and bb > 0.5:
        label = "📈 기술 양호"
    elif ma_score <= 1 or rsi_slope < -0.5:
        label = "🔴 기술 약세"
    else:
        label = "➡️ 기술 중립"

    return {
        "ma_score":  ma_score,
        "bb_pct":    round(bb, 2),
        "bb_trend":  bb_trend,
        "rsi_slope": rsi_slope,
        "tech_label": label,
        "tech_score": round(score, 3),
    }


def macro_signals(summary_df: pd.DataFrame) -> dict:
    """매크로 선행 지표 계산 — 기존 ETF 데이터로 추정.

    구리/금 비율  : 경기 선행 (구리↑/금↑ = 성장 기대)
    TLT vs SHY   : 수익률 곡선 대리 (장기채>단기채 = 안전자산 선호)
    VIX 레벨     : 공포 지수 (>25 = 매수 기회, <15 = 과열 경계)
    HYG/LQD 대리 : 신용 위험 (COPX vs BND로 대체)

    Returns dict with regime_tilt adjustments per bucket.
    """
    if summary_df.empty:
        return {}

    latest = summary_df.sort_values("date").groupby("ticker").last().reset_index()
    latest["ticker"] = latest["ticker"].astype(str).str.upper()

    def _r(t, col="return_1m_pct"):
        r = latest[latest["ticker"] == t]
        return float(r[col].values[0]) if not r.empty and col in r.columns else None

    out = {}

    # 구리/금 비율 → 경기 선행 (COPX 1M - GLD 1M)
    copx = _r("COPX"); gld = _r("GLD")
    if copx is not None and gld is not None:
        cu_au = round(copx - gld, 2)
        out["구리금비율"] = cu_au
        out["경기신호"]  = ("📈 성장 기대" if cu_au > 2 else
                           ("📉 위험회피" if cu_au < -2 else "➡️ 중립"))

    # 수익률 곡선 (TLT 1M vs SHY 1M) — 장기채가 더 오르면 안전자산 선호
    tlt = _r("TLT"); shy = _r("SHY")
    if tlt is not None and shy is not None:
        curve = round(tlt - shy, 2)
        out["수익률곡선"] = curve
        out["곡선신호"]  = ("⚠️ 안전자산선호" if curve > 2 else
                           ("✅ 위험자산선호" if curve < -2 else "➡️ 중립"))

    # VIX (^VIX가 summary에 있으면 사용)
    vix_row = latest[latest["ticker"].isin(["^VIX", "VIX"])]
    if not vix_row.empty:
        vix = float(vix_row["close"].values[0])
        out["VIX"] = round(vix, 1)
        out["공포신호"] = ("🔥 공포 극단(매수기회)" if vix > 30 else
                          ("⚠️ 변동성 상승"        if vix > 20 else
                          ("✅ 안정"               if vix > 12 else
                           "🌡️ 과열 경계")))

    # 달러 강도 (DXJ 1M > VEU 1M → 달러 강세 가능성 높음)
    dxj = _r("DXJ"); veu = _r("VEU")
    if dxj is not None and veu is not None:
        out["달러강도"] = ("강달러 추정" if dxj > veu + 2 else
                          ("약달러 추정" if dxj < veu - 2 else "중립"))

    return out


def enrich_with_volume(df: pd.DataFrame, results_dir) -> pd.DataFrame:
    """score_etfs 결과에 거래량·기술 지표 추가 + 검증 기반 점수 보정.

    백테스트 검증 결과 (signal_validation.csv) 적용:
      MA정렬·BB위치·RSI기울기 IC < 0  → 과열 경보, 점수 감점
      거래량비율 IC=+0.04 p=0.001     → 급증 시 점수 완화
      MACD IC≈0                       → 제거

    점수 보정 규칙:
      MA=3 + BB>0.85 (과열) → score × 0.88  (12% 감점)
      MA=3 + BB>0.85 + 거래량급증(>1.3) → score × 0.94  (6% 감점, 거래량이 완화)
      이 외 → 보정 없음
    """
    out = df.reset_index(drop=True).copy()
    vols  = [volume_signals(str(t), results_dir)    for t in out["ticker"]]
    techs = [technical_signals(str(t), results_dir) for t in out["ticker"]]

    out["거래량비율"]   = [v.get("vol_ratio")       for v in vols]
    out["OBV추세"]      = [v.get("obv_slope")       for v in vols]
    out["거래량신호"]   = [v.get("vol_label", "—")  for v in vols]
    out["PV다이버전스"] = [v.get("pv_signal", "—")  for v in vols]
    out["MA정렬"]       = [t.get("ma_score")         for t in techs]
    out["BB위치"]       = [t.get("bb_pct")           for t in techs]
    out["RSI기울기"]    = [t.get("rsi_slope")        for t in techs]

    def _overheat_label(t, v):
        ma  = t.get("ma_score", 0) or 0
        bb  = t.get("bb_pct",   0.5) or 0.5
        rsi = t.get("rsi_slope", 0) or 0
        vol = v.get("vol_ratio", 1.0) or 1.0
        if ma == 3 and bb > 0.85:
            return "⚠️ 과열" if vol < 1.3 else "🌡️ 과열+거래량"
        if ma >= 2 and bb > 0.7:
            return "🌡️ 상단 근접"
        if ma <= 1 or bb < 0.3:
            return "❄️ 하단 지지"
        return "➡️ 보통"

    def _score_adjust(base_score, t, v):
        """과열 시 감점, 거래량 급증 시 완화 (백테스트 검증 반영)."""
        if pd.isna(base_score):
            return base_score
        ma  = t.get("ma_score", 0) or 0
        bb  = t.get("bb_pct",   0.5) or 0.5
        vol = v.get("vol_ratio", 1.0) or 1.0
        if ma == 3 and bb > 0.85:
            factor = 0.94 if vol >= 1.3 else 0.88
            return round(float(base_score) * factor, 1)
        return base_score

    out["과열신호"] = [_overheat_label(t, v) for t, v in zip(techs, vols)]
    out["score"]    = [_score_adjust(s, t, v)
                       for s, t, v in zip(out["score"], techs, vols)]

    # H15 냉각지수 (검증됨: IC=0.087, p<0.001, Quantile Spread 1.79%p p=0.001)
    # = -(BB위치)*0.57 - (MA정렬/3)*0.43  → 높을수록 "덜 과열" = 향후 수익 좋은 경향
    def _cooling(t: dict) -> float | None:
        bb = t.get("bb_pct")
        ma = t.get("ma_score")
        if bb is None or ma is None:
            return None
        return round(-float(bb) * 0.57 - (float(ma) / 3.0) * 0.43, 3)

    out["냉각지수"] = [_cooling(t) for t in techs]

    # 냉각지수 → 순위 레이블 (1위가 가장 덜 과열)
    valid_cool = out["냉각지수"].dropna()
    if not valid_cool.empty:
        ranks = valid_cool.rank(ascending=False).astype(int)
        out["냉각순위"] = ranks.reindex(out.index)
    else:
        out["냉각순위"] = None

    return out

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
    """섹터 상대강도(1M, %p) → 사이클 배율.
    백테스트 결과(H12): IC=-0.023, p=0.34 — 예측력 없음.
    배율 범위를 ±25%→±5%로 축소. 참고 정보 역할만 유지.
    """
    if rel_1m >  6: return 1.05
    if rel_1m >  3: return 1.02
    if rel_1m > -3: return 1.00
    if rel_1m > -6: return 0.98
    return 0.95


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
    # 백테스트 검증 결과 반영 (signal_validation.csv)
    # VIX 역발상 IC=0.14 — 공포 극단일 때 공격 자산 부스트
    # 과열 경계일 때 공격 자산 감점
    "fear":        {"공격": 1.45, "핵심": 1.20, "대안": 0.95, "방어": 0.70},
    "bull":        {"공격": 1.30, "핵심": 1.10, "대안": 0.90, "방어": 0.70},
    "mixed":       {"공격": 1.00, "핵심": 1.00, "대안": 1.00, "방어": 1.00},
    "bear":        {"공격": 0.70, "핵심": 0.90, "대안": 1.20, "방어": 1.30},
    "complacent":  {"공격": 0.85, "핵심": 0.95, "대안": 1.05, "방어": 1.15},
}


def market_regime(summary_df: pd.DataFrame) -> dict:
    """summary_signals DataFrame → 시장 국면 반환.

    국면 5단계 (백테스트 검증 기반):
      fear       : VIX>30 + 시장 하락 → 역발상 매수 타이밍 (IC=0.14 검증)
      bull       : 브레드스 높음 + SPY 상승 + 채권 약세
      mixed      : 방향성 불명확
      bear       : 브레드스 낮음 or 급락 + 채권 강세
      complacent : VIX<15 + 브레드스 매우 높음 → 과열 경계
    """
    if summary_df.empty:
        return dict(label="🔘 데이터 없음", key="mixed", desc="",
                    breadth=0, spy_1m=0, spy_12m=0, tlt_1m=0, bond_winning=False,
                    vix=None, vix_signal="—")

    latest = summary_df.sort_values("date").groupby("ticker").last().reset_index()
    breadth = (latest["state"] == "bull").mean() * 100

    def _get(t, col):
        r = latest[latest["ticker"] == t]
        return float(r[col].values[0]) if not r.empty and col in r.columns else 0.0

    spy_1m       = _get("SPY", "return_1m_pct")
    spy_12m      = _get("SPY", "return_12m_pct")
    tlt_1m       = _get("TLT", "return_1m_pct")
    bond_winning = tlt_1m > spy_1m

    # VIX (^VIX가 summary에 있으면 사용)
    vix_row = latest[latest["ticker"].astype(str).str.upper() == "^VIX"]
    vix = float(vix_row["close"].values[0]) if not vix_row.empty else None
    if vix and vix > 30:
        vix_signal = "🔥 공포 극단 — 역발상 매수 타이밍"
    elif vix and vix > 20:
        vix_signal = "⚠️ 변동성 상승"
    elif vix and vix < 13:
        vix_signal = "🌡️ 과열 경계 — 신규 매수 신중"
    else:
        vix_signal = "✅ 안정"

    # 국면 판정 — VIX 우선
    if vix and vix > 30 and spy_1m < 0:
        label = "🔥 공포 극단 (역발상 매수)"
        key   = "fear"
        desc  = f"VIX {vix:.0f} 공포 극단 · SPY 1M {spy_1m:+.1f}% · 역발상 매수 타이밍 (IC검증)"
    elif vix and vix < 13 and breadth >= 65:
        label = "🌡️ 과열 경계"
        key   = "complacent"
        desc  = f"VIX {vix:.0f} 저공포 · 브레드스 {breadth:.0f}% — 신규 매수 신중"
    elif breadth >= 55 and spy_1m >= 0 and not bond_winning:
        label = "🟢 강세 (Risk-On)"
        key   = "bull"
        desc  = f"브레드스 {breadth:.0f}% · SPY 1M {spy_1m:+.1f}% · 주식 > 채권"
    elif breadth <= 40 or spy_1m <= -5 or (bond_winning and spy_1m < 0):
        label = "🔴 약세 (Risk-Off)"
        key   = "bear"
        desc  = f"브레드스 {breadth:.0f}% · SPY 1M {spy_1m:+.1f}% · {'채권 > 주식' if bond_winning else '낙폭 과대'}"
    else:
        label = "🟡 혼조"
        key   = "mixed"
        desc  = f"브레드스 {breadth:.0f}% · SPY 1M {spy_1m:+.1f}% · 방향성 불명확"

    return dict(label=label, key=key, desc=desc,
                breadth=breadth, spy_1m=spy_1m, spy_12m=spy_12m,
                tlt_1m=tlt_1m, bond_winning=bond_winning,
                vix=vix, vix_signal=vix_signal)


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


def tactical_alloc(scored_df: pd.DataFrame, total_amount: float,
                   regime: dict = None) -> pd.DataFrame:
    """VIX 국면 기반 전술적 배분 계산.

    백테스트 검증 반영:
      VIX>25 → 공격/핵심 버킷 추가 오버웨이트 (역발상, IC=0.14 검증)
      VIX<13 → 공격 버킷 소폭 언더웨이트 (과열 경계)
      과열신호(⚠️) ETF → 전술비중 추가 감점
      섹터사이클(IC=-0.023, 예측력 없음)은 배분 계산에서 제외

    Returns scored_df에 추가 컬럼:
        기본비중, 전술비중, 기본배분, 전술배분, 배분차이, 전환신호
    """
    df = scored_df.dropna(subset=["close", "score"]).copy()
    if df.empty:
        return df

    vix = (regime or {}).get("vix")

    # VIX 기반 버킷 조정 배율
    if vix and vix > 25:
        vix_adj = {"공격": 1.30, "핵심": 1.15, "대안": 0.95, "방어": 0.75}
        vix_note = f"VIX {vix:.0f} 역발상 → 공격 오버웨이트"
    elif vix and vix < 13:
        vix_adj = {"공격": 0.85, "핵심": 0.95, "대안": 1.05, "방어": 1.10}
        vix_note = f"VIX {vix:.0f} 과열 경계 → 공격 언더웨이트"
    else:
        vix_adj = {"공격": 1.0, "핵심": 1.0, "대안": 1.0, "방어": 1.0}
        vix_note = None

    n = len(df)
    df["기본비중"] = 1 / n

    # 전술비중 = 기본비중 × VIX 버킷 배율 × 과열 감점 (섹터사이클은 예측력 없어 제외)
    def _tact_mult(row):
        bkt = str(row.get("버킷", "핵심"))
        vh  = vix_adj.get(bkt, 1.0)
        # 과열 신호 있으면 추가 언더웨이트
        overheat = str(row.get("과열신호", ""))
        oh = 0.90 if "⚠️ 과열" in overheat else 1.0
        return vh * oh

    raw = df.apply(_tact_mult, axis=1) * df["기본비중"]
    df["전술비중"] = raw / raw.sum()
    df["기본배분"] = (df["기본비중"] * total_amount).round(0)
    df["전술배분"] = (df["전술비중"] * total_amount).round(0)
    df["배분차이"] = df["전술배분"] - df["기본배분"]
    if vix_note:
        df["_vix_note"] = vix_note  # UI 표시용

    def _rotation_signal(row):
        r12  = row.get("return_12m_pct", 0) or 0
        r1   = row.get("return_1m_pct",  0) or 0
        rsi  = row.get("rsi14", 50) or 50
        over = str(row.get("과열신호", ""))
        # 사이클배율(IC=-0.023, 예측력 없음)은 사용하지 않음 — 과열신호(H10)·수익률만 근거로 사용
        if "⚠️ 과열" in over and r12 > 20 and r1 < 0:
            return "🚨 과열+전환 경고"
        if r12 > 20 and r1 < 0 and rsi < 50:
            return "⚠️ 전환 주의"
        if "⚠️ 과열" in over or "🌡️" in over:
            return "📉 모멘텀 둔화"
        if "❄️ 하단 지지" in over:
            return "🔥 반등 여력"
        return "✅ 중립"

    df["전환신호"] = df.apply(_rotation_signal, axis=1)
    return df


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

    # 백테스트 검증 결과 요약:
    #   H8  VIX 역발상    IC=+0.14  p<0.001  ✅ 강력 유효 → 점수의 유일한 드라이버
    #   H10 과열조합      IC=+0.028 p=0.023  ⚠️ 약하게 유효 → enrich_with_volume 감점으로 별도 반영
    #   H12 섹터사이클    IC=-0.023 p=0.34   ❌ 예측력 없음 → 점수 미반영, 표에는 참고용으로만 표시
    #   H13 Bull추세필터  IC=-0.047 p=0.010  ❌ 역방향(쓸수록 손해) → 점수·필터 어디에도 미사용
    #   H1  모멘텀        IC=+0.019 p=0.61   ❌ 예측력 없음 → 점수 미반영, mom_score는 표시만
    #
    # 점수 = 100(균등 기준) × VIX국면배율. 섹터사이클·모멘텀은 검증 실패로 점수에서 제외.
    w = _BUCKET_WEIGHT.get(regime_key, _BUCKET_WEIGHT["mixed"])
    valid["score"] = valid.apply(
        lambda r: 100 * w.get(r["버킷"], 1.0),
        axis=1,
    )

    result = merged.copy()
    result = result.merge(
        valid[["ticker", "버킷", "섹터사이클", "사이클배율", "mom_score", "score"]],
        on="ticker", how="left",
    )
    return result
