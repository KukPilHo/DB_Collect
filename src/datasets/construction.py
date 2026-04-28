"""
전국건설업체정보표준데이터 (15065485)
======================================
수집 방식: 파일 다운로드 (표준데이터, CSV)
카테고리: 건설_물류_시설
"""

from pathlib import Path

import pandas as pd
import requests

from src.config import CATEGORY_건설, TIMEOUT_SEC, USER_AGENT, log
from .base import Dataset, ensure_unified_schema, generate_company_key


class ConstructionDataset(Dataset):
    id = "15065485"
    name = "전국건설업체정보표준데이터"
    source_url = "https://www.data.go.kr/data/15065485/standard.do"
    category_default = CATEGORY_건설

    def download(self, force: bool = False) -> Path:
        if not force and self.is_raw_cached():
            log.info("[%s] raw 캐시 존재, 스킵", self.id)
            return self.raw_dir()

        out_dir = self.raw_dir()
        log.info("[%s] data.go.kr KISCON OpenAPI 호출 시도 (서울, 2003~2010년, 1000건)", self.id)

        import os
        from urllib.parse import unquote
        
        service_key = os.getenv("DATA_GO_KR_SERVICE_KEY")
        if not service_key:
            log.warning("[%s] DATA_GO_KR_SERVICE_KEY 환경변수 없음", self.id)
            return out_dir

        # API 키가 이미 인코딩되어 있을 수 있으므로 디코딩 처리 (requests가 재인코딩함)
        service_key_dec = unquote(service_key)

        url = "http://apis.data.go.kr/1613000/ConAdminInfoSvc1/GongsiReg"
        params = {
            "serviceKey": service_key_dec,
            "pageNo": "1",
            "numOfRows": "1000",
            "sDate": "20030101",
            "eDate": "20101231",
            "ncrAreaName": "서울",
            "_type": "json"
        }
        
        try:
            r = requests.get(url, params=params, timeout=TIMEOUT_SEC * 3)
            r.raise_for_status()
            out_path = out_dir / "construction.json"
            out_path.write_text(r.text, encoding="utf-8")
            log.info("[%s] OpenAPI 호출 성공, 저장: %s", self.id, out_path)
        except Exception as e:
            log.warning("[%s] OpenAPI 호출 실패: %s", self.id, e)

        return out_dir

    def normalize(self) -> pd.DataFrame:
        raw_dir = self.latest_raw_dir()
        if raw_dir is None:
            raise FileNotFoundError(f"[{self.id}] raw 데이터 없음.")

        files = [f for f in raw_dir.glob("*") if f.suffix.lower() in (".json", ".csv", ".xlsx")]
        if not files:
            from .base import build_empty_unified_df
            return build_empty_unified_df()

        # json 우선 처리
        json_files = [f for f in files if f.suffix.lower() == ".json"]
        path = sorted(json_files)[-1] if json_files else sorted(files)[-1]
        log.info("[%s] 정규화: %s", self.id, path)

        if path.suffix.lower() == ".json":
            import json
            try:
                data = json.loads(path.read_text(encoding="utf-8"))
                items = data.get("response", {}).get("body", {}).get("items", {}).get("item", [])
                if isinstance(items, dict):
                    items = [items]
                df = pd.DataFrame(items).astype(str)
                
                # API 컬럼 매핑
                col_map = {
                    "ncrGsKname": "회사명_원본",
                    "ncrGsMaster": "대표자",
                    "ncrGsAddr": "도로명주소",
                    "ncrGsRegdate": "등록일",
                    "ncrItemName": "업종명_원본",
                    "ncrMasterNum": "사업자등록번호",
                    "ncrOffTel": "대표전화",
                }
                
                # 없는 컬럼은 빈 값으로 처리하여 에러 방지
                rename_map = {k: v for k, v in col_map.items() if k in df.columns}
                df = df.rename(columns=rename_map)
                
            except Exception as e:
                log.warning("[%s] JSON 파싱 실패: %s", self.id, e)
                return self._empty_df()
        elif path.suffix.lower() == ".csv":
            try:
                df = pd.read_csv(path, dtype=str, encoding="utf-8").fillna("")
            except UnicodeDecodeError:
                df = pd.read_csv(path, dtype=str, encoding="cp949", encoding_errors="replace").fillna("")
            except pd.errors.EmptyDataError:
                return self._empty_df()
            col_map = {}
            for c in df.columns:
                cs = c.strip()
                if "사업자" in cs and "번호" in cs: col_map[c] = "사업자등록번호"
                elif "업체" in cs or "회사" in cs or "상호" in cs: col_map[c] = "회사명_원본"
                elif "대표" in cs and "자" in cs: col_map[c] = "대표자"
                elif "도로명" in cs and "주소" in cs: col_map[c] = "도로명주소"
                elif "지번" in cs: col_map[c] = "지번주소"
                elif "소재" in cs or "주소" in cs: col_map[c] = "도로명주소"
                elif "전화" in cs or "연락" in cs: col_map[c] = "대표전화"
                elif "업종" in cs: col_map[c] = "업종명_원본"
                elif "면허" in cs or "등록" in cs and "일" in cs: col_map[c] = "등록일"
                elif "자본금" in cs: col_map[c] = "자본금"
            df = df.rename(columns=col_map)
        else:
            df = pd.read_excel(path, dtype=str).fillna("")

        df = df.rename(columns=col_map)
        if "회사명_원본" not in df.columns:
            df["회사명_원본"] = ""
        df["회사명"] = df["회사명_원본"].apply(lambda x: str(x).strip() if pd.notna(x) else "")

        if "도로명주소" in df.columns:
            from .kicox import KicoxDataset
            df["시도"] = df["도로명주소"].apply(KicoxDataset._extract_sido)
            df["시군구"] = df["도로명주소"].apply(KicoxDataset._extract_sigungu)

        df["회사키"] = df.apply(
            lambda r: generate_company_key(r.get("사업자등록번호"), r.get("회사명",""), r.get("시도"), r.get("시군구")),
            axis=1,
        )

        for col in ("자본금",):
            if col in df.columns:
                df[col] = pd.to_numeric(df[col].astype(str).str.replace(",","").str.strip(), errors="coerce")

        df = self._set_common_fields(df)
        df = ensure_unified_schema(df)
        df = df.drop_duplicates(subset=["회사키"]).reset_index(drop=True)
        log.info("[%s] 정규화 완료: %d행", self.id, len(df))
        return df
