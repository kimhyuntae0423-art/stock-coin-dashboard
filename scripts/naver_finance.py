"""
네이버 금융 크롤링 — 한국 주식 PER/PBR/EPS/배당수익률 보강.

yfinance가 한국 종목 trailing PE / PBR을 자주 누락하므로 보완 용도.
"""
from urllib.request import Request, urlopen
import re
import time


HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                  "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
}


def _strip_kr_suffix(ticker: str) -> str:
    """'005930.KS' → '005930'"""
    return ticker.replace(".KS", "").replace(".KQ", "")


def _parse_number(s: str):
    if not s or "N/A" in s.upper():
        return None
    try:
        return float(s.replace(",", ""))
    except ValueError:
        return None


def fetch_one(code: str) -> dict:
    """한 종목의 PER/PBR/EPS/배당수익률을 네이버에서 가져옴."""
    url = f"https://finance.naver.com/item/main.naver?code={code}"
    try:
        req = Request(url, headers=HEADERS)
        with urlopen(req, timeout=10) as r:
            html = r.read().decode("euc-kr", errors="replace")
    except Exception as e:
        return {"error": str(e)}

    out = {}
    patterns = {
        "per": r'<em[^>]*id="_per"[^>]*>([0-9,.\-N/A]+)</em>',
        "pbr": r'<em[^>]*id="_pbr"[^>]*>([0-9,.\-N/A]+)</em>',
        "eps": r'<em[^>]*id="_eps"[^>]*>([0-9,.\-N/A]+)</em>',
        "dividend_yield_pct": r'<em[^>]*id="_dvr"[^>]*>([0-9,.\-N/A]+)</em>',
    }
    for k, pat in patterns.items():
        m = re.search(pat, html)
        out[k] = _parse_number(m.group(1)) if m else None
    return out


def fetch_korean_fundamentals(tickers: list) -> dict:
    """
    한국 티커 리스트(.KS/.KQ 포함)에 대해 PER/PBR/EPS/배당수익률 수집.
    반환: {ticker: {per, pbr, eps, dividend_yield_pct}, ...}
    """
    result = {}
    for t in tickers:
        if not (t.endswith(".KS") or t.endswith(".KQ")):
            continue
        code = _strip_kr_suffix(t)
        data = fetch_one(code)
        if "error" in data:
            print(f"  네이버 {t}: 실패 - {data['error']}")
        else:
            result[t] = data
            print(f"  네이버 {t}: PER={data.get('per')} PBR={data.get('pbr')}")
        time.sleep(0.3)  # 서버 매너
    return result


if __name__ == "__main__":
    print(fetch_one("005930"))
    print(fetch_one("000660"))
