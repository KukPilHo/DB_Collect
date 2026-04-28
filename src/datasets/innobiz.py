"""
이노비즈 기업정보
==================
innobiz.net/company/company2_list.asp
수집 방식: 웹 크롤링 (공식 API 없음)
카테고리: IT_SW_벤처
셀렉터를 한 곳에 모아 구조 변경 대응.
"""

from pathlib import Path
from typing import List

import pandas as pd
import requests
import time
from bs4 import BeautifulSoup

from src.config import CATEGORY_IT, CRAWL_DELAY_SEC, TIMEOUT_SEC, USER_AGENT, log
from .base import Dataset, ensure_unified_schema, generate_company_key

# ── 셀렉터 중앙 관리 ─────────────────────────────────────
# HTML 구조 변경 시 여기만 수정
SELECTORS = {
    "list_table": "table.table_list",       # 목록 테이블
    "list_rows": "table.table_list tbody tr",  # 각 행
    "company_name": "td:nth-child(2)",       # 기업명 셀
    "industry": "td:nth-child(3)",           # 업종 셀
    "region": "td:nth-child(4)",             # 지역 셀
    "cert_date": "td:nth-child(5)",          # 인증일 셀
}

BASE_URL = "https://www.innobiz.net/company/company2_list.asp"


def _validate_page_structure(soup: BeautifulSoup) -> bool:
    """페이지 구조 검증. 테이블이 없으면 False."""
    table = soup.select_one(SELECTORS["list_table"])
    return table is not None


class InnobizDataset(Dataset):
    id = "innobiz"
    name = "이노비즈 기업정보"
    source_url = "https://www.innobiz.net/company/company2_list.asp"
    category_default = CATEGORY_IT

    def download(self, force: bool = False) -> Path:
        if not force and self.is_raw_cached():
            log.info("[%s] raw 캐시 존재, 스킵", self.id)
            return self.raw_dir()

        out_dir = self.raw_dir()
        all_rows: List[dict] = []
        page = 1
        max_pages = 50  # 안전 한도

        log.info("[%s] 웹 크롤링 시작: %s", self.id, BASE_URL)

        while page <= max_pages:
            try:
                r = requests.get(
                    BASE_URL, params={"page": page},
                    timeout=TIMEOUT_SEC,
                    headers={"User-Agent": USER_AGENT},
                )
                r.raise_for_status()
                if r.encoding is None or r.encoding.lower() == "iso-8859-1":
                    r.encoding = r.apparent_encoding

                soup = BeautifulSoup(r.text, "lxml")

                if page == 1 and not _validate_page_structure(soup):
                    raise ValueError(
                        f"[{self.id}] 페이지 구조 변경 감지! "
                        f"셀렉터 '{SELECTORS['list_table']}'에 해당하는 테이블 없음. "
                        f"innobiz.net HTML 구조를 확인하고 SELECTORS를 수정하세요."
                    )

                rows = soup.select(SELECTORS["list_rows"])
                if not rows:
                    break

                for tr in rows:
                    cells = tr.find_all("td")
                    if len(cells) < 4:
                        continue
                    all_rows.append({
                        "회사명": cells[1].get_text(strip=True) if len(cells) > 1 else "",
                        "업종": cells[2].get_text(strip=True) if len(cells) > 2 else "",
                        "지역": cells[3].get_text(strip=True) if len(cells) > 3 else "",
                        "인증일": cells[4].get_text(strip=True) if len(cells) > 4 else "",
                    })

                log.info("[%s] page=%d, 누적 %d행", self.id, page, len(all_rows))
                page += 1
                time.sleep(CRAWL_DELAY_SEC)

            except ValueError:
                raise  # 구조 변경은 즉시 중단
            except Exception as e:
                log.warning("[%s] page=%d 크롤링 실패: %s", self.id, page, e)
                break

        if all_rows:
            df = pd.DataFrame(all_rows)
            out_path = out_dir / "innobiz.csv"
            df.to_csv(out_path, index=False, encoding="utf-8-sig")
            log.info("[%s] 저장 완료: %s (%d행)", self.id, out_path, len(all_rows))
        else:
            log.warning("[%s] 크롤링 결과 0행", self.id)

        return out_dir

    def normalize(self) -> pd.DataFrame:
        raw_dir = self.latest_raw_dir()
        if raw_dir is None:
            raise FileNotFoundError(f"[{self.id}] raw 데이터 없음.")

        files = list(raw_dir.glob("*.csv"))
        if not files:
            log.warning("[%s] CSV 파일 없음, 빈 DataFrame 반환", self.id)
            from .base import build_empty_unified_df
            return build_empty_unified_df()

        df = pd.read_csv(files[0], dtype=str).fillna("")
        log.info("[%s] 정규화: %d행", self.id, len(df))

        df = df.rename(columns={
            "회사명": "회사명_원본",
            "업종": "업종명_원본",
            "지역": "시도",
            "인증일": "등록일",
        })

        df["회사명"] = df["회사명_원본"].apply(lambda x: str(x).strip())

        df["회사키"] = df.apply(
            lambda r: generate_company_key(None, r.get("회사명",""), r.get("시도"), None),
            axis=1,
        )

        df = self._set_common_fields(df)
        df = ensure_unified_schema(df)
        df = df.drop_duplicates(subset=["회사키"]).reset_index(drop=True)
        log.info("[%s] 정규화 완료: %d행", self.id, len(df))
        return df
