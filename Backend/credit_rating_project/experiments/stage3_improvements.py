# -*- coding: utf-8 -*-
"""
experiments/stage3_improvements.py — 3단계: 위험 과소평가를 줄이는 개선 실험

목표: 투기등급 재현율(recall) 향상 = 위험 과소평가(실제 투기등급을 투자등급으로
      오판) 건수 감소. QWK가 크게 떨어지면 안 됨.

비교 대상 (모두 baseline과 동일 설정 + 아래 항목만 변경):
  A. 투기등급 표본 가중치 추가 상향 (기존 class-balanced 가중치에 배율 곱)
  B. 비대칭 손실: CatBoost Quantile 손실 (alpha=0.7 → '위험을 낮게 예측'하는
     오류(FP: 실제투기→예측투자)에 더 큰 패널티)
  C. 투자/투기 이진 게이트로 먼저 거른 뒤, 게이트가 '투기'로 판단하지만
     회귀모델이 투자등급을 예측한 경우 최저 투기등급 notch로 보정.
     임계값 0.5(기본), 0.3(더 공격적으로 투기 판정) 두 가지 비교.

2단계와 동일한 반복 시드 목록으로 평균±표준편차를 계산합니다.

사용법:
  python experiments/stage3_improvements.py --data /path/to/real_dataset.xlsx
"""
import argparse
import os
import sys

import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from experiments.common import load_valid_data, run_cv_once, compute_metrics, RunConfig  # noqa: E402
from experiments.stage2_stability import DEFAULT_SEEDS  # noqa: E402

METHOD_CONFIGS = [
    dict(name="baseline", speculative_extra_weight=1.0, loss_function="RMSE", use_gate=False),
    dict(name="A_투기가중치x3", speculative_extra_weight=3.0, loss_function="RMSE", use_gate=False),
    dict(name="B_Quantile(a=0.7)", speculative_extra_weight=1.0, loss_function="Quantile",
         quantile_alpha=0.7, use_gate=False),
    dict(name="C_게이트(th=0.5)", speculative_extra_weight=1.0, loss_function="RMSE",
         use_gate=True, gate_threshold=0.5),
    dict(name="C_게이트(th=0.3)", speculative_extra_weight=1.0, loss_function="RMSE",
         use_gate=True, gate_threshold=0.3),
]


def run_all_methods(data_path: str, seeds: list[int], model_seed: int = 42) -> pd.DataFrame:
    df_raw, X, y_all, ids, label2id, id2label = load_valid_data(data_path)
    rows = []
    for method in METHOD_CONFIGS:
        print(f"\n--- 방법: {method['name']} ---")
        for s in seeds:
            cfg = RunConfig(cv_seed=s, model_seed=model_seed, **method)
            y_oof, _, n_splits = run_cv_once(X, y_all, cfg, id2label, label2id)
            m = compute_metrics(y_all, y_oof, id2label)
            m["method"] = method["name"]
            m["cv_seed"] = s
            rows.append(m)
            print(f"  seed={s:>3}  QWK={m['qwk']:.4f}  투기recall={m['speculative_recall']:.4f}  "
                  f"투기precision={m['speculative_precision']:.4f}  위험과소평가={m['risk_underestimation_count']}건")
    return pd.DataFrame(rows)


def summarize(df: pd.DataFrame) -> pd.DataFrame:
    agg = df.groupby("method").agg(
        qwk_mean=("qwk", "mean"), qwk_std=("qwk", "std"),
        spec_recall_mean=("speculative_recall", "mean"), spec_recall_std=("speculative_recall", "std"),
        spec_precision_mean=("speculative_precision", "mean"), spec_precision_std=("speculative_precision", "std"),
        risk_mean=("risk_underestimation_count", "mean"), risk_std=("risk_underestimation_count", "std"),
    ).reset_index()
    order = [m["name"] for m in METHOD_CONFIGS]
    agg["__order"] = agg["method"].map({n: i for i, n in enumerate(order)})
    return agg.sort_values("__order").drop(columns="__order").reset_index(drop=True)


def print_tradeoff_commentary(summary: pd.DataFrame):
    base = summary[summary["method"] == "baseline"].iloc[0]
    print("\n" + "=" * 70)
    print("트레이드오프 설명 (baseline 대비)")
    print("=" * 70)
    for _, row in summary.iterrows():
        if row["method"] == "baseline":
            continue
        d_qwk = row["qwk_mean"] - base["qwk_mean"]
        d_recall = row["spec_recall_mean"] - base["spec_recall_mean"]
        d_risk = row["risk_mean"] - base["risk_mean"]
        print(f"\n[{row['method']}]")
        print(f"  QWK 변화        : {d_qwk:+.4f}  (baseline {base['qwk_mean']:.4f} → {row['qwk_mean']:.4f})")
        print(f"  투기recall 변화 : {d_recall:+.4f}  (baseline {base['spec_recall_mean']:.4f} → {row['spec_recall_mean']:.4f})")
        print(f"  위험과소평가 변화: {d_risk:+.2f}건  (baseline {base['risk_mean']:.2f} → {row['risk_mean']:.2f})")
        if d_recall > 0 and d_qwk >= -0.03:
            verdict = "투기recall 개선 + QWK 손실 적음 → 채택 후보"
        elif d_recall > 0 and d_qwk < -0.03:
            verdict = "투기recall은 개선되지만 QWK가 눈에 띄게 하락 → 트레이드오프 고려 필요"
        elif d_recall <= 0:
            verdict = "투기recall이 개선되지 않음 → 이 설정만으로는 목표 미달성"
        else:
            verdict = "판단 보류"
        print(f"  → {verdict}")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--data", required=True)
    parser.add_argument("--seeds", type=str, default=None)
    parser.add_argument("--model_seed", type=int, default=42)
    parser.add_argument("--out_dir", type=str, default="experiments_out")
    args = parser.parse_args()
    os.makedirs(args.out_dir, exist_ok=True)

    seeds = [int(s) for s in args.seeds.split(",")] if args.seeds else DEFAULT_SEEDS
    print("=" * 70)
    print(f"[3단계] 위험 과소평가 개선 실험 — 반복 시드 {len(seeds)}개: {seeds}")
    print("=" * 70)

    df = run_all_methods(args.data, seeds, model_seed=args.model_seed)
    detail_path = os.path.join(args.out_dir, "stage3_all_runs.csv")
    df.to_csv(detail_path, index=False, encoding="utf-8-sig")

    summary = summarize(df)
    print("\n" + "=" * 70)
    print("방법별 비교 (평균 ± 표준편차, n_seeds=%d)" % len(seeds))
    print("=" * 70)
    for _, row in summary.iterrows():
        print(f"\n[{row['method']}]")
        print(f"  QWK              : {row['qwk_mean']:.4f} ± {row['qwk_std']:.4f}")
        print(f"  투기등급 recall   : {row['spec_recall_mean']:.4f} ± {row['spec_recall_std']:.4f}")
        print(f"  투기등급 precision: {row['spec_precision_mean']:.4f} ± {row['spec_precision_std']:.4f}")
        print(f"  위험과소평가 건수 : {row['risk_mean']:.2f} ± {row['risk_std']:.2f}")

    print_tradeoff_commentary(summary)

    summary_path = os.path.join(args.out_dir, "stage3_summary.csv")
    summary.to_csv(summary_path, index=False, encoding="utf-8-sig")
    print(f"\n\n상세 결과: {detail_path}")
    print(f"요약 결과: {summary_path}")


if __name__ == "__main__":
    main()
