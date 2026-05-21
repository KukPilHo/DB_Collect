#!/usr/bin/env python3
"""
Factory DB & Email Crawler 통합 매니저
복잡한 CLI 명령어를 외울 필요 없이, 터미널 메뉴에서 번호를 선택해 실행합니다.
"""

import sys
import subprocess
from pathlib import Path

def print_menu():
    print("\n" + "=" * 50)
    print("  Factory DB & Email Crawler 통합 매니저")
    print("=" * 50)
    print("1. 공장 DB 원본 다운로드 (KICOX, 경기도)")
    print("2. 공장 DB 전체 파이프라인 실행 (정규화, 마스터 빌드, 보강 등)")
    print("3. 내 엑셀 파일 이메일 보강 (최적화/단일 추출 병렬 모드)")
    print("4. 현재 DB 수집 상태 확인")
    print("0. 종료")
    print("-" * 50)

def main():
    while True:
        print_menu()
        try:
            choice = input("원하시는 작업 번호를 입력하세요: ").strip()
        except (KeyboardInterrupt, EOFError):
            print("\n프로그램을 종료합니다.")
            break

        if choice == "1":
            print("\n[공장 DB 원본 다운로드 실행]")
            # src.datasets 다운로드
            try:
                from src.datasets import DATASETS
                for ds in DATASETS:
                    ds.download()
                print("✅ 다운로드 완료")
            except Exception as e:
                print(f"❌ 오류 발생: {e}")

        elif choice == "2":
            print("\n[공장 DB 전체 파이프라인 실행]")
            subprocess.run([sys.executable, "-m", "src.cli", "all"])

        elif choice == "3":
            print("\n[내 엑셀 파일 이메일 보강 (최적화 모드)]")
            file_path = input("엑셀 파일 경로를 입력하세요 (예: 수행기관조회_20260520.xlsx): ").strip()
            if not file_path:
                print("취소되었습니다.")
                continue
                
            path = Path(file_path)
            if not path.exists():
                print(f"❌ 파일을 찾을 수 없습니다: {path.absolute()}")
                continue
                
            try:
                from src.pipeline.enrich_excel import run_enrich_excel_fast
                run_enrich_excel_fast(str(path))
            except Exception as e:
                print(f"❌ 오류 발생: {e}")

        elif choice == "4":
            print("\n[현재 상태 확인]")
            subprocess.run([sys.executable, "-m", "src.cli", "status"])

        elif choice == "0":
            print("프로그램을 종료합니다.")
            break
        else:
            print("❌ 잘못된 입력입니다. 0~4 사이의 번호를 입력해주세요.")

if __name__ == "__main__":
    main()
