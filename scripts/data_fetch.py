import os
from pathlib import Path
import pandas as pd
import yfinance as yf


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
            if df.empty:
                print(f"{t}: 데이터 없음")
                continue
            df.dropna(how="all", inplace=True)
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

            rows.append({
                "ticker": t,
                "per": per,
                "forward_per": info.get("forwardPE"),
                "pbr": pbr,
                "dividend_yield_pct": div_pct,
                "market_cap": info.get("marketCap"),
                "roe_pct": (info.get("returnOnEquity") or 0) * 100 if info.get("returnOnEquity") else None,
                "profit_margin_pct": (info.get("profitMargins") or 0) * 100 if info.get("profitMargins") else None,
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
