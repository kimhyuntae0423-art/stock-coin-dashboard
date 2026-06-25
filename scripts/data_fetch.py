import os
from pathlib import Path
import pandas as pd
import yfinance as yf


# CoinGecko 코인 ID 매핑 (Binance도 막힐 때 최종 fallback)
_COINGECKO_IDS = {
    "MASK-USD":  "mask-network",
    "ID-USD":    "space-id",
    "TRUMP-USD": "official-trump",
    "ZETA-USD":  "zetachain",
    "ENS-USD":   "ethereum-name-service",
}


def _fetch_binance_ohlcv(ticker_usd: str, days: int = 1825) -> pd.DataFrame:
    """yfinance가 지원 안 하는 코인을 Binance REST API로 대체 수집."""
    import requests
    symbol = ticker_usd.replace("-USD", "USDT")
    url = "https://api.binance.com/api/v3/klines"
    params = {"symbol": symbol, "interval": "1d", "limit": min(days, 1000)}
    r = requests.get(url, params=params, timeout=15)
    r.raise_for_status()
    data = r.json()
    if not data:
        return pd.DataFrame()
    df = pd.DataFrame(data, columns=[
        "open_time", "Open", "High", "Low", "Close", "Volume",
        "close_time", "quote_vol", "num_trades", "taker_base", "taker_quote", "ignore"
    ])
    df["Date"] = pd.to_datetime(df["open_time"], unit="ms").dt.normalize()
    df = df.set_index("Date")[["Open", "High", "Low", "Close", "Volume"]]
    return df.astype(float)


def _fetch_coingecko_ohlcv(ticker_usd: str) -> pd.DataFrame:
    """CoinGecko API로 일봉 수집 — Binance 차단 시 최종 fallback."""
    cg_id = _COINGECKO_IDS.get(ticker_usd.upper())
    if not cg_id:
        return pd.DataFrame()
    import requests
    url = f"https://api.coingecko.com/api/v3/coins/{cg_id}/market_chart"
    params = {"vs_currency": "usd", "days": "365", "interval": "daily"}
    r = requests.get(url, params=params, timeout=20, headers={"accept": "application/json"})
    r.raise_for_status()
    data = r.json()
    prices  = data.get("prices", [])
    volumes = data.get("total_volumes", [])
    if not prices:
        return pd.DataFrame()
    p_df = pd.DataFrame(prices,  columns=["ts", "Close"]).set_index("ts")["Close"]
    v_df = pd.DataFrame(volumes, columns=["ts", "Volume"]).set_index("ts")["Volume"]
    df = pd.DataFrame({"Close": p_df, "Volume": v_df})
    df.index = pd.to_datetime(df.index, unit="ms").normalize()
    df.index.name = "Date"
    df["Open"] = df["Close"]
    df["High"] = df["Close"]
    df["Low"]  = df["Close"]
    return df[["Open", "High", "Low", "Close", "Volume"]].dropna().astype(float)


def fetch_tickers(tickers_file: str = "../tickers.csv") -> list:
    p = Path(__file__).resolve().parents[0] / Path(tickers_file)
    if not p.exists():
        raise FileNotFoundError(f"티커 파일을 찾을 수 없습니다: {p}")
    with open(p, "r", encoding="utf-8") as f:
        lines = [l.strip() for l in f.readlines() if l.strip() and not l.startswith("#")]
    return lines


