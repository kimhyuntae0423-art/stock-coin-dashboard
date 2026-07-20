"""중앙 경로·상수 관리 (SSOT).

파일 구조가 바뀌면 이 파일만 수정한다.
다른 스크립트에서 경로를 직접 선언하지 말고 여기서 임포트한다.
"""
from pathlib import Path

# 프로젝트 루트 (scripts/ 의 상위 디렉토리)
ROOT = Path(__file__).resolve().parent.parent

# 핵심 데이터 파일
TICKERS_FILE  = ROOT / "tickers.csv"
CORE_ETF_FILE = ROOT / "core_etfs.csv"
NAMES_FILE    = ROOT / "names.csv"
HOLDINGS_FILE = ROOT / "holdings.csv"

# 결과 디렉토리
RESULTS_DIR = ROOT / "results"

# ── 목표 자산 배분 (Core-Satellite-Cash, 3버킷) ──────────────────────────────
# 코인(BTC 포함)은 Satellite 버킷에 포함된다 — scripts/asset_allocation.py의
# classify_holdings()가 core_etfs.csv에 없는 종목을 전부 Satellite로 분류.
# 이 세 값이 유일한 기본값이다. rebalancing_page.py의 number_input, why_market_page.py의
# 배너, asset_allocation.py의 함수 기본값이 전부 여기를 참조해야 한다 — 2026-07-20 통일.
DEFAULT_TARGET_CORE      = 80
DEFAULT_TARGET_SATELLITE = 10
DEFAULT_TARGET_CASH      = 10

# rebalancing_page.py의 st.number_input key= / st.session_state 키 이름.
# 여기 바뀌면 why_market_page.py도 같이 못 읽게 되므로 상수로 공유한다.
KEY_TARGET_CORE      = "tgt_core_"
KEY_TARGET_SATELLITE = "tgt_sat_"
KEY_TARGET_CASH      = "tgt_cash_"
