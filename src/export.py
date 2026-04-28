"""
엑셀 엑스포트
==============
enrichment_state JOIN master → output/outbound_db_<날짜>.xlsx
시트 6개: 카테고리 4시트 + 통합 + summary
그레이스케일 스타일링 (기존 save_db_excel 이식).
"""

from datetime import date

import pandas as pd
from openpyxl.styles import Alignment, Font, PatternFill

from src.config import (
    CATEGORY_QUOTA,
    MASTER_PATH,
    OUTPUT_DIR,
    log,
)
from src.enricher.state import EnrichmentState, STATUS_COLLECTED


def _style_sheet(ws, df: pd.DataFrame) -> None:
    """그레이스케일 엑셀 스타일링: 헤더 #D9D9D9, bold, freeze A2."""
    header_fill = PatternFill("solid", fgColor="D9D9D9")
    header_font = Font(bold=True)
    header_align = Alignment(horizontal="left", vertical="center")

    for cell in ws[1]:
        cell.font = header_font
        cell.fill = header_fill
        cell.alignment = header_align

    # 컬럼 너비 자동 조정
    for i, col in enumerate(df.columns, start=1):
        sample = df[col].astype(str).fillna("").head(200)
        width = max([len(str(col))] + [min(len(str(v)), 60) for v in sample]) + 2
        ws.column_dimensions[ws.cell(row=1, column=i).column_letter].width = min(max(12, width), 60)

    ws.freeze_panes = "A2"


def run_export() -> str:
    """enrichment_state + master → 최종 엑셀 생성."""
    if not MASTER_PATH.exists():
        raise FileNotFoundError("master.parquet 없음.")

    master = pd.read_parquet(MASTER_PATH)
    state = EnrichmentState()
    emails = state.get_all_emails()
    state.close()

    # 이메일 데이터를 DataFrame으로
    email_df = pd.DataFrame(emails)

    if email_df.empty:
        log.warning("enrichment_state에 데이터 없음. 빈 엑셀 생성.")
        email_df = pd.DataFrame(columns=["회사키", "이메일", "이메일_출처_URL", "이메일_방법", "상태"])

    # master와 JOIN
    if not email_df.empty:
        # collected인 행만 (이메일 있는 것)
        collected = email_df[email_df["상태"] == STATUS_COLLECTED].copy()
        if not collected.empty:
            # 중복 회사명 컬럼 제거 후 JOIN
            collected = collected.drop(columns=["회사명"], errors="ignore")
            merged = master.merge(collected, on="회사키", how="inner")
        else:
            merged = master.head(0)  # 빈 DataFrame
    else:
        merged = master.head(0)

    # 출력 컬럼 선택
    out_cols = [
        "회사명", "사업자등록번호", "대표자", "업종명_원본",
        "시도", "시군구", "도로명주소", "대표전화", "홈페이지",
        "종업원수", "자본금", "카테고리", "출처_데이터셋ID",
        "이메일", "이메일_출처_URL", "이메일_방법",
    ]
    out_cols = [c for c in out_cols if c in merged.columns]

    out_path = OUTPUT_DIR / f"outbound_db_{date.today().isoformat()}.xlsx"

    with pd.ExcelWriter(out_path, engine="openpyxl") as writer:
        # 카테고리별 시트
        categories = list(CATEGORY_QUOTA.keys())
        summary_data = []

        for cat in categories:
            cat_df = merged[merged["카테고리"] == cat][out_cols].copy() if not merged.empty else pd.DataFrame(columns=out_cols)
            sheet_name = cat[:31]  # 엑셀 시트명 31자 제한
            cat_df.to_excel(writer, sheet_name=sheet_name, index=False)
            ws = writer.book[sheet_name]
            _style_sheet(ws, cat_df)

            # summary 데이터
            quota = CATEGORY_QUOTA.get(cat, 0)
            actual = len(cat_df.drop_duplicates(subset=["회사키"])) if "회사키" in cat_df.columns else len(cat_df)
            summary_data.append({
                "카테고리": cat,
                "목표(quota)": quota,
                "실제 행수": len(cat_df),
                "고유 회사 수": actual,
                "미달/초과": actual - quota,
            })

        # 통합 시트
        if not merged.empty:
            merged[out_cols].to_excel(writer, sheet_name="통합", index=False)
            ws = writer.book["통합"]
            _style_sheet(ws, merged[out_cols])
        else:
            pd.DataFrame(columns=out_cols).to_excel(writer, sheet_name="통합", index=False)

        # summary 시트
        summary_df = pd.DataFrame(summary_data)

        # hit rate 계산
        state2 = EnrichmentState()
        status_counts = state2.count_by_status()
        total_processed = sum(status_counts.values())
        collected_count = status_counts.get(STATUS_COLLECTED, 0)
        hit_rate = (collected_count / total_processed * 100) if total_processed > 0 else 0
        state2.close()

        hit_info = pd.DataFrame([{
            "전체 처리": total_processed,
            "이메일 발견": collected_count,
            "hit rate (%)": f"{hit_rate:.1f}",
        }])
        summary_df = pd.concat([summary_df, pd.DataFrame([{}]), hit_info], ignore_index=True)

        summary_df.to_excel(writer, sheet_name="summary", index=False)
        ws = writer.book["summary"]
        _style_sheet(ws, summary_df)

    log.info("엑셀 저장 완료: %s", out_path)
    return str(out_path)
