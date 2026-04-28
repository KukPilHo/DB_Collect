"""
경기도 공장등록현황 (15057023)
===============================
openapi.gg.go.kr/FACTRYREGISTTM
수집 방식: Open API 페이징
카테고리: 제조
KICOX(15105482)와 일부 중복 가능 — dedup이 처리.
"""

import json
import time
from pathlib import Path
from typing import List, Optional

import pandas as pd
import requests
from bs4 import BeautifulSoup
from tenacity import retry, retry_if_exception_type, stop_after_attempt, wait_exponential

from src.config import (
    CATEGORY_제조,
    DATA_GO_KR_SERVICE_KEY,
    GG_API_URL,
    TIMEOUT_SEC,
    USER_AGENT,
    log,
)
from .base import (
    Dataset,
    ensure_unified_schema,
    generate_company_key,
)


@retry(
    stop=stop_after_attempt(3),
    wait=wait_exponential(multiplier=2, max=20),
    retry=retry_if_exception_type(requests.RequestException),
)
def _gg_api_call(page: int, per_page: int) -> dict:
    """경기도 API 한 페이지 호출."""
    if not (DATA_GO_KR_SERVICE_KEY and GG_API_URL):
        raise RuntimeError(
            "DATA_GO_KR_SERVICE_KEY 와 GG_API_URL 환경변수 필요. "
            "data.go.kr/data/15057023 활용신청 후 .env 설정."
        )
    if "openapi.gg.go.kr" in GG_API_URL:
        params = {
            "pIndex": page,
            "pSize": per_page,
            "KEY": DATA_GO_KR_SERVICE_KEY,
            "Type": "json",
        }
    else:
        params = {
            "page": page,
            "perPage": per_page,
            "serviceKey": DATA_GO_KR_SERVICE_KEY,
            "returnType": "JSON",
        }
    r = requests.get(
        GG_API_URL, params=params, timeout=TIMEOUT_SEC,
        headers={"User-Agent": USER_AGENT},
    )
    r.raise_for_status()
    try:
        return r.json()
    except json.JSONDecodeError:
        # XML 폴백
        soup = BeautifulSoup(r.content, "lxml-xml")
        items = []
        for it in soup.find_all("item"):
            items.append({c.name: (c.text or "") for c in it.find_all() if c.name})
        total = soup.find("totalCount")
        return {
            "data": items,
            "totalCount": int(total.text) if total and total.text else len(items),
        }


