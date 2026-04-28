# 600 Outbound DB 수집·보강 파이프라인 개발 명세

## 0. 한 줄 요약
한국 공공데이터 8~9개 소스에서 회사 정보를 수집·통합·dedup·카테고리 분류·샘플링한 뒤, 검색 기반으로 이메일을 보강해 약 600개(최대 1,000개) outbound 타깃 DB(엑셀)를 산출하는 파이프라인. 단계별 캐싱과 분할/재개 실행을 지원하며, 새 데이터셋 추가 시 한 클래스 추가만으로 확장 가능해야 한다.

사용 컨텍스트: B2B AI/DX 교육 영업 outbound용. 즉 발송 자체가 아니라 발송 직전까지의 데이터 빌드.

## 1. 목표와 비목표

### 목표
- 4개 카테고리 outbound 타깃을 이메일 포함 엑셀로 산출
  - 제조 300
  - IT/SW/벤처 120
  - 도소매·콘텐츠·전문서비스 120
  - 건설·물류·시설관리 60
- 데이터셋 추가가 클래스 1개 추가로 끝나는 확장성
- 다운로드, 정규화, 이메일 크롤 결과를 모두 캐싱해 두 번 일하지 않음
- 새 환경(다른 사람 머신)에서 코드 받자마자 처음부터 다시 돌릴 수 있음
- 분할 실행과 재개 지원 (한 번에 600개 다 못 돌릴 가능성 큼)

### 비목표
- 메일 발송, CRM 등록, 에디터 UI
- 외부 API로 매출/직원수 등 추가 검증
- 사업자등록번호 외부 조회

## 2. 데이터 소스 매트릭스

| ID | 이름 | URL 또는 위치 | 카테고리 | 수집 방식 | 비고 |
|---|---|---|---|---|---|
| 15105482 | KICOX 전국공장등록현황 | data.go.kr/data/15105482 | 제조 | 파일 다운로드(csv) | 약 20만 레코드 |
| 15057023 | 경기도 공장등록현황 | openapi.gg.go.kr/FACTRYREGISTTM | 제조 | Open API 페이징 | 15105482와 일부 중복 가능 |
| 15052274 | SW산업정보 사업자정보 | data.go.kr/data/15052274 | IT/SW/벤처 | 파일 또는 API | 정보통신산업진흥원 |
| innobiz | 이노비즈 기업정보 | innobiz.net/company/company2_list.asp | IT/SW/벤처 | 웹 크롤링 | 공식 API 없음 |
| 15118569 | 대중문화예술기획업 등록기업 | data.go.kr/data/15118569 | 도소매·콘텐츠·전문서비스 | 파일 다운로드 | 한국콘텐츠진흥원 |
| TBD-DESIGN | 산업디자인전문회사 | data.go.kr 또는 한국디자인진흥원 | 도소매·콘텐츠·전문서비스 | TBD | **구현 첫 단계에서 ID 확정** |
| TBD-RESEARCH | 전문연구사업자 신고기업 | data.go.kr | 도소매·콘텐츠·전문서비스 | TBD | **구현 첫 단계에서 ID 확정** |
| TBD-CONSTRUCT | 전국건설업체정보표준데이터 | data.go.kr 표준데이터셋 | 건설·물류·시설관리 | 파일 또는 API | **구현 첫 단계에서 ID 확정** |
| 15071341 | 서울 건물위생관리업 인허가 | data.go.kr/data/15071341 | 건설·물류·시설관리 | 파일 다운로드 | 시설관리 |

TBD 3개는 구현 첫 단계에서 data.go.kr 검색으로 정확한 데이터셋 ID와 수집 방식을 확정하고 README의 결정사항 섹션에 기록할 것.

## 3. 기존 코드 자산 처리

기존 파일 두 개는 모두 폐기. 단 다음 로직만 신규 모듈로 이식:

