"""
카테고리 매핑
==============
master.parquet에 카테고리 컬럼을 채운다.
1차: 출처 데이터셋 ID → 카테고리 (기본)
2차: KSIC 대분류로 검증 (1차와 모순 시 KSIC 우선)
"""

import pandas as pd

from src.config import (
    CATEGORY_IT,
    CATEGORY_건설,
    CATEGORY_서비스,
    CATEGORY_제조,
    MASTER_PATH,
    log,
)

# ── 1차 매핑: 데이터셋 ID → 카테고리 ─────────────────────
_SOURCE_CATEGORY = {
    "15105482": CATEGORY_제조,
    "15057023": CATEGORY_제조,
    "15052274": CATEGORY_IT,
    "innobiz":  CATEGORY_IT,
    "15118569": CATEGORY_서비스,
    "15086381": CATEGORY_서비스,
    "15099307": CATEGORY_서비스,
    "15065485": CATEGORY_건설,
    "15071341": CATEGORY_건설,
}

# ── 2차 매핑: KSIC 대분류 → 카테고리 ─────────────────────
# KSIC 코드의 앞 2자리로 대분류 판단
_KSIC_CATEGORY = {
    # C (10~33) 제조업
    **{str(i): CATEGORY_제조 for i in range(10, 34)},
    # J (58~63) 정보통신업
    **{str(i): CATEGORY_IT for i in range(58, 64)},
    # F (41~42) 건설업
    **{str(i): CATEGORY_건설 for i in range(41, 43)},
    # H (49~52) 운수창고업
    **{str(i): CATEGORY_건설 for i in range(49, 53)},
    # N (74~75) 사업시설관리·사업지원
    **{str(i): CATEGORY_건설 for i in range(74, 76)},
    # G (45~47) 도매소매업
    **{str(i): CATEGORY_서비스 for i in range(45, 48)},
    # M (70~73) 전문과학기술서비스
    **{str(i): CATEGORY_서비스 for i in range(70, 74)},
    # R (90~91) 예술스포츠여가
    **{str(i): CATEGORY_서비스 for i in range(90, 92)},
}


def _get_ksic_category(ksic_code: str) -> str:
    """KSIC 코드 → 카테고리. 매핑 없으면 빈 문자열."""
    if not ksic_code or pd.isna(ksic_code):
        return ""
    code = str(ksic_code).strip()
    if len(code) >= 2:
        prefix = code[:2]
        return _KSIC_CATEGORY.get(prefix, "")
    return ""


def categorize_row(source_id: str, ksic_code: str) -> str:
    """
    1차 매핑(출처 기반) + 2차 검증(KSIC).
    KSIC가 있고 1차와 모순되면 KSIC 우선.
    """
    cat1 = _SOURCE_CATEGORY.get(str(source_id), "")
    cat2 = _get_ksic_category(ksic_code)

    if cat2 and cat2 != cat1:
        # KSIC 우선
        return cat2
    return cat1 if cat1 else CATEGORY_서비스  # 매핑 불가능한 경우 기본값


def run_categorize() -> pd.DataFrame:
    """master.parquet 카테고리 컬럼 채움."""
    if not MASTER_PATH.exists():
        raise FileNotFoundError("master.parquet 없음. build-master 먼저 실행.")

    master = pd.read_parquet(MASTER_PATH)
    log.info("카테고리 매핑 시작: %d행", len(master))

    master["카테고리"] = master.apply(
        lambda r: categorize_row(
            r.get("출처_데이터셋ID", ""),
            r.get("업종_KSIC", ""),
        ),
        axis=1,
    )

    # 카테고리별 분포 로그
    dist = master["카테고리"].value_counts()
    for cat, cnt in dist.items():
        log.info("  %s: %d행", cat, cnt)

    # 카테고리 100% 채워짐 확인
    empty_cat = master["카테고리"].isna().sum() + (master["카테고리"] == "").sum()
    if empty_cat > 0:
        log.warning("카테고리 미지정 행: %d건", empty_cat)

    master.to_parquet(MASTER_PATH, index=False)
    log.info("master.parquet 카테고리 갱신 완료")
    return master
