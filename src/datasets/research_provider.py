"""
전문연구사업자 신고기업 현황 (15099307)
========================================
과학기술정보통신부 제공.
수집 방식: 파일 다운로드 (CSV)
카테고리: 도소매_콘텐츠_전문서비스
"""

from pathlib import Path

import pandas as pd
import requests

from src.config import CATEGORY_서비스, TIMEOUT_SEC, USER_AGENT, log
from .base import Dataset, ensure_unified_schema, generate_company_key


class ResearchProviderDataset(Dataset):
    id = "15099307"
    name = "전문연구사업자 신고기업 현황"
    source_url = "https://www.data.go.kr/data/15099307/fileData.do"
    category_default = CATEGORY_서비스

    def download(self, force: bool = False) -> Path:
        if not force and self.is_raw_cached():
            log.info("[%s] raw 캐시 존재, 스킵", self.id)
            return self.raw_dir()

        out_dir = self.raw_dir()
        log.info("[%s] data.go.kr에서 파일 다운로드 시도", self.id)

        # data.go.kr 직접 다운로드 시도
        try:
            r = requests.get(
                f"https://www.data.go.kr/cmm/cmm/fileDownload.do?atchFileId=FILE_000000002761958&fileDetailSn=1",
                stream=True, timeout=TIMEOUT_SEC * 3,
                headers={"User-Agent": USER_AGENT},
            )
            r.raise_for_status()
            out_path = out_dir / "research_provider.csv"
            with open(out_path, "wb") as f:
                for chunk in r.iter_content(chunk_size=8192):
                    f.write(chunk)
            log.info("[%s] 다운로드 완료: %s", self.id, out_path)
        except Exception as e:
            log.warning("[%s] 자동 다운로드 실패: %s", self.id, e)
            (out_dir / "_MANUAL_DOWNLOAD_NEEDED.txt").write_text(
                f"{self.source_url} 에서 직접 다운로드 후 이 폴더에 저장하세요."
            )
        return out_dir

    def normalize(self) -> pd.DataFrame:
        raw_dir = self.latest_raw_dir()
        if raw_dir is None:
            raise FileNotFoundError(f"[{self.id}] raw 데이터 없음.")

        files = [f for f in raw_dir.glob("*") if f.suffix.lower() in (".csv", ".xlsx")]
        if not files:
            from .base import build_empty_unified_df
            return build_empty_unified_df()

        path = sorted(files)[-1]
        log.info("[%s] 정규화: %s", self.id, path)

        if path.suffix.lower() == ".csv":
            try:
                df = pd.read_csv(path, dtype=str, encoding="utf-8").fillna("")
            except UnicodeDecodeError:
                df = pd.read_csv(path, dtype=str, encoding="cp949", encoding_errors="replace").fillna("")
        else:
            df = pd.read_excel(path, dtype=str).fillna("")

        col_map = {}
        for c in df.columns:
            cs = c.strip()
            if "사업자" in cs and "번호" in cs: col_map[c] = "사업자등록번호"
            elif "업체" in cs or "회사" in cs or "기업" in cs: col_map[c] = "회사명_원본"
            elif "대표" in cs: col_map[c] = "대표자"
            elif "소재" in cs or "주소" in cs: col_map[c] = "도로명주소"
            elif "업종" in cs or "분야" in cs: col_map[c] = "업종명_원본"
            elif "승인" in cs or "신고" in cs and "일" in cs: col_map[c] = "등록일"

        df = df.rename(columns=col_map)
        if "회사명_원본" not in df.columns:
            df["회사명_원본"] = ""
        df["회사명"] = df["회사명_원본"].apply(lambda x: str(x).strip())

        if "도로명주소" in df.columns:
            from .kicox import KicoxDataset
            df["시도"] = df["도로명주소"].apply(KicoxDataset._extract_sido)
            df["시군구"] = df["도로명주소"].apply(KicoxDataset._extract_sigungu)

        df["회사키"] = df.apply(
            lambda r: generate_company_key(r.get("사업자등록번호"), r.get("회사명",""), r.get("시도"), r.get("시군구")),
            axis=1,
        )
        df = self._set_common_fields(df)
        df = ensure_unified_schema(df)
        df = df.drop_duplicates(subset=["회사키"]).reset_index(drop=True)
        log.info("[%s] 정규화 완료: %d행", self.id, len(df))
        return df
