# -*- coding: utf-8 -*-
"""
experiments/stage1_label_check.py — 1단계: 라벨 검증

목적:
1) real_dataset.xlsx에 등급 평가 시점을 알 수 있는 컬럼(평가일자 등)이 있는지 확인
2) 없다면, baseline OOF(seed=42) 기준으로 '실제 투기등급인데 투자등급으로 예측'한
   7건의 회사명 + 라벨 등급을 표로 정리 (사용자가 NICE에서 현재 등급과 직접 대조하기 위함)

사용법:
  python experiments/stage1_label_check.py --data /path/to/real_dataset.xlsx
"""
import argparse
import os
import re
import sys

import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from experiments.common import (  # noqa: E402
    load_valid_data, run_cv_once, RunConfig, is_investment_grade,
)

DATE_HINT_PATTERN = re.compile(
    r"(일자|날짜|date|평가일|기준일|공시일|보고일|year|연도|기준연도|발표일)", re.IGNORECASE
)


def find_date_like_columns(df: pd.DataFrame) -> list[str]:
    return [c for c in df.columns if DATE_HINT_PATTERN.search(str(c))]


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--data", required=True, help="real_dataset.xlsx 경로")
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--out_dir", type=str, default="experiments_out")
    args = parser.parse_args()
    os.makedirs(args.out_dir, exist_ok=True)

    df_raw, X, y_all, ids, label2id, id2label = load_valid_data(args.data)

    print("=" * 60)
    print("[1단계] 라벨 검증")
    print("=" * 60)
    print(f"\nreal_dataset.xlsx 전체 컬럼: {list(df_raw.columns)}")

    date_cols = find_date_like_columns(df_raw)
    if date_cols:
        print(f"\n✅ 날짜/시점 관련 컬럼 후보 발견: {date_cols}")
        print("   → 각 라벨이 언제 기준인지 이 컬럼으로 확인 가능할 수 있습니다. 값을 확인해보세요:")
        print(df_raw[["회사명"] + date_cols].head(10).to_string(index=False))
    else:
        print(
            "\n❌ 날짜/평가시점을 나타낼 만한 컬럼이 없습니다 "
            "(컬럼명에 '일자/날짜/date/평가일/기준일' 등의 패턴 없음)."
        )
        print("   즉 이 라벨이 정확히 언제 기준 등급인지는 데이터만으로는 알 수 없습니다.")
        print("   → 아래 7개 기업은 사용자가 NICE신용평가에서 직접 현재 등급과 대조해야 합니다.")

    # baseline OOF 재계산 (analyze_oof.py와 동일 설정) → FP(위험 과소평가) 7건 추출
    cfg = RunConfig(name="baseline", cv_seed=args.seed, model_seed=args.seed)
    y_oof, _, n_splits = run_cv_once(X, y_all, cfg, id2label, label2id)

    id2label_int = {int(k): v for k, v in id2label.items()}
    y_true_label = [id2label_int[i] for i in y_all]
    y_pred_label = [id2label_int[i] for i in y_oof]
    true_inv = [is_investment_grade(l) for l in y_true_label]
    pred_inv = [is_investment_grade(l) for l in y_pred_label]

    fp_rows = []
    for i in range(len(y_all)):
        if (not true_inv[i]) and pred_inv[i]:
            fp_rows.append({
                "회사명": ids.iloc[i],
                "라벨_등급(real_dataset.xlsx)": y_true_label[i],
                "모델_예측등급(OOF)": y_pred_label[i],
            })
    fp_df = pd.DataFrame(fp_rows)

    print(f"\n[재현 확인] baseline OOF 기준 '실제투기→예측투자' 건수: {len(fp_df)}건 (n_splits={n_splits})")
    print("\n=== 위험 과소평가 7건 (사용자 대조용) ===")
    print(fp_df.to_string(index=False))

    out_path = os.path.join(args.out_dir, "stage1_risk_underestimation_companies.csv")
    fp_df.to_csv(out_path, index=False, encoding="utf-8-sig")
    print(f"\n저장: {out_path}")


if __name__ == "__main__":
    main()
