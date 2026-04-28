"""
Dataset 추상 클래스
====================
모든 공공데이터 소스는 이 클래스를 상속하여 download()와 normalize()를 구현한다.
새 데이터셋 추가 시 이 클래스를 상속하고 __init__.py DATASETS 리스트에 등록하면 끝.
"""

import hashlib
import re
from abc import ABC, abstractmethod
from datetime import date, datetime
from pathlib import Path
from typing import Optional

import pandas as pd

from src.config import (
    NORMALIZED_DIR,
    RAW_DIR,
    UNIFIED_COLUMNS,
    log,
)

# ── 회사명 정규화용 법인격 패턴 ──────────────────────────
_CORP_PATTERNS = re.compile(
    r"주식회사|유한회사|사단법인|재단법인|합자회사|합명회사"
    r"|\(주\)|\(유\)|\(사\)|\(재\)|\(합\)"
    r"|\(주식회사\)|\(유한회사\)|\(사단법인\)|\(재단법인\)"
)
# 특수문자 제거 (괄호, 따옴표, dot)
_SPECIAL_CHARS = re.compile(r"[()（）「」『』\[\]<>《》\"'.,·•]")


def normalize_company_name(name) -> str:
    """
    회사명 정규화: 법인격 제거 → 특수문자 제거 → 공백 제거 → 영문 lower.
    dedup용 키 생성에 사용.
    """
    if name is None or (isinstance(name, float)) or str(name).strip() == "":
        return ""
    name = str(name)
    s = _CORP_PATTERNS.sub("", name)
    s = _SPECIAL_CHARS.sub("", s)
    s = re.sub(r"\s+", "", s)  # 공백 모두 제거
    return s.lower()


def generate_company_key(
    biz_reg_no: Optional[str],
    company_name: str,
    sido: Optional[str] = None,
    sigungu: Optional[str] = None,
) -> str:
    """
    회사키 생성 우선순위:
      (1) 사업자등록번호가 있으면 하이픈 제거 후 10자리
      (2) 없으면 sha256(normalize(회사명) | normalize(시도) | normalize(시군구))[:16]
    """
    # (1) 사업자등록번호
    if biz_reg_no:
        cleaned = re.sub(r"[^0-9]", "", str(biz_reg_no))
        if len(cleaned) == 10:
            return cleaned

    # (2) 해시 기반
    norm_name = normalize_company_name(company_name)
    norm_sido = str(sido).strip() if pd.notna(sido) else ""
    norm_sigungu = str(sigungu).strip() if pd.notna(sigungu) else ""
    raw = f"{norm_name}|{norm_sido}|{norm_sigungu}"
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:16]


def build_empty_unified_df() -> pd.DataFrame:
    """통일 스키마의 빈 DataFrame 생성."""
    return pd.DataFrame(columns=UNIFIED_COLUMNS)


def ensure_unified_schema(df: pd.DataFrame) -> pd.DataFrame:
    """DataFrame에 통일 스키마 컬럼이 모두 존재하도록 보장 (없는 컬럼은 None)."""
    for col in UNIFIED_COLUMNS:
        if col not in df.columns:
            df[col] = None
    return df[UNIFIED_COLUMNS].copy()


class Dataset(ABC):
    """
    공공데이터 소스 추상 클래스.
    모든 구현체는 download()와 normalize()를 반드시 구현해야 한다.
    """

    id: str                  # 예: "15105482"
    name: str                # 예: "KICOX 전국공장등록현황"
    source_url: str          # 데이터셋 페이지 URL
    category_default: str    # 예: "제조"

    # ── 공통 헬퍼 ─────────────────────────────────────────

    def raw_dir(self, date_str: Optional[str] = None) -> Path:
        """raw/<id>/<YYYY-MM-DD>/ 경로 반환. 날짜 미지정 시 오늘."""
        d = date_str or date.today().isoformat()
        p = RAW_DIR / self.id / d
        p.mkdir(parents=True, exist_ok=True)
        return p

    def latest_raw_dir(self) -> Optional[Path]:
        """가장 최근 날짜의 raw/<id>/<date>/ 디렉토리 반환."""
        base = RAW_DIR / self.id
        if not base.exists():
            return None
        dirs = sorted([d for d in base.iterdir() if d.is_dir()])
        return dirs[-1] if dirs else None

    def normalized_path(self) -> Path:
        """normalized/<id>.parquet 경로."""
        return NORMALIZED_DIR / f"{self.id}.parquet"

    def is_raw_cached(self) -> bool:
        """오늘 날짜로 raw가 이미 존재하는지 확인."""
        today_dir = RAW_DIR / self.id / date.today().isoformat()
        return today_dir.exists() and any(today_dir.iterdir())

    def is_normalized_cached(self) -> bool:
        """normalized parquet이 존재하는지 확인."""
        return self.normalized_path().exists()

    # ── 추상 메서드 ───────────────────────────────────────

    @abstractmethod
    def download(self, force: bool = False) -> Path:
        """
        raw/<id>/<오늘 날짜>/에 원본 저장하고 폴더 경로 반환.
        force=False이면 캐시 있으면 스킵.
        """

    @abstractmethod
    def normalize(self) -> pd.DataFrame:
        """
        raw 파일 → 통일 스키마 DataFrame 반환.
        수집일은 오늘 날짜로 자동 채움.
        """

    # ── 편의 메서드 ───────────────────────────────────────

    def _set_common_fields(self, df: pd.DataFrame) -> pd.DataFrame:
        """출처, 수집일 등 공통 필드 설정."""
        df["출처_데이터셋ID"] = self.id
        df["출처_URL"] = self.source_url
        df["출처_목록"] = self.id
        df["카테고리"] = ""  # categorize 단계에서 채움
        df["수집일"] = datetime.now().strftime("%Y-%m-%d")
        return df

    def __repr__(self) -> str:
        return f"<Dataset {self.id}: {self.name}>"
