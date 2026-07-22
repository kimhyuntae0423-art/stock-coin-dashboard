# 1인 투자 하우스 — 프로젝트 컨텍스트

이 저장소는 사용자(개인 투자자)의 주식 분석 + 의사결정 보조 도구입니다.
Streamlit 대시보드(QVGM 점수, 골든크로스, 코인 온체인 지표, 보유종목)와
**리서치/분석/판단 보조 AI 에이전트 5개**로 구성됩니다.

## ⚠️ 절대 규칙: 크로스커팅 값은 `ARCHITECTURE.md`부터 확인

정책성 숫자(목표비중 등)·파일 경로·session_state 키처럼 여러 페이지가 공유하는
값을 새로 만들거나 수정하기 전에 **반드시 `ARCHITECTURE.md`의 연계 맵을 먼저 확인**한다.
이미 있는 개념이면 그 SSOT를 재사용하고, 새 크로스커팅 개념을 만들었으면
`ARCHITECTURE.md`에 행을 추가한다. 페이지에 숫자/경로를 직접 다시 타이핑하지 않는다.
(2026-07-20: 목표비중이 3개 파일에 63/15/15/7, 80/10/10, 70/20/10으로 제각각
박혀 있던 걸 발견하고 이 문서 체계를 만듦 — 재발 방지용.)

---

## ⚠️ 절대 규칙: 신호·인사이트는 백테스트 검증된 것만 사용

**이 규칙은 대시보드 코드·분석 텍스트·인사이트 카드 모두에 적용된다. 위반 금지.**

### 자산별 검증된 신호 (사용 가능)

| 자산 | 허용 신호 | 근거 |
|---|---|---|
| **코인** | `regime` (coin_backtest.py 결과) | accumulation/markup/distribution/markdown |
| **코인** | MVRV Z-score 구간 | <0: 바닥, 0~1.5: 저평가, 1.5~2.5: 경계, >2.5: 과열. scripts/onchain.py가 0/2/5/7 구간을 써서 이 표와 어긋나 있었음 — 2026-07-20 코드 수정으로 통일 |
| **코인** | 알트 시즌 점수 | <25: BTC 시즌, >75: 알트 시즌 |
| **코인** | RSI<=25 과매도 (H20) | 1M/3M 적중률 51~54% ⚠️ 약함. run_coin_rsi_validation 검증 — 2026-07-20 |
| **코인(BTC 한정)** | RSI>=70 상승지속 참고(과열 아님) | ⚠️ H20은 코인 전체(BTC+알트)를 풀링한 결과(과매수 34~47%, 역방향)라 BTC 단독 재검증은 아님 — portfolio_page.py에서 BTC만 예외 취급 중이나 근거가 약함, 향후 BTC 단독 백테스트 권장 — 2026-07-21 |
| **ETF/주식** | VIX 국면 (market_regime) | IC=+0.14, p<0.001 ✅ 강력 검증 |
| **ETF/주식** | 냉각지수 H15 (BB+MA 혼합) | IC=+0.087, p<0.001 ✅ 검증 |
| **ETF/주식** | 수익률곡선 (TLT 1M-SHY 1M, H18) | IC=+0.25, p<0.001 ✅ 검증. 안전자산선호 높을수록 SPY 향후수익 낮음 |
| **ETF/주식** | 달러강도 (DXJ 1M-VEU 1M, H19) | IC=+0.16, p=0.007 ✅ 검증. 강달러일수록 SPY 향후수익 높음 |
| **ETF/주식** | 구리/금비율 역방향 (H17) | IC=-0.37, p<0.001 ✅ 강력 검증(역방향). 구리 과열=SPY 향후수익 낮음. 기존 "성장기대=긍정" 라벨은 오류였음 — 2026-07-20 수정 |
| **공통** | RSI < 30 이탈 (과매도) | 5일 적중률 58% ✅ |

### 검증 실패 — 절대 사용 금지

