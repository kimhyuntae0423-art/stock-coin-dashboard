# 아키텍처 — 크로스커팅 연계 맵

이 문서는 "여러 파일에 걸쳐 공유되는 하나의 개념인데, 자칫 여러 곳에서 따로
정의되기 쉬운 것들"을 추적한다. 목적: 한 곳을 고치면 나머지가 자동으로
맞춰지게(또는 최소한 어디를 같이 고쳐야 하는지 즉시 알 수 있게) 하기 위함.

**새 기능을 추가할 때**: 아래 표에 이미 비슷한 개념이 있는지 먼저 확인하고,
있으면 그 SSOT를 재사용한다. 새로운 크로스커팅 개념(여러 페이지/스크립트가
같은 정책성 숫자·티커 목록·문자열 키를 공유하게 되는 경우)을 만들었으면
이 표에 행을 추가한다. (이 파일 자체를 최신으로 유지하는 게 작업의 일부다.)

## 원칙

1. **정책성 숫자·문자열**(목표비중, 신호 임계값, session_state 키 이름)은
   반드시 단일 파일에서 정의하고 나머지는 import해서 쓴다. 절대 페이지에
   숫자를 다시 타이핑하지 않는다.
2. **파일 경로**는 `scripts/config.py` 하나에서만 선언한다.
3. **신호(백테스트로 검증해야 하는 것)**는 코드가 아니라 `CLAUDE.md`의
   "자산별 검증된 신호" 표가 SSOT다 — 새 신호를 코드에 추가하기 전에
   먼저 거기 등재(백테스트 근거 포함)한다.
4. 같은 개념이 페이지마다 다른 문자열 키(`session_state` key 등)를 쓰면
   안 된다 — 상수로 공유해서 오타/드리프트를 원천 차단한다.

## 연계 맵

