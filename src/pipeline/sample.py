"""
샘플링 파이프라인
==================
master.parquet → candidates.parquet
카테고리별 quota * multiplier만큼 후보 추출.
"""

import numpy as np
import pandas as pd

from src.config import (
    CANDIDATES_PATH,
    CATEGORY_QUOTA,
    MASTER_PATH,
    log,
)

# 수도권 시도 목록
_METRO = {"서울특별시", "경기도", "인천광역시"}

RANDOM_SEED = 42


def run_sample(multiplier: float = 1.5) -> pd.DataFrame:
    """
    master → candidates.parquet.
    카테고리별 quota × multiplier 추출.
    """
    if not MASTER_PATH.exists():
        raise FileNotFoundError("master.parquet 없음. build-master + categorize 먼저 실행.")

    master = pd.read_parquet(MASTER_PATH)
    log.info("샘플링 시작: master %d행, multiplier=%.1f", len(master), multiplier)

    candidates_list = []

    for category, quota in CATEGORY_QUOTA.items():
        target_n = int(quota * multiplier)
        pool = master[master["카테고리"] == category].copy()

        if pool.empty:
            log.warning("[%s] 해당 카테고리 데이터 0행, 스킵", category)
            continue

        log.info("[%s] 풀 크기: %d → 목표 candidate: %d", category, len(pool), target_n)

        # ── (1) 가동상태 = 가동중만 (컬럼이 있고 값이 있는 행만 필터) ─
        if "가동상태" in pool.columns:
            has_status = pool["가동상태"].notna() & (pool["가동상태"] != "")
            active = pool[has_status & pool["가동상태"].isin(["가동중", "가동", "정상"])]
            # 가동상태 정보가 있는 행 중 가동중만 + 가동상태 정보 없는 행 유지
            no_status = pool[~has_status]
            pool = pd.concat([active, no_status], ignore_index=True)

        # ── (2) 영세 기업 제외 (하위 10%) ─────────────────
        for col in ("종업원수", "자본금"):
            if col in pool.columns:
                numeric = pd.to_numeric(pool[col], errors="coerce")
                has_val = numeric.notna()
                if has_val.sum() > 10:
                    threshold = numeric[has_val].quantile(0.1)
                    # 값이 있으면서 하위 10%인 행만 제외, 값 없는 행은 유지
                    exclude = has_val & (numeric <= threshold)
                    pool = pool[~exclude].copy()

        # ── (3) 시도 stratified: 수도권 60%, 비수도권 40% ─
        if "시도" in pool.columns and pool["시도"].notna().sum() > 0:
            metro = pool[pool["시도"].isin(_METRO)]
            non_metro = pool[~pool["시도"].isin(_METRO)]

            metro_target = int(target_n * 0.6)
            non_metro_target = target_n - metro_target

            rng = np.random.RandomState(RANDOM_SEED)

            # 등록일 신순 정렬 후 상위에서 추출
            for subset in [metro, non_metro]:
                if "등록일" in subset.columns:
                    subset = subset.sort_values("등록일", ascending=False, na_position="last")

            if len(metro) >= metro_target:
                metro_sample = metro.head(int(metro_target * 1.2)).sample(
                    n=min(metro_target, len(metro)),
                    random_state=RANDOM_SEED,
                )
            else:
                metro_sample = metro

            if len(non_metro) >= non_metro_target:
                non_metro_sample = non_metro.head(int(non_metro_target * 1.2)).sample(
                    n=min(non_metro_target, len(non_metro)),
                    random_state=RANDOM_SEED,
                )
            else:
                non_metro_sample = non_metro

            pool = pd.concat([metro_sample, non_metro_sample], ignore_index=True)
        else:
            # 시도 정보 없으면 등록일 신순으로 상위 추출
            if "등록일" in pool.columns:
                pool = pool.sort_values("등록일", ascending=False, na_position="last")
            pool = pool.head(int(target_n * 1.2)).sample(
                n=min(target_n, len(pool)),
                random_state=RANDOM_SEED,
            )

        # ── (4) KSIC cap: 동일 KSIC 5자리에 5% 이상 쏠리지 않도록 ─
        if "업종_KSIC" in pool.columns and pool["업종_KSIC"].notna().sum() > 0:
            cap = max(1, int(len(pool) * 0.05))
            ksic_counts = pool["업종_KSIC"].value_counts()
            over_cap = ksic_counts[ksic_counts > cap].index.tolist()
            if over_cap:
                keep_rows = []
                for ksic in over_cap:
                    subset = pool[pool["업종_KSIC"] == ksic]
                    keep_rows.append(subset.sample(n=cap, random_state=RANDOM_SEED))
                not_over = pool[~pool["업종_KSIC"].isin(over_cap)]
                pool = pd.concat([not_over] + keep_rows, ignore_index=True)

        # 최종 target_n 맞추기
        if len(pool) > target_n:
            pool = pool.sample(n=target_n, random_state=RANDOM_SEED)

        log.info("[%s] 최종 candidate: %d행 (quota %d × %.1f = %d)",
                 category, len(pool), quota, multiplier, target_n)
        candidates_list.append(pool)

    candidates = pd.concat(candidates_list, ignore_index=True)
    candidates.to_parquet(CANDIDATES_PATH, index=False)
    log.info("candidates.parquet 저장 완료: %d행", len(candidates))

    # 카테고리별 요약
    dist = candidates["카테고리"].value_counts()
    for cat, cnt in dist.items():
        log.info("  %s: %d명", cat, cnt)

    return candidates