| 신호 | 이유 |
|---|---|
| ETF bull/bear state | IC=**-0.047** (역방향) — 쓸수록 손해 |
| RSI > 70 과매수 기준 (주식) | 5일 적중률 47% (동전던지기보다 나쁨). scripts/stock_score.py의 overheat_penalty(), portfolio_page.py의 holding_signal() 개별주 severity에 남아있던 것 2026-07-20 제거 |
| RSI > 73/80 기준 (주식) | 5일 적중률 41% ❌ |
| RSI 35/38/40 과매도 (주식) | 미검증 임계값 — RSI 30만 유효 |
| 코인 RSI>70/75/80 과매수 (H20) | 1M 적중률 44.5%/39.1%/34.3% — 임계값 높을수록 더 나쁨(역방향). 2026-07-20 coin_page.py·crypto_analysis.py에서 제거 |
| 코인 RSI<=30/35 과매도 | 적중률 41.8~52.3%로 25보다 약함/무효 — 25만 채택 |
| 섹터사이클 배율 | IC=-0.023, p=0.34 ❌ 예측력 없음 |
| 모멘텀 단독 신호 | IC=+0.019, p=0.61 ❌ 예측력 없음 |
| ret1m < -10/-15 기준 | 미검증 임계값 |
| OBV 10일 추세 (H3) | IC=-0.014(1M)/-0.022(3M), 적중률 49.4% ❌ 사실상 역방향·무예측력. rebalancing_page.py "보유 현황" 표의 "OBV(%)" 컬럼 2026-07-22 제거(점수엔 원래 안 들어갔었음, 표시만 삭제) |

### 일관성 원칙
- **자산별로 다른 신호를 쓰는 것은 허용** (코인은 regime, ETF는 VIX 국면)
- **같은 자산에 대해서는 대시보드 전체에서 동일한 기준 적용** (한 곳에서 RSI 30 쓰면 모든 곳에서 RSI 30)
- **새 신호를 추가하려면 results/backtest/ 에서 근거 먼저 확인** — 근거 없으면 추가 금지
- **소스**: `results/backtest/rsi_signals.csv`, `cross_signals.csv`, `coin_mvrv_zones.csv`, `scripts/etf_recommend.py` 주석
- **정책성 숫자(목표비중 등)는 scripts/config.py가 유일한 소스** — 페이지마다 하드코딩 금지.
  Core-Satellite-Cash 3버킷 구조 확정(코인/BTC는 Satellite에 포함, 별도 버킷 없음).
  `DEFAULT_TARGET_CORE/SATELLITE/CASH`, `KEY_TARGET_*` 상수를 모든 페이지가 import해서 씀 — 2026-07-20

---

## 절대 원칙 (모든 에이전트 공통)

1. **확정적으로 "사라/팔아라/무조건 오른다"고 말하지 않는다.** 분석 보조다.
2. **AI 투자는 종목 추천이 아니라 의사결정 과정 개선이다.**
3. **데이터 ≠ 의견** — 두 가지를 구분해서 출력한다.
4. **모르는 숫자는 만들지 않는다.** 모르면 "확인 필요"로 명시.
5. **반대 논리(부정 시나리오)를 반드시 함께 제시한다.**
6. **최고의 수익률 찾기보다 최악의 행동 피하기를 우선한다.**
7. 매 분석 마지막에 다음 문장을 그대로 포함:
   > 이 분석은 투자 판단을 돕기 위한 의사결정 보조 자료이며, 최종 매수·매도 결정은 공식 공시, 최신 실적, 본인의 투자 기간과 위험 감내 범위를 확인한 뒤 내려야 합니다.

---

## 의사결정 프레임워크: WRAP

모든 깊이 있는 분석은 WRAP 구조를 따른다.

