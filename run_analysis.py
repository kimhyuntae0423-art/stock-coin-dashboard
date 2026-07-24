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
from scripts.price_archive import update_archive, load_core_etf_tickers


def run_stocks(out_dir):
    print("=== 주식 분석 ===")
    tickers = fetch_tickers("../tickers.csv")
    raw = download_prices(tickers)
    core_etf_tickers = load_core_etf_tickers()
    archive_closes = {}
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

            # 코어 ETF 후보군은 5년 롤링과 별도로 종가를 무제한 누적(백테스트용,
            # 2026-07-24 신설) — {ticker}_signals.csv는 5년마다 오래된 날짜가
            # 빠지지만 이 아카이브는 삭제 없이 계속 쌓인다.
            if t in core_etf_tickers:
                archive_closes[t] = sigs["Close"]
        except Exception as e:
            print(f"{t}: 처리 실패 - {e}")
    pd.DataFrame(rows).to_csv(out_dir / "summary_signals.csv", index=False)
    update_archive(archive_closes)
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


def run_coin_backtests():
    print("\n=== 코인 전략 백테스트 ===")
    from scripts.coin_backtest import run as _run_coin
    _run_coin()


def run_h15_strategy():
    print("\n=== H15 ETF 전략 백테스트 (상대적 저점 Top3) ===")
    try:
        from scripts.signal_validation import run_etf_strategy_backtest
        results_dir = Path(__file__).resolve().parent / "results"
        eq_df, mt_df = run_etf_strategy_backtest(results_dir, n_top=3)
        if not eq_df.empty:
            eq_df.to_csv(results_dir / "strategy_equity.csv",  index=False, encoding="utf-8-sig")
            mt_df.to_csv(results_dir / "strategy_metrics.csv", index=False, encoding="utf-8-sig")
            print(f"  → {len(eq_df)}개월 백테스트 완료")
        else:
            print("  → 데이터 부족, 스킵")
    except Exception as e:
        print(f"  → H15 전략 백테스트 실패: {e}")


def validate_ticker_consistency():
    """4개 데이터 소스 간 KR ETF 티커 일관성 검증.

    검증 대상:
      A. etf_rotation.py의 ISA 추천 티커가 core_etfs.csv에 존재하는지
      B. etf_rotation.py의 ISA 추천 티커가 tickers.csv(수집 대상)에 존재하는지
      C. core_etfs.csv의 isa_preferred ETF가 tickers.csv에 존재하는지
    """
    base = Path(__file__).resolve().parent
    issues = []

    tickers_path = base / "tickers.csv"
    tickers_set: set[str] = set()
    if tickers_path.exists():
        for line in tickers_path.read_text(encoding="utf-8").splitlines():
            t = line.strip()
            if t and not t.startswith("#"):
                tickers_set.add(t)

    core_path = base / "core_etfs.csv"
    if not core_path.exists():
        print("[경고] core_etfs.csv 없음 — 검증 스킵")
        return
    core_df = pd.read_csv(core_path)
    core_tickers = set(core_df["ticker"].astype(str))

    from scripts.etf_rotation import CORE_ROLES
    rotation_kr = {r["kr"] for r in CORE_ROLES if r.get("kr")}

    for t in sorted(rotation_kr):
        if t not in core_tickers:
            issues.append(f"  etf_rotation.py ISA '{t}' → core_etfs.csv에 없음")
        if t not in tickers_set:
            issues.append(f"  etf_rotation.py ISA '{t}' → tickers.csv에 없음 (수집 대상 누락)")

    if "isa_preferred" in core_df.columns:
        preferred = core_df[core_df["isa_preferred"].astype(str).str.lower() == "true"]
        for _, row in preferred.iterrows():
            t = str(row["ticker"])
            if t not in tickers_set:
                issues.append(f"  core_etfs isa_preferred '{t}' → tickers.csv에 없음 (수집 대상 누락)")

    if issues:
        print("\n[경고] 티커 일관성 검증 실패:")
        for msg in issues:
            print(msg)
        raise SystemExit(f"\n검증 실패 {len(issues)}건 -- core_etfs.csv 또는 tickers.csv 수정 필요")
    print("[OK] 티커 일관성 검증 통과")


def run_all():
    base = Path(__file__).resolve().parent
    out_dir = base / "results"
    out_dir.mkdir(exist_ok=True)
    validate_ticker_consistency()
    run_stocks(out_dir)
    run_coins(out_dir)
    run_factor_backtests()
    run_etf_backtests()
    run_coin_backtests()
    run_h15_strategy()
    print("\n완료. 결과는 results/ 폴더를 확인하세요.")


if __name__ == "__main__":
    run_all()