DB_pipeline.py에서 가져올 자산:
- EmailHit dataclass와 is_valid 룰
- EMAIL_BLOCKLIST_DOMAINS, EMAIL_BLOCKLIST_LOCAL, URL_BLOCKLIST 상수
- extract_emails_from_text 정규식과 후처리
- find_contact_pages 휴리스틱
- naver_search, google_cse, duckduckgo_search 함수
- fetch_html, scrape_emails_from_url 흐름
- search_emails_for_company의 다중 쿼리 + 후보 URL 방문 흐름
- save_db_excel의 그레이스케일 엑셀 스타일링

download_datasets.py는 통째 폐기. 다운로드 책임은 Dataset 클래스로 흡수.

## 4. 디렉토리 구조와 데이터 흐름

```
project_root/
├── src/
│   ├── datasets/
│   │   ├── base.py                # Dataset 추상 클래스
│   │   ├── kicox.py               # 15105482
│   │   ├── gyeonggi.py            # 15057023
│   │   ├── sw_industry.py         # 15052274
│   │   ├── innobiz.py             # 웹 크롤
│   │   ├── content_agency.py      # 15118569
│   │   ├── industrial_design.py   # TBD
│   │   ├── research_provider.py   # TBD
│   │   ├── construction.py        # TBD
│   │   ├── building_sanitation.py # 15071341
│   │   └── __init__.py            # 등록 (DATASETS = [...])
│   ├── pipeline/
│   │   ├── normalize.py
│   │   ├── master.py
│   │   ├── category.py
│   │   ├── sample.py
│   │   └── enrich.py
│   ├── enricher/
│   │   ├── state.py    # sqlite 인터페이스
│   │   ├── search.py   # naver/google/ddg 검색
│   │   └── scraper.py  # html fetch + email 추출
│   ├── export.py
│   ├── config.py
│   └── cli.py
├── raw/                       # 원본 (gitignore)
│   └── <dataset_id>/<YYYY-MM-DD>/
├── normalized/                # 통일 스키마 parquet (gitignore)
├── master.parquet             # (gitignore)
├── candidates.parquet         # (gitignore)
├── enrichment_state.sqlite    # (gitignore)
├── output/                    # 최종 deliverable (gitignore)
├── tests/
├── .env.example
├── .gitignore
├── requirements.txt
└── README.md
```

데이터 흐름:
- (1) download: Dataset.download() -> raw/<id>/<date>/...
- (2) normalize: Dataset.normalize() -> normalized/<id>.parquet (통일 스키마)
- (3) build-master: 모든 normalized 합쳐 dedup -> master.parquet
- (4) categorize: 카테고리 컬럼 채움 -> master.parquet 갱신
- (5) sample: 카테고리별 quota * 1.5배 후보 추출 -> candidates.parquet
- (6) enrich: candidates -> 이메일 검색 -> enrichment_state.sqlite append
- (7) export: enrichment_state JOIN master -> output/outbound_db_<date>.xlsx

각 단계는 독립 실행 가능해야 하며, 입력 파일이 이미 존재하면 다시 만들지 않음 (--force로 강제 재생성).

## 5. 통일 스키마

