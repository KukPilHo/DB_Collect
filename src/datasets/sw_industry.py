"""
SW산업정보 사업자정보 (15052274)
==================================
정보통신산업진흥원 제공.
수집 방식: 파일 다운로드 (CSV)
카테고리: IT_SW_벤처
"""

from pathlib import Path

import pandas as pd
import requests

from src.config import CATEGORY_IT, DATA_GO_KR_SERVICE_KEY, TIMEOUT_SEC, USER_AGENT, log
from .base import Dataset, ensure_unified_schema, generate_company_key


class SwIndustryDataset(Dataset):
    id = "15052274"
    name = "SW산업정보 사업자정보"
    source_url = "https://www.data.go.kr/data/15052274/fileData.do"
    category_default = CATEGORY_IT

    def download(self, force: bool = False) -> Path:
        if not force and self.is_raw_cached():
            log.info("[%s] raw 캐시 존재, 스킵", self.id)
            return self.raw_dir()

        out_dir = self.raw_dir()
        # data.go.kr 파일 다운로드 시도
        url = f"https://www.data.go.kr/cmm/cmm/fileDownload.do?atchFileId=FILE_000000002514437&fileDetailSn=1"
        log.info("[%s] 파일 다운로드 시도: %s", self.id, url)
        try:
            r = requests.get(url, stream=True, timeout=TIMEOUT_SEC * 3,
                             headers={"User-Agent": USER_AGENT})
            r.raise_for_status()
            out_path = out_dir / "sw_industry.csv"
            with open(out_path, "wb") as f:
                for chunk in r.iter_content(chunk_size=8192):
                    f.write(chunk)
            log.info("[%s] 다운로드 완료: %s", self.id, out_path)
        except Exception as e:
            log.warning("[%s] 파일 다운로드 실패: %s (data.go.kr에서 수동 다운로드 필요)", self.id, e)
            # 빈 마커 파일 생성
            (out_dir / "_MANUAL_DOWNLOAD_NEEDED.txt").write_text(
                f"data.go.kr/data/{self.id}/fileData.do 에서 직접 다운로드 후 이 폴더에 저장하세요."
            )
        return out_dir

    def normalize(self) -> pd.DataFrame:
        raw_dir = self.latest_raw_dir()
        if raw_dir is None:
            raise FileNotFoundError(f"[{self.id}] raw 데이터 없음.")

        files = [f for f in raw_dir.glob("*") if f.suffix.lower() in (".csv", ".xlsx")]
        if not files:
            log.warning("[%s] 데이터 파일 없음, 빈 DataFrame 반환", self.id)
            return self._empty_df()

        path = sorted(files)[-1]
        log.info("[%s] 정규화: %s", self.id, path)

        if path.suffix.lower() == ".csv":
            import os
            if os.path.getsize(path) == 0:
                log.warning("[%s] 파일 크기가 0입니다. 빈 DataFrame 반환", self.id)
                return self._empty_df()
            try:
                try:
                    df = pd.read_csv(path, dtype=str, encoding="utf-8").fillna("")
                except UnicodeDecodeError:
                    df = pd.read_csv(path, dtype=str, encoding="cp949", encoding_errors="replace").fillna("")
            except pd.errors.EmptyDataError:
                log.warning("[%s] 파싱할 컬럼이 없습니다(EmptyDataError). 빈 DataFrame 반환", self.id)
                return self._empty_df()
        else:
            df = pd.read_excel(path, dtype=str).fillna("")

        # 컬럼 매핑
        col_map = {}
        for c in df.columns:
            cs = c.strip()
            if "사업자" in cs and "번호" in cs: col_map[c] = "사업자등록번호"
            elif "업체" in cs or "회사" in cs or "기업" in cs: col_map[c] = "회사명_원본"
            elif "대표" in cs and "자" in cs: col_map[c] = "대표자"
            elif "업종" in cs: col_map[c] = "업종명_원본"
            elif "주소" in cs: col_map[c] = "도로명주소"
            elif "전화" in cs or "연락" in cs: col_map[c] = "대표전화"
            elif "홈페이지" in cs or "URL" in cs.upper(): col_map[c] = "홈페이지"
            elif "종업원" in cs or "직원" in cs: col_map[c] = "종업원수"

        df = df.rename(columns=col_map)
        if "회사명_원본" not in df.columns:
            df["회사명_원본"] = ""
        df["회사명"] = df["회사명_원본"].apply(lambda x: str(x).strip() if pd.notna(x) else "")

        # 시도/시군구 추출
        if "도로명주소" in df.columns:
            from .kicox import KicoxDataset
            df["시도"] = df["도로명주소"].apply(KicoxDataset._extract_sido)
            df["시군구"] = df["도로명주소"].apply(KicoxDataset._extract_sigungu)

        df["회사키"] = df.apply(
            lambda r: generate_company_key(r.get("사업자등록번호"), r.get("회사명",""), r.get("시도"), r.get("시군구")),
            axis=1,
        )

        for col in ("종업원수", "자본금", "매출액"):
            if col in df.columns:
                df[col] = pd.to_numeric(df[col].astype(str).str.replace(",","").str.strip(), errors="coerce")

        df = self._set_common_fields(df)
        df = ensure_unified_schema(df)
        df = df.drop_duplicates(subset=["회사키"]).reset_index(drop=True)
        log.info("[%s] 정규화 완료: %d행", self.id, len(df))
        return df

    def _empty_df(self):
        from .base import build_empty_unified_df
        return build_empty_unified_df()
