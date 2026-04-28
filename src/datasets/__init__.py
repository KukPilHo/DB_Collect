"""
데이터셋 등록
=============
새 데이터셋 추가 시 아래 리스트에 1줄 추가만 하면 됨.
"""

from .kicox import KicoxDataset
from .gyeonggi import GyeonggiDataset
from .sw_industry import SwIndustryDataset
from .innobiz import InnobizDataset
from .content_agency import ContentAgencyDataset
from .industrial_design import IndustrialDesignDataset
from .research_provider import ResearchProviderDataset
from .construction import ConstructionDataset
from .building_sanitation import BuildingSanitationDataset

DATASETS = [
    KicoxDataset(),
    GyeonggiDataset(),
    SwIndustryDataset(),
    InnobizDataset(),
    ContentAgencyDataset(),
    IndustrialDesignDataset(),
    ResearchProviderDataset(),
    ConstructionDataset(),
    BuildingSanitationDataset(),
]


def get_dataset_by_id(dataset_id: str):
    """데이터셋 ID로 인스턴스 검색."""
    for ds in DATASETS:
        if ds.id == dataset_id:
            return ds
    return None
