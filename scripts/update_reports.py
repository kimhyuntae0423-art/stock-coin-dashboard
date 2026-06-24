"""보유종목 리서치 노트 자동 갱신 — Claude Haiku API 호출.

GitHub Actions daily-update.yml에서 run_analysis.py 이후 실행.
ANTHROPIC_API_KEY 환경변수 없으면 스킵.
"""
import json
import os
import time
from datetime import date

import pandas as pd

from scripts.config import ROOT, HOLDINGS_FILE, RESULTS_DIR as RESULTS
REPORTS_FILE = ROOT / "asset_reports.json"


def _load_names() -> dict:
    names: dict = {}
    for path in (ROOT / "names.csv", ROOT / "coin_names.csv"):
        if path.exists():
            df = pd.read_csv(path)
            names.update(dict(zip(df["ticker"], df["name"])))
    return names


def _fmt(v, suffix="", decimals=1) -> str:
    if v is None or (isinstance(v, float) and pd.isna(v)):
        return "N/A"
    try:
        return f"{float(v):.{decimals}f}{suffix}"
    except Exception:
        return str(v)


def _build_context(ticker, is_coin, h_row, summary, funda, coin_sum, cycle) -> dict | None:
    buy_price = float(h_row.get("buy_price") or 0)

    if is_coin:
        c = coin_sum[coin_sum["ticker"] == ticker]
        if c.empty:
            return None
        c = c.iloc[0]
        close = float(c.get("close") or 0)
        ctx = {
            "close": close,
            "pnl_pct": (close / buy_price - 1) * 100 if buy_price > 0 else 0,
            "rsi": c.get("rsi"),
            "regime": c.get("regime", "-"),
            "r90d": c.get("return_90d_pct"),
        }
        if cycle:
            ctx["mvrv_z"] = cycle.get("mvrv_z")
            ctx["nupl"]   = cycle.get("nupl")
            ctx["puell"]  = cycle.get("puell")
        return ctx

    s = summary[summary["ticker"] == ticker]
    if s.empty:
        return None
    s = s.iloc[0]
    close = float(s.get("close") or 0)
    ctx = {
        "close":         close,
        "pnl_pct":       (close / buy_price - 1) * 100 if buy_price > 0 else 0,
        "action":        s.get("action", "-"),
        "rsi":           s.get("rsi14"),
        "return_12m":    s.get("return_12m_pct"),
        "return_1m":     s.get("return_1m_pct"),
    }
    if funda is not None and not funda.empty:
        f = funda[funda["ticker"] == ticker]
        if not f.empty:
            f = f.iloc[0]
            ctx["per"]             = f.get("per")
            ctx["pbr"]             = f.get("pbr")
            ctx["roe"]             = f.get("roe_pct")
            ctx["rev_growth"]      = f.get("revenue_growth_yoy_pct")
            ctx["earn_growth"]     = f.get("earnings_growth_yoy_pct")
    return ctx


def _build_prompt(ticker, name, is_coin, is_etf, ctx) -> str:
    pnl = ctx.get("pnl_pct", 0)

    lines = [
        f"종목: {name} ({ticker})",
        f"현재 수익률: {pnl:+.1f}% (매수가 대비)",
        "",
    ]

    if is_coin:
        lines += [
            "[온체인·기술적]",
            f"- MVRV Z-Score: {_fmt(ctx.get('mvrv_z'), decimals=2)}",
            f"- NUPL: {_fmt(ctx.get('nupl'), decimals=2)}",
            f"- Puell Multiple: {_fmt(ctx.get('puell'), decimals=2)}",
            f"- 사이클 국면: {ctx.get('regime', 'N/A')}",
            f"- RSI: {_fmt(ctx.get('rsi'), decimals=0)}",
            f"- 90일 수익률: {_fmt(ctx.get('r90d'), suffix='%')}",
        ]
    elif is_etf:
        lines += [
            "[기술적]",
            f"- 추세: {ctx.get('action', 'N/A')}",
            f"- RSI: {_fmt(ctx.get('rsi'), decimals=0)}",
            f"- 12개월 수익률: {_fmt(ctx.get('return_12m'), suffix='%')}",
            f"- 1개월 수익률: {_fmt(ctx.get('return_1m'), suffix='%')}",
        ]
    else:
        lines += [
            "[기술적]",
            f"- 추세: {ctx.get('action', 'N/A')}",
            f"- RSI: {_fmt(ctx.get('rsi'), decimals=0)}",
            f"- 12개월 수익률: {_fmt(ctx.get('return_12m'), suffix='%')}",
            "",
            "[펀더멘털]",
            f"- PER: {_fmt(ctx.get('per'), decimals=1)}",
            f"- PBR: {_fmt(ctx.get('pbr'), decimals=2)}",
            f"- ROE: {_fmt(ctx.get('roe'), suffix='%')}",
            f"- 매출 YoY: {_fmt(ctx.get('rev_growth'), suffix='%')}",
            f"- 영업익 YoY: {_fmt(ctx.get('earn_growth'), suffix='%')}",
        ]

    data_str = "\n".join(lines)

    return f"""당신은 개인 투자자의 보유종목 분석 보조 AI입니다.
아래 데이터를 바탕으로 오늘 기준 보유 현황을 분석하세요.

{data_str}

[원칙]
- "사라/팔아라/무조건 오른다" 같은 확정 표현 금지
- 데이터와 의견을 구분
- 모르는 숫자는 만들지 않고 "확인 필요"로 표기
- 반대 시나리오(틀릴 조건)를 반드시 제시

아래 JSON 형식으로만 응답하세요 (마크다운 코드블록 없이 순수 JSON만):
{{
  "opinion": "한 줄 요약 (15자 이내)",
  "opinion_type": "positive 또는 caution 또는 negative",
  "summary": "현재 상황 요약 — 데이터 기반, 150자 이내",
  "bull": "강세 근거 (60자 이내)",
  "bear": "약세 근거 / 틀릴 조건 (60자 이내)"
}}"""