class GyeonggiDataset(Dataset):
    id = "15057023"
    name = "경기도 공장등록현황"
    source_url = "https://www.data.go.kr/data/15057023/openapi.do"
    category_default = CATEGORY_제조

    def download(self, force: bool = False) -> Path:
        if not force and self.is_raw_cached():
            log.info("[%s] raw 캐시 존재, 스킵", self.id)
            return self.raw_dir()

        if not (DATA_GO_KR_SERVICE_KEY and GG_API_URL):
            log.warning("[%s] API 키 미설정 → 빈 데이터", self.id)
            out_dir = self.raw_dir()
            pd.DataFrame().to_json(out_dir / "data.json", orient="records", force_ascii=False)
            return out_dir

        log.info("[%s] API 페이징 시작", self.id)
        rows: List[dict] = []
        page = 1
        per_page = 1000
        total: Optional[int] = None

        while True:
            try:
                payload = _gg_api_call(page, per_page)
            except Exception as e:
                log.error("[%s] API page=%d 실패: %s", self.id, page, e)
                break

            data = (
                payload.get("data")
                or payload.get("response", {}).get("body", {}).get("items")
            )
            # 경기데이터드림 (FACTRYREGISTTM) 지원
            if not data and "FACTRYREGISTTM" in payload:
                for item in payload["FACTRYREGISTTM"]:
                    if "row" in item:
                        data = item["row"]
                        break
            data = data or []

            if not data:
                break
            rows.extend(data)

            if total is None:
                total = (
                    payload.get("totalCount")
                    or payload.get("response", {}).get("body", {}).get("totalCount")
                )
                if not total and "FACTRYREGISTTM" in payload:
                    for item in payload["FACTRYREGISTTM"]:
                        if "head" in item:
                            total = item["head"][0].get("list_total_count")
                            break
                if total:
                    log.info("[%s] 총 데이터 건수: %s", self.id, total)

            log.info("[%s] page=%d 누적 %d행", self.id, page, len(rows))
            if total and len(rows) >= int(total):
                break
            page += 1
            time.sleep(0.5)

        out_dir = self.raw_dir()
        out_path = out_dir / "data.json"
        pd.DataFrame(rows).to_json(out_path, orient="records", force_ascii=False)
        log.info("[%s] 저장 완료: %s (%d행)", self.id, out_path, len(rows))
        return out_dir

    def normalize(self) -> pd.DataFrame:
        raw_dir = self.latest_raw_dir()
        if raw_dir is None:
            raise FileNotFoundError(
                f"[{self.id}] raw 데이터 없음. 먼저 download 실행 필요."
            )

        # JSON 또는 엑셀 파일 탐색
        json_files = list(raw_dir.glob("*.json"))
        xlsx_files = list(raw_dir.glob("*.xlsx"))

        if json_files:
            df = pd.read_json(json_files[0], dtype=str).fillna("")
        elif xlsx_files:
            df = pd.read_excel(xlsx_files[0], dtype=str).fillna("")
        else:
            raise FileNotFoundError(f"[{self.id}] {raw_dir} 안에 데이터 파일 없음.")

        log.info("[%s] 정규화 시작: %d행", self.id, len(df))

        # 컬럼 매핑 — 경기도 API 컬럼명 명시 매핑
        _EXPLICIT_MAP = {
            "COMPNY_GRP_NM": "회사명_원본",
            "CMPNY_NM": "회사명_원본",
            "REFINE_ROADNM_ADDR": "도로명주소",
            "REFINE_LOTNO_ADDR": "지번주소",
            "TELNO": "대표전화",
            "PRDT_INFO": "업종명_원본",
            "INDUTYPE_DESC_DTCONT": "업종명_원본",
            "INDUTYPE_CD_INFO": "업종_KSIC",
            "EMPLY_CNT": "종업원수",
            "FACTRY_REGIST_DE": "등록일",
            "LOT_AR": "_부지면적",
        }
        col_map = {}
        for c in df.columns:
            cs = c.strip()
            # 명시 매핑 우선
            if cs in _EXPLICIT_MAP:
                target = _EXPLICIT_MAP[cs]
                # 이미 다른 컬럼이 같은 target에 매핑됐으면 스킵 (중복 방지)
                if target not in col_map.values():
                    col_map[c] = target
            elif cs in ("업체명", "회사명", "기업체명"):
                if "회사명_원본" not in col_map.values():
                    col_map[c] = "회사명_원본"
            elif "사업자" in cs and ("번호" in cs or "등록" in cs):
                col_map[c] = "사업자등록번호"
            elif "대표자" in cs or "REPRSNT" in cs.upper():
                col_map[c] = "대표자"
            elif "가동" in cs or "OPERTN" in cs.upper():
                col_map[c] = "가동상태"

        df = df.rename(columns=col_map)

        if "회사명_원본" not in df.columns:
            log.warning("[%s] 회사명 컬럼 매핑 실패, 컬럼: %s", self.id, list(df.columns))
            df["회사명_원본"] = ""

        df["회사명"] = df["회사명_원본"].apply(lambda x: str(x).strip() if pd.notna(x) else "")

        # 시도, 시군구 추출
        addr_col = "도로명주소" if "도로명주소" in df.columns else ("지번주소" if "지번주소" in df.columns else None)
        if addr_col and addr_col in df.columns:
            from .kicox import KicoxDataset
            df["시도"] = df[addr_col].apply(KicoxDataset._extract_sido)
            df["시군구"] = df[addr_col].apply(KicoxDataset._extract_sigungu)

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

        # 공통 필드 설정 + 스키마 통일
        df = self._set_common_fields(df)
        df = ensure_unified_schema(df)
        df = df.drop_duplicates(subset=["회사키"]).reset_index(drop=True)

        log.info("[%s] 정규화 완료: %d행", self.id, len(df))
        return df
