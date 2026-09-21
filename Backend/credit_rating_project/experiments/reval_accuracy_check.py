# -*- coding: utf-8 -*-
"""
experiments/reval_accuracy_check.py — ACI 재검증 [4. 정확도 검증]

기존 OOF(원래 라벨, seed=42) 기준으로:
  - 정확 일치(exact match) 정확도
  - 가장 많은 등급 하나로만 예측했을 때의 baseline 정확도 (majority-class baseline)
  - 등급별 표본 수 (모델이 실제로 평가하는 유효 66건 기준)

⚠️ 크롤링이 필요 없는 단계라 real_dataset.xlsx만 있으면 바로 실행됩니다.
   기존 src/*, experiments/common.py는 수정하지 않고 그대로 import해서 사용합니다.

사용법:
  python experiments/reval_accuracy_check.py --data /path/to/real_dataset.xlsx
"""
import argparse
import os
import sys
from collections import Counter

import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from experiments.common import load_valid_data, run_cv_once, RunConfig  # noqa: E402


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--data", required=True)
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--out_dir", type=str, default="experiments_out")
    args = parser.parse_args()
    os.makedirs(args.out_dir, exist_ok=True)

    df_raw, X, y_all, ids, label2id, id2label = load_valid_data(args.data)
    id2label_int = {int(k): v for k, v in id2label.items()}

    cfg = RunConfig(name="baseline", cv_seed=args.seed, model_seed=args.seed)
    y_oof, _, n_splits = run_cv_once(X, y_all, cfg, id2label, label2id)

    exact_match = (y_oof == y_all).mean()

    counts = Counter(y_all)
    majority_id, majority_n = counts.most_common(1)[0]
    majority_label = id2label_int[majority_id]
    majority_baseline_acc = majority_n / len(y_all)

    class_table = pd.DataFrame(
        [{"등급": id2label_int[k], "표본수": v} for k, v in counts.items()]
    )
    class_table["__rank"] = class_table["등급"].map(
        {lbl: i for i, lbl in enumerate(sorted(id2label_int.values(), key=lambda l: label2id[l]))}
    )
    class_table = class_table.sort_values("__rank").drop(columns="__rank").reset_index(drop=True)

    print("=" * 60)
    print("[4단계] 정확도 검증 (원래 라벨, seed=42, n_splits=%d)" % n_splits)
    print("=" * 60)
    print(f"\n유효 표본 수: {len(y_all)}건")
    print(f"정확 일치(exact match) 정확도: {exact_match:.4f} ({int((y_oof==y_all).sum())}/{len(y_all)})")
    print(f"최빈 등급: {majority_label} ({majority_n}건)")
    print(f"최빈 등급 1개로만 예측 시 baseline 정확도: {majority_baseline_acc:.4f}")
    print(f"exact-match 정확도 - baseline 대비 개선폭: {exact_match - majority_baseline_acc:+.4f}")

    print("\n등급별 표본 수 (총 %d등급):" % len(class_table))
    print(class_table.to_string(index=False))

    out_path = os.path.join(args.out_dir, "stage4_accuracy_check.csv")
    summary = pd.DataFrame([{
        "n": len(y_all),
        "exact_match_accuracy": exact_match,
        "majority_label": majority_label,
        "majority_baseline_accuracy": majority_baseline_acc,
        "improvement_over_baseline": exact_match - majority_baseline_acc,
    }])
    summary.to_csv(out_path, index=False, encoding="utf-8-sig")
    class_table.to_csv(os.path.join(args.out_dir, "stage4_class_counts.csv"), index=False, encoding="utf-8-sig")
    print(f"\n저장: {out_path}")
    print(f"저장: {os.path.join(args.out_dir, 'stage4_class_counts.csv')}")


if __name__ == "__main__":
    main()
