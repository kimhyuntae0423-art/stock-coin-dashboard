# 페이지별 기능 명세

`주식.py`(st.navigation 라우터)가 아래 7개 페이지를 로드한다. 각 섹션은 "이 페이지가
실제로 하는 일"의 목록이다 — 코드가 바뀌면 이 문서도 같이 갱신할 것.
크로스커팅 개념(여러 페이지가 공유하는 값·공식)은 여기 말고 `ARCHITECTURE.md`가 SSOT다.

## 1. why_market_page.py — "투자 대원칙" (기본 진입 페이지)

- **핵심 구조 배너**: Core/Satellite/Cash 목표비중 카드(세션 상태 `_t_core` 등 반영,
  `scripts/config.py` 기본값)
- **섹션 1 "시장을 이긴 종목은 몇 개였을까?"**: US/KR/Coin 카테고리별 승률 카드
  (`load_returns()` → 종목별 매칭기간 연환산수익 vs 벤치마크)
- **섹션 2 미국 주식 수익률 분포 차트**: 종목별 막대그래프, 벤치마크(S&P500) 기준선
- **섹션 3 코인 수익률 분포 차트**: 알트코인 vs BTC 막대그래프
- **섹션 4 "전문가도 못 이긴다"**: SPIVA 통계·버핏 인용·Core 비중 카드
- 데이터 소스: `results/*_signals.csv`, `results/coin_*_signals.csv`, yfinance(SPY/069500.KS/BTC-USD)

## 2. portfolio_page.py — "보유 종목"

- **✏️ 보유 내역 추가/편집**: `st.data_editor`(종목명/티커/수량/매수가/매수일/이름/메모),
  💾 저장 시 로컬 저장 + GitHub push
- **📊 현황 + 매도 신호**: 사람 필터 적용된 보유 종목 표, 원금/평가금액/손익/보유현금 메트릭
- **자산유형 판별**: 코인(`-USD`)/ETF(`core_etfs.csv`)/개별주 분류
- **`holding_signal()`**: 종목별 매수/보유/매도 판정(개별주는 RSI 과열 신호 미사용,
  CLAUDE.md 준수)
- **📋 자산별 상세 리포트**(종목별 expander): 핵심 지표 카드(RSI/추세/MACD/BB),
  강세·약세 근거 리스트(`_bull_items`/`_bear_items`), 종합 의견 합성 텍스트
- 데이터 소스: `holdings.csv`, `results/{ticker}_signals.csv`, `results/coin_summary.csv`

## 3. rebalancing_page.py — "리밸런싱"

- **✏️ 보유 내역 관리**: portfolio_page와 별도 구현된 편집기(동일 패턴, 코드 공유 없음)
- **📊 포트폴리오 전반 인사이트**: 시장 국면 배너, 매크로 레이더 요약
- **💼 보유 현황**: 통합 표(추세/국면·RSI·모멘텀·과열신호·액션) — 코인/주식 분기 처리
- **📊 배분 현황 & 리밸런싱**: 목표 대비 편차, 추가 매수/매도 금액 계산, 종목별 인사이트 문구
  (코인은 regime+RSI≤25, 주식/ETF는 기술적 신호 기반)
- **🏛️ 코어 ETF 매수 후보 순위** / **🎯 위성 매수 후보**: 전술비중·냉각지수 기반 순위표
- **📋 월별 비중 변화 이력**: `holdings_snapshots.json`에 스냅샷 저장/조회("📸 이번 달 비중 저장")
- **🚪 코인 비중 축소 로드맵**: 목표 대비 코인 초과분 단계별 매도 계획
- 데이터 소스: `holdings.csv`, `results/summary_signals.csv`, `results/coin_summary.csv`,
  `holdings_snapshots.json`

## 4. backtest_page.py — "신호 백테스트"

4개 탭:
- **탭1 요약**: 검증/폐기/보조 신호 3분류 카드, 전체 판정표, 핵심 인사이트 3가지,
  변경 이력 표 (`_load_sum()` — 7개 backtest CSV 집계, 실패 시 "확인 필요" 표시)
- **탭2 전략 백테스트**: 코어 ETF 로테이션(VIX국면×5역할), H15 상대저점 전략,
  학술 전략(Dual Momentum/Risk Parity/GTAA), 팩터 전략(모멘텀/저변동성/가치/퀄리티),
  코인 전략(MVRV/모멘텀/BTC+ETH 리밸런싱)
- **탭3 개별주 vs 시장**: Buy&Hold 비교, 골든/데스크로스 검증, RSI 신호 검증,
  손절선(-8%/-20%) 검증
- **탭4 신호 예측력 연구**: H1~H20 가설별 상세 검증(추천시스템·상대저점·매크로레이더·
  코인RSI 등)
- 데이터 소스: `results/backtest/*.csv`, `results/rotation_*.csv`

## 5. etf_page.py — "코어 ETF (참고)"

