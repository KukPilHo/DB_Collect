# 600 Outbound DB 수집·보강 파이프라인

B2B AI/DX 교육 영업 outbound용 타깃 DB 빌더.  
한국 공공데이터 9개 소스에서 회사 정보를 수집·통합·dedup·카테고리 분류·샘플링한 뒤, 검색 기반으로 이메일을 보강하여 약 600개(최대 1,000개) outbound 타깃 DB(엑셀)를 산출한다.

## 셋업

```bash
# 1. 저장소 클론
git clone <REPO_URL>
cd Factory_DB

# 2. 가상환경 생성 + 활성화
python -m venv venv
source venv/bin/activate   # macOS/Linux
# venv\Scripts\activate    # Windows

# 3. 의존성 설치
pip install -r requirements.txt

# 4. 환경변수 설정
cp .env.example .env
# .env 파일을 열고 API 키 입력

# 5. 전체 파이프라인 일괄 실행 (다운로드부터 엑셀 생성까지 자동으로 진행)
python -m src.cli all
```

> **💡 데이터셋 ID란?**
> 공공데이터포털(data.go.kr) 등에서 부여한 각 데이터의 고유 숫자 번호입니다.
> 예: `15105482` = 전국공장등록현황, `15057023` = 경기도 공장등록현황

### 필수 API 키

