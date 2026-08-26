"""scripts/check_alerts.py의 코인 손익 신호 — 카카오 알림 파이프라인.

2026-07-22 실사용 중 발견된 버그: sig_row["close"](USD)와 row["buy_price"](KRW)를
환율 변환 없이 나눠서 보유 코인 전부가 -100%에 가까운 손익으로 계산되던 버그.

2026-08-24: check_alerts.py 알트코인 전용 "BB(%B)>1+RSI>70 → 매도" 신호를 완전히
제거하고, rebalancing_page.py "보유 현황" 표와 완전히 같은 온체인 국면(MVRV)
판단 하나로 통일했다 — 그 BB 신호 자체가 백테스트 승률 27%(동전던지기보다
나쁨)였고, 대시보드와 무관하게 따로 동작해서 같은 코인이 카톡("매도 검토")과
대시보드("매수 우호")에서 정반대로 뜨는 걸 사용자가 실제로 목격함. 이 과정에서
G1/G2 로드맵 대상이 아닌 코인의 "개별 손실만으로 severity 1(주의)" 규칙도
같이 제거했다 — 그 규칙도 rebalancing_page.py엔 없는(대시보드는 이런 코인을
온체인 국면 그대로 "매수 우호"로 보여줌) check_alerts.py 전용 규칙이라
같은 부류의 불일치였기 때문. 이 테스트는 두 버그가 다시 생기면 실패한다.
"""
import sys
from pathlib import Path

sys.path.append(str(Path(__file__).resolve().parent.parent))
sys.path.append(str(Path(__file__).resolve().parent.parent / "scripts"))

from scripts.check_alerts import severity_for_holding, check_cycle, format_trend_flips
from scripts.onchain import classify_regime

USDKRW = 1380.0


def test_currency_conversion_not_flat_minus_100():
    """USD 종가 * 환율로 변환해야 정상적인 손익이 나온다(변환 안 하면 -100%에 가까운
    값). G1 로드맵 대상(TRUMP)이 손절 검증 구간(-40%~-20%)에 들어오도록 값을
    잡아서, 실제 문구에 pnl_pct가 제대로(약 -30%, -100% 근처 아님) 반영되는지 확인."""
    row = {"buy_price": 25_631.0, "ticker": "TRUMP-USD"}  # 실제 holdings.csv 예시(KRW)
    close_usd = (25_631.0 * 0.70) / USDKRW  # 손익 -30% 근방이 되도록 역산
    sig_row = {"close": close_usd}
    severity, reasons = severity_for_holding(
        row, sig_row, mvrv_z=0.42, is_coin=True, usdkrw=USDKRW,
    )
    assert severity == 2
    assert "-100" not in reasons[0]
    assert "30" in reasons[0]  # -30%대 손익이 실제로 문구에 반영됐는지


def test_g1_ticker_deep_loss_not_flagged_sell_when_roadmap_says_wait():
    """G1(TRUMP 등) 코인은 손절선(-40%)보다 훨씬 깊이 물려 있으면
    severity 0(알림 없음) — 검증 안 된 규칙으로 '매도 검토' 내면 안 됨."""
    row = {"buy_price": 12_629.0, "ticker": "TRUMP-USD"}
    sig_row = {"close": 1.6}  # 실제 데이터 기준 손실 -80%대
    severity, reasons = severity_for_holding(
        row, sig_row, mvrv_z=0.42, is_coin=True, usdkrw=USDKRW,
    )
    assert severity == 0
    assert reasons == []


def test_g1_ticker_sells_when_recovered_to_threshold():
    """G1 코인이 손절선(-40%) 이내로 회복하면 severity 2로 매도 신호를 내야 한다."""
    row = {"buy_price": 100_000.0, "ticker": "TRUMP-USD"}
    # 손익 -35% (환율 반영 후, 손절선 -40%보다 나은 상태) 나오도록 close 역산
    close_usd = (100_000.0 * 0.65) / USDKRW
    sig_row = {"close": close_usd}
    severity, reasons = severity_for_holding(
        row, sig_row, mvrv_z=0.42, is_coin=True, usdkrw=USDKRW,
    )
    assert severity == 2
    assert "회복" in reasons[0] or "매도" in reasons[0]


