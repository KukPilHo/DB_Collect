"""
이메일 보강 파이프라인
=======================
candidates 순회 → state 조회 → search 호출 → state 갱신.
ThreadPoolExecutor 동시성 지원.
"""

from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Optional

import pandas as pd
from tqdm import tqdm

from src.config import CANDIDATES_PATH, ENRICHMENT_CONCURRENCY, log
from src.enricher.search import search_emails_for_company
from src.enricher.state import (
    EnrichmentState,
    STATUS_COLLECTED,
    STATUS_FAILED,
    STATUS_NOT_FOUND,
    STATUS_SKIPPED,
)


def _process_one(row: pd.Series, state: EnrichmentState) -> str:
    """회사 한 건 처리. 반환: 상태 문자열."""
    회사키 = row["회사키"]
    회사명 = str(row.get("회사명", "")).strip()
    주소 = str(row.get("도로명주소", "") or row.get("지번주소", "") or "").strip()

    if not 회사명:
        state.upsert(회사키, 회사명, 상태=STATUS_SKIPPED, 에러메시지="회사명 없음")
        return STATUS_SKIPPED

    홈페이지 = str(row.get("홈페이지", "") or "").strip()

    try:
        hits = search_emails_for_company(회사명, 주소, homepage_url=홈페이지)
    except Exception as e:
        state.upsert(회사키, 회사명, 상태=STATUS_FAILED, 에러메시지=str(e))
        return STATUS_FAILED

    if not hits:
        state.upsert(회사키, 회사명, 상태=STATUS_NOT_FOUND)
        return STATUS_NOT_FOUND

    for h in hits:
        state.upsert(
            회사키, 회사명,
            이메일=h.email,
            출처URL=h.source_url,
            방법=h.method,
            상태=STATUS_COLLECTED,
        )
    return STATUS_COLLECTED


def run_enrich(
    category: Optional[str] = None,
    limit: int = 0,
    start_idx: int = 0,
    end_idx: int = 0,
    concurrency: int = ENRICHMENT_CONCURRENCY,
    retry_failed: bool = False,
) -> None:
    """
    candidates.parquet → enrichment_state.sqlite 보강.
    """
    if not CANDIDATES_PATH.exists():
        raise FileNotFoundError("candidates.parquet 없음. sample 먼저 실행.")

    candidates = pd.read_parquet(CANDIDATES_PATH)

    if category:
        candidates = candidates[candidates["카테고리"] == category].copy()
        log.info("카테고리 필터: %s → %d행", category, len(candidates))

    # 범위 지정
    if end_idx > 0:
        candidates = candidates.iloc[start_idx:end_idx]
    elif start_idx > 0:
        candidates = candidates.iloc[start_idx:]

    if limit > 0:
        candidates = candidates.head(limit)

    log.info("enrichment 대상: %d행 (concurrency=%d)", len(candidates), concurrency)

    state = EnrichmentState()
    stats = {STATUS_COLLECTED: 0, STATUS_NOT_FOUND: 0, STATUS_FAILED: 0, STATUS_SKIPPED: 0}

    # 처리 대상 필터링
    to_process = []
    for _, row in candidates.iterrows():
        회사키 = row["회사키"]
        if retry_failed:
            result = state.get_status(회사키)
            if result and result[0] == STATUS_FAILED:
                to_process.append(row)
            elif result is None:
                to_process.append(row)
        elif state.should_process(회사키):
            to_process.append(row)

    skipped = len(candidates) - len(to_process)
    if skipped > 0:
        log.info("기처리 %d건 자동 스킵", skipped)

    if not to_process:
        log.info("처리할 회사 없음 (모두 기처리)")
        state.close()
        return

    # 동시성 1이면 순차 처리 (디버깅 편의)
    if concurrency <= 1:
        for row in tqdm(to_process, desc="이메일 보강"):
            tqdm.write(f"\n[작업 중] {row.get('회사명', '')}")
            status = _process_one(row, state)
            stats[status] = stats.get(status, 0) + 1
    else:
        with ThreadPoolExecutor(max_workers=concurrency) as executor:
            futures = {}
            for row in to_process:
                future = executor.submit(_process_one, row, state)
                futures[future] = row

            for future in tqdm(as_completed(futures), total=len(futures), desc="이메일 보강"):
                row = futures[future]
                try:
                    status = future.result()
                    stats[status] = stats.get(status, 0) + 1
                except Exception as e:
                    log.error("예외 발생 [%s]: %s", row.get("회사명", ""), e)
                    stats[STATUS_FAILED] += 1

    state.close()

    log.info("enrichment 완료:")
    for s, cnt in stats.items():
        log.info("  %s: %d건", s, cnt)
    total = sum(stats.values())
    if total > 0:
        hit_rate = stats[STATUS_COLLECTED] / total * 100
        log.info("  hit rate: %.1f%%", hit_rate)
