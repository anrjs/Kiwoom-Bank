# -*- coding: utf-8 -*-
"""
experiments/reval_corrected_rerun.py — ACI 재검증 [2. 교정 라벨로 재실험]

원래 라벨 데이터셋과, NICE 이력으로 교정한 라벨 데이터셋(등급 없는 기업 제외)에 대해
동일한 10개 CV 분할 시드로 baseline / 게이트(threshold 0.5) / 게이트(threshold 0.3)를
각각 반복 실행하고, QWK·투기등급 precision/recall·위험과소평가 건수를 평균±표준편차로
나란히 비교합니다.

사용법:
  python experiments/reval_corrected_rerun.py \
      --data real_dataset.xlsx \
      --labels experiments_out/stage1_corrected_labels.csv
"""
import argparse
import os
import sys

import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from experiments.common import load_valid_data, run_cv_once, compute_metrics, RunConfig  # noqa: E402
from experiments.reval_common import load_corrected_data  # noqa: E402

DEFAULT_SEEDS = [42, 1, 2, 3, 4, 5, 6, 7, 8, 9]

METHODS = [
    dict(name="baseline", use_gate=False),
    dict(name="게이트(th=0.5)", use_gate=True, gate_threshold=0.5),
    dict(name="게이트(th=0.3)", use_gate=True, gate_threshold=0.3),
]


def run_grid(X, y_all, ids, label2id, id2label, seeds, model_seed, label_set_name):
    rows = []
    for method in METHODS:
        for s in seeds:
            cfg = RunConfig(cv_seed=s, model_seed=model_seed, **method)
            y_oof, _, n_splits = run_cv_once(X, y_all, cfg, id2label, label2id)
            m = compute_metrics(y_all, y_oof, id2label)
            m.update({"label_set": label_set_name, "method": method["name"], "cv_seed": s, "n_splits": n_splits})
            rows.append(m)
        print(f"  [{label_set_name}] {method['name']} 완료 ({len(seeds)}개 시드)")
    return rows


def summarize(df: pd.DataFrame) -> pd.DataFrame:
    agg = df.groupby(["label_set", "method"]).agg(
        n_mean=("n", "mean"),
        qwk_mean=("qwk", "mean"), qwk_std=("qwk", "std"),
        spec_precision_mean=("speculative_precision", "mean"), spec_precision_std=("speculative_precision", "std"),
        spec_recall_mean=("speculative_recall", "mean"), spec_recall_std=("speculative_recall", "std"),
        risk_mean=("risk_underestimation_count", "mean"), risk_std=("risk_underestimation_count", "std"),
    ).reset_index()
    label_order = {"원래라벨": 0, "교정라벨": 1}
    method_order = {m["name"]: i for i, m in enumerate(METHODS)}
    agg["__lo"] = agg["label_set"].map(label_order)
    agg["__mo"] = agg["method"].map(method_order)
    return agg.sort_values(["__lo", "__mo"]).drop(columns=["__lo", "__mo"]).reset_index(drop=True)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--data", required=True)
    parser.add_argument("--labels", required=True, help="stage1_corrected_labels.csv 경로")
    parser.add_argument("--seeds", type=str, default=None)
    parser.add_argument("--model_seed", type=int, default=42)
    parser.add_argument("--out_dir", type=str, default="experiments_out")
    args = parser.parse_args()
    os.makedirs(args.out_dir, exist_ok=True)

    seeds = [int(s) for s in args.seeds.split(",")] if args.seeds else DEFAULT_SEEDS
    print("=" * 70)
    print(f"[2단계] 교정 라벨 재실험 — 반복 시드 {len(seeds)}개: {seeds}")
    print("=" * 70)

    print("\n--- 원래 라벨 데이터 로드 ---")
    _, X_o, y_o, ids_o, l2i_o, i2l_o = load_valid_data(args.data)
    print(f"원래 라벨 유효 표본: {len(y_o)}건")

    print("\n--- 교정 라벨 데이터 로드 ---")
    X_c, y_c, ids_c, l2i_c, i2l_c = load_corrected_data(args.data, args.labels)
    print(f"교정 라벨 유효 표본: {len(y_c)}건")

    print("\n--- 원래 라벨 그리드 실행 ---")
    rows_o = run_grid(X_o, y_o, ids_o, l2i_o, i2l_o, seeds, args.model_seed, "원래라벨")
    print("\n--- 교정 라벨 그리드 실행 ---")
    rows_c = run_grid(X_c, y_c, ids_c, l2i_c, i2l_c, seeds, args.model_seed, "교정라벨")

    df = pd.DataFrame(rows_o + rows_c)
    detail_path = os.path.join(args.out_dir, "stage2_corrected_rerun_all_runs.csv")
    df.to_csv(detail_path, index=False, encoding="utf-8-sig")

    summary = summarize(df)
    print("\n" + "=" * 70)
    print("비교 표 (평균 ± 표준편차, n_seeds=%d)" % len(seeds))
    print("=" * 70)
    for _, row in summary.iterrows():
        print(f"\n[{row['label_set']} / {row['method']}]  (n={row['n_mean']:.0f})")
        print(f"  QWK              : {row['qwk_mean']:.4f} ± {row['qwk_std']:.4f}")
        print(f"  투기등급 precision: {row['spec_precision_mean']:.4f} ± {row['spec_precision_std']:.4f}")
        print(f"  투기등급 recall   : {row['spec_recall_mean']:.4f} ± {row['spec_recall_std']:.4f}")
        print(f"  위험과소평가 건수 : {row['risk_mean']:.2f} ± {row['risk_std']:.2f}")

    summary_path = os.path.join(args.out_dir, "stage2_corrected_rerun_summary.csv")
    summary.to_csv(summary_path, index=False, encoding="utf-8-sig")
    print(f"\n상세: {detail_path}")
    print(f"요약: {summary_path}")


if __name__ == "__main__":
    main()
