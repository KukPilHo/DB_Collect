"""
한국디자인진흥원 디자인전문회사 (15086381)
===========================================
수집 방식: Open API
카테고리: 도소매_콘텐츠_전문서비스
"""

import time
from pathlib import Path
from typing import List

import pandas as pd
import requests

from src.config import CATEGORY_서비스, DATA_GO_KR_SERVICE_KEY, TIMEOUT_SEC, USER_AGENT, log
from .base import Dataset, ensure_unified_schema, generate_company_key


class IndustrialDesignDataset(Dataset):
    id = "15086381"
    name = "한국디자인진흥원 디자인전문회사"
    source_url = "https://www.data.go.kr/data/15086381/openapi.do"
    category_default = CATEGORY_서비스

    _API_URL = "https://api.odcloud.kr/api/15086381/v1/uddi:7a93d220-2ce4-4e9e-9a0f-24a8e498ef09"

    def download(self, force: bool = False) -> Path:
        if not force and self.is_raw_cached():
            log.info("[%s] raw 캐시 존재, 스킵", self.id)
            return self.raw_dir()

        if not DATA_GO_KR_SERVICE_KEY:
            log.warning("[%s] API 키 미설정", self.id)
            out_dir = self.raw_dir()
            (out_dir / "_NEED_API_KEY.txt").write_text("DATA_GO_KR_SERVICE_KEY 필요")
            return out_dir

        out_dir = self.raw_dir()
        rows: List[dict] = []
        page = 1
        per_page = 500

        log.info("[%s] Open API 페이징 시작", self.id)
        while True:
            try:
                r = requests.get(
                    self._API_URL,
                    params={"serviceKey": DATA_GO_KR_SERVICE_KEY, "page": page, "perPage": per_page, "returnType": "JSON"},
                    timeout=TIMEOUT_SEC,
                    headers={"User-Agent": USER_AGENT},
                )
                r.raise_for_status()
                payload = r.json()
                data = payload.get("data", [])
                if not data:
                    break
                rows.extend(data)
                total = payload.get("totalCount", 0)
                log.info("[%s] page=%d 누적 %d/%s행", self.id, page, len(rows), total)
                if total and len(rows) >= int(total):
                    break
                page += 1
                time.sleep(0.5)
            except Exception as e:
                log.error("[%s] API 호출 실패 page=%d: %s", self.id, page, e)
                break

        out_path = out_dir / "data.json"
        pd.DataFrame(rows).to_json(out_path, orient="records", force_ascii=False)
        log.info("[%s] 저장: %s (%d행)", self.id, out_path, len(rows))
        return out_dir

    def normalize(self) -> pd.DataFrame:
        raw_dir = self.latest_raw_dir()
        if raw_dir is None:
            raise FileNotFoundError(f"[{self.id}] raw 데이터 없음.")

        json_files = list(raw_dir.glob("*.json"))
        if not json_files:
            from .base import build_empty_unified_df
            return build_empty_unified_df()

        df = pd.read_json(json_files[0], dtype=str).fillna("")
        log.info("[%s] 정규화: %d행", self.id, len(df))

        col_map = {}
        for c in df.columns:
            cs = c.strip()
            if "기업" in cs or "회사" in cs or "업체" in cs: col_map[c] = "회사명_원본"
            elif "대표" in cs: col_map[c] = "대표자"
            elif "주소" in cs or "소재" in cs: col_map[c] = "도로명주소"
            elif "전화" in cs or "연락" in cs: col_map[c] = "대표전화"
            elif "분류" in cs or "분야" in cs: col_map[c] = "업종명_원본"
            elif "인력" in cs or "직원" in cs: col_map[c] = "종업원수"
            elif "홈페이지" in cs or "URL" in cs.upper(): col_map[c] = "홈페이지"

        df = df.rename(columns=col_map)
        if "회사명_원본" not in df.columns:
            df["회사명_원본"] = ""
        df["회사명"] = df["회사명_원본"].apply(lambda x: str(x).strip())

        if "도로명주소" in df.columns:
            from .kicox import KicoxDataset
            df["시도"] = df["도로명주소"].apply(KicoxDataset._extract_sido)
            df["시군구"] = df["도로명주소"].apply(KicoxDataset._extract_sigungu)

        df["회사키"] = df.apply(
            lambda r: generate_company_key(None, r.get("회사명",""), r.get("시도"), r.get("시군구")),
            axis=1,
        )

        for col in ("종업원수",):
            if col in df.columns:
                df[col] = pd.to_numeric(df[col].astype(str).str.replace(",","").str.strip(), errors="coerce")

        df = self._set_common_fields(df)
        df = ensure_unified_schema(df)
        df = df.drop_duplicates(subset=["회사키"]).reset_index(drop=True)
        log.info("[%s] 정규화 완료: %d행", self.id, len(df))
        return df
