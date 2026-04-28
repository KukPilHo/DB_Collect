"""
카테고리 매핑 테스트
=====================
- 1차 매핑 (출처 기반)
- 2차 매핑 (KSIC 기반)
- KSIC 모순 케이스 (KSIC 우선)
"""

import pytest
from src.pipeline.category import categorize_row, _get_ksic_category
from src.config import CATEGORY_제조, CATEGORY_IT, CATEGORY_서비스, CATEGORY_건설


class Test1차매핑:
    """출처 데이터셋 ID 기반 카테고리 매핑."""

    def test_kicox_제조(self):
        assert categorize_row("15105482", "") == CATEGORY_제조

    def test_경기도_제조(self):
        assert categorize_row("15057023", "") == CATEGORY_제조

    def test_sw_IT(self):
        assert categorize_row("15052274", "") == CATEGORY_IT

    def test_innobiz_IT(self):
        assert categorize_row("innobiz", "") == CATEGORY_IT

    def test_건설업체(self):
        assert categorize_row("15065485", "") == CATEGORY_건설


class Test2차KSIC:
    """KSIC 대분류 기반 카테고리."""

    def test_제조업_C(self):
        assert _get_ksic_category("10") == CATEGORY_제조
        assert _get_ksic_category("29") == CATEGORY_제조
        assert _get_ksic_category("33101") == CATEGORY_제조

    def test_정보통신_J(self):
        assert _get_ksic_category("58") == CATEGORY_IT
        assert _get_ksic_category("62010") == CATEGORY_IT

    def test_건설_F(self):
        assert _get_ksic_category("41") == CATEGORY_건설

    def test_운수창고_H(self):
        assert _get_ksic_category("49") == CATEGORY_건설

    def test_전문과학기술_M(self):
        assert _get_ksic_category("70") == CATEGORY_서비스
        assert _get_ksic_category("72100") == CATEGORY_서비스

    def test_없는코드(self):
        assert _get_ksic_category("99") == ""
        assert _get_ksic_category("") == ""
        assert _get_ksic_category(None) == ""


class TestKSIC모순:
    """1차 매핑(출처)과 KSIC가 모순될 때 KSIC 우선."""

    def test_kicox에서_왔지만_KSIC가_IT(self):
        """출처=KICOX(제조)인데 KSIC=62(IT) → IT 우선."""
        result = categorize_row("15105482", "62010")
        assert result == CATEGORY_IT

    def test_sw에서_왔지만_KSIC가_제조(self):
        """출처=SW산업(IT)인데 KSIC=29(제조) → 제조 우선."""
        result = categorize_row("15052274", "29000")
        assert result == CATEGORY_제조

    def test_일치하면_그대로(self):
        """출처=KICOX(제조)이고 KSIC=10(제조) → 제조."""
        result = categorize_row("15105482", "10110")
        assert result == CATEGORY_제조

    def test_KSIC없으면_1차매핑(self):
        """KSIC 없으면 출처 기반 1차 매핑 사용."""
        result = categorize_row("15105482", "")
        assert result == CATEGORY_제조
