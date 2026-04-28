"""
CLI 엔트리포인트
=================
python -m src.cli <command> [flags]
"""

from typing import Optional

import click

from src.config import CANDIDATES_PATH, ENRICHMENT_CONCURRENCY, MASTER_PATH, log


@click.group()
def cli():
    """600 Outbound DB 수집·보강 파이프라인"""
    pass


@cli.command()
@click.option("--datasets", default="", help="콤마 구분 데이터셋 ID (미지정 시 전체)")
@click.option("--force", is_flag=True, help="캐시 무시 후 재다운로드")
def download(datasets: str, force: bool):
    """모든 등록 데이터셋의 raw 다운로드."""
    from src.datasets import DATASETS, get_dataset_by_id

    if datasets:
        ids = [d.strip() for d in datasets.split(",")]
        targets = [get_dataset_by_id(i) for i in ids]
        targets = [t for t in targets if t is not None]
    else:
        targets = DATASETS

    for ds in targets:
        try:
            ds.download(force=force)
        except Exception as e:
            log.error("[%s] 다운로드 실패: %s", ds.id, e)


@cli.command()
@click.option("--datasets", default="", help="콤마 구분 데이터셋 ID")
@click.option("--force", is_flag=True, help="캐시 무시")
def normalize(datasets: str, force: bool):
    """raw → normalized parquet."""
    from src.pipeline.normalize import run_normalize

    ids = [d.strip() for d in datasets.split(",")] if datasets else None
    run_normalize(dataset_ids=ids, force=force)


@cli.command("build-master")
@click.option("--force", is_flag=True)
def build_master(force: bool):
    """normalized/* → master.parquet (dedup 포함)."""
    from src.pipeline.master import build_master as _build
    _build(force=force)


@cli.command()
def categorize():
    """master.parquet에 카테고리 컬럼 채움."""
    from src.pipeline.category import run_categorize
    run_categorize()


@cli.command()
@click.option("--multiplier", type=float, default=1.5, help="quota 배수 (기본 1.5)")
def sample(multiplier: float):
    """master → candidates.parquet."""
    from src.pipeline.sample import run_sample
    run_sample(multiplier=multiplier)


@cli.command()
@click.option("--category", default="", help="특정 카테고리만")
@click.option("--limit", type=int, default=0, help="테스트용 상위 N개")
@click.option("--start-idx", type=int, default=0)
@click.option("--end-idx", type=int, default=0)
@click.option("--concurrency", type=int, default=ENRICHMENT_CONCURRENCY)
@click.option("--retry-failed", is_flag=True, help="failed 상태 재시도")
def enrich(category: str, limit: int, start_idx: int, end_idx: int,
           concurrency: int, retry_failed: bool):
    """candidates → enrichment_state.sqlite 이메일 보강."""
    from src.pipeline.enrich import run_enrich
    run_enrich(
        category=category or None,
        limit=limit,
        start_idx=start_idx,
        end_idx=end_idx,
        concurrency=concurrency,
        retry_failed=retry_failed,
    )


@cli.command()
def export():
    """enrichment_state + master → 최종 엑셀."""
    from src.export import run_export
    path = run_export()
    click.echo(f"엑셀 저장: {path}")


@cli.command("all")
@click.option("--multiplier", type=float, default=1.5)
@click.option("--concurrency", type=int, default=ENRICHMENT_CONCURRENCY)
def run_all(multiplier: float, concurrency: int):
    """download → normalize → build-master → categorize → sample → enrich → export 일괄."""
    from src.datasets import DATASETS
    from src.pipeline.normalize import run_normalize
    from src.pipeline.master import build_master
    from src.pipeline.category import run_categorize
    from src.pipeline.sample import run_sample
    from src.pipeline.enrich import run_enrich
    from src.export import run_export

    log.info("=== [1/7] download ===")
    for ds in DATASETS:
        try:
            ds.download()
        except Exception as e:
            log.error("[%s] 다운로드 실패: %s", ds.id, e)

    log.info("=== [2/7] normalize ===")
    run_normalize()

    log.info("=== [3/7] build-master ===")
    build_master(force=True)

    log.info("=== [4/7] categorize ===")
    run_categorize()

    log.info("=== [5/7] sample ===")
    run_sample(multiplier=multiplier)

    log.info("=== [6/7] enrich ===")
    run_enrich(concurrency=concurrency)

    log.info("=== [7/7] export ===")
    path = run_export()
    log.info("완료! 결과: %s", path)


@cli.command()
def status():
    """현재 진행 상황 출력."""
    import pandas as pd
    from src.enricher.state import EnrichmentState

    state = EnrichmentState()
    counts = state.count_by_status()
    total = state.total_processed()
    state.close()

    click.echo(f"\n=== Enrichment 상태 ===")
    click.echo(f"총 처리 회사: {total}")
    for s, cnt in counts.items():
        click.echo(f"  {s}: {cnt}")

    collected = counts.get("collected", 0)
    if total > 0:
        click.echo(f"  hit rate: {collected / total * 100:.1f}%")

    # candidates 정보
    if CANDIDATES_PATH.exists():
        cand = pd.read_parquet(CANDIDATES_PATH)
        click.echo(f"\n=== Candidates ===")
        click.echo(f"총 candidate: {len(cand)}")
        dist = cand["카테고리"].value_counts()
        for cat, cnt in dist.items():
            click.echo(f"  {cat}: {cnt}")
        progress = total / len(cand) * 100 if len(cand) > 0 else 0
        click.echo(f"  진행률: {progress:.1f}%")

    # master 정보
    if MASTER_PATH.exists():
        master = pd.read_parquet(MASTER_PATH)
        click.echo(f"\n=== Master ===")
        click.echo(f"총 회사: {len(master)}")
        if "출처_목록" in master.columns:
            multi_source = master["출처_목록"].str.contains(",", na=False).sum()
            click.echo(f"다중 출처(중복 제거됨): {multi_source}건")


def main():
    cli()


if __name__ == "__main__":
    main()