def download_prices(tickers: list, period: str = "5y", interval: str = "1d") -> pd.DataFrame:
    # yfinance can download multiple tickers at once; we save per-ticker files too
    out_dir = Path(__file__).resolve().parents[0] / "data"
    out_dir.mkdir(exist_ok=True)

    all_signals = {}
    for t in tickers:
        try:
            df = yf.download(t, period=period, interval=interval, progress=False)
            # yfinance may return MultiIndex columns when grouped; flatten to single-level
            if hasattr(df, 'columns') and getattr(df.columns, 'nlevels', 1) > 1:
                try:
                    df.columns = df.columns.get_level_values(0)
                except Exception:
                    df.columns = [c[-1] if isinstance(c, tuple) else c for c in df.columns]
            df.dropna(how="all", inplace=True)

            # 코인(-USD)이고 yfinance 데이터가 30일 이상 오래됐거나 가격 오류가 알려진 종목은 Binance로 교체
            _BINANCE_FORCE = {
                "ID-USD",     # yfinance 가격이 10배 낮게 잘못 수집됨
                "TRUMP-USD",  # yfinance 오매핑 ($0.0003, 2026-02 이후 멈춤)
                "MASK-USD",   # yfinance 추적 중단 (2022-08 이후 멈춤, 가격 $814 오류)
            }
            if "-USD" in t:
                try:
                    last_dt = df.index[-1]
                    # timezone-aware 인덱스 대응
                    now = pd.Timestamp.now(tz=last_dt.tzinfo) if last_dt.tzinfo else pd.Timestamp.now()
                    yf_stale = df.empty or (now - last_dt).days > 30
                except Exception:
                    yf_stale = True
                if yf_stale or t in _BINANCE_FORCE:
                    print(f"{t}: yfinance 데이터 오래됨 → Binance fallback 시도...")
                    _binance_ok = False
                    try:
                        df_b = _fetch_binance_ohlcv(t, days=1825)
                        if not df_b.empty:
                            df = df_b
                            _binance_ok = True
                            print(f"{t}: Binance 수집 완료 ({len(df)} rows)")
                        else:
                            print(f"{t}: Binance 데이터 없음")
                    except Exception as be:
                        print(f"{t}: Binance 실패 - {be}")
                    if not _binance_ok and t.upper() in _COINGECKO_IDS:
                        print(f"{t}: CoinGecko fallback 시도...")
                        try:
                            df_c = _fetch_coingecko_ohlcv(t)
                            if not df_c.empty:
                                df = df_c
                                print(f"{t}: CoinGecko 수집 완료 ({len(df_c)} rows)")
                            else:
                                print(f"{t}: CoinGecko도 데이터 없음")
                        except Exception as ce:
                            print(f"{t}: CoinGecko 실패 - {ce}")

            if df.empty:
                print(f"{t}: 데이터 없음")
                continue
            df.to_csv(out_dir / f"{t}.csv")
            all_signals[t] = df
            print(f"{t}: 다운로드 완료 ({len(df)} rows)")
        except Exception as e:
            print(f"{t}: 다운로드 실패 - {e}")

    return all_signals


def fetch_fundamentals(tickers: list) -> pd.DataFrame:
    """
    각 티커의 밸류에이션/펀더멘털을 yfinance에서 수집.
    한국 종목(.KS/.KQ)은 yfinance가 PER/PBR을 자주 누락해서, 네이버 금융에서 보강.
    """
    from .naver_finance import fetch_korean_fundamentals

    # 1) 한국 종목 PER/PBR을 네이버에서 미리 수집
    korean_data = fetch_korean_fundamentals(tickers)

    rows = []
    for t in tickers:
        try:
            info = yf.Ticker(t).info or {}
            div_pct = info.get("dividendYield")

            per = info.get("trailingPE")
            pbr = info.get("priceToBook")

            # PBR이 0.1 미만이면 yfinance 데이터 오류로 간주 (BRK-B 케이스 등)
            if pbr is not None and pbr < 0.1:
                pbr = None

            # 한국 종목: 네이버 값으로 fallback / overwrite
            if t in korean_data:
                kr = korean_data[t]
                if per is None and kr.get("per") is not None:
                    per = kr["per"]
                if pbr is None and kr.get("pbr") is not None:
                    pbr = kr["pbr"]
                # 배당수익률도 yfinance가 없을 때 네이버로 보강
                if (div_pct is None or div_pct == 0) and kr.get("dividend_yield_pct"):
                    div_pct = kr["dividend_yield_pct"]

            # Growth factor: yfinance가 0.083 같은 소수로 반환 → %로 변환
            def _pct(key):
                v = info.get(key)
                return v * 100 if v is not None and not pd.isna(v) else None

            rows.append({
                "ticker": t,
                "per": per,
                "forward_per": info.get("forwardPE"),
                "pbr": pbr,
                "dividend_yield_pct": div_pct,
                "market_cap": info.get("marketCap"),
                "roe_pct": _pct("returnOnEquity"),
                "profit_margin_pct": _pct("profitMargins"),
                "revenue_growth_yoy_pct": _pct("revenueGrowth"),
                "earnings_growth_yoy_pct": _pct("earningsGrowth"),
                "eps_growth_q_pct": _pct("earningsQuarterlyGrowth"),
                "consensus_target": info.get("targetMeanPrice"),
                "analyst_count": info.get("numberOfAnalystOpinions"),
                "recommendation_mean": info.get("recommendationMean"),
                "sector": info.get("sector"),
                "industry": info.get("industry"),
                "currency": info.get("currency"),
            })
            print(f"{t}: 펀더멘털 OK")
        except Exception as e:
            print(f"{t}: 펀더멘털 실패 - {e}")
            rows.append({"ticker": t})
    return pd.DataFrame(rows)


if __name__ == "__main__":
    tickers = fetch_tickers()
    download_prices(tickers)