normalized/*.parquet과 master.parquet 모두 다음 컬럼.

| 컬럼 | 타입 | 설명 | 필수 |
|---|---|---|---|
| 회사키 | string | PK. 사업자등록번호 또는 hash | yes |
| 사업자등록번호 | string | 있으면 채움 | no |
| 회사명 | string | 정규화된 표기 | yes |
| 회사명_원본 | string | 원본 표기 그대로 | yes |
| 대표자 | string | | no |
| 업종_KSIC | string | 5자리 또는 대분류 1자리 | no |
| 업종명_원본 | string | 데이터셋의 업종 표기 | no |
| 시도 | string | 17개 광역 표준 표기 | no |
| 시군구 | string | | no |
| 도로명주소 | string | | no |
| 지번주소 | string | | no |
| 대표전화 | string | | no |
| 홈페이지 | string | enrich 단계에서 발견 시 보강 가능 | no |
| 종업원수 | int | nullable | no |
| 자본금 | int | 원 단위 nullable | no |
| 매출액 | int | 원 단위 nullable (대부분 null 예상) | no |
| 등록일 | date | 데이터셋 등록일 또는 설립일 | no |
| 가동상태 | string | 가동중/휴업/폐업/미상 | no |
| 출처_데이터셋ID | string | 예: 15105482 | yes |
| 출처_URL | string | 데이터셋 페이지 URL | yes |
| 출처_목록 | string | dedup 후 모든 출처 ID 콤마 결합 | yes (master만) |
| 카테고리 | string | 제조 / IT_SW_벤처 / 도소매_콘텐츠_전문서비스 / 건설_물류_시설 | yes (categorize 후) |
| 수집일 | date | normalize 실행 날짜 | yes |

데이터셋이 컬럼을 가지지 않으면 null. 매출액은 거의 모든 공공데이터에 없을 것이므로 null이 정상.

## 6. 회사키와 dedup 정책

### 회사키 생성 우선순위
- (1) 사업자등록번호가 있으면 사업자등록번호 (하이픈 제거 후 10자리)
- (2) 없으면 sha256(normalize(회사명) + "|" + normalize(시도) + "|" + normalize(시군구))의 앞 16자

normalize(회사명) 룰:
- 공백 모두 제거
- 법인격 표기 통일 후 제거: 주식회사, (주), 유한회사, (유), (주식회사), 사단법인, (사), 재단법인, (재) 등
- 영문은 lower
- 특수문자 제거 (괄호, 따옴표, dot)

### Master 빌드 시 dedup
- 회사키로 group by
- 같은 회사키에 여러 행이 있으면 다음 우선순위로 1행 선택:
  - 카테고리 quota 핵심 데이터셋 우선 (제조에서는 #1 KICOX > #2 경기도)
  - 가장 최신 등록일
  - null 컬럼이 적은 쪽
- 출처는 출처_목록 컬럼에 모든 데이터셋 ID 콤마 결합으로 보존
- 출처_데이터셋ID는 선택된 1행의 ID 유지

## 7. 카테고리 매핑 정책

### 1차 매핑 (출처 기반, 기본)

| 데이터셋 ID | 카테고리 |
|---|---|
| 15105482 | 제조 |
| 15057023 | 제조 |
| 15052274 | IT_SW_벤처 |
| innobiz | IT_SW_벤처 |
| 15118569 | 도소매_콘텐츠_전문서비스 |
| TBD-DESIGN | 도소매_콘텐츠_전문서비스 |
| TBD-RESEARCH | 도소매_콘텐츠_전문서비스 |
| TBD-CONSTRUCT | 건설_물류_시설 |
| 15071341 | 건설_물류_시설 |

### 2차 검증 (KSIC 기반, 가능한 경우)

업종_KSIC가 있는 회사는 다음 표로 검증. 1차 매핑과 모순되면 KSIC 우선.

| KSIC 대분류 | 카테고리 |
|---|---|
| C (10~33) 제조업 | 제조 |
| J (58~63) 정보통신업 | IT_SW_벤처 |
| F (41~42) 건설업 | 건설_물류_시설 |
| H (49~52) 운수창고업 | 건설_물류_시설 (물류) |
| N (74~75) 사업시설관리·사업지원 | 건설_물류_시설 (시설) |
| G (45~47) 도매소매업 | 도소매_콘텐츠_전문서비스 |
| M (70~73) 전문과학기술서비스 | 도소매_콘텐츠_전문서비스 |
| R (90~91) 예술스포츠여가 | 도소매_콘텐츠_전문서비스 |

KSIC가 없는 회사는 1차 매핑 그대로 사용.

## 8. 샘플링 정책

카테고리별 candidate 수 = quota * multiplier. 초기 multiplier = 1.5, 50개 파일럿 후 hit rate에 따라 조정.

초기 candidate 수:
- 제조: 450 (quota 300)
- IT/SW/벤처: 180 (quota 120)
- 도소매·콘텐츠·전문서비스: 180 (quota 120)
- 건설·물류·시설관리: 90 (quota 60)
- 합계 약 900

각 카테고리 샘플링 룰 (적용 가능한 컬럼이 있을 때만):
- (1) 가동상태 = 가동중만 (가동상태 컬럼이 있는 데이터셋만)
- (2) 종업원수 또는 자본금이 있을 경우 하위 10% 제외 (영세 제외)
- (3) 시도 stratified: 수도권(서울/경기/인천) 60%, 비수도권 40%
- (4) 업종 stratified: 동일 KSIC 5자리에 candidate의 5% 이상 쏠리지 않도록 cap
- (5) 등록일 신순 우선

random seed = 42로 고정해 재현 가능하게 한다.

## 9. enrichment_state 스키마와 라이프사이클

### sqlite 테이블

```sql
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
```

상태 값:
- collected: 이메일 1건 이상 수집 완료
- not_found: 검색·크롤 끝까지 했으나 이메일 없음
- failed: 네트워크/API 오류로 미완료
- skipped: 회사명 없음 등 사유로 처리 자체 불가

한 회사 다수 이메일이면 (회사키, 이메일) 복합 PK로 행 분할 저장.
not_found / failed / skipped 케이스도 행은 저장하되 이메일 = '' 로 마커.

### 라이프사이클
- (1) enrich가 candidates 한 행씩 처리
- (2) enrichment_state에서 회사키 조회 후 분기:
  - 행 없음 -> 새 작업
  - 상태 = collected 또는 not_found -> 스킵
  - 상태 = failed and 재시도_횟수 < 2 -> 재시도
  - 상태 = failed and 재시도_횟수 >= 2 -> 스킵
  - 상태 = skipped -> 스킵
- (3) 검색 + 크롤 시도
- (4) 결과 sqlite에 즉시 commit (배치 안 함, 한 행마다 write)
- (5) export 단계가 master JOIN enrichment_state로 최종 엑셀 생성

이 구조면 새 데이터셋이 추가돼 candidates에 회사가 늘어도 기존에 처리된 회사는 자동 스킵되고, 다른 카테고리에서 같은 회사가 잡혀도 재크롤 안 함.

## 10. CLI 명세

`python -m src.cli <command> [flags]`

### download
모든 등록된 데이터셋의 raw 다운로드.
- --datasets <id1,id2,...> : 특정만
- --force : 캐시 무시 후 재다운
- 캐시 룰: raw/<id>/<오늘 날짜>/ 폴더 존재 시 스킵

### normalize
raw -> normalized parquet.
- --datasets <id,...>
- --force

### build-master
normalized/* -> master.parquet (dedup 포함).

### categorize
master.parquet에 카테고리 컬럼 채움.

### sample
master -> candidates.parquet.
- --multiplier <float> : 기본 1.5

### enrich
candidates -> enrichment_state.sqlite append.
- --category <카테고리명> : 해당 카테고리만
- --limit <N> : 테스트용 상위 N개
- --start-idx, --end-idx : 분할 실행
- --concurrency <N> : 동시성 (기본 1, 권장 5~10)
- --retry-failed : failed 상태 재시도

### export
enrichment_state + master -> output/outbound_db_<오늘날짜>.xlsx
- 시트 구성: 카테고리 4시트 + 통합 1시트 + summary 1시트(카테고리별 행수, hit rate)

### all
download -> normalize -> build-master -> categorize -> sample -> enrich -> export 일괄.

### status
현재 candidates 진행률, 카테고리별 enrichment 카운트, hit rate 출력.

## 11. 모듈 명세 (요점만)

### src/datasets/base.py

```python
from abc import ABC, abstractmethod
from pathlib import Path
import pandas as pd

class Dataset(ABC):
    id: str                  # 예: "15105482"
    name: str                # 예: "KICOX 전국공장등록현황"
    source_url: str
    category_default: str    # 예: "제조"

    @abstractmethod
    def download(self, force: bool = False) -> Path:
        """raw/<id>/<오늘 날짜>/에 원본 저장하고 폴더 경로 반환."""

    @abstractmethod
    def normalize(self) -> pd.DataFrame:
        """raw 파일 -> 통일 스키마 DataFrame 반환."""
```

### src/datasets/__init__.py
모든 Dataset 구현체를 리스트로 등록.

```python
from .kicox import KicoxDataset
from .gyeonggi import GyeonggiDataset
# ...

DATASETS = [
    KicoxDataset(),
    GyeonggiDataset(),
    # ...
]
```

새 데이터셋 추가는 클래스 1개 + 이 리스트 1줄 추가.

### src/enricher/state.py
sqlite 인터페이스. 최소 함수:
- get_status(회사키) -> tuple[str, int] or None
- upsert(회사키, 회사명, 이메일, 출처URL, 방법, 상태, 에러메시지=None)
- count_by_status(카테고리=None) -> dict
- list_companies_by_status(상태) -> list

### src/enricher/search.py, scraper.py
기존 DB_pipeline.py 함수 그대로 이식. 단 모듈 분리:
- search.py: naver_search, google_cse, duckduckgo_search, search_emails_for_company
- scraper.py: fetch_html, extract_emails_from_text, find_contact_pages, scrape_emails_from_url, EmailHit

### src/pipeline/enrich.py
candidates 순회 + state 조회 + search 호출 + state 갱신.
- 동시성 옵션: ThreadPoolExecutor 권장 (각 회사가 다른 도메인이라 도메인별 충돌 거의 없음)
- 단 Naver/Google API는 process-level rate limit 고려해 token bucket 1개

## 12. 환경 변수

`.env.example`:

```
# 공공데이터포털
DATA_GO_KR_SERVICE_KEY=

# 경기도 공장등록 (FACTRYREGISTTM)
GG_API_URL=https://openapi.gg.go.kr/FACTRYREGISTTM

# 검색 API (이메일 enrichment용)
NAVER_CLIENT_ID=
NAVER_CLIENT_SECRET=
GOOGLE_CSE_API_KEY=
GOOGLE_CSE_CX=

# 옵션
ENRICHMENT_CONCURRENCY=5
USER_AGENT=AblearnBD-Research/1.0
```

별도 신규 키 필요 없음. 다만 다음 검토:
- DuckDuckGo 라이브러리(ddgs)가 비공식이라 안정성 떨어짐. 깨지면 SerpAPI로 대체 가능 (SERPAPI_KEY 추가). 현재는 추가하지 않음.
- Google CSE 무료 일 100쿼리 제한. 회사당 4쿼리면 일 25개 회사 한도. 제조 candidate 450개 enrich 시 며칠 분산 또는 결제 전환 필요. 명세에서는 일단 무료 한도 가정.

## 13. 의존성 (requirements.txt)

```
pandas>=2.0
pyarrow>=14
openpyxl>=3.1
requests>=2.31
beautifulsoup4>=4.12
lxml>=4.9
tqdm>=4.66
tenacity>=8.2
python-dotenv>=1.0
ddgs>=4.0
click>=8.1
```

Python 3.10+.

## 14. 검증 단계 (50개 파일럿)

본 enrichment 전 필수.

- (1) categorize 후 제조 카테고리에서 50개 random sample 선정
- (2) `python -m src.cli enrich --category 제조 --limit 50` 실행
- (3) `python -m src.cli status`로 hit rate 측정 (collected / 50)
- (4) hit rate에 따라 multiplier 조정 후 README 결정사항에 기록
  - 50% 이상이면 multiplier 1.5 유지
  - 30~50%면 multiplier 2.0
  - 30% 미만이면 multiplier 2.5 + 검색 쿼리 다양화 검토
- (5) status 출력에 평균 회사당 처리 시간도 포함시켜 본 작업 시간 견적

## 15. Acceptance criteria

- [ ] 9개 데이터셋 모두 download/normalize 가능 (TBD 3개는 식별 후)
- [ ] 동일 회사 다중 출처일 때 1행으로 dedup, 출처_목록에 보존
- [ ] master.parquet 카테고리 컬럼 100% 채워짐
- [ ] candidates.parquet 카테고리별 quota * multiplier만큼 생성
- [ ] enrich 중단 후 재실행 시 기처리 행 자동 스킵 (resume 자동)
- [ ] 새 데이터셋 추가 시 src/datasets/<new>.py 1개 + DATASETS 리스트 1줄 등록만으로 동작
- [ ] export 결과 엑셀이 카테고리별 4시트 + 통합 1시트 + summary 1시트
- [ ] 빈 디렉토리에서 .env만 채우고 `python -m src.cli all` 한 번 실행으로 endpoint까지 도달
- [ ] README에 셋업/실행/캐시 무효화/추가 데이터셋 작성법 문서화
- [ ] pytest 단위 테스트: 회사키 정규화, 카테고리 매핑, dedup 우선순위, sqlite 상태 전이 최소 4개

## 16. 알려진 제약 / 구현 중 판단할 것

- TBD 3개 데이터셋(산업디자인전문회사, 전문연구사업자, 전국건설업체)의 정확한 data.go.kr ID는 첫 단계에서 검색 후 결정. README 결정사항에 기록.
- 이노비즈는 공식 API 없음. HTML 구조 변경 시 깨지므로 셀렉터를 한 곳에 모으고 페이지 구조 검증 함수를 둘 것. 깨지면 ValueError 던지고 즉시 알리기.
- 경기도(15057023)와 KICOX 전국(15105482)이 일부 중복될 가능성 큼. dedup이 처리하지만 status 명령에 중복 비율 보고 항목 추가.
- 물류 카테고리 데이터셋이 현재 8~9개 안에 없음. 시설관리(#15071341)로 60개 채워야 함. 부족 시 README에 보고하고 화물자동차운송사업자 추가 등 옵션 제시.
- Naver Open API 일 25,000회 제한. 회사당 8회면 일 3,000개 회사 가능, 600~900 candidate에는 여유.
- Google CSE 무료 일 100쿼리. candidate 1개당 4쿼리면 일 25개 회사밖에 못함. 무료 유지 시 분산 실행 필수, 또는 Google CSE 호출을 회사당 1쿼리로 줄이거나, 결제 전환.
- 사업자등록번호가 데이터셋에 거의 없을 가능성 -> 회사키가 회사명 hash가 됨 -> 회사명 표기만 다른 동일 회사 dedup 실패. normalize(회사명) 룰을 강하게 잡되, 그래도 일부는 못 잡음을 인정. 외부 조회는 안 함.
- 이메일 한 회사 다수 hit 시 행 분할 저장 (PK = 회사키 + 이메일). 기존 코드 방식 유지.
- 그레이스케일 엑셀 출력. 색상 강조 금지. 헤더 fill #D9D9D9, 헤더 bold, freeze panes A2.
- 600 quota 미달 시 에러가 아니라 README/summary 시트에 미달 사유와 함께 보고.

## 17. README 작성 요구사항

- 셋업: clone -> python -m venv -> pip install -> .env 작성 -> python -m src.cli all
- 단계별 실행 방법
- 캐시 무효화 방법 (--force, raw/ 삭제)
- 새 데이터셋 추가 방법 (Dataset 상속 + DATASETS 등록)
- 결정사항 섹션: TBD 3개 ID, multiplier 확정값, 알려진 제약 실제 측정값
- 문제 해결: 자주 발생할 만한 에러 (rate limit, encoding 문제 등)
