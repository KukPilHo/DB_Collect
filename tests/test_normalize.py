"""
회사키 정규화 테스트
=====================
- 사업자등록번호 있는 케이스
- 사업자등록번호 없는 케이스 (해시 기반)
"""

import pytest
from src.datasets.base import generate_company_key, normalize_company_name


class Test회사명정규화:
    """회사명 normalize 함수 테스트."""

    def test_법인격_제거(self):
        assert normalize_company_name("(주)삼성전자") == "삼성전자"
        assert normalize_company_name("주식회사 엘지") == "엘지"
        assert normalize_company_name("(주식회사)현대") == "현대"

    def test_공백_제거(self):
        assert normalize_company_name("삼 성 전 자") == "삼성전자"

    def test_특수문자_제거(self):
        assert normalize_company_name("삼성.전자(주)") == "삼성전자"
        assert normalize_company_name("'삼성전자'") == "삼성전자"

    def test_영문_lower(self):
        assert normalize_company_name("Samsung Electronics") == "samsungelectronics"

    def test_빈값(self):
        assert normalize_company_name("") == ""
        assert normalize_company_name(None) == ""

    def test_복합_케이스(self):
        assert normalize_company_name("(주) SK하이닉스.") == "sk하이닉스"


class Test회사키생성:
    """회사키 generate_company_key 테스트."""

    def test_사업자등록번호_있는_케이스(self):
        """사업자등록번호(10자리)가 있으면 하이픈 제거 후 그대로 사용."""
        key = generate_company_key("123-45-67890", "테스트회사")
        assert key == "1234567890"

    def test_사업자등록번호_하이픈_없는_케이스(self):
        key = generate_company_key("1234567890", "테스트회사")
        assert key == "1234567890"

    def test_사업자등록번호_길이_부적합(self):
        """10자리가 아니면 해시 기반으로 전환."""
        key = generate_company_key("12345", "테스트회사", "서울특별시", "강남구")
        assert len(key) == 16  # sha256[:16]

    def test_사업자등록번호_없는_케이스_해시(self):
        """사업자등록번호 없으면 회사명+시도+시군구 해시."""
        key = generate_company_key(None, "테스트회사", "서울특별시", "강남구")
        assert len(key) == 16

    def test_같은_입력_같은_키(self):
        """동일 입력은 동일 키 생성."""
        k1 = generate_company_key(None, "(주)테스트회사", "서울특별시", "강남구")
        k2 = generate_company_key(None, "(주)테스트회사", "서울특별시", "강남구")
        assert k1 == k2

    def test_다른_입력_다른_키(self):
        """다른 시도/시군구 → 다른 키."""
        k1 = generate_company_key(None, "테스트회사", "서울특별시", "강남구")
        k2 = generate_company_key(None, "테스트회사", "경기도", "수원시")
        assert k1 != k2

    def test_사업자번호_빈문자열(self):
        """빈 문자열도 None과 동일 처리."""
        key = generate_company_key("", "테스트회사", "서울특별시", "강남구")
        assert len(key) == 16
