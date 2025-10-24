# examples/run_batch.py
import argparse
from kiwoom_finance.batch import get_metrics_for_codes

if __name__ == "__main__":
    p = argparse.ArgumentParser()
    p.add_argument(
        "--codes",
        "--names",
        dest="identifiers",
        nargs="+",
        required=True,
        help="종목명 또는 종목코드 (예: 삼성전자 카카오 또는 005930 035720)",
    )
    p.add_argument("--all-periods", action="store_true", help="모든 연도 포함")
    p.add_argument("--no-percent", action="store_true", help="퍼센트 문자열 대신 숫자 반환")
    p.add_argument(
        "--search-mode",
        choices=["auto", "name", "code"],
        default="auto",
        help="식별자 해석 모드 (auto: 종목명 우선)",
    )
    args = p.parse_args()

    df = get_metrics_for_codes(
        codes=args.identifiers,
        latest_only=not args.all_periods,
        percent_format=not args.no_percent,
        identifier_type=args.search_mode,
    )
    print(df)
    df.to_csv("batch_metrics.csv", encoding="utf-8-sig", index=True)
    print("Saved to batch_metrics.csv")
