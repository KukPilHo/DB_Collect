import os
import requests
import pandas as pd
from pathlib import Path
from dotenv import load_dotenv

# .env 파일 로드
load_dotenv()

INPUT_DIR = Path("./input")
INPUT_DIR.mkdir(exist_ok=True)

# KICOX 전국 파일 다운로드 URL (data.go.kr 직접 링크)
KICOX_DOWNLOAD_URL = "https://www.data.go.kr/cmm/cmm/fileDownload.do?atchFileId=FILE_000000003109845&fileDetailSn=1&insertDataPrcus=N"

DATA_GO_KR_KEY = os.getenv("DATA_GO_KR_SERVICE_KEY", "")
GG_API_URL     = os.getenv("GG_API_URL", "")

def download_kicox():
    print("=========================================")
    print("1. KICOX 전국공장등록현황 다운로드 시작...")
    print("=========================================")
    try:
        # stream=True로 대용량 파일 받기
        r = requests.get(KICOX_DOWNLOAD_URL, stream=True)
        r.raise_for_status()
        
        # 파일명 지정 (원본이 CSV 형태임)
        out_path = INPUT_DIR / "한국산업단지공단_전국등록공장현황.csv"
        
        with open(out_path, "wb") as f:
            for chunk in r.iter_content(chunk_size=8192):
                f.write(chunk)
                
        print(f"✅ 다운로드 완료: {out_path.absolute()}")
    except Exception as e:
        print(f"❌ 다운로드 실패: {e}")

def download_gyeonggi():
    print("\n=========================================")
    print("2. 경기도 공장등록현황 (Open API) 다운로드 시작...")
    print("=========================================")
    
    if not DATA_GO_KR_KEY or not GG_API_URL:
        print("❌ 경기도 API 키 또는 URL이 설정되지 않았습니다. .env 파일을 먼저 작성해주세요.")
        return
        
    print("API를 통해 데이터를 수집합니다. 데이터가 많아 시간이 다소 소요될 수 있습니다...")
    
    rows = []
    page = 1
    per_page = 1000
    total = None
    
    while True:
        try:
            if "openapi.gg.go.kr" in GG_API_URL:
                params = {
                    "KEY": DATA_GO_KR_KEY,
                    "Type": "json",
                    "pIndex": page,
                    "pSize": per_page
                }
            else:
                params = {
                    "page": page,
                    "perPage": per_page,
                    "serviceKey": DATA_GO_KR_KEY,
                    "returnType": "JSON",
                }
            
            r = requests.get(GG_API_URL, params=params, timeout=15)
            r.raise_for_status()
            
            payload = r.json()
            data = payload.get("data") or payload.get("response", {}).get("body", {}).get("items")
            
            # 경기데이터드림 (FACTRYREGISTTM) 지원
            if not data and "FACTRYREGISTTM" in payload:
                for item in payload["FACTRYREGISTTM"]:
                    if "row" in item:
                        data = item["row"]
                        break
            data = data or []
            
            if not data:
                break
                
            rows.extend(data)
            
            if total is None:
                total = payload.get("totalCount") or payload.get("response", {}).get("body", {}).get("totalCount")
                if not total and "FACTRYREGISTTM" in payload:
                    for item in payload["FACTRYREGISTTM"]:
                        if "head" in item:
                            total = item["head"][0].get("list_total_count")
                            break
                            
                if total:
                    print(f"  -> 전체 예상 데이터 건수: {total}건")
                    
            print(f"  - page={page} 수집 완료 (누적 {len(rows)}건)")
            
            if total and len(rows) >= int(total):
                break
                
            page += 1
        except Exception as e:
            print(f"❌ API 호출 실패 (page={page}): {e}")
            break
            
    if rows:
        df = pd.DataFrame(rows)
        out_path = INPUT_DIR / "경기도_공장등록현황.xlsx"
        df.to_excel(out_path, index=False)
        print(f"✅ 저장 완료: {out_path.absolute()}")
    else:
        print("❌ 수집된 경기도 데이터가 없습니다.")

if __name__ == "__main__":
    download_kicox()
    download_gyeonggi()
    print("\n🎉 모든 데이터셋 개별 다운로드 작업이 종료되었습니다.")