| 개념 | SSOT (정의 위치) | 참조하는 곳 | 비고 |
|---|---|---|---|
| 목표 자산배분 (Core/Satellite/Cash) | `scripts/config.py` (`DEFAULT_TARGET_*`, `KEY_TARGET_*`) | `rebalancing_page.py`, `why_market_page.py`, `scripts/asset_allocation.py` | 2026-07-20 통일. BTC는 Satellite에 포함(별도 버킷 없음, 확정) |
| 파일 경로 (results/holdings/names/coin_names/core_etfs/tickers) | `scripts/config.py` | 전 페이지 | 2026-07-20 통일. 이전엔 페이지마다 `Path(__file__)...`로 재선언 |
| Core ETF 후보 목록 | `core_etfs.csv` (`scripts/config.py::CORE_ETF_FILE`) | `scripts/asset_allocation.py::load_core_etfs()`, `etf_page.py`, `rebalancing_page.py`, `scripts/etf_recommend.py` | |
| 코어 ETF 장기 가격 아카이브 (5년 롤링과 별도, 삭제 없이 누적) | `results/price_archive.csv` (`scripts/price_archive.py::update_archive()`) | `run_analysis.py::run_stocks()`가 매일 자동 append | 2026-07-24 신설 — `{ticker}_signals.csv`는 `yf.download(period="5y")`라서 오래된 날짜가 매일 자동으로 빠짐(코어 ETF 조합 백테스트 중 발견). 이 아카이브는 core_etfs.csv 후보군(40종목)만 대상으로 날짜 삭제 없이 계속 쌓여서, 시간이 지날수록 5년보다 긴 구간 백테스트가 가능해짐. 2026-07-24에 현재 5년치(2021-07-26~)로 최초 시드. 새 종목이 core_etfs.csv에 편입되면 그 시점부터만 쌓이기 시작 — 과거분은 자동 복구 불가, 필요 시 수동으로 보완 |
| Core/Satellite 종목 분류 | `scripts/asset_allocation.py::classify_holdings()` | `rebalancing_page.py`, `portfolio_page.py` | core_etfs.csv에 없으면 전부 Satellite(코인 포함) |
| 주식 티커 목록 | `tickers.csv` | `run_analysis.py`, `stocks_page.py` | `scripts/config.py::TICKERS_FILE`이 있지만 `data_fetch.py`/`run_analysis.py`는 아직 이걸 안 쓰고 자체 상대경로 사용 — 동작은 정상(파일 위치 기준 상대경로라 안전), 통합은 미완 |
| 시장 국면 (VIX 기반, 5단계: fear/bull/mixed/bear/complacent) | `scripts/etf_recommend.py::market_regime()` | `etf_page.py`, `rebalancing_page.py`, `stocks_page.py` | 2026-07-20 stocks_page 통일(CNN F&G 대체). IC=+0.14 검증 |
| 로테이션 국면 (4단계: fear/recovery/expansion/overheated) | `scripts/etf_rotation.py::_REGIME_TO_PHASE` | `rebalancing_page.py::rotation_target()` | market_regime의 5단계를 4단계로 재매핑하는 유일한 지점 |
| ETF 리스크 버킷 배율 (공격/핵심/대안/방어 × VIX국면) | `scripts/etf_recommend.py::_BUCKET_WEIGHT` | `score_etfs()`, `tactical_alloc()` | 단일 정의, 중복 없음 (참고용 좋은 예시) |
| 허용/금지 신호 목록 (RSI 임계값, MVRV 구간, 섹터사이클 등) | `CLAUDE.md` "자산별 검증된 신호" 표 | 각 스크립트 주석에서 인용 | **문서가 SSOT** — 코드보다 여기가 먼저. 백테스트 함수는 `scripts/signal_validation.py` |
| 코인 MVRV Z-Score 구간 (0/1.5/2.5, regime={deep_value,accumulation,bull,top,unknown}) | `scripts/onchain.py::classify_regime()` | `coin_page.py`, `run_analysis.py`→`coin_summary.csv`, `rebalancing_page.py`(보유현황 액션·리밸런싱 인사이트·코인 사이클 카드), `portfolio_page.py`(개별 코인 서술·사이클 온도계), `scripts/check_alerts.py`(BTC severity·BTC 사이클 카톡 알림) | 2026-07-20 통일(0/2/5/7→0/1.5/2.5). 2026-07-22 rebalancing_page.py·portfolio_page.py가 각자 이 경계를 재구현하며 일부는 존재하지 않는 regime 값(markup/distribution/markdown)으로 갈라졌던 것 발견·통일. **2026-08-21 감사에서 발견**: `scripts/check_alerts.py`가 이 SSOT를 안 쓰고 독자적인 `classify_cycle_stage()`(0/2/4/6 경계, NUPL·Pi Cycle까지 반영, 백테스트 근거 없음)로 BTC 사이클 카톡 알림을 보내서 같은 순간 대시보드와 다른 국면·다른 목표비중을 말하던 것 발견 — `classify_regime()` 재사용으로 통일, `classify_cycle_stage`/`STAGE_TEMPLATES` 제거 |
| 코인 regime 한글 라벨 | `scripts/onchain.py::REGIME_LABEL_KR` | `rebalancing_page.py`, `portfolio_page.py` | 2026-07-22 신설 — 위 항목의 5단계 regime 문자열을 표시용 한글 단어로 바꾸는 지점을 하나로 통일 |
| 코인 RSI 임계값 (과매도 25만 유효) | `scripts/signal_validation.py::run_coin_rsi_validation()` 결과 | `coin_page.py::recommend_score()`, `scripts/crypto_analysis.py::latest_crypto_signal()` | 2026-07-20 통일 |
| 코인 매수/매도 판단 문구 (보유현황 액션 · 리밸런싱 인사이트) | `scripts/crypto_analysis.py::coin_holdings_action_text()`/`coin_rebalance_insight()` | `rebalancing_page.py`("보유 현황" 표·"배분 현황" 인사이트), `portfolio_page.py::holding_signal()`, `scripts/check_alerts.py::severity_for_holding()` | 2026-07-22 신설 — 인라인으로 각자 떨어져 있어서 같은 코인에 반대 방향(매도 vs 매수) 문구가 동시에 뜨던 사고 이후 하나로 추출. `tests/test_coin_regime_consistency.py`가 두 함수의 방향 불일치를 회귀 테스트로 고정. **2026-08-24 감사에서 발견**: `portfolio_page.py::holding_signal()`와 `scripts/check_alerts.py::severity_for_holding()`가 이 SSOT와 무관하게 독자적인 "BB(%B)>1+RSI>70 → 매도" 신호를 알트코인에 따로 쓰고 있었음 — 코드 주석에 이미 "백테스트 승률 27%"(동전던지기보다 나쁨)라고 적혀 있던 신호였는데도 실제 매도 알림을 띄워서, 매집(accumulation) 구간이라 리밸런싱 페이지는 "매수 우호"인데 카카오·보유종목 페이지는 "매도 검토"를 동시에 보여주는 사고로 이어짐(사용자 실제 목격). 두 파일 모두 BB 신호(+alt "반등후보"도 pooled 승률 50%로 무근거)를 제거하고 이 SSOT(MVRV 국면 + G1/G2 손절 로드맵)만 쓰도록 통일. `tests/test_check_alerts.py::test_alt_severity_matches_dashboard_action_text_for_every_regime`가 회귀 방지 |
| 코인 정리 로드맵 그룹(G1/G2/G3)·G1·G2 개별손실 손절선(-40%/2027년말) | `scripts/crypto_analysis.py::COIN_EXIT_GROUPS`/`ALT_STOPLOSS_RECOVERY_PCT`/`coin_alt_stoploss_status()` | `rebalancing_page.py`("코인 정리 로드맵" 카드), `portfolio_page.py`(`holding_signal()`), `scripts/check_alerts.py`(카카오 알림) | 2026-07-22 신설(당시 이름 `coin_g1_exit_status`, G1·-60%만) → 같은 날 사용자 요청으로 -40%(19종목·10,940건 백테스트 근거, `scripts/backtest.py::backtest_loss_cut()`과 동일 방법론)로 조정하고 G2까지 확장, `coin_alt_stoploss_status`로 개명. G3(BTC·ETH·SOL)는 핵심 장기보유라 이 손절선 규칙 대상에서 명시적으로 제외 — MVRV 트리거로만 관리. `tests/test_coin_alt_stoploss_status.py` 참고. **2026-07-23 감사에서 발견**: `COIN_EXIT_GROUPS` 어디에도 없는 보유 코인(예: XRP-USD)은 로드맵 매도 규칙이 영구히 미적용인 채 조용히 빠짐 — `rebalancing_page.py`에 미분류 코인 경고(`_ungrouped_held`, 실제 보유 대비 그룹 목록 diff라 신규 코인 자동 감지)를 추가해 이 gap 자체는 재발해도 항상 감지됨. 단, `portfolio_page.py`의 🔵 레전드 카드(`_SIGNAL_DISPLAY`, ~726행) 문구는 `is_bounce`(488-492행)의 "G1만 제외" 조건을 **수동으로 옮겨적은 것**이라 자동 동기화 안 됨 — `is_bounce` 조건을 바꾸면 이 표의 문구도 반드시 같이 고칠 것 (2026-07-23, "43~79%만 G2·G3"이라는 과장 표기를 뒤늦게 발견해 수정한 전례) |
| 매크로 레이더 3개 지표 방향(구리/금비율·수익률곡선·달러강도) | `scripts/etf_recommend.py::macro_signals()` | `etf_page.py` | 2026-07-20 백테스트(H17~H19)로 방향 검증·수정 |
| 보유종목 데이터 | `holdings.csv` | `portfolio_page.py`, `rebalancing_page.py` | person 컬럼으로 김현태/김보라 계좌 구분 |
| "보기/계산 대상" 사람 필터 | 각 페이지 자체 `session_state` 키 (`person_filter` / `rebal_person_filter`) | `portfolio_page.py`, `rebalancing_page.py` | **의도적으로 분리** — 2026-07-20 사용자 확인, 연동하지 않기로 결정. 실수로 "통일" 시도하지 말 것 |
| 종목별 기술적 신호 (과열신호/거래량신호/OBV) | `scripts/etf_recommend.py::technical_signals()`/`volume_signals()` — **주식·ETF 전용**(`results/{ticker}_signals.csv` 필요, bb_pct/macd_hist/obv 컬럼 기반) | `rebalancing_page.py`("보유 현황" 표, "🇰🇷 한국주식/ETF" 섹션), `scripts/etf_recommend.py::enrich_with_volume()` | **코인엔 못 씀** — 코인 시그널 파일(`coin_{ticker}_signals.csv`)엔 bb_pct/macd_hist/obv 컬럼 자체가 없음. 코인은 `coin_summary.csv`(rsi14/regime/action) 기반 전용 로직 사용 — 2026-07-20, "보유 현황" 표가 코인 티커를 그대로 이 함수들에 넘겨서 전부 빈 값→기본값 폴백되던 버그 발견·수정 (마침 보유 코인이 전부 큰 손실 중이라 우연히 같은 라벨로 안 들켰음). 새로 이런 종목별 신호 루프를 짤 때는 **항상 코인/주식 분기부터 확인**(`rebalancing_page.py:805`처럼 `-USD` 필터링) |
| **보유종목 "액션"(매수/보유/매도류) 판정** | `rebalancing_page.py` "보유 현황" 표 하나(`_overheat_lbl`/`_action`, 코인은 `coin_summary.csv`의 `action`) | (과거엔 "📊 보유 종목 종합 분석" 익스팬더가 별도로 있었음) | **2026-07-20 통합 → 그 다음 표 자체를 병합**: 처음엔 "종합 분석" 익스팬더가 technical_signals를 다시 불러와 다른 임계값(BB<0.2 vs 위 표 0.3, `state` vs `ma_score`)으로 액션을 재계산해서 같은 종목·같은 시점에 두 표가 다른 결론을 내던 버그를 발견 → `_tbl` 계산 재사용으로 1차 통합 → 그래도 "기술등급=과열신호", "분석액션=액션"이 값만 같고 컬럼명만 다르게 중복 표시되는 게 남아있어서, 아예 익스팬더를 없애고 "보유 현황" 표 하나에 추세/국면·RSI·모멘텀(%) 컬럼을 추가하는 걸로 최종 병합. 앱 전체에서 "이 종목 사야 하나"를 계산하는 곳은 이제 이 표 + `portfolio_page.py::holding_signal()` 2곳뿐 — 둘은 페이지 성격이 달라(리밸런싱 vs 보유관리) 의도적으로 별개 유지 |
| **총수익률/연환산수익률(CAGR) 계산 공식** | `scripts/returns.py::compute_returns(f_, l_, days)` | `why_market_page.py::load_returns()`, `backtest_page.py::load_vs_market()` | **2026-07-21 통합**: `/code-review ultra` 로컬 리뷰에서 같은 공식이 4곳(같은 파일 내 `_ret`/`_bench` 2곳 × 2파일)에 문자 그대로 중복돼 있던 걸 발견 — 공용 헬퍼로 추출. 시작가 0 이하/종가 음수/기간 0 이하면 `None` 반환(예전엔 `ZeroDivisionError`나 복소수→`round()` `TypeError`로 페이지가 죽었음). 단위테스트: `tests/test_returns.py`. `backtest_page.py`의 벤치마크 계산이 여전히 전체 구간 단일 창(글로벌 min/max)을 쓰는 문제는 이번 범위 밖 — 아래 "알려진 잔여 항목" 참고 |
| **벤치마크 수익률 — 종목별 보유기간 매칭** | `why_market_page.py::load_returns()`의 `_bench_matched()` → `df["bench_ann"]` 컬럼 | `why_market_page.py` 섹션 1(승/패 카운트)·섹션 2·3(막대 색상) | **2026-07-21**: 예전엔 벤치마크를 전체 종목 통합 구간(min~max) 하나로만 계산해서, 종목마다 다른 시장 국면과 비교되는 문제가 있었음(연환산 전환만으론 기간 "길이" 차이만 상쇄, 국면 자체는 안 맞음). 이미 받아둔 벤치마크 슈퍼셋 시계열(`bench_close`)을 종목별 `[start,end]`로 슬라이싱하는 방식으로 추가 API 호출 없이 해결. 헤드라인 카드·차트 기준선은 여전히 전체기간 값(`benchmarks[cat]["ann_ret"]`)을 "참고"로 표시 — 실제 승/패 판정만 매칭값(`bench_ann`) 기준 |
| **보유 내역 편집기(추가/수정 UI)** | `portfolio_page.py`("✏️ 보유 내역 추가/편집")와 `rebalancing_page.py`("✏️ 보유 내역 관리") — 편집기 UI 자체는 각 파일에 독립 구현(테이블 컬럼 구성이 다름), **buy_date 파싱/저장만** `scripts/holdings_io.py::parse_buy_dates()`/`format_buy_dates()`가 SSOT | `holdings.csv` 저장 | **2026-07-21 두 파일에서 각각 같은 클래스의 버그 발견·수정**: (1) `buy_date` 입력 컬럼이 UI에 아예 없어서 저장할 때마다 무조건(또는 행 개수 바뀔 때만) 전체 매수일이 빈 값으로 덮어써짐 → 양쪽 다 `st.column_config.DateColumn` 추가 + 실제 편집값을 그대로 저장하도록 수정. (2) CASH 합계가 "👤 계산 대상" person 필터 적용 **전에** 미리 전체 합산돼서, 특정 사람만 선택해도 배우자 현금까지 섞여 나옴 → 필터 적용 후 계산하도록 순서 변경(사용자 확인: "선택한 사람 것만 나와야 함"). 같은 세션에서 같은 패턴이 두 번 독립 재발한 걸 확인하고, buy_date 파싱/저장 2줄만 공용 헬퍼로 추출(편집기 전체 통합은 페이지 성격이 달라 비권장 — 개선-검증 반복 라운드에서 확정) |
| **12-1M 모멘텀(진짜 계산)** | `scripts/factor_calc.py::momentum_12_1()` → `enrich_price_factors()`가 `mom_12_1` 컬럼 생성 → `scripts/stock_score.py::rank_stocks_v3()`가 `z_momentum`/`momentum_score`로 변환 | `stocks_page.py`(모멘텀 분위, "12-1M 모멘텀" 표시 컬럼) | **2026-07-21 버그 발견·수정**: `stocks_page.py::_add_mom_quartile()`가 이미 계산된 `z_momentum`을 쓰지 않고 `return_12m_pct - return_1m_pct`로 **완전히 다른(틀린) 값**을 자체 계산해서 "매수 우선순위"·"통합 추천" 정렬 기준으로 썼음 — 지난달 폭락한 종목일수록 이 값이 커져서 오히려 모멘텀 상위로 뽑히는 반대 결과. `z_momentum` 재사용으로 수정. **모멘텀 관련 새 계산을 추가할 때는 항상 `mom_12_1`/`z_momentum`이 이미 있는지부터 확인, `return_12m_pct`/`return_1m_pct`를 직접 조합하지 말 것** |
| **pyarrow 직렬화 안전성 (st.dataframe에 넘기는 표)** | 컬럼이 결측(NaN)과 bool/str이 섞인 object dtype이면 `st.dataframe()`이 내부적으로 크래시 후 자동복구(로그에 Traceback 남음, 화면엔 안 보임) | `backtest_page.py`(손절선 상세표, `groupby().agg(lambda x: x.sum())`), `stocks_page.py`(종목 비교표, `pd.DataFrame(dict).T`) | **2026-07-21 같은 원인으로 2곳에서 독립 발견**: (1) NaN 섞인 bool 컬럼을 `.sum()`하면 그룹에 값이 1개뿐일 때 합산 없이 원본 bool을 그대로 반환해 int/bool 혼합 → `.fillna(False).astype(bool).sum()`로 항상 int 반환하게 수정. (2) 일부 컬럼만 문자열로 포맷하고 나머지는 raw int로 남긴 채 `.T`로 전치하면 같은 컬럼(전치 후 티커별)에 str/int가 섞임 → 전부 `fmt()` 헬퍼로 문자열화. **표에 넣을 컬럼은 전부 같은 타입(전부 문자열 또는 전부 순수 숫자)으로 맞출 것 — 특히 `.agg(lambda ...)`나 `.T` 전치를 쓸 때 주의** |