def test_g2_ticker_also_uses_roadmap_not_flagged_sell_when_deep():
    """G2(ETC 등)도 이제 같은 손절선 로드맵을 쓴다 — 깊이 물려 있으면 severity 0."""
    row = {"buy_price": 25_631.0, "ticker": "ETC-USD"}
    sig_row = {"close": 7.0}  # 실제 데이터 기준 손실 -60%대
    severity, reasons = severity_for_holding(
        row, sig_row, mvrv_z=0.42, is_coin=True, usdkrw=USDKRW,
    )
    assert severity == 0
    assert reasons == []


def test_g3_alt_deep_loss_matches_dashboard_not_flagged_when_regime_bullish():
    """G3(BTC·ETH·SOL, 핵심 장기보유)는 손절선 로드맵 대상이 아니다.
    rebalancing_page.py "보유 현황" 표(coin_holdings_action_text())는 이런 코인을
    개별 손실과 무관하게 온체인 국면 그대로 보여준다 — z=0.42는 매집(accumulation)
    구간이라 대시보드는 "매수 우호"를 보여주므로, 카톡도 severity 0(알림 없음)이어야
    한다. 예전엔 check_alerts.py 전용 "개별 손실 → severity 1" 규칙이 있어서 이
    경우에도 대시보드와 다르게 "주의"를 보냈었다(2026-08-24 정리)."""
    row = {"buy_price": 4_111_452.0, "ticker": "ETH-USD"}
    sig_row = {"close": 1_920.0}  # 실제 데이터 기준 손실 -35%대
    severity, reasons = severity_for_holding(
        row, sig_row, mvrv_z=0.42, is_coin=True, usdkrw=USDKRW,
    )
    assert severity == 0
    assert reasons == []


def test_btc_severity_uses_mvrv_only_not_pnl():
    row = {"buy_price": 133_952_455.0, "ticker": "BTC-USD"}
    sig_row = {"close": 65_972.0}
    severity, reasons = severity_for_holding(
        row, sig_row, mvrv_z=0.42, is_coin=True, is_etf=False, usdkrw=USDKRW,
    )
    assert severity == 0  # accumulation 구간(0~1.5)이라 알림 없음
    assert reasons == []


def test_btc_severity_matches_dashboard_regime_at_bull_boundary():
    """2026-08-21 발견된 버그의 회귀 테스트: 카톡(check_alerts)이 대시보드
    (portfolio_page.py::holding_signal)와 다른 MVRV Z 경계를 쓰던 사고.
    z=1.8은 classify_regime() 기준 'bull'(45% 구간, 대시보드는 🟠로 표시) —
    카톡도 반드시 severity 1(주의)을 내야 하고, 예전처럼 severity 0으로
    조용히 넘어가면 안 된다."""
    row = {"buy_price": 133_952_455.0, "ticker": "BTC-USD"}
    sig_row = {"close": 65_972.0}
    z = 1.8
    assert classify_regime(z)["regime"] == "bull"
    severity, reasons = severity_for_holding(
        row, sig_row, mvrv_z=z, is_coin=True, is_etf=False, usdkrw=USDKRW,
    )
    assert severity == 1
    assert reasons


def test_alt_severity_matches_dashboard_action_text_for_every_regime():
    """rebalancing_page.py "보유 현황" 표(coin_holdings_action_text())가 매도(top)일
    때만 카톡도 severity 2, 나머지 국면(deep_value/accumulation/bull)에선
    대시보드가 매수/보유 우호를 보여주는 만큼 카톡도 severity 2를 내면 안 된다.
    2026-08-24 BB 신호 제거 후 회귀 방지용 — 이 관계가 깨지면 실패한다."""
    from scripts.crypto_analysis import coin_holdings_action_text

    row = {"buy_price": 25_631.0, "ticker": "SAND-USD"}  # G2 대상 아님, 손실 없음
    sig_row = {"close": 25_631.0 / USDKRW}  # 손익 0%
    for z, expect_sell in [(-1.0, False), (0.5, False), (1.8, False), (3.0, True)]:
        regime = classify_regime(z)["regime"]
        dashboard_text = coin_holdings_action_text("매도" if regime == "top" else "보유", None, regime)
        severity, reasons = severity_for_holding(
            row, sig_row, mvrv_z=z, is_coin=True, usdkrw=USDKRW,
        )
        dashboard_says_sell = "비중 축소 검토" in dashboard_text
        assert dashboard_says_sell == expect_sell  # 표에 정의된 그대로인지 자체 확인
        assert (severity == 2) == expect_sell, f"z={z} regime={regime}에서 카톡·대시보드 불일치"


