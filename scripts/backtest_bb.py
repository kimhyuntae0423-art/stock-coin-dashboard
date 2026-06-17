"""볼린저 밴드 신호 백테스트 — 알트코인 / BTC

테스트 신호:
  1. %B 위치 구간별 30/90/180일 수익률
  2. 밴드폭(Bandwidth) 스퀴즈 이후 방향성
  3. %B + RSI 조합
  4. %B + 추세(bull/bear) 조합
  5. σ 배수(1.5 / 2.0 / 2.5)별 하단 이탈 신호 비교

Usage:
    python scripts/backtest_bb.py
"""
import pandas as pd
import numpy as np
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
RESULTS = ROOT / "results"
TICKERS = ["ETC-USD", "ENS-USD", "BTC-USD"]
BB_WINDOW = 20


def load(ticker: str) -> pd.DataFrame:
    path = RESULTS / f"coin_{ticker}_signals.csv"
    df = pd.read_csv(path, parse_dates=["Date"])
    df = df.sort_values("Date").reset_index(drop=True)
    for col in ["Close", "High", "Low", "rsi14"]:
        df[col] = pd.to_numeric(df.get(col), errors="coerce")
    return df


def add_bb(df: pd.DataFrame) -> pd.DataFrame:
    df = df.copy()
    df["bb_mid"] = df["Close"].rolling(BB_WINDOW).mean()
    df["bb_std"] = df["Close"].rolling(BB_WINDOW).std()

    # sigma별 밴드 계산
    for sig in [1.5, 2.0, 2.5]:
        key = str(sig).replace(".", "")
        df[f"bb_upper_{key}"] = df["bb_mid"] + sig * df["bb_std"]
        df[f"bb_lower_{key}"] = df["bb_mid"] - sig * df["bb_std"]

    # %B (2σ 기준)
    band_range = df["bb_upper_20"] - df["bb_lower_20"]
    df["pct_b"] = (df["Close"] - df["bb_lower_20"]) / band_range.replace(0, np.nan)

    # 밴드폭(변동성 척도)
    df["bw"] = band_range / df["bb_mid"]

    # 미래 수익률
    for days in [30, 90, 180]:
        df[f"fwd_{days}d"] = (df["Close"].shift(-days) / df["Close"] - 1) * 100

    # 추세
    df["trend"] = df["state"].fillna("bear")
    return df


def s(series: pd.Series, label: str = "") -> str:
    v = series.dropna()
    if len(v) < 8:
        return f"n={len(v)} (부족)"
    pos = (v > 0).mean() * 100
    prefix = f"{label:<28}" if label else ""
    return (
        f"{prefix}평균 {v.mean():+6.1f}%  중간값 {v.median():+6.1f}%"
        f"  승률 {pos:.0f}%  n={len(v)}"
    )


