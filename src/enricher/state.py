"""
Enrichment 상태 관리 (SQLite)
==============================
enrichment_state.sqlite를 통해 크롤링 진행 상태를 영속화.
"""

import sqlite3
from datetime import datetime
from typing import Dict, List, Optional, Tuple

from src.config import ENRICHMENT_DB_PATH

STATUS_COLLECTED = "collected"
STATUS_NOT_FOUND = "not_found"
STATUS_FAILED = "failed"
STATUS_SKIPPED = "skipped"
MAX_RETRY = 2

_CREATE_SQL = """
CREATE TABLE IF NOT EXISTS emails (
    회사키        TEXT NOT NULL,
    이메일        TEXT NOT NULL DEFAULT '',
    회사명        TEXT NOT NULL,
    이메일_출처_URL TEXT,
    이메일_방법    TEXT,
    상태          TEXT NOT NULL,
    조회시각      TEXT NOT NULL,
    재시도_횟수    INTEGER NOT NULL DEFAULT 0,
    에러_메시지    TEXT,
    PRIMARY KEY (회사키, 이메일)
);
CREATE INDEX IF NOT EXISTS idx_emails_상태 ON emails(상태);
CREATE INDEX IF NOT EXISTS idx_emails_회사키 ON emails(회사키);
"""


class EnrichmentState:
    """enrichment_state.sqlite 인터페이스."""

    def __init__(self, db_path: str = None):
        self.db_path = db_path or str(ENRICHMENT_DB_PATH)
        self.conn = sqlite3.connect(self.db_path, check_same_thread=False)
        self.conn.execute("PRAGMA journal_mode=WAL")
        self.conn.executescript(_CREATE_SQL)
        self.conn.commit()

    def close(self):
        self.conn.close()

    def get_status(self, 회사키: str) -> Optional[Tuple[str, int]]:
        cur = self.conn.execute(
            "SELECT 상태, 재시도_횟수 FROM emails WHERE 회사키 = ? LIMIT 1", (회사키,)
        )
        row = cur.fetchone()
        return (row[0], row[1]) if row else None

    def upsert(self, 회사키: str, 회사명: str, 이메일: str = "",
               출처URL: str = "", 방법: str = "", 상태: str = STATUS_COLLECTED,
               에러메시지: str = None) -> None:
        now = datetime.now().isoformat(timespec="seconds")
        cur = self.conn.execute(
            "SELECT 재시도_횟수 FROM emails WHERE 회사키 = ? AND 이메일 = ?", (회사키, 이메일)
        )
        row = cur.fetchone()
        retry_count = (row[0] + 1) if row else 0
        self.conn.execute("""
            INSERT INTO emails (회사키,이메일,회사명,이메일_출처_URL,이메일_방법,상태,조회시각,재시도_횟수,에러_메시지)
            VALUES (?,?,?,?,?,?,?,?,?)
            ON CONFLICT(회사키,이메일) DO UPDATE SET
                회사명=excluded.회사명, 이메일_출처_URL=excluded.이메일_출처_URL,
                이메일_방법=excluded.이메일_방법, 상태=excluded.상태,
                조회시각=excluded.조회시각, 재시도_횟수=excluded.재시도_횟수,
                에러_메시지=excluded.에러_메시지
        """, (회사키, 이메일, 회사명, 출처URL, 방법, 상태, now, retry_count, 에러메시지))
        self.conn.commit()

    def should_process(self, 회사키: str) -> bool:
        result = self.get_status(회사키)
        if result is None:
            return True
        status, retry_count = result
        if status in (STATUS_COLLECTED, STATUS_NOT_FOUND, STATUS_SKIPPED):
            return False
        if status == STATUS_FAILED and retry_count < MAX_RETRY:
            return True
        return False

    def count_by_status(self, 카테고리: str = None) -> Dict[str, int]:
        cur = self.conn.execute(
            "SELECT 상태, COUNT(DISTINCT 회사키) FROM emails GROUP BY 상태"
        )
        return dict(cur.fetchall())

    def list_companies_by_status(self, 상태: str) -> List[str]:
        cur = self.conn.execute(
            "SELECT DISTINCT 회사키 FROM emails WHERE 상태 = ?", (상태,)
        )
        return [row[0] for row in cur.fetchall()]

    def get_all_emails(self) -> List[dict]:
        cur = self.conn.execute(
            "SELECT 회사키,이메일,회사명,이메일_출처_URL,이메일_방법,상태,조회시각 FROM emails"
        )
        cols = ["회사키","이메일","회사명","이메일_출처_URL","이메일_방법","상태","조회시각"]
        return [dict(zip(cols, row)) for row in cur.fetchall()]

    def total_processed(self) -> int:
        cur = self.conn.execute("SELECT COUNT(DISTINCT 회사키) FROM emails")
        return cur.fetchone()[0]
