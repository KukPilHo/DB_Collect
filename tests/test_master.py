"""
Master dedup 우선순위 테스트
==============================
"""

import pandas as pd
import pytest
from unittest.mock import patch

from src.config import NORMALIZED_DIR, MASTER_PATH, UNIFIED_COLUMNS
from src.pipeline.master import build_master


@pytest.fixture
def setup_normalized(tmp_path):
    """테스트용 normalized parquet 생성."""
    # NORMALIZED_DIR을 tmp_path로 패치
    norm_dir = tmp_path / "normalized"
    norm_dir.mkdir()
    master_path = tmp_path / "master.parquet"

    # 데이터셋1: KICOX (우선순위 1)
    df1 = pd.DataFrame({
        "회사키": ["key001", "key002", "key003"],
        "사업자등록번호": ["1234567890", "", ""],
        "회사명": ["회사A", "회사B", "회사C"],
        "회사명_원본": ["회사A", "회사B", "회사C"],
        "대표자": ["김대표", None, "박대표"],
        "업종_KSIC": ["10110", "", ""],
        "업종명_원본": ["식품제조", "", ""],
        "시도": ["서울특별시", "경기도", ""],
        "시군구": ["강남구", "수원시", ""],
        "도로명주소": ["서울 강남구 테헤란로 1", "경기 수원시 영통구 1", ""],
        "지번주소": ["", "", ""],
        "대표전화": ["02-1234-5678", "", ""],
        "홈페이지": ["", "", ""],
        "종업원수": [100, None, None],
        "자본금": [500000000, None, None],
        "매출액": [None, None, None],
        "등록일": ["2024-01-15", "2023-06-01", "2022-01-01"],
        "가동상태": ["가동중", "가동중", ""],
        "출처_데이터셋ID": ["15105482", "15105482", "15105482"],
        "출처_URL": ["https://data.go.kr/15105482", "https://data.go.kr/15105482", "https://data.go.kr/15105482"],
        "출처_목록": ["15105482", "15105482", "15105482"],
        "카테고리": ["", "", ""],
        "수집일": ["2024-01-20", "2024-01-20", "2024-01-20"],
    })

    # 데이터셋2: 경기도 (우선순위 2) — key001 중복
    df2 = pd.DataFrame({
        "회사키": ["key001", "key004"],
        "사업자등록번호": ["1234567890", ""],
        "회사명": ["회사A(경기)", "회사D"],
        "회사명_원본": ["회사A(경기)", "회사D"],
        "대표자": ["김대표", "이대표"],
        "업종_KSIC": ["", ""],
        "업종명_원본": ["", "기계제조"],
        "시도": ["경기도", "경기도"],
        "시군구": ["안산시", "평택시"],
        "도로명주소": ["경기 안산시 1", "경기 평택시 1"],
        "지번주소": ["", ""],
        "대표전화": ["031-111-2222", "031-333-4444"],
        "홈페이지": ["", ""],
        "종업원수": [50, 30],
        "자본금": [100000000, 50000000],
        "매출액": [None, None],
        "등록일": ["2024-06-01", "2024-03-01"],
        "가동상태": ["가동중", "가동중"],
        "출처_데이터셋ID": ["15057023", "15057023"],
        "출처_URL": ["https://data.go.kr/15057023", "https://data.go.kr/15057023"],
        "출처_목록": ["15057023", "15057023"],
        "카테고리": ["", ""],
        "수집일": ["2024-01-20", "2024-01-20"],
    })

    df1.to_parquet(norm_dir / "15105482.parquet", index=False)
    df2.to_parquet(norm_dir / "15057023.parquet", index=False)

    return norm_dir, master_path


class TestDedup우선순위:

    def test_중복_회사_kicox_우선(self, setup_normalized):
        """동일 회사키 → KICOX(우선순위 1)가 경기도(우선순위 2)보다 우선."""
        norm_dir, master_path = setup_normalized

        with patch("src.pipeline.master.NORMALIZED_DIR", norm_dir), \
             patch("src.pipeline.master.MASTER_PATH", master_path):
            master = build_master(force=True)

        # key001은 KICOX와 경기도 양쪽에 있음 → KICOX 선택
        key001 = master[master["회사키"] == "key001"]
        assert len(key001) == 1
        assert key001.iloc[0]["출처_데이터셋ID"] == "15105482"  # KICOX

    def test_출처목록_보존(self, setup_normalized):
        """중복 제거 후 출처_목록에 모든 데이터셋 ID 포함."""
        norm_dir, master_path = setup_normalized

        with patch("src.pipeline.master.NORMALIZED_DIR", norm_dir), \
             patch("src.pipeline.master.MASTER_PATH", master_path):
            master = build_master(force=True)

        key001 = master[master["회사키"] == "key001"].iloc[0]
        sources = key001["출처_목록"].split(",")
        assert "15105482" in sources
        assert "15057023" in sources

    def test_고유_회사_보존(self, setup_normalized):
        """중복 아닌 회사는 그대로 보존."""
        norm_dir, master_path = setup_normalized

        with patch("src.pipeline.master.NORMALIZED_DIR", norm_dir), \
             patch("src.pipeline.master.MASTER_PATH", master_path):
            master = build_master(force=True)

        # key001(중복), key002, key003, key004 → 총 4행
        assert len(master) == 4

    def test_dedup_후_행수_감소(self, setup_normalized):
        """합산 5행 → dedup 후 4행."""
        norm_dir, master_path = setup_normalized

        with patch("src.pipeline.master.NORMALIZED_DIR", norm_dir), \
             patch("src.pipeline.master.MASTER_PATH", master_path):
            master = build_master(force=True)

        assert len(master) < 5  # 원본 합산 = 5행
