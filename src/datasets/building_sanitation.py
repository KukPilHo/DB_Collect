"""
서울 건물위생관리업 인허가 (15071341)
======================================
수집 방식: 파일 다운로드
카테고리: 건설_물류_시설 (시설관리)
"""

from pathlib import Path

import pandas as pd
import requests

from src.config import CATEGORY_건설, TIMEOUT_SEC, USER_AGENT, log
from .base import Dataset, ensure_unified_schema, generate_company_key


class BuildingSanitationDataset(Dataset):
    id = "15071341"
    name = "서울 건물위생관리업 인허가"
    source_url = "https://www.data.go.kr/data/15071341/fileData.do"
    category_default = CATEGORY_건설

    def download(self, force: bool = False) -> Path:
        if not force and self.is_raw_cached():
            log.info("[%s] raw 캐시 존재, 스킵", self.id)
            return self.raw_dir()

        out_dir = self.raw_dir()
        log.info("[%s] data.go.kr에서 파일 다운로드 시도", self.id)

        try:
            r = requests.get(
                f"https://www.data.go.kr/cmm/cmm/fileDownload.do?atchFileId=FILE_000000002467296&fileDetailSn=1",
                stream=True, timeout=TIMEOUT_SEC * 3,
                headers={"User-Agent": USER_AGENT},
            )
            r.raise_for_status()
            out_path = out_dir / "building_sanitation.csv"
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

        # 명시적 컬럼 매핑으로 중복 방지
        exact_map = {
            "사업장명": "회사명_원본",
            "업소명": "회사명_원본",
            "전화번호": "대표전화",
            "소재지전화번호": "대표전화",
            "지번주소": "지번주소",
            "소재지지번주소": "지번주소",
            "도로명주소": "도로명주소",
            "소재지도로명주소": "도로명주소",
            "영업상태명": "가동상태",
            "인허가일자": "등록일"
        }
        
        col_map = {}
        for c in df.columns:
            cs = c.strip()
            if cs in exact_map:
                col_map[c] = exact_map[cs]

        df = df.rename(columns=col_map)
        if "회사명_원본" not in df.columns:
            df["회사명_원본"] = ""
        df["회사명"] = df["회사명_원본"].apply(lambda x: str(x).strip() if pd.notna(x) else "")

        # 영업상태 → 가동상태 변환
        if "가동상태" in df.columns:
            status_map = {"영업중": "가동중", "영업/정상": "가동중", "폐업": "폐업", "휴업": "휴업"}
            df["가동상태"] = df["가동상태"].map(lambda x: status_map.get(str(x).strip(), str(x).strip()))

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
