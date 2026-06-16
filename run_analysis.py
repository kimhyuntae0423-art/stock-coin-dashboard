from pathlib import Path
import pandas as pd
from scripts.data_fetch import fetch_tickers, download_prices, fetch_fundamentals
from scripts.indicators import compute_indicators
from scripts.signal_generator import generate_signals, latest_signal
from scripts.crypto_analysis import (
    compute_crypto_indicators,
    generate_crypto_signals,
    latest_crypto_signal,
)
from scripts.onchain import (
    fetch_mvrv_zscore_latest, fetch_mvrv_zscore_history,
    fetch_nupl_latest, fetch_puell_latest,
    compute_pi_cycle, compute_altcoin_season,
    classify_regime,
)


def run_stocks(out_dir):
    print("=== 주식 분석 ===")
    tickers = fetch_tickers("../tickers.csv")
    raw = download_prices(tickers)
    rows = []
    for t, df in raw.items():
        try:
            ind = compute_indicators(df)
            sigs = generate_signals(ind)
            sigs.to_csv(out_dir / f"{t}_signals.csv")
            meta = latest_signal(sigs)
            meta["ticker"] = t

            # 12개월 모멘텀 + 1개월 모멘텀 + 현재 RSI 추가
            if len(sigs) >= 252:
                meta["return_12m_pct"] = round(
                    (float(sigs["Close"].iloc[-1]) / float(sigs["Close"].iloc[-252]) - 1) * 100, 2
                )
            else:
                meta["return_12m_pct"] = None
            if len(sigs) >= 22:
                meta["return_1m_pct"] = round(
                    (float(sigs["Close"].iloc[-1]) / float(sigs["Close"].iloc[-22]) - 1) * 100, 2
                )
            else:
                meta["return_1m_pct"] = None
            last_rsi = sigs["rsi14"].iloc[-1] if "rsi14" in sigs.columns else None
            meta["rsi14"] = round(float(last_rsi), 2) if last_rsi is not None and not pd.isna(last_rsi) else None
            rows.append(meta)
        except Exception as e:
            print(f"{t}: 처리 실패 - {e}")
    pd.DataFrame(rows).to_csv(out_dir / "summary_signals.csv", index=False)
    print("주식 펀더멘털 수집 중...")
    fetch_fundamentals(tickers).to_csv(out_dir / "fundamentals.csv", index=False)