| 키 | 용도 | 발급처 |
|---|---|---|
| `DATA_GO_KR_SERVICE_KEY` | 공공데이터포털 API | [data.go.kr](https://www.data.go.kr) |
| `NAVER_CLIENT_ID` / `SECRET` | 이메일 검색 | [developers.naver.com](https://developers.naver.com) |
| `GOOGLE_CSE_API_KEY` / `CX` | 이메일 검색 (선택) | [Google CSE](https://programmablesearchengine.google.com) |

## 단계별 실행

각 단계는 독립 실행 가능. 입력 파일이 이미 존재하면 재생성하지 않음.

```bash
# 1. 원본 다운로드
python -m src.cli download                    # 등록된 전체 데이터셋 다운로드
python -m src.cli download --datasets 15105482,15057023  # 특정 데이터셋 2개만 다운로드 (숫자는 데이터셋 고유 ID입니다)
python -m src.cli download --force            # 기존에 다운로드한 파일(캐시)을 무시하고 다시 다운로드

# 2. 정규화 (통일 스키마 parquet)
python -m src.cli normalize
python -m src.cli normalize --datasets 15105482

# 3. 마스터 빌드 (dedup)
python -m src.cli build-master

# 4. 카테고리 매핑
python -m src.cli categorize

# 5. 샘플링 (candidate 추출)
python -m src.cli sample --multiplier 1.5

# 6. 이메일 보강 (웹 검색 및 크롤링)
python -m src.cli enrich                       # 전체 대상 실행
python -m src.cli enrich --category 제조 --limit 50  # [파일럿 테스트용] 제조 카테고리 50개만 시범 실행
python -m src.cli enrich --start-idx 0 --end-idx 100  # 데이터를 100개씩 쪼개서 분할 실행 (중단/재개 시 유용)
python -m src.cli enrich --retry-failed        # 이전에 실패했던 회사들만 다시 시도
python -m src.cli enrich --concurrency 10      # 한 번에 10개씩 동시에 검색 (속도가 빨라집니다)

# 7. 엑셀 엑스포트
python -m src.cli export

# 진행 상황 확인
python -m src.cli status
```

## 데이터 흐름

```
download → raw/<id>/<date>/
    ↓
normalize → normalized/<id>.parquet (통일 스키마)
    ↓
build-master → master.parquet (dedup)
    ↓
categorize → master.parquet (카테고리 컬럼 갱신)
    ↓
sample → candidates.parquet (quota × multiplier)
    ↓
enrich → enrichment_state.sqlite (이메일 크롤)
    ↓
export → output/outbound_db_<날짜>.xlsx
```

## 카테고리별 목표 (quota)

| 카테고리 | quota | candidate (×1.5) |
|---|---|---|
| 제조 | 300 | 450 |
| IT/SW/벤처 | 120 | 180 |
| 도소매·콘텐츠·전문서비스 | 120 | 180 |
| 건설·물류·시설관리 | 60 | 90 |
| **합계** | **600** | **900** |

## 캐시 무효화

```bash
# 특정 데이터셋 재다운로드
python -m src.cli download --datasets 15105482 --force

# 정규화 재실행
python -m src.cli normalize --force

# 마스터 재빌드
python -m src.cli build-master --force

# 전체 초기화 (raw 데이터부터 다시)
rm -rf raw/ normalized/ master.parquet candidates.parquet
python -m src.cli all
```

## 새 데이터셋 추가 방법

1. `src/datasets/` 안에 새 파일 생성 (예: `new_dataset.py`)
2. `Dataset` 클래스를 상속하고 `download()`와 `normalize()` 구현:

```python
from src.datasets.base import Dataset, ensure_unified_schema, generate_company_key
from src.config import CATEGORY_제조

class NewDataset(Dataset):
    id = "12345678"
    name = "새 데이터셋"
    source_url = "https://data.go.kr/data/12345678"
    category_default = CATEGORY_제조

    def download(self, force=False) -> Path:
        # raw/<id>/<date>/ 에 저장
        ...

    def normalize(self) -> pd.DataFrame:
        # 통일 스키마 DataFrame 반환
        ...
```

3. `src/datasets/__init__.py`의 `DATASETS` 리스트에 1줄 추가:

```python
from .new_dataset import NewDataset
DATASETS = [
    ...,
    NewDataset(),
]
```

## 결정사항

### TBD 데이터셋 확정

| 명세 ID | 확정 ID | 정식 명칭 | 수집 방식 |
|---|---|---|---|
| TBD-DESIGN | **15086381** | 한국디자인진흥원_디자인전문회사 | Open API |
| TBD-RESEARCH | **15099307** | 과학기술정보통신부_전문연구사업자 신고기업 현황 | 파일 다운로드 (CSV) |
| TBD-CONSTRUCT | **15065485** | 전국건설업체정보표준데이터 | 파일 다운로드 (CSV/표준데이터) |

### multiplier 초기값

- **1.5** (명세 기본값)
- 50개 파일럿 후 hit rate에 따라 조정 예정:
  - 50% 이상 → 1.5 유지
  - 30~50% → 2.0
  - 30% 미만 → 2.5

### 알려진 제약

- **이노비즈**: 공식 API 없음, HTML 크롤링. 구조 변경 시 `ValueError` 발생.
- **Google CSE**: 무료 일 100쿼리. 회사당 4쿼리면 일 25개 회사. 분산 실행 또는 결제 전환 필요.
- **사업자등록번호**: 대부분의 공공데이터에 없을 가능성. 회사명 해시 기반 dedup에 한계 존재.
- **물류 카테고리**: 전용 데이터셋 없음. 건물위생관리업(15071341) + 건설업체(15065485)로 60개 충당.
  부족 시 화물자동차운송사업자 추가 검토.

## 문제 해결

### Rate Limit 오류

```
# Naver API: 일 25,000회 한도
# → 회사당 ~8쿼리, 일 ~3,000개 처리 가능 (600~900에는 여유)

# Google CSE: 무료 일 100쿼리
# → --concurrency 1로 낮추고 분산 실행, 또는 결제 전환
```

### Encoding 오류

```
# CSV 파일 인코딩 문제
# → 각 Dataset의 normalize()에서 utf-8 → cp949 폴백 처리됨
# → 그래도 안 되면 raw 파일을 UTF-8로 변환 후 재실행
```

### DuckDuckGo 라이브러리 깨짐

```
# ddgs 비공식 라이브러리 → 불안정할 수 있음
# 깨지면 Naver + Google CSE만으로 동작
# 대안: SERPAPI_KEY 환경변수 추가 후 SerpAPI 연동
```

### enrichment 중단 후 재개

```bash
# enrichment_state.sqlite에 진행 상태가 저장됨
# 같은 명령 재실행하면 기처리 행 자동 스킵
python -m src.cli enrich  # 그냥 다시 실행하면 됨
```

## 테스트

```bash
python -m pytest tests/ -v
```

## 프로젝트 구조

```
src/
├── datasets/           # 데이터셋별 수집·정규화
│   ├── base.py         # Dataset 추상 클래스
│   ├── kicox.py        # KICOX 전국공장 (15105482)
│   ├── gyeonggi.py     # 경기도 공장 (15057023)
│   ├── sw_industry.py  # SW산업정보 (15052274)
│   ├── innobiz.py      # 이노비즈 (웹크롤)
│   ├── content_agency.py      # 대중문화예술기획업 (15118569)
│   ├── industrial_design.py   # 디자인전문회사 (15086381)
│   ├── research_provider.py   # 전문연구사업자 (15099307)
│   ├── construction.py        # 건설업체 (15065485)
│   └── building_sanitation.py # 건물위생관리업 (15071341)
├── pipeline/           # 데이터 파이프라인 코어
│   ├── normalize.py    # 정규화 실행
│   ├── master.py       # 마스터 빌드 + dedup
│   ├── category.py     # 카테고리 매핑
│   ├── sample.py       # 샘플링
│   └── enrich.py       # 이메일 보강 실행
├── enricher/           # 이메일 검색·크롤링
│   ├── state.py        # SQLite 상태 관리
│   ├── search.py       # Naver/Google/DDG 검색
│   └── scraper.py      # HTML fetch + 이메일 추출
├── export.py           # 엑셀 엑스포트
├── config.py           # 전역 설정
└── cli.py              # Click CLI
```

## 초보자를 위한 가이드: 이 프로그램은 어떻게 작동하나요?

이 프로그램은 **"영업할 기업들의 이메일 주소를 자동으로 찾아주는 로봇"**입니다. 과정은 크게 4단계로 진행됩니다.

### 1. 어디서 회사 목록을 가져오나요? (데이터 수집)
이메일을 찾기 위한 첫 출발점(원본 데이터)은 **정부의 공공데이터**입니다.
- 공공데이터포털(data.go.kr), 지자체 API 등에서 제공하는 '전국 공장 등록 현황', '전문연구사업자 현황' 같은 공식 데이터를 프로그램이 자동으로 다운로드합니다.
- 이 데이터에는 회사명, 주소, 업종 등은 있지만, 우리가 가장 필요한 **"이메일 주소"는 비어있는 경우가 대부분**입니다. `enrich` 명령어는 이 빈칸을 채우는 작업을 시작합니다.

### 2. 이메일을 어떻게 찾나요? (이메일 보강 - `enrich`)
프로그램은 다운로드한 "회사명"과 "주소"를 가지고 사람이 구글링하듯 인터넷을 뒤집니다.
- **검색 엔진 활용:** 네이버, 구글, 덕덕고(DuckDuckGo) 등의 검색 엔진에 `"(회사명) 공식 홈페이지"`, `"(회사명) 이메일"` 등을 자동으로 검색합니다.
- **홈페이지 방문:** 검색 결과로 나온 회사의 공식 사이트나 연락처 페이지에 직접 접속해서 화면에 적혀있는 이메일 주소(예: `info@company.com`)를 싹 읽어옵니다.

### 3. 쓸데없는 이메일은 어떻게 걸러내나요? (데이터 필터링)
단순히 긁어오기만 하면 구인구직 사이트(사람인, 잡코리아)의 담당자 이메일, 뉴스 기사를 쓴 기자 이메일 등 불필요한 노이즈가 엄청나게 섞입니다. 이를 막기 위해 3중 필터를 거칩니다.
- **1단계 (블랙리스트 차단):** 뉴스 사이트, 구인구직, 커뮤니티 도메인(`saramin.co.kr`, `boannews.com` 등)에서 나온 이메일이나 방문 주소는 원천 차단합니다.
- **2단계 (Cross-domain 필터):** 이메일 주소의 뒷부분(도메인)이 방문한 웹사이트 주소와 다르면 제3자의 이메일(스팸/광고)로 간주하고 버립니다.
- **3단계 (AI 필터링):** 최신 인공지능(ChatGPT API)에게 찾은 문맥과 이메일을 보여주고 *"이 이메일이 이 회사의 공식 비즈니스 이메일이 맞아?"* 라고 물어본 뒤, AI가 "노이즈다"라고 판별하면 탈락시킵니다.

### 4. 가장 좋은 이메일 1~2개만 고르기 (Best-Pick)
한 회사에서 이메일이 10개씩 나오면 영업팀에서 메일을 보내기 난감합니다. 그래서 찾은 이메일들에 점수를 매겨 **가장 확실한 1~2개**만 최종 엑셀에 담습니다.
- **높은 점수를 받는 이메일:** 회사 홈페이지 주소와 똑같은 이메일(자체 도메인), 그리고 아이디가 `sales@`, `info@`, `biz@`, `ceo@` 처럼 비즈니스 관련 부서인 경우 최우선으로 선택됩니다.
