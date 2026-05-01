"""
프로젝트 전역 설정
==================
환경변수 로드, 경로 상수, 크롤링 설정 등 모든 모듈이 공유하는 값을 한 곳에 모은다.
"""

import logging
import os
from pathlib import Path

from dotenv import load_dotenv

# ── .env 로드 ──────────────────────────────────────────────
load_dotenv()

# ── 프로젝트 루트 (src/ 의 부모) ──────────────────────────
PROJECT_ROOT = Path(__file__).resolve().parent.parent

# ── 데이터 디렉토리 ───────────────────────────────────────
RAW_DIR = PROJECT_ROOT / "raw"
NORMALIZED_DIR = PROJECT_ROOT / "normalized"
OUTPUT_DIR = PROJECT_ROOT / "output"
MASTER_PATH = PROJECT_ROOT / "master.parquet"
CANDIDATES_PATH = PROJECT_ROOT / "candidates.parquet"
ENRICHMENT_DB_PATH = PROJECT_ROOT / "enrichment_state.sqlite"

for _d in (RAW_DIR, NORMALIZED_DIR, OUTPUT_DIR):
    _d.mkdir(parents=True, exist_ok=True)

# ── 공공데이터포털 / 경기도 API ──────────────────────────
DATA_GO_KR_SERVICE_KEY = os.getenv("DATA_GO_KR_SERVICE_KEY", "")
GG_API_URL = os.getenv("GG_API_URL", "https://openapi.gg.go.kr/FACTRYREGISTTM")

# ── 검색 API (이메일 enrichment) ─────────────────────────
NAVER_CLIENT_ID = os.getenv("NAVER_CLIENT_ID", "")
NAVER_CLIENT_SECRET = os.getenv("NAVER_CLIENT_SECRET", "")
GOOGLE_CSE_API_KEY = os.getenv("GOOGLE_CSE_API_KEY", "")
GOOGLE_CSE_CX = os.getenv("GOOGLE_CSE_CX", "")

# ── 크롤링 및 AI 설정 ────────────────────────────────────
CRAWL_DELAY_SEC = 1.5
TIMEOUT_SEC = 12
USER_AGENT = os.getenv("USER_AGENT", "AblearnBD-Research/1.0")
ENRICHMENT_CONCURRENCY = int(os.getenv("ENRICHMENT_CONCURRENCY", "5"))

# AI 이메일 검증
USE_AI_FILTER = os.getenv("USE_AI_FILTER", "False").lower() in ("true", "1", "yes", "on")
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY", "")

# ── 카테고리 정의 ─────────────────────────────────────────
CATEGORY_제조 = "제조"
CATEGORY_IT = "IT_SW_벤처"
CATEGORY_서비스 = "도소매_콘텐츠_전문서비스"
CATEGORY_건설 = "건설_물류_시설"

# 카테고리별 quota
CATEGORY_QUOTA = {
    CATEGORY_제조: 300,
    CATEGORY_IT: 120,
    CATEGORY_서비스: 520,  # 200건 추가 확보를 위해 기존 320 -> 520으로 대폭 상향
    CATEGORY_건설: 260,
}

# ── 데이터셋 우선순위 (dedup 시 사용, 낮을수록 높은 우선순위) ──
DATASET_PRIORITY = {
    "15105482": 1,   # KICOX 전국공장
    "15057023": 2,   # 경기도 공장등록
    "15052274": 3,   # SW산업정보
    "innobiz": 4,    # 이노비즈
    "15118569": 5,   # 대중문화예술기획업
    "15086381": 6,   # 디자인전문회사
    "15099307": 7,   # 전문연구사업자
    "15065485": 8,   # 전국건설업체
    "15071341": 9,   # 서울 건물위생관리업
}

# ── 통일 스키마 컬럼 ─────────────────────────────────────
UNIFIED_COLUMNS = [
    "회사키", "사업자등록번호", "회사명", "회사명_원본",
    "대표자", "업종_KSIC", "업종명_원본",
    "시도", "시군구", "도로명주소", "지번주소",
    "대표전화", "홈페이지", "종업원수", "자본금", "매출액",
    "등록일", "가동상태",
    "출처_데이터셋ID", "출처_URL", "출처_목록",
    "카테고리", "수집일",
]

# ── 로깅 설정 ─────────────────────────────────────────────
logging.basicConfig(
    level=logging.WARNING,
    format="%(asctime)s [%(levelname)s] %(message)s",
)
log = logging.getLogger("outbound_db")
log.setLevel(logging.INFO)
