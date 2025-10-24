import argparse
import sys
from .crawler import crawl_companies
import os

def main():
    parser = argparse.ArgumentParser(
        prog="nice_rating",
        description="NICE 회사채등급 크롤러 - 회사명을 인자로 넘기거나, 입력 없으면 companies.txt 사용"
    )
    parser.add_argument("companies", nargs="*", help="회사명들 공백으로 구분하여 입력 (예: 삼성전자 SK하이닉스)")
    args = parser.parse_args()

    if args.companies:
        companies = args.companies
    else:
        # fallback to data/input/companies.txt if exists
        base_dir = os.path.dirname(__file__)
        input_path = os.path.join(base_dir, "..", "data", "input", "companies.txt")
        input_path = os.path.normpath(input_path)
        if os.path.exists(input_path):
            with open(input_path, "r", encoding="utf-8-sig") as f:
                companies = [ln.strip() for ln in f if ln.strip()]
        else:
            print("회사명이 CLI로 제공되지 않았고 data/input/companies.txt 파일도 없습니다. 실행을 중단합니다.")
            sys.exit(1)

    print(f"실행 대상 회사 수: {len(companies)}")
    df_final, skipped_all = crawl_companies(companies)

    print("\n[결과 미리보기]")
    print(df_final.head(10))

    if skipped_all:
        print("\n[스킵된 항목]")
        for name, why in skipped_all:
            print(f" - {name}: {why}")

if __name__ == "__main__":
    main()