def _call_api(prompt: str, api_key: str) -> dict:
    import anthropic
    client = anthropic.Anthropic(api_key=api_key)
    msg = client.messages.create(
        model="claude-haiku-4-5-20251001",
        max_tokens=512,
        messages=[{"role": "user", "content": prompt}],
    )
    text = msg.content[0].text.strip()
    # 코드블록 감싸진 경우 벗기기
    if "```" in text:
        parts = text.split("```")
        for part in parts:
            if part.startswith("json"):
                text = part[4:].strip()
                break
            if part.strip().startswith("{"):
                text = part.strip()
                break
    return json.loads(text)


def run():
    api_key = os.environ.get("ANTHROPIC_API_KEY")
    if not api_key:
        print("ANTHROPIC_API_KEY 없음 — 리서치 노트 갱신 스킵")
        return

    if not HOLDINGS_FILE.exists():
        print("holdings.csv 없음 — 스킵")
        return

    holdings = pd.read_csv(HOLDINGS_FILE).dropna(subset=["ticker"])
    holdings["ticker"] = holdings["ticker"].astype(str).str.strip().str.upper()

    names    = _load_names()
    summary  = pd.read_csv(RESULTS / "summary_signals.csv") if (RESULTS / "summary_signals.csv").exists() else pd.DataFrame()
    funda    = pd.read_csv(RESULTS / "fundamentals.csv")    if (RESULTS / "fundamentals.csv").exists()    else pd.DataFrame()
    coin_sum = pd.read_csv(RESULTS / "coin_summary.csv")    if (RESULTS / "coin_summary.csv").exists()    else pd.DataFrame()
    cycle_f  = RESULTS / "cycle_metrics.csv"
    cycle    = pd.read_csv(cycle_f).iloc[0].to_dict() if cycle_f.exists() else None

    etf_file    = ROOT / "core_etfs.csv"
    etf_tickers = set(pd.read_csv(etf_file)["ticker"].astype(str).str.strip()) if etf_file.exists() else set()

    reports = json.loads(REPORTS_FILE.read_text(encoding="utf-8")) if REPORTS_FILE.exists() else {}

    today = date.today().isoformat()
    ok_count = 0

    for _, h_row in holdings.drop_duplicates("ticker").iterrows():
        ticker  = str(h_row["ticker"])
        is_coin = "-USD" in ticker
        is_etf  = ticker in etf_tickers
        name    = names.get(ticker, ticker)

        print(f"  [{ticker}] {name} 분석 중...", end=" ", flush=True)
        ctx = _build_context(ticker, is_coin, h_row, summary, funda, coin_sum, cycle)
        if ctx is None:
            print("데이터 없음 — 스킵")
            continue

        prompt = _build_prompt(ticker, name, is_coin, is_etf, ctx)
        try:
            result = _call_api(prompt, api_key)
            result["updated"] = today
            # 기존 sources 보존 (수동 작성 링크, 자동 생성 불가)
            if ticker in reports and "sources" in reports[ticker]:
                result["sources"] = reports[ticker]["sources"]
            reports[ticker] = result
            ok_count += 1
            print(f"→ {result['opinion_type']}: {result['opinion']}")
        except Exception as e:
            print(f"→ 오류 ({e}), 기존 유지")

        time.sleep(0.5)  # API 레이트 리밋 여유

    REPORTS_FILE.write_text(
        json.dumps(reports, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print(f"\n✓ 리서치 노트 갱신 완료: {ok_count}/{len(holdings)}개")


if __name__ == "__main__":
    run()