def test_dedup_holding_alert_only_fires_on_severity_change():
    """2026-08-25: 손익 구간이 유지되기만 하면(악화·완화 없이) 매일 파이프라인이
    돌 때마다 같은 내용을 다시 보내던 문제 — severity가 실제로 바뀔 때만
    True를 반환해야 한다."""
    from scripts.check_alerts import _dedup_holding_alert

    assert _dedup_holding_alert(2, None) is True   # 처음 걸림 → 알림
    assert _dedup_holding_alert(2, 2) is False      # 어제와 동일 → 생략(중복 방지)
    assert _dedup_holding_alert(1, 2) is True        # 완화(매도 검토→주의) → 다시 알림
    assert _dedup_holding_alert(2, 1) is True        # 악화(주의→매도 검토) → 다시 알림
    assert _dedup_holding_alert(0, 2) is False        # 회복 — 애초에 알림 후보가 아님


def test_check_dedups_repeated_severity_across_runs(tmp_path, monkeypatch):
    """check() 전체를 두 번 호출했을 때, 같은 로트가 같은 severity를 유지하면
    두 번째 호출에선 alerts에서 빠져야 한다(회귀 방지 — 2026-08-25 오늘 코드
    푸시 4번 + 정기 스케줄 1번, 총 5번 daily-update.yml이 돌면서 매도 검토
    알림이 그대로 반복 발송된 실사고 재발 방지). 회복 후 재악화하면 다시
    뜨는 것까지 확인한다."""
    import scripts.check_alerts as ca

    (tmp_path / "holdings.csv").write_text(
        "ticker,qty,buy_price,buy_date,person,notes\n"
        "TESTX,10,10000,2026-01-01,tester,\n",
        encoding="utf-8",
    )
    summary_csv = tmp_path / "summary_signals.csv"

    monkeypatch.setattr(ca, "ROOT", tmp_path)
    monkeypatch.setattr(ca, "HOLDINGS", tmp_path / "holdings.csv")
    monkeypatch.setattr(ca, "SUMMARY", summary_csv)
    monkeypatch.setattr(ca, "COIN_SUMMARY", tmp_path / "coin_summary.csv")
    monkeypatch.setattr(ca, "CYCLE_METRICS", tmp_path / "cycle_metrics.csv")
    monkeypatch.setattr(ca, "HOLDING_ALERT_STATE", tmp_path / "holding_alert_state.json")

    summary_csv.write_text("ticker,close,rsi14,action\nTESTX,7000,50,매도\n", encoding="utf-8")  # -30%
    first = ca.check()
    assert len(first) == 1 and first[0]["severity"] == 2

    second = ca.check()  # 손실 그대로 유지
    assert second == []

    summary_csv.write_text("ticker,close,rsi14,action\nTESTX,9700,50,매수\n", encoding="utf-8")  # -3% 회복
    third = ca.check()
    assert third == []

    summary_csv.write_text("ticker,close,rsi14,action\nTESTX,7500,50,매도\n", encoding="utf-8")  # -25% 재악화
    fourth = ca.check()
    assert len(fourth) == 1 and fourth[0]["severity"] == 2


def test_format_trend_flips_uses_korean_name_and_shows_direction():
    """티커만 오면 못 알아본다는 사용자 피드백(2026-08-21) — 한글명을 반드시 병기해야 한다."""
    flips = [{"ticker": "ETH-USD", "from": "bull", "to": "bear"}]
    lines = format_trend_flips(flips)
    assert len(lines) == 1
    assert "이더리움" in lines[0]
    assert "ETH-USD" in lines[0]
    assert "bull" in lines[0] and "bear" in lines[0]
    assert "📉" in lines[0]  # bear 전환은 하락 방향 아이콘