- **W** Widen Options — 종목/섹터만 좁게 보지 말고 대안·경쟁사·밸류체인 위아래 함께
- **R** Reality-test Assumptions — 사용자의 가정을 데이터로 검증·반박
- **A** Attain Distance — 매매 결정 전 감정 분리 질문
- **P** Prepare to Be Wrong — 틀릴 조건, 매도/추가매수 금지 신호 명시

---

## 에이전트 라우팅 (메인 Claude의 위임 규칙)

사용자 발화에서 의도가 명확하면 적절한 서브에이전트(`subagent_type`)로 위임한다.
여러 에이전트를 **병렬로** 호출해도 된다 (예: 종목 분석 + 섹터 컨텍스트 동시).

| 사용자가 묻는 것 | 위임 대상 | 키워드 예시 |
|---|---|---|
| 섹터·산업·테마·밸류체인 분석 | `sector-analyst` | "반도체 섹터", "AI 밸류체인", "방산 어때" |
| 특정 기업 심층 분석 | `company-analyst` | "삼성전자 분석", "AAPL 어때", "엔비디아 봐줘" |
| 실적 발표 전·후 분석 | `earnings-watcher` | "다음 주 실적", "컨센서스", "어닝 프리뷰" |
| 매매 결정·감정·급락 대응 | `decision-coach` | "팔까", "손절해야 해?", "폭락했는데", "추가매수?" |
| 투자 기록·모닝 노트·백테스트 | `journal-keeper` | "기록해줘", "모닝 노트", "백테스트", "이 종목 등록" |

**라우팅 원칙**:
- 단순 사실 질의(현재가/PER 등 단답): 인라인 처리 (results/ CSV 직접 조회)
- 멀티스텝 리서치/분석: 서브에이전트 위임
- 감정 신호("불안", "어떡해", "팔아야 할 것 같아") 감지되면 무조건 `decision-coach`부터

---

## 데이터 소스 (이미 셋업됨)

### 정량 데이터 (results/ 폴더, 매일 자동 갱신)
- `summary_signals.csv` — 주식 추세 신호 + 12M 수익률 + RSI
- `fundamentals.csv` — PER/PBR/ROE/매출YoY/EPS YoY/섹터 등
- `{ticker}_signals.csv` — 일별 OHLCV + MA20/50/200, RSI, MACD, BB, OBV
- `coin_summary.csv`, `cycle_metrics.csv` — 코인 + MVRV/NUPL/Puell/Pi Cycle
- `mvrv_history.csv` — BTC MVRV Z-Score 3년치
- `holdings.csv` — 사용자 보유 종목 (있을 때)

### 외부 (필요 시 WebSearch/WebFetch)
- 공식 공시: DART (dart.fss.or.kr), SEC EDGAR
- IR 자료: 기업 공식 IR 페이지
- 컨센서스: 네이버금융, FnGuide, Bloomberg/Reuters 기사
- 산업 리포트: 증권사 리서치, 산업 협회

### 신뢰성 위계 (분석 시 우선순위)
1. 공식 공시(사업보고서/분기보고서) → 2. 실적발표/컨콜 → 3. IR자료 →
4. 애널리스트 컨센서스 → 5. 정부·협회 통계 → 6. 주요 언론 →
**커뮤니티/루머는 절대 핵심 근거로 사용하지 않는다.**

---

## 투자 기록 위치

- 폴더: `investment-journal/`
- 파일명 규칙: `{YYYY-MM-DD}_{ticker}_{종목명}.md`
- 양식: `investment-journal/_template.md` 참고
- 사용자가 매수/관심종목 지정 시 `journal-keeper`가 자동 생성
- 사용자가 후일 불안/매도 문의 시 **반드시 기존 기록을 먼저 다시 보여준다**

---

## Streamlit 대시보드 코드 (참고)

- 메인 진입: `주식.py` (st.navigation 라우터)
- 페이지: `stocks_page.py`, `coin_page.py`, `portfolio_page.py`
- 분석 파이프라인: `run_analysis.py` + `scripts/*`
- 매일 새벽 7시(KST) GitHub Actions로 자동 갱신
- 배포: https://stock-coin-dashboard-jdlrktuq3b7dzn5canhyeo.streamlit.app/