## 신규 기능 추가 시 체크리스트

1. 이 표에서 비슷한 개념이 이미 있는지 검색한다.
2. 있으면 그 SSOT를 확장해서 쓴다 — 새 파일/새 상수를 만들지 않는다.
3. 없고, 정책성 숫자/문자열이면 → `scripts/config.py`에 상수로 추가.
   목록성 데이터(티커 등)면 → CSV 파일 + `scripts/config.py`에 경로 상수 추가.
   신호(백테스트 필요한 것)면 → `CLAUDE.md` 표에 먼저 등재.
4. 다른 페이지가 이 값을 다시 하드코딩하고 싶은 유혹이 들면, 그 페이지는
   반드시 SSOT를 import하게 만든다.
5. 이 표에 새 행을 추가한다.

## 알려진 잔여 항목 (일부러 안 건드림)

- `scripts/data_fetch.py::fetch_tickers()` / `run_analysis.py`가 `scripts/config.py::TICKERS_FILE`을
  안 쓰고 자체 상대경로(`"../tickers.csv"`, 모듈 파일 기준 — CWD 기준 아님, 정상 동작 확인함)를 씀.
  당장 깨진 건 아니라 우선순위 낮음.
- `backtest_page.py::load_vs_market()`의 `_bench()`가 여전히 전체 종목 통합 구간(min~max) 하나로
  벤치마크를 계산 — `why_market_page.py`에 2026-07-21 적용한 "종목별 보유기간 매칭" 방식이
  이 페이지엔 아직 적용 안 됨. 이번 수정 범위 밖(해당 diff가 이 페이지를 안 건드림)이라 의도적으로
  보류. 이 페이지의 승률 지표를 신뢰도 있게 쓰려면 나중에 같은 패턴 적용 필요.
