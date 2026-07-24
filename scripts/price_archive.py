"""
백테스트용 장기 가격 아카이브.

{ticker}_signals.csv는 yf.download(period="5y")라서 매일 롤링(오래된 날짜가
자동으로 빠짐) — 대시보드 표시용으론 문제없지만, "5년보다 긴 구간 백테스트"엔
못 쓴다(2026-07-24, 코어 ETF 조합 백테스트 중 발견). 이 모듈은 core_etfs.csv
후보군의 종가를 삭제 없이 계속 누적해서, 시간이 지날수록 자연히 5년보다 긴
구간이 쌓이게 한다. run_analysis.py가 매일 실행될 때마다 호출되므로 별도
스케줄링 불필요.
"""
from pathlib import Path
import pandas as pd

ARCHIVE_FILE = Path(__file__).resolve().parents[1] / "results" / "price_archive.csv"


def update_archive(closes: dict) -> None:
    """closes: {ticker: Close 가격 Series(날짜 인덱스)}. 기존에 없는 (날짜,티커)만 추가."""
    new_rows = []
    for ticker, s in closes.items():
        if s is None or len(s) == 0:
            continue
        df = s.rename("close").to_frame()
        df["date"] = pd.to_datetime(df.index).date
        df["ticker"] = ticker
        new_rows.append(df[["date", "ticker", "close"]])
    if not new_rows:
        return
    incoming = pd.concat(new_rows, ignore_index=True)

    if ARCHIVE_FILE.exists():
        existing = pd.read_csv(ARCHIVE_FILE, parse_dates=["date"])
        existing["date"] = existing["date"].dt.date
        combined = pd.concat([existing, incoming], ignore_index=True)
    else:
        combined = incoming

    combined = combined.drop_duplicates(subset=["date", "ticker"], keep="last")
    combined = combined.sort_values(["ticker", "date"])
    combined.to_csv(ARCHIVE_FILE, index=False)


def load_core_etf_tickers() -> set:
    p = Path(__file__).resolve().parents[1] / "core_etfs.csv"
    df = pd.read_csv(p)
    return set(df["ticker"].astype(str).str.strip())