def run(ticker: str):
    df = load(ticker)
    df = add_bb(df)

    print(f"\n{'='*65}")
    print(f"  {ticker}  ({df['Date'].min().date()} ~ {df['Date'].max().date()})")
    print(f"{'='*65}")

    # ── 1. %B 위치 구간 -> 90일 수익률 ──────────────────────────
    print("\n[1] %B 위치 -> 90일 수익률 (BB 2sigma 기준)")
    print("    %B < 0   : 하단 이탈 (극과매도)")
    print("    %B 0~0.2 : 하단 근접")
    print("    %B 0.2~0.5: 하단 중립")
    print("    %B 0.5~0.8: 상단 중립")
    print("    %B 0.8~1  : 상단 근접")
    print("    %B > 1    : 상단 이탈 (극과매수)")
    bins = [
        ("<0 하단이탈",   df["pct_b"] < 0),
        ("0~0.2 하단근접", df["pct_b"].between(0, 0.2)),
        ("0.2~0.5 하단중립", df["pct_b"].between(0.2, 0.5)),
        ("0.5~0.8 상단중립", df["pct_b"].between(0.5, 0.8)),
        ("0.8~1 상단근접", df["pct_b"].between(0.8, 1.0)),
        (">1 상단이탈",   df["pct_b"] > 1.0),
    ]
    for label, mask in bins:
        print(f"  {s(df.loc[mask, 'fwd_90d'], label)}")

    # ── 2. 밴드폭 스퀴즈 이후 방향성 ───────────────────────────
    print("\n[2] 밴드폭 스퀴즈(하위 20%) 이후 수익률")
    print("    스퀴즈 = 변동성 수축 -> 폭발 전조 신호")
    bw_threshold = df["bw"].quantile(0.20)
    squeeze = df["bw"] <= bw_threshold
    not_squeeze = df["bw"] > bw_threshold
    for days in [30, 90]:
        print(f"  {s(df.loc[squeeze, f'fwd_{days}d'], f'스퀴즈 {days}일 후')}")
        print(f"  {s(df.loc[not_squeeze, f'fwd_{days}d'], f'비스퀴즈 {days}일 후')}")

    # 스퀴즈 직후 %B 방향으로 조건 분기
    print("  스퀴즈 후 %B 방향 분기 (30일):")
    sq_up = squeeze & (df["pct_b"] > 0.5)
    sq_dn = squeeze & (df["pct_b"] <= 0.5)
    print(f"    {s(df.loc[sq_up, 'fwd_30d'], '스퀴즈+%B위(>0.5)')}")
    print(f"    {s(df.loc[sq_dn, 'fwd_30d'], '스퀴즈+%B아래(<=0.5)')}")

    # ── 3. %B + RSI 조합 ─────────────────────────────────────────
    print("\n[3] %B + RSI 조합 -> 90일 수익률")
    combos = [
        ("%B<0 + RSI<30 강과매도",   (df["pct_b"] < 0) & (df["rsi14"] < 30)),
        ("%B<0.2 + RSI<40 과매도",   (df["pct_b"] < 0.2) & (df["rsi14"] < 40)),
        ("%B<0.2 + RSI 40-60 중립",  (df["pct_b"] < 0.2) & df["rsi14"].between(40, 60)),
        ("%B>0.8 + RSI>60 과매수",   (df["pct_b"] > 0.8) & (df["rsi14"] > 60)),
        ("%B>1 + RSI>70 강과매수",   (df["pct_b"] > 1.0) & (df["rsi14"] > 70)),
    ]
    for label, mask in combos:
        print(f"  {s(df.loc[mask, 'fwd_90d'], label)}")

    # ── 4. %B + 추세 조합 ────────────────────────────────────────
    print("\n[4] %B + 추세(bull/bear) -> 90일 수익률")
    combos4 = [
        ("%B<0.2 + bear(하락추세)",  (df["pct_b"] < 0.2) & (df["trend"] == "bear")),
        ("%B<0.2 + bull(상승추세)",  (df["pct_b"] < 0.2) & (df["trend"] == "bull")),
        ("%B>0.8 + bull(상승추세)",  (df["pct_b"] > 0.8) & (df["trend"] == "bull")),
        ("%B>0.8 + bear(하락추세)",  (df["pct_b"] > 0.8) & (df["trend"] == "bear")),
    ]
    for label, mask in combos4:
        print(f"  {s(df.loc[mask, 'fwd_90d'], label)}")

    # ── 5. σ 배수별 하단 이탈 신호 비교 ─────────────────────────
    print("\n[5] sigma 배수별 하단 이탈 -> 90일 수익률")
    print("    (sigma 작을수록 이탈 빈번, 클수록 희귀하지만 강한 신호)")
    for sig, key in [(1.5, "15"), (2.0, "20"), (2.5, "25")]:
        below = df["Close"] < df[f"bb_lower_{key}"]
        inside = (df["Close"] >= df[f"bb_lower_{key}"]) & (df["Close"] <= df[f"bb_upper_{key}"])
        above = df["Close"] > df[f"bb_upper_{key}"]
        print(f"  {sig}sigma 하단이탈: {s(df.loc[below, 'fwd_90d'], f'{sig}s 하단이탈')}")
        print(f"  {sig}sigma 상단이탈: {s(df.loc[above, 'fwd_90d'], f'{sig}s 상단이탈')}")

    # ── 6. 밴드워크(연속 하단 이탈) ─────────────────────────────
    print("\n[6] 밴드워크 — 연속 N일 하단 이탈 -> 이후 30일")
    print("    밴드워크 = 추세적 하락 vs 반등 신호 구분 핵심")
    below_band = (df["Close"] < df["bb_lower_20"]).astype(int)
    df["consec_below"] = below_band.groupby(
        (below_band != below_band.shift()).cumsum()
    ).cumcount() + 1
    df["consec_below"] = df["consec_below"] * below_band  # 이탈 아닐 때 0

    for n in [1, 3, 5]:
        mask = df["consec_below"] == n
        print(f"  {s(df.loc[mask, 'fwd_30d'], f'{n}일째 이탈중')}")

    print()


def summary():
    print("\n" + "=" * 65)
    print("  해석 가이드 — 볼린저 밴드 신호 설계 참고")
    print("=" * 65)
    guide = """
핵심 개념 정리:
  %B < 0   : 2sigma 하단 이탈 -> 평균회귀 vs 추세 하락 판단 필요
  %B > 1   : 2sigma 상단 이탈 -> 과매수 or 모멘텀 (BTC는 모멘텀 경향)
  스퀴즈   : 밴드폭 수축 -> 방향 예측 불가, 변동성 폭발 전조
  밴드워크 : 연속 N일 밴드 이탈 -> 추세 강도 확인

알트 vs BTC 차이:
  알트    : 하단 이탈 후 평균회귀 경향 강함 (RSI<30 조합 유효)
  BTC     : 상단 이탈도 90일 후 양수 (모멘텀 지속 경향)

실무 활용 기준:
  - 90일 승률 65%+ + 평균 +15%+ -> 신호로 사용 검토
  - n < 20 -> 신뢰도 부족, 참고만
"""
    print(guide)


if __name__ == "__main__":
    for t in TICKERS:
        try:
            run(t)
        except FileNotFoundError:
            print(f"\n{t}: 파일 없음 -- 스킵")
    summary()