def run_coins(out_dir):
    print("\n=== 코인 분석 ===")
    tickers = fetch_tickers("../coins.csv")
    raw = download_prices(tickers)

    # 사이클 지표 수집 — 실패 시 직전 cycle_metrics.csv에서 fallback
    import time
    print("\n사이클/온체인 지표 수집 중...")
    prev_file = out_dir / "cycle_metrics.csv"
    prev = pd.read_csv(prev_file).iloc[0].to_dict() if prev_file.exists() else {}

    mvrv = fetch_mvrv_zscore_latest()
    time.sleep(3.0)
    nupl = fetch_nupl_latest()
    time.sleep(3.0)
    puell = fetch_puell_latest()

    # fallback: 이전 성공 값으로 폴백
    mvrv_val = mvrv.get("value") if mvrv.get("value") is not None else prev.get("mvrv_z")
    mvrv_date = mvrv.get("date") if mvrv.get("value") is not None else prev.get("mvrv_date")
    mvrv_cached = mvrv.get("value") is None and mvrv_val is not None

    nupl_val = nupl.get("value") if nupl.get("value") is not None else prev.get("nupl")
    nupl_date = nupl.get("date") if nupl.get("value") is not None else prev.get("nupl_date")
    nupl_cached = nupl.get("value") is None and nupl_val is not None

    puell_val = puell.get("value") if puell.get("value") is not None else prev.get("puell")
    puell_date = puell.get("date") if puell.get("value") is not None else prev.get("puell_date")
    puell_cached = puell.get("value") is None and puell_val is not None

    print(f"  MVRV : z={mvrv_val} ({mvrv_date}){' [캐시]' if mvrv_cached else ''}")
    print(f"  NUPL : {nupl_val} ({nupl_date}){' [캐시]' if nupl_cached else ''}")
    print(f"  Puell: {puell_val} ({puell_date}){' [캐시]' if puell_cached else ''}")

    # MVRV 히스토리(차트용)
    mvrv_hist = fetch_mvrv_zscore_history()
    if not mvrv_hist.empty:
        mvrv_hist.to_csv(out_dir / "mvrv_history.csv")

    # Pi Cycle (BTC 가격으로 계산)
    pi_cycle = {}
    if "BTC-USD" in raw:
        pi = compute_pi_cycle(raw["BTC-USD"])
        if "series" in pi:
            pi_series = pi.pop("series")
            pi_series.to_csv(out_dir / "pi_cycle_series.csv")
        pi_cycle = pi
    print(f"  PiCyc: ratio={pi_cycle.get('ratio')}")

    # 90일 BTC 대비 수익률로 alt season index 계산
    coin_returns = {}
    for t, df in raw.items():
        try:
            if len(df) < 91:
                continue
            close = df.rename(columns=lambda c: c.capitalize())["Close"]
            r = float(close.iloc[-1] / close.iloc[-91] - 1)
            coin_returns[t] = r
        except Exception:
            pass
    btc_ret = coin_returns.get("BTC-USD")
    alt_season = compute_altcoin_season(coin_returns, btc_ret)
    print(f"  AltSe: score={alt_season.get('score')} regime={alt_season.get('regime')}")

    # 코인별 분석 (regime은 MVRV 기준 — fallback 포함)
    z = mvrv_val
    regime = classify_regime(z)["regime"] if z is not None else "unknown"
    rows = []
    for t, df in raw.items():
        try:
            ind = compute_crypto_indicators(df)
            sigs = generate_crypto_signals(ind)
            sigs.to_csv(out_dir / f"coin_{t}_signals.csv")
            meta = latest_crypto_signal(sigs, regime=regime)
            meta["ticker"] = t
            meta["return_90d_pct"] = round(coin_returns.get(t, 0) * 100, 2) if t in coin_returns else None
            rows.append(meta)
        except Exception as e:
            print(f"{t}: 처리 실패 - {e}")
    pd.DataFrame(rows).to_csv(out_dir / "coin_summary.csv", index=False)

    # 사이클 지표 종합 파일 (fallback 적용된 값 저장)
    metrics = {
        "mvrv_z": mvrv_val,
        "mvrv_date": mvrv_date,
        "nupl": nupl_val,
        "nupl_date": nupl_date,
        "puell": puell_val,
        "puell_date": puell_date,
        "pi_ratio": pi_cycle.get("ratio"),
        "pi_sma111": pi_cycle.get("sma111"),
        "pi_sma350x2": pi_cycle.get("sma350x2"),
        "pi_date": pi_cycle.get("date"),
        "alt_season_score": alt_season.get("score"),
        "alt_season_regime": alt_season.get("regime"),
        "alt_season_label": alt_season.get("label"),
        "btc_return_90d_pct": alt_season.get("btc_return_90d_pct"),
    }
    pd.DataFrame([metrics]).to_csv(out_dir / "cycle_metrics.csv", index=False)


def run_factor_backtests():
    print("\n=== 팩터 백테스트 ===")
    from scripts.factor_backtest import run as _run_factors
    _run_factors()


def run_etf_backtests():
    print("\n=== ETF 전략 백테스트 ===")
    from scripts.etf_backtest import run as _run_etf
    _run_etf()


def run_all():
    base = Path(__file__).resolve().parent
    out_dir = base / "results"
    out_dir.mkdir(exist_ok=True)
    run_stocks(out_dir)
    run_coins(out_dir)
    run_factor_backtests()
    print("\n완료. 결과는 results/ 폴더를 확인하세요.")


if __name__ == "__main__":
    run_all()
