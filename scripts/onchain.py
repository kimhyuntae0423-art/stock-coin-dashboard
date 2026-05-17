"""
온체인 + 사이클 지표 — 가장 신뢰받는 비트코인 분석법들.

지표별 출처:
- MVRV Z-Score, NUPL, Puell Multiple: bitcoin-data.com 무료 API
- Pi Cycle Top: BTC 가격으로 직접 계산 (111-day SMA vs 350-day SMA × 2)
- Altcoin Season Index: 보유 코인들의 90일 BTC 대비 상대 수익률
"""
from urllib.request import Request, urlopen
from urllib.error import HTTPError
import json
import time
import pandas as pd


BASE = "https://bitcoin-data.com/api/v1"
HEADERS = {"User-Agent": "Mozilla/5.0", "Accept": "application/json"}


def _fetch(endpoint: str, retries: int = 4, backoffs=(5, 15, 30, 60)):
    last_err = None
    for i in range(retries):
        try:
            req = Request(f"{BASE}/{endpoint}", headers=HEADERS)
            with urlopen(req, timeout=15) as r:
                return json.loads(r.read())
        except HTTPError as e:
            last_err = e
            if e.code in (429, 503) and i < retries - 1:
                time.sleep(backoffs[i])
                continue
            raise
        except Exception as e:
            last_err = e
            if i < retries - 1:
                time.sleep(2.0)
                continue
            raise
    raise last_err


# ============= 1. MVRV Z-Score =============
def fetch_mvrv_zscore_latest() -> dict:
    try:
        d = _fetch("mvrv-zscore/last")
        return {"date": d["d"], "value": float(d["mvrvZscore"])}
    except Exception as e:
        return {"error": str(e)}


def fetch_mvrv_zscore_history() -> pd.DataFrame:
    try:
        data = _fetch("mvrv-zscore")
        df = pd.DataFrame(data)
        df["date"] = pd.to_datetime(df["d"])
        return df.set_index("date").sort_index()[["mvrvZscore"]].rename(
            columns={"mvrvZscore": "value"})
    except Exception:
        return pd.DataFrame(columns=["value"])


# ============= 2. NUPL =============
def fetch_nupl_latest() -> dict:
    try:
        d = _fetch("nupl/last")
        return {"date": d["d"], "value": float(d["nupl"])}
    except Exception as e:
        return {"error": str(e)}


# ============= 3. Puell Multiple =============
def fetch_puell_latest() -> dict:
    try:
        d = _fetch("puell-multiple/last")
        return {"date": d["d"], "value": float(d["puellMultiple"])}
    except Exception as e:
        return {"error": str(e)}


# ============= 4. Pi Cycle Top (computed) =============
def compute_pi_cycle(btc_df: pd.DataFrame) -> dict:
    """
    Pi Cycle Top Indicator:
      - 111-day SMA
      - 350-day SMA × 2
      - 111SMA가 350SMA×2를 상향돌파하면 사이클 천정 신호 (2013·2017·2021 천정 정확히 포착)
    """
    if btc_df.empty or len(btc_df) < 360:
        return {"error": "데이터 부족"}

    df = btc_df.copy()
    df.rename(columns=lambda c: c.capitalize(), inplace=True)
    df["sma111"] = df["Close"].rolling(111).mean()
    df["sma350x2"] = df["Close"].rolling(350).mean() * 2
    df["ratio"] = df["sma111"] / df["sma350x2"]
    last = df.iloc[-1]
    return {
        "date": last.name.strftime("%Y-%m-%d"),
        "sma111": float(last["sma111"]) if pd.notna(last["sma111"]) else None,
        "sma350x2": float(last["sma350x2"]) if pd.notna(last["sma350x2"]) else None,
        "ratio": float(last["ratio"]) if pd.notna(last["ratio"]) else None,
        "series": df[["sma111", "sma350x2"]],
    }


