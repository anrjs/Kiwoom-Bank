import argparse
from kiwoom_finance.batch import get_metrics_for_codes

if __name__ == "__main__":
    p = argparse.ArgumentParser()
    p.add_argument("--codes", nargs="+", required=True, help="예: 005380 095570 005930")
    p.add_argument("--all-periods", action="store_true", help="모든 연도 포함")
    p.add_argument("--no-percent", action="store_true", help="퍼센트 문자열 대신 숫자 반환")
    args = p.parse_args()

    df = get_metrics_for_codes(
        codes=args.codes,
        latest_only=not args.all_periods,
        percent_format=not args.no_percent
    )
    print(df)
    df.to_csv("batch_metrics.csv", encoding="utf-8-sig", index=True)
    print("Saved to batch_metrics.csv")
