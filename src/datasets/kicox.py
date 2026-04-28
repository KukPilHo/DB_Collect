"""
KICOX 전국공장등록현황 (15105482)
==================================
data.go.kr/data/15105482/fileData.do
수집 방식: 파일 다운로드 (CSV)
카테고리: 제조
약 20만 레코드.
"""

import re
from pathlib import Path
from typing import Optional

import pandas as pd
import requests

from src.config import (
    CATEGORY_제조,
    TIMEOUT_SEC,
    USER_AGENT,
    log,
)
from .base import (
    Dataset,
    ensure_unified_schema,
    generate_company_key,
)

# data.go.kr 파일 직접 다운로드 URL
_DOWNLOAD_URL = (
    "https://www.data.go.kr/cmm/cmm/fileDownload.do"
    "?atchFileId=FILE_000000003109845&fileDetailSn=1&insertDataPrcus=N"
)


class KicoxDataset(Dataset):
    id = "15105482"
    name = "KICOX 전국공장등록현황"
    source_url = "https://www.data.go.kr/data/15105482/fileData.do"
    category_default = CATEGORY_제조

    def download(self, force: bool = False) -> Path:
        if not force and self.is_raw_cached():
            log.info("[%s] raw 캐시 존재, 스킵", self.id)
            return self.raw_dir()

        out_dir = self.raw_dir()
        out_path = out_dir / "kicox_전국등록공장현황.csv"
        log.info("[%s] 파일 다운로드 시작: %s", self.id, _DOWNLOAD_URL)

        r = requests.get(
            _DOWNLOAD_URL,
            stream=True,
            timeout=TIMEOUT_SEC * 5,  # 대용량 파일
            headers={"User-Agent": USER_AGENT},
        )
        r.raise_for_status()

        with open(out_path, "wb") as f:
            for chunk in r.iter_content(chunk_size=8192):
                f.write(chunk)

        log.info("[%s] 다운로드 완료: %s", self.id, out_path)
        return out_dir

    def normalize(self) -> pd.DataFrame:
        raw_dir = self.latest_raw_dir()
        if raw_dir is None:
            raise FileNotFoundError(
                f"[{self.id}] raw 데이터 없음. 먼저 download 실행 필요."
            )

        # csv 또는 xlsx 파일 찾기
        files = list(raw_dir.glob("*"))
        valid = [f for f in files if f.suffix.lower() in (".csv", ".xlsx")]
        if not valid:
            raise FileNotFoundError(
                f"[{self.id}] {raw_dir} 안에 csv/xlsx 파일이 없음."
            )
        path = sorted(valid)[-1]
        log.info("[%s] 정규화 시작: %s", self.id, path)

        # 파일 로드
        if path.suffix.lower() == ".csv":
            try:
                df = pd.read_csv(path, dtype=str, encoding="utf-8").fillna("")
            except UnicodeDecodeError:
                df = pd.read_csv(
                    path, dtype=str, encoding="cp949", encoding_errors="replace"
                ).fillna("")
        else:
            df = pd.read_excel(path, dtype=str).fillna("")

        # 컬럼 매핑 (원본 → 통일 스키마)
        col_map = {}
        for c in df.columns:
            cs = c.strip()
            if "사업자" in cs and ("번호" in cs or "등록" in cs):
                col_map[c] = "사업자등록번호"
            elif "회사" in cs or "업체" in cs or "기업" in cs:
                col_map[c] = "회사명_원본"
            elif "대표자" in cs or "대표" in cs:
                col_map[c] = "대표자"
            elif "업종" in cs and "코드" in cs:
                col_map[c] = "업종_KSIC"
            elif "업종" in cs:
                col_map[c] = "업종명_원본"
            elif "도로명" in cs and "주소" in cs:
                col_map[c] = "도로명주소"
            elif "지번" in cs and "주소" in cs:
                col_map[c] = "지번주소"
            elif "주소" in cs:
                col_map[c] = "도로명주소"  # 주소 컬럼이 하나면 도로명주소로
            elif "전화" in cs or "연락" in cs:
                col_map[c] = "대표전화"
            elif "종업원" in cs or "직원" in cs or "인원" in cs:
                col_map[c] = "종업원수"
            elif "자본금" in cs:
                col_map[c] = "자본금"
            elif "가동" in cs or "상태" in cs:
                col_map[c] = "가동상태"
            elif "설립" in cs or "등록일" in cs or "인가" in cs:
                col_map[c] = "등록일"
            elif "생산" in cs or "품목" in cs:
                col_map[c] = "업종명_원본"  # 생산품 → 업종명_원본
            elif "홈페이지" in cs or "URL" in cs.upper():
                col_map[c] = "홈페이지"

        df = df.rename(columns=col_map)

        # 회사명 설정
        if "회사명_원본" not in df.columns:
            # 컬럼 매핑 실패 시 첫 번째 텍스트 컬럼 사용
            log.warning("[%s] 회사명 컬럼 자동 매핑 실패, 컬럼 목록: %s", self.id, list(df.columns))
            df["회사명_원본"] = ""

        df["회사명"] = df["회사명_원본"].apply(lambda x: str(x).strip() if pd.notna(x) else "")

        # 시도, 시군구 추출 (주소에서)
        addr_col = "도로명주소" if "도로명주소" in df.columns else ("지번주소" if "지번주소" in df.columns else None)
        if addr_col and addr_col in df.columns:
            df["시도"] = df[addr_col].apply(self._extract_sido)
            df["시군구"] = df[addr_col].apply(self._extract_sigungu)

        # 회사키 생성
        df["회사키"] = df.apply(
            lambda r: generate_company_key(
                str(r.get("사업자등록번호", "") or ""),
                str(r.get("회사명", "") or ""),
                str(r.get("시도", "") or ""),
                str(r.get("시군구", "") or ""),
            ),
            axis=1,
        )

        # 숫자 컬럼 변환
        for col in ("종업원수", "자본금", "매출액"):
            if col in df.columns:
                df[col] = pd.to_numeric(
                    df[col].astype(str).str.replace(",", "").str.strip(),
                    errors="coerce",
                )

        # 공통 필드 설정
        df = self._set_common_fields(df)

        # 스키마 통일
        df = ensure_unified_schema(df)
        df = df.drop_duplicates(subset=["회사키"]).reset_index(drop=True)

        log.info("[%s] 정규화 완료: %d행", self.id, len(df))
        return df

    @staticmethod
    def _extract_sido(addr: str) -> Optional[str]:
        """주소에서 시도(광역시/도) 추출."""
        if addr is None or (isinstance(addr, float)) or str(addr).strip() == "":
            return None
        addr = str(addr).strip()
        # 17개 광역 표준 표기
        patterns = [
            "서울", "부산", "대구", "인천", "광주", "대전", "울산", "세종",
            "경기", "강원", "충북", "충남", "전북", "전남", "경북", "경남", "제주",
        ]
        # 정식 명칭 매핑
        full_names = {
            "서울": "서울특별시", "부산": "부산광역시", "대구": "대구광역시",
            "인천": "인천광역시", "광주": "광주광역시", "대전": "대전광역시",
            "울산": "울산광역시", "세종": "세종특별자치시",
            "경기": "경기도", "강원": "강원특별자치도", "충북": "충청북도",
            "충남": "충청남도", "전북": "전북특별자치도", "전남": "전라남도",
            "경북": "경상북도", "경남": "경상남도", "제주": "제주특별자치도",
        }
        for p in patterns:
            if addr.startswith(p):
                return full_names.get(p, p)
        return None

    @staticmethod
    def _extract_sigungu(addr: str) -> Optional[str]:
        """주소에서 시군구 추출."""
        if addr is None or (isinstance(addr, float)) or str(addr).strip() == "":
            return None
        parts = str(addr).strip().split()
        if len(parts) >= 2:
            candidate = parts[1]
            if candidate.endswith(("시", "군", "구")):
                return candidate
        return None
