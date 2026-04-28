"""
Enrichment State 상태 전이 테스트
===================================
- collected / not_found / failed / skipped 상태
- should_process 판단 로직
- 재시도 횟수 관리
"""

import os
import pytest
import tempfile

from src.enricher.state import (
    EnrichmentState,
    STATUS_COLLECTED,
    STATUS_NOT_FOUND,
    STATUS_FAILED,
    STATUS_SKIPPED,
    MAX_RETRY,
)


@pytest.fixture
def state_db():
    """임시 SQLite DB로 테스트."""
    fd, path = tempfile.mkstemp(suffix=".sqlite")
    os.close(fd)
    s = EnrichmentState(db_path=path)
    yield s
    s.close()
    os.unlink(path)


class Test상태조회:

    def test_행없음_None(self, state_db):
        """행이 없으면 None 반환."""
        assert state_db.get_status("nonexistent") is None

    def test_collected_상태(self, state_db):
        state_db.upsert("key1", "회사1", 이메일="a@b.com", 상태=STATUS_COLLECTED)
        result = state_db.get_status("key1")
        assert result[0] == STATUS_COLLECTED

    def test_not_found_상태(self, state_db):
        state_db.upsert("key2", "회사2", 상태=STATUS_NOT_FOUND)
        result = state_db.get_status("key2")
        assert result[0] == STATUS_NOT_FOUND


class Test상태전이:

    def test_새회사_처리가능(self, state_db):
        """행 없음 → should_process = True."""
        assert state_db.should_process("new_key") is True

    def test_collected_스킵(self, state_db):
        """collected → should_process = False."""
        state_db.upsert("key1", "회사1", 이메일="a@b.com", 상태=STATUS_COLLECTED)
        assert state_db.should_process("key1") is False

    def test_not_found_스킵(self, state_db):
        """not_found → should_process = False."""
        state_db.upsert("key2", "회사2", 상태=STATUS_NOT_FOUND)
        assert state_db.should_process("key2") is False

    def test_skipped_스킵(self, state_db):
        """skipped → should_process = False."""
        state_db.upsert("key3", "회사3", 상태=STATUS_SKIPPED)
        assert state_db.should_process("key3") is False

    def test_failed_재시도가능(self, state_db):
        """failed + 재시도횟수 < MAX_RETRY → should_process = True."""
        state_db.upsert("key4", "회사4", 상태=STATUS_FAILED)
        assert state_db.should_process("key4") is True

    def test_failed_재시도한도초과(self, state_db):
        """failed + 재시도횟수 >= MAX_RETRY → should_process = False."""
        state_db.upsert("key5", "회사5", 상태=STATUS_FAILED)
        # 재시도 반복하여 한도 초과
        for _ in range(MAX_RETRY + 1):
            state_db.upsert("key5", "회사5", 상태=STATUS_FAILED)
        assert state_db.should_process("key5") is False


class Test다중이메일:

    def test_한회사_다수이메일(self, state_db):
        """한 회사에 여러 이메일 → 행 분할 저장."""
        state_db.upsert("key1", "회사1", 이메일="a@b.com", 상태=STATUS_COLLECTED)
        state_db.upsert("key1", "회사1", 이메일="c@d.com", 상태=STATUS_COLLECTED)

        emails = state_db.get_all_emails()
        key1_emails = [e for e in emails if e["회사키"] == "key1"]
        assert len(key1_emails) == 2

    def test_not_found_빈이메일(self, state_db):
        """not_found → 이메일 = '' 마커 행."""
        state_db.upsert("key2", "회사2", 이메일="", 상태=STATUS_NOT_FOUND)
        emails = state_db.get_all_emails()
        key2 = [e for e in emails if e["회사키"] == "key2"]
        assert len(key2) == 1
        assert key2[0]["이메일"] == ""


class Test카운트:

    def test_상태별카운트(self, state_db):
        state_db.upsert("k1", "a", 이메일="a@b.com", 상태=STATUS_COLLECTED)
        state_db.upsert("k2", "b", 상태=STATUS_NOT_FOUND)
        state_db.upsert("k3", "c", 상태=STATUS_FAILED)
        state_db.upsert("k4", "d", 상태=STATUS_SKIPPED)

        counts = state_db.count_by_status()
        assert counts.get(STATUS_COLLECTED, 0) == 1
        assert counts.get(STATUS_NOT_FOUND, 0) == 1
        assert counts.get(STATUS_FAILED, 0) == 1
        assert counts.get(STATUS_SKIPPED, 0) == 1