# ============= 5. Altcoin Season Index =============
def compute_altcoin_season(coin_returns: dict, btc_return: float) -> dict:
    """
    Altcoin Season Index = BTC 대비 90일 outperform한 알트 비율 × 100
    - 우리가 가진 14개 코인 기준이라 CoinMarketCap의 정식 지수와는 다를 수 있음
    - >= 75: 알트시즌
    - <= 25: 비트코인 시즌
    """
    if btc_return is None or len(coin_returns) <= 1:
        return {"error": "데이터 부족"}
    alts = {t: r for t, r in coin_returns.items() if t != "BTC-USD" and r is not None}
    if not alts:
        return {"error": "알트 데이터 없음"}
    outperforming = sum(1 for r in alts.values() if r > btc_return)
    score = round(100 * outperforming / len(alts), 1)
    if score >= 75:
        regime = "altcoin_season"
        label = "🟢 알트시즌 — 알트가 BTC를 광범위하게 능가"
    elif score <= 25:
        regime = "bitcoin_season"
        label = "🟠 비트코인 시즌 — 알트가 부진"
    else:
        regime = "transition"
        label = "🔵 전환 구간"
    return {
        "score": score,
        "regime": regime,
        "label": label,
        "btc_return_90d_pct": round(btc_return * 100, 2),
        "alt_returns": alts,
    }


# ============= 점수화 & 종합 신호 =============
def score_mvrv(z: float) -> int:
    if z is None or pd.isna(z): return 0
    if z < 0: return 2
    if z < 2: return 1
    if z < 5: return 0
    if z < 7: return -1
    return -2


def score_nupl(n: float) -> int:
    if n is None or pd.isna(n): return 0
    if n < 0: return 2          # 자본 항복
    if n < 0.25: return 1       # 희망/믿음
    if n < 0.5: return 0        # 낙관
    if n < 0.75: return -1      # 신뢰/탐욕
    return -2                   # 도취 — 천정


def score_puell(p: float) -> int:
    if p is None or pd.isna(p): return 0
    if p < 0.5: return 2        # 채굴자 항복 (역사적 바닥)
    if p < 1.0: return 1
    if p < 2.0: return 0
    if p < 4.0: return -1
    return -2                   # 채굴자 차익 실현 (천정)


def score_pi_cycle(ratio: float) -> int:
    """ratio = sma111 / sma350x2. 1에 가까울수록 천정 신호."""
    if ratio is None or pd.isna(ratio): return 0
    if ratio < 0.5: return 1
    if ratio < 0.9: return 0
    if ratio < 1.0: return -1
    return -2                   # 1 이상이면 천정 시그널 발동


def score_fng(score: float) -> int:
    """크립토 F&G. 공포일수록 매수, 탐욕일수록 매도."""
    if score is None or pd.isna(score): return 0
    if score < 25: return 2
    if score < 45: return 1
    if score < 55: return 0
    if score < 75: return -1
    return -2


def classify_regime(z_score: float) -> dict:
    """기존 호환용 — MVRV Z-Score 단독 분류."""
    if z_score is None or pd.isna(z_score):
        return {"regime": "unknown", "label": "데이터 없음", "color": "#888"}
    if z_score < 0:
        return {"regime": "deep_value", "label": "🔥 자본 항복 (역사적 바닥)", "color": "#16a085"}
    if z_score < 2:
        return {"regime": "accumulation", "label": "🟢 누적 구간 (싸다)", "color": "#27ae60"}
    if z_score < 5:
        return {"regime": "bull", "label": "🔵 강세장 진행 중", "color": "#2980b9"}
    if z_score < 7:
        return {"regime": "late_bull", "label": "🟠 후기 강세 (주의)", "color": "#e67e22"}
    return {"regime": "top", "label": "🔴 역사적 천정 (강한 매도)", "color": "#c0392b"}


def composite_score(scores: dict) -> dict:
    """
    각 지표 점수(-2~+2)의 평균. 누락 지표는 제외.
    반환: avg score, label, action
    """
    valid = {k: v for k, v in scores.items() if v is not None}
    if not valid:
        return {"avg": 0, "label": "데이터 없음", "action": "보유"}
    avg = sum(valid.values()) / len(valid)
    if avg >= 1.5:
        return {"avg": avg, "label": "🟢🟢 강한 매수 (다수 지표가 매우 싸다고 판단)", "action": "강한매수"}
    if avg >= 0.5:
        return {"avg": avg, "label": "🟢 매수 우호", "action": "매수"}
    if avg > -0.5:
        return {"avg": avg, "label": "🔵 중립 — 관망", "action": "보유"}
    if avg > -1.5:
        return {"avg": avg, "label": "🟠 매도 우호", "action": "매도"}
    return {"avg": avg, "label": "🔴🔴 강한 매도 (다수 지표가 천정 신호)", "action": "강한매도"}


if __name__ == "__main__":
    print("MVRV:", fetch_mvrv_zscore_latest())
    print("NUPL:", fetch_nupl_latest())
    print("Puell:", fetch_puell_latest())
