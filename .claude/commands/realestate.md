부동산 분석 프로젝트로 전환합니다.

**GitHub**: https://github.com/kimhyuntae0423-art/realestate-analysis
**대시보드**: https://realestate-analysis-p6jdtbkpo6u245ekj4cy4d.streamlit.app/

Codespaces 환경에서는 아래 레포를 clone하거나 별도 Codespace에서 작업하세요:
`git clone https://github.com/kimhyuntae0423-art/realestate-analysis`

주요 컨텍스트:
- 한국 부동산 실거래가 수집·분석 도구
- 데이터: 국토부 실거래가 API / KOSIS / 카카오
- DB: SQLite (`data/processed/realestate.db`)
- 분석 모듈: `src/analysis/` (가격추이·갭·수익률·호재·Prophet예측)
- 대시보드: `streamlit run src/ui/streamlit_app.py`
- API 키: `.env` 파일 (DATA_GO_KR_API_KEY 필수)
