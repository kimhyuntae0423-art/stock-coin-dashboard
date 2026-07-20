# 📈 주식 & 코인 분석 대시보드

Streamlit으로 만든 한·미 주식 + 암호화폐 종합 분석 대시보드.
학술적으로 검증된 멀티팩터 점수 시스템과 비트코인 온체인 지표를 결합해서
**어떤 종목을 살지 추천**해줍니다.

## 주요 기능

### 📈 주식 페이지
- **시장 국면 (VIX 기반 market_regime)** — ETF/리밸런싱 페이지와 동일 기준, IC=+0.14 백테스트 검증
- **QVM 종합 점수** — Value(PER/PBR) · Quality(ROE) · Momentum(12M 수익률) · Technical(RSI) 4-팩터 점수 시스템
- **매수 우선순위 TOP 5** — 종합 점수 기반 추천
- 골든/데드 크로스 (50/200일선) 추세 시그널
- 한국 주식 PER/PBR은 **네이버 금융 크롤링**으로 보강 (yfinance 한계 보완)
- 종목별 백테스트 (전략 vs 매수후보유)

### 🪙 코인 페이지
- **Crypto Fear & Greed Index** (Alternative.me)
- **5개 사이클 지표 통합**: MVRV Z-Score · NUPL · Puell Multiple · Pi Cycle Top · F&G
- **Altcoin Season Index** — 비트코인 시즌 vs 알트시즌 판단
- 종합 점수에 따른 코인 매수 우선순위 추천

## 데이터 출처 (모두 무료)
- yfinance — 가격 데이터
- 네이버 금융 — 한국 주식 PER/PBR
- bitcoin-data.com — BTC 온체인 지표 (MVRV, NUPL, Puell)
- Alternative.me — 코인 Fear & Greed 지수

## 로컬 실행
```bash
python -m pip install -r requirements.txt
python run_analysis.py          # 데이터 수집 + 분석 (~2분)
streamlit run 주식.py            # 대시보드 실행
```

## 디렉토리 구조
```
주식/
├── 주식.py                       # 메인 페이지 (주식)
├── pages/
│   └── 1_🪙_코인.py              # 코인 페이지
├── scripts/
│   ├── data_fetch.py             # yfinance + 펀더멘털
│   ├── naver_finance.py          # 한국 주식 PER/PBR 크롤러
│   ├── indicators.py             # MA, RSI 등 기술지표
│   ├── signal_generator.py       # 골든/데드 크로스
│   ├── stock_score.py            # QVM 4-팩터 점수
│   ├── crypto_analysis.py        # 코인 지표
│   ├── onchain.py                # MVRV·NUPL·Puell·Pi Cycle
│   ├── fear_greed.py             # F&G 인덱스
│   └── ui.py                     # 공용 UI 컴포넌트
├── tickers.csv                   # 분석 대상 주식
├── coins.csv                     # 분석 대상 코인
├── names.csv / coin_names.csv    # 한글 종목명
├── results/                      # 분석 결과 (CSV)
└── run_analysis.py               # 분석 파이프라인 진입점
```

## 면책

이 도구는 **참고용**이며 매매 권유가 아닙니다. 백테스트는 수수료/세금/슬리피지를
반영하지 않고, 과거 성과가 미래를 보장하지 않습니다. 투자는 본인 책임입니다.
