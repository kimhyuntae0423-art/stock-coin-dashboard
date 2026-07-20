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
| Core/Satellite 종목 분류 | `scripts/asset_allocation.py::classify_holdings()` | `rebalancing_page.py`, `portfolio_page.py` | core_etfs.csv에 없으면 전부 Satellite(코인 포함) |
| 주식 티커 목록 | `tickers.csv` | `run_analysis.py`, `stocks_page.py` | `scripts/config.py::TICKERS_FILE`이 있지만 `data_fetch.py`/`run_analysis.py`는 아직 이걸 안 쓰고 자체 상대경로 사용 — 동작은 정상(파일 위치 기준 상대경로라 안전), 통합은 미완 |
| 시장 국면 (VIX 기반, 5단계: fear/bull/mixed/bear/complacent) | `scripts/etf_recommend.py::market_regime()` | `etf_page.py`, `rebalancing_page.py`, `stocks_page.py` | 2026-07-20 stocks_page 통일(CNN F&G 대체). IC=+0.14 검증 |
| 로테이션 국면 (4단계: fear/recovery/expansion/overheated) | `scripts/etf_rotation.py::_REGIME_TO_PHASE` | `rebalancing_page.py::rotation_target()` | market_regime의 5단계를 4단계로 재매핑하는 유일한 지점 |
| ETF 리스크 버킷 배율 (공격/핵심/대안/방어 × VIX국면) | `scripts/etf_recommend.py::_BUCKET_WEIGHT` | `score_etfs()`, `tactical_alloc()` | 단일 정의, 중복 없음 (참고용 좋은 예시) |
| 허용/금지 신호 목록 (RSI 임계값, MVRV 구간, 섹터사이클 등) | `CLAUDE.md` "자산별 검증된 신호" 표 | 각 스크립트 주석에서 인용 | **문서가 SSOT** — 코드보다 여기가 먼저. 백테스트 함수는 `scripts/signal_validation.py` |
| 코인 MVRV Z-Score 구간 (0/1.5/2.5) | `scripts/onchain.py::classify_regime()` | `coin_page.py`, `run_analysis.py` → `coin_summary.csv` | 2026-07-20 통일 (예전엔 0/2/5/7 별도값 사용) |
| 코인 RSI 임계값 (과매도 25만 유효) | `scripts/signal_validation.py::run_coin_rsi_validation()` 결과 | `coin_page.py::recommend_score()`, `scripts/crypto_analysis.py::latest_crypto_signal()` | 2026-07-20 통일 |
| 매크로 레이더 3개 지표 방향(구리/금비율·수익률곡선·달러강도) | `scripts/etf_recommend.py::macro_signals()` | `etf_page.py` | 2026-07-20 백테스트(H17~H19)로 방향 검증·수정 |
| 보유종목 데이터 | `holdings.csv` | `portfolio_page.py`, `rebalancing_page.py` | person 컬럼으로 김현태/김보라 계좌 구분 |
| "보기/계산 대상" 사람 필터 | 각 페이지 자체 `session_state` 키 (`person_filter` / `rebal_person_filter`) | `portfolio_page.py`, `rebalancing_page.py` | **의도적으로 분리** — 2026-07-20 사용자 확인, 연동하지 않기로 결정. 실수로 "통일" 시도하지 말 것 |
| 종목별 기술적 신호 (과열신호/거래량신호/OBV) | `scripts/etf_recommend.py::technical_signals()`/`volume_signals()` — **주식·ETF 전용**(`results/{ticker}_signals.csv` 필요, bb_pct/macd_hist/obv 컬럼 기반) | `rebalancing_page.py`("보유 현황" 표, "🇰🇷 한국주식/ETF" 섹션), `scripts/etf_recommend.py::enrich_with_volume()` | **코인엔 못 씀** — 코인 시그널 파일(`coin_{ticker}_signals.csv`)엔 bb_pct/macd_hist/obv 컬럼 자체가 없음. 코인은 `coin_summary.csv`(rsi14/regime/action) 기반 전용 로직 사용 — 2026-07-20, "보유 현황" 표가 코인 티커를 그대로 이 함수들에 넘겨서 전부 빈 값→기본값 폴백되던 버그 발견·수정 (마침 보유 코인이 전부 큰 손실 중이라 우연히 같은 라벨로 안 들켰음). 새로 이런 종목별 신호 루프를 짤 때는 **항상 코인/주식 분기부터 확인**(`rebalancing_page.py:805`처럼 `-USD` 필터링) |
| **보유종목 "액션"(매수/보유/매도류) 판정** | `rebalancing_page.py` "보유 현황" 표(`_overheat_lbl`/`_action`, 코인은 `coin_summary.csv`의 `action`) | 같은 파일의 "📊 보유 종목 종합 분석" 익스팬더(🇰🇷 한국주식/ETF, 🪙 코인 섹션) | **2026-07-20 통합**: "종합 분석" 익스팬더가 technical_signals를 다시 불러와 다른 임계값(BB<0.2 vs 위 표 0.3, `state` vs `ma_score`)으로 액션을 재계산해서, 같은 종목·같은 시점에 두 표가 다른 결론을 내던 버그. 코인 쪽은 한술 더 떠 RSI<35/40(H20 백테스트로 이미 "무효" 판정난 임계값, 위 행 참고)을 썼음 — CLAUDE.md 위반. `_tbl`(위 표)의 계산 결과를 그대로 재사용하도록 통합. 앱 전체에서 "이 종목 사야 하나"를 계산하는 곳은 이제 여기(_tbl) + `portfolio_page.py::holding_signal()` 2곳뿐 — 둘은 페이지 성격이 달라(리밸런싱 vs 보유관리) 의도적으로 별개 유지 |

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