- **🌐 매크로 레이더**: 구리/금비율·수익률곡선·달러강도 3지표
- **시장 국면 배너**: VIX 기반 5단계
- **🎯 ETF 배분 점수**: Top5 카드(냉각지수 기준 정렬), 과열신호 캡션
- **수익률 비교 차트**, **전체 목록 표**
- 데이터 소스: `core_etfs.csv`, `scripts/etf_recommend.py`(market_regime/score_etfs/
  technical_signals/macro_signals)

## 6. stocks_page.py — "주식 분석 대시보드 (참고)"

3개 탭:
- **탭1 요약&추천**: 통합 추천(펀더 QVGM + 12-1M 모멘텀 결합), 매수 우선순위 TOP5,
  용어 사전 expander, 로직 설명 expander
- **탭2 종목 비교**: 레이더 차트 + 상세 지표 비교표(전치 테이블)
- **탭3 종목 상세**: 개별 종목 팩터 점수(V/Q/G/M/T), 밸류에이션 카드
- 데이터 소스: `results/summary_signals.csv`, `results/fundamentals.csv`,
  `scripts/stock_score.py`(rank_stocks_v3), `scripts/factor_calc.py`(mom_12_1)

## 7. coin_page.py — "코인 분석 대시보드 (참고)"

- **🧠 코인 시장 심리**: Crypto Fear & Greed Index
- **🎯 종합 매매 신호**: 5개 지표 합성(regime/MVRV/RSI/알트시즌/모멘텀)
- **🪙 Altcoin Season Index**
- **💰 매수 우선순위 추천**: `recommend_score()` — MVRV·RSI≤25만 사용, 90일 모멘텀
  보정(미검증 임계값, 낮은 우선순위 이슈로 남아있음)
- **📐 MVRV Z-Score 히스토리 차트**, **🥧 Pi Cycle Top Indicator**
- **🔍 코인별 상세 분석**
- 데이터 소스: `results/coin_summary.csv`, `results/cycle_metrics.csv`,
  `results/mvrv_history.csv`, `scripts/onchain.py`

---

## 디버그 이력 (이 문서 기준 순차 점검)

| 순서 | 페이지 | 상태 | 비고 |
|---|---|---|---|
| — | 주식.py | 확인 완료 (2026-07-21) | 라우터, 이상 없음 |
| 1 | why_market_page.py | **완료 (2026-07-21)** | 신규 발견: `rows`가 비면(모든 신호 CSV 로드 실패) `load_returns()` 내부 `df["start"]`에서 KeyError 크래시 — 빈 df를 안전 반환하도록 가드 추가. 그 외 재확인한 로직(섹션1~4, bench_ann 매칭, beat_results 연동)은 이상 없음 |
| 2 | portfolio_page.py | **완료 (2026-07-21)** | 신규 발견: `ASSET_LABEL_TO_TICKER`/`ASSET_LABELS`가 완전히 동일한 계산으로 2번 정의(죽은 중복) — 제거. `holding_signal()`/종합의견/CASH/편집기는 오늘 이미 수정된 상태 재확인, 이상 없음. `_rsi_label()`(표 컬럼용 "RSI(과열)" 태그)은 raw 지표 표시일 뿐 매수/매도 판단에 안 쓰여서 CLAUDE.md 위반 아님 — 손대지 않음 |
| 3 | rebalancing_page.py | **완료 (2026-07-21)** | 오늘 이전 수정(buy_date/코인RSI/연산자우선순위/CASH) 전부 재확인, 이상 없음. 추가로 확인: 월별 스냅샷 저장/로드(`_snap_upsert` 같은 달 덮어쓰기, `_snap_save` 실패시 로컬폴백 후 사용자에게 정확히 경고 표시) 정상. "코인 비중 축소 로드맵"은 이미 person 필터 적용된 `holdings`를 쓰므로 별도 필터링 불필요, 정상. `summary_signals.csv`에 보유 종목 가격 결측 시 조용히 0원 처리되는 방어적 허점 있으나 현재 데이터로는 안 터짐(낮은 우선순위, 미조치) |
| 4 | backtest_page.py | **완료 (2026-07-21)** | 오늘 수정(가짜숫자→확인필요, pyarrow bool/int 크래시) 재확인 — 전체 실행 시 트레이스백 완전히 사라짐(수정 전엔 있었음). 25곳의 `st.dataframe()` 호출을 훑어 동일 클래스의 dtype 혼합 위험이 더 있는지 확인, 추가 발견 없음(대부분 CSV 직접 읽기라 컬럼 dtype 일관됨) |
| 5 | etf_page.py | **완료 (2026-07-21)** | 오늘 수정(과열신호 문자열매칭)한 2곳 재확인 정상. 신규 발견: 요약 메트릭의 "12M 최고/최저" 카드가 `_valid.empty` 기준으로 가드했는데 실제 접근하는 건 `_all`을 다른 컬럼(`return_12m_pct`)으로 dropna한 `_best12` — 두 데이터프레임이 달라서 이론상 `_valid`는 비어있지 않은데 `_best12`만 비어있으면 IndexError 가능 → `_best12.empty` 기준으로 가드 변경 |
| 6 | stocks_page.py | **완료 (2026-07-21)** | 오늘 수정(모멘텀 공식, 종목비교표 pyarrow) 재확인 정상. 신규 발견 2건: (1) 종목 상세 탭에서 `summary`엔 있지만 `score_disp`엔 없는 티커(펀더멘털 결측 등) 선택 시 `.iloc[0]` IndexError 가능 → 가드 추가. (2) 간이 백테스트가 `ma200` 계산에 필요한 200일치 데이터 없는 신규 티커에서 `df_bt.iloc[-1]` IndexError 가능(현재 데이터로는 전 종목 안전하지만 신규 상장/신규 추가 티커에서 터질 수 있음) → 가드 추가 |
| 7 | coin_page.py | **완료 (2026-07-21)** | `recommend_score()`의 90일 모멘텀 보정(−30%/+100%, 무근거 하드코딩)을 CLAUDE.md "일관성 원칙"(근거 없으면 추가 금지)에 따라 제거 — 같은 함수의 RSI≤25 가산은 H20(51~54%) 인용이 있는데 이 항목만 백테스트 인용이 전혀 없었음. `sel`/`rec_row`/`row` 조회는 전부 `summary` 기준으로 일관돼 있어 IndexError 위험 없음(다른 페이지와 달리 별도 merge/필터 파이프라인 없음) |

