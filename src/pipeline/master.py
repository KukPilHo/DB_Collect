"""
마스터 빌드
============
모든 normalized parquet을 합치고 dedup → master.parquet
"""

import pandas as pd

from src.config import (
    DATASET_PRIORITY,
    MASTER_PATH,
    NORMALIZED_DIR,
    UNIFIED_COLUMNS,
    log,
)


def _dedup_priority_score(row: pd.Series) -> tuple:
    """
    dedup 우선순위 점수 (낮을수록 우선).
    (1) 데이터셋 우선순위
    (2) 등록일 역순 (최신이 우선 = 큰 값이 먼저 → 음수)
    (3) null 컬럼 수 (적을수록 우선)
    """
    ds_prio = DATASET_PRIORITY.get(str(row.get("출처_데이터셋ID", "")), 99)
    # 등록일: 날짜 문자열 → 정렬 가능하도록
    reg_date = str(row.get("등록일", "") or "")
    null_count = row.isna().sum()
    return (ds_prio, reg_date, null_count)


def build_master(force: bool = False) -> pd.DataFrame:
    """
    normalized/*.parquet → master.parquet (dedup 포함).
    """
    if not force and MASTER_PATH.exists():
        log.info("master.parquet 캐시 존재, 스킵 (--force로 재생성)")
        return pd.read_parquet(MASTER_PATH)

    # 모든 normalized parquet 로드
    parquet_files = sorted(NORMALIZED_DIR.glob("*.parquet"))
    if not parquet_files:
        raise FileNotFoundError("normalized/ 디렉토리에 parquet 파일이 없음. normalize 먼저 실행.")

    dfs = []
    for pf in parquet_files:
        df = pd.read_parquet(pf)
        log.info("로드: %s (%d행)", pf.name, len(df))
        dfs.append(df)

    combined = pd.concat(dfs, ignore_index=True)
    log.info("전체 합산: %d행", len(combined))

    # ── dedup ─────────────────────────────────────────────
    # 회사키별 그룹 → 우선순위 정렬 → 첫 행 선택 + 출처_목록 결합
    result_rows = []
    grouped = combined.groupby("회사키", sort=False)

    for company_key, group in grouped:
        if len(group) == 1:
            row = group.iloc[0].copy()
            row["출처_목록"] = str(row.get("출처_데이터셋ID", ""))
            result_rows.append(row)
        else:
            # 출처_목록: 모든 데이터셋 ID 콤마 결합
            all_sources = ",".join(
                sorted(set(group["출처_데이터셋ID"].dropna().astype(str).unique()))
            )

            # 우선순위 정렬
            scored = []
            for idx, row in group.iterrows():
                ds_prio = DATASET_PRIORITY.get(str(row.get("출처_데이터셋ID", "")), 99)
                reg_date = str(row.get("등록일", "") or "")
                null_count = row.isna().sum()
                scored.append((ds_prio, -len(reg_date), null_count, idx))

            scored.sort()
            best_idx = scored[0][3]
            best = group.loc[best_idx].copy()
            best["출처_목록"] = all_sources
            result_rows.append(best)

    master = pd.DataFrame(result_rows)

    # 컬럼 순서 보장
    for col in UNIFIED_COLUMNS:
        if col not in master.columns:
            master[col] = None
    master = master[UNIFIED_COLUMNS].reset_index(drop=True)

    # 중복 비율 보고
    dup_count = len(combined) - len(master)
    dup_pct = (dup_count / len(combined) * 100) if len(combined) > 0 else 0
    log.info(
        "dedup 완료: %d행 → %d행 (중복 %d행, %.1f%%)",
        len(combined), len(master), dup_count, dup_pct,
    )

    master.to_parquet(MASTER_PATH, index=False)
    log.info("master.parquet 저장 완료: %s", MASTER_PATH)
    return master
