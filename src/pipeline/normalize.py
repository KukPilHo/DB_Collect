"""
정규화 파이프라인
==================
각 Dataset.normalize() 호출 → normalized/<id>.parquet 저장.
"""

from typing import List, Optional

import pandas as pd

from src.config import log
from src.datasets import DATASETS, get_dataset_by_id
from src.datasets.base import Dataset


def run_normalize(
    dataset_ids: Optional[List[str]] = None,
    force: bool = False,
) -> None:
    """
    데이터셋 정규화 실행.
    dataset_ids 미지정 시 모든 등록 데이터셋 대상.
    """
    targets: List[Dataset] = []
    if dataset_ids:
        for did in dataset_ids:
            ds = get_dataset_by_id(did)
            if ds is None:
                log.warning("데이터셋 ID '%s'를 찾을 수 없음, 스킵", did)
            else:
                targets.append(ds)
    else:
        targets = DATASETS

    for ds in targets:
        if not force and ds.is_normalized_cached():
            log.info("[%s] normalized 캐시 존재, 스킵", ds.id)
            continue

        try:
            df = ds.normalize()
            out_path = ds.normalized_path()
            df.to_parquet(out_path, index=False)
            log.info("[%s] → %s (%d행)", ds.id, out_path, len(df))
        except Exception as e:
            log.error("[%s] 정규화 실패: %s", ds.id, e)