(2026-07-21 이전 라운드에서 6개 페이지 병렬 점검으로 11개 버그 이미 수정 — `ARCHITECTURE.md`
연계 맵 및 각 파일 커밋 이력 참고. 이번 라운드는 그 이후 남은 부분·새 회귀를 순차적으로
더 깊게 재점검한다.)

## 2026-07-22 라운드 — 7개 페이지 병렬 감사 (맥락 없는 독립 에이전트, 실제 데이터 재현)

사용자가 "못믿겠어, 페이지 별로 디버그해줘"라고 요청 — 같은 날 있었던 코인 regime
SSOT 통일 작업(rebalancing_page.py/portfolio_page.py) 이후 회귀가 없는지, 그리고
평소 디버그 사이클에서 놓친 게 없는지 7개 페이지 전체를 맥락 없는 병렬 에이전트로
재검증. 발견·수정된 실제 버그:

- **why_market_page.py**: 벤치마크 티커(SPY/069500.KS/BTC-USD)가 종목 목록에 안 걸러져
  자기 자신과 비교되던 통계 왜곡, `yf.download` 미가드 크래시, `beat_results["Coin"]`
  KeyError 위험 — 3건 수정
- **rebalancing_page.py**: "코인 정리 로드맵" 카드의 개별손실/데드라인 규칙(lvl=0)이
  렌더링 로직상 구조적으로 절대 🔔가 안 켜지던 버그(`coin_alt_stoploss_status()`가
  이 파일에서 한 번도 호출 안 되고 있었음, ARCHITECTURE.md는 연결됐다고 잘못 기록) — 수정
- **portfolio_page.py + scripts/crypto_analysis.py**: `coin_alt_stoploss_status()`에
  하한이 없어서 G1·G2 코인이 -1% 같은 사소한 손실에도 "매도 권장"이 뜨는 **critical**
  버그(오늘 보유 코인이 전부 -40%보다 깊이 물려 있어 우연히 안 드러남) — 하한
  -20%(백테스트 검증 구간의 얕은 경계) 추가. 문구 중복, 신규 🟡 신호 범례 누락도 수정
- **backtest_page.py**: H15 전략 카드 `.iloc[0]`가 `.empty` 체크보다 먼저 실행되던
  IndexError, `load_vs_market()`의 `df["start"]` KeyError(빈 rows) — 2건 수정
- **etf_page.py**: `_regime.get("vix", 0.0)`가 값이 None일 때 기본값이 안 먹혀
  `TypeError`로 페이지 전체가 죽던 버그, `score_etfs()` 매칭 실패 시 `enrich_with_volume()`
  KeyError, 검증 실패 신호 OBV(%)가 다른 신호의 IC(+0.04)를 잘못 빌려 쓰며 남아있던 것
  (rebalancing_page.py는 이미 제거) — 3건 수정
- **stocks_page.py + portfolio_page.py**: 12-1M 모멘텀 Q1 백테스트 수치가 4곳에
  "+45.9%"로 하드코딩돼 있었는데 매일 자동 갱신되는 실제 값(당시 +40.2%)과 어긋남 —
  `scripts/stock_score.py::load_mom_q1_ann_pct()` 신설로 통일
- **coin_page.py**: RSI≥80 "상승지속" 문구가 BTC/알트 구분 없이 전부에 뜨던 것
  (CLAUDE.md는 BTC 한정, portfolio_page.py는 이미 알트를 다르게 처리 중) — 게이팅 추가.
  `scripts/onchain.py` 문서의 존재하지 않는 `_mvrv_zone` 참조 정리. `recommend_score()`
  매수 순위가 실제 보유 중인 G1·G2 손절 로드맵 상태를 몰라서 "대기" 코인을 Top5에
  올릴 수 있던 잠재 모순 — 점수는 안 건드리고 로드맵 상태를 병기하는 방식으로 완화

전부 실제 데이터/재현 스크립트로 검증 후 수정, pytest 87건 전부 통과.
