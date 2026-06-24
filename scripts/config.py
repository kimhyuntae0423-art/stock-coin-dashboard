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