대시보드 코드 수정은 가능하지만, **에이전트의 주 임무는 리서치·분석·기록**이지
대시보드 개발이 아니다. 대시보드 변경 요청 시에만 코드 수정.

---

## 리서치 노트 수동 업데이트 명령

사용자가 **"리서치 노트 업데이트"**, **"리서치 노트 써줘"**, **"분석 노트 갱신"** 등을 말하면:

### 실행 순서

1. **데이터 읽기** (모두 읽기)
   - `holdings.csv` — 보유 종목 목록 + 매수가
   - `results/summary_signals.csv` — 추세/RSI/12M 수익률
   - `results/fundamentals.csv` — PER/PBR/ROE/성장률
   - `results/coin_summary.csv` — 코인 현재가/RSI
   - `results/cycle_metrics.csv` — MVRV Z-Score/NUPL/Puell
   - `core_etfs.csv` — ETF 티커 목록
   - `asset_reports.json` — 기존 리서치 노트 (sources 필드 보존)

2. **종목별 분석** (각 보유 종목에 대해)
   - 자산 유형 판별: `-USD` 포함 → 코인, `core_etfs.csv` 해당 → ETF, 나머지 → 개별주
   - 수익률 계산: `(현재가 / 매수가 - 1) × 100`
   - 데이터 기반 분석 (절대 원칙 준수)

3. **JSON 작성** — 종목별로 아래 형식:
   ```json
   {
     "opinion": "한 줄 요약 (15자 이내)",
     "opinion_type": "positive 또는 caution 또는 negative",
     "summary": "현재 상황 요약 — 150자 이내, 투자 비전문가도 이해할 수 있도록 쉬운 말로 작성",
     "bull": "강세 근거 — 쉬운 말로, 80자 이내",
     "bear": "약세 근거 / 틀릴 조건 — 쉬운 말로, 80자 이내",
     "updated": "YYYY-MM-DD",
     "sources": "(기존 값 그대로 보존, 없으면 생략)"
   }
   ```
   - `opinion_type` 기준: positive = 추세 양호/상승, caution = 혼조/주의, negative = 손실/약세
   - **summary / bull / bear 작성 원칙 (필수)**:
     - RSI, MACD, %B, PER, PBR 같은 전문 약어는 단독으로 쓰지 않고 반드시 괄호로 뜻을 설명한다. 예: "RSI 63(과열 없음)" → "과열 지표(RSI)가 63으로 아직 위험 구간이 아닙니다"
     - "12M +41%" 같은 단축 표기 금지 → "지난 1년간 41% 상승했습니다"
     - "골든크로스 274일" 같은 표현 금지 → "274일째 단기 평균선이 장기 평균선 위에 머물며 상승 흐름이 이어지고 있습니다"
     - "MVRV Z-Score", "NUPL", "Puell" 등 온체인 지표는 지표 이름만 쓰지 말고 의미를 함께 설명한다
     - 숫자는 맥락 없이 나열하지 않는다. 수치를 쓸 때는 "그게 왜 중요한지"를 한 문장에 담는다

4. **파일 저장** — `asset_reports.json` 덮어쓰기

5. **Git 커밋 & 푸시** — 사용자 확인 후
   ```
   git add asset_reports.json
   git commit -m "data: 리서치 노트 수동 갱신 YYYY-MM-DD"
   git push
   ```

### 분석 원칙 (절대 원칙에 추가)
- 코인: MVRV Z < 0 → positive, 0~1.5 → positive, 1.5~2.5 → caution, ≥ 2.5 → negative
- ETF: 모멘텀 Q1 → positive, Q4 → caution, 나머지 → positive (리밸런싱 관리)
- 개별주: 수익률 ≥ 0 + Q1 → positive / 수익률 -8% 이상 또는 Q4 → caution / -20% 이하 → negative
