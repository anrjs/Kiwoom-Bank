# -*- coding: utf-8 -*-
"""
experiments/stage2_stability.py — 2단계: 안정성 확인

동일 설정(seed=42 모델, 증강/가중치/단조제약 동일)에서 "CV 분할 시드"만 여러 번
바꿔가며 반복 실행해, QWK와 투기등급 재현율(recall)의 평균/표준편차를 계산합니다.

- CV 분할 시드(cv_seed)만 바뀌고, 모델 자체의 random_state(model_seed)는 42로 고정합니다.
  (n=66, 2-fold라 폴드에 어떤 회사가 들어가는지에 따른 변동성만 순수하게 보기 위함)

사용법:
  python experiments/stage2_stability.py --data /path/to/real_dataset.xlsx
  python experiments/stage2_stability.py --data ... --seeds 42,1,2,3,4,5,6,7,8,9
"""
import argparse
import os
import sys

import numpy as np
import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from experiments.common import load_valid_data, run_cv_once, compute_metrics, RunConfig  # noqa: E402

DEFAULT_SEEDS = [42, 1, 2, 3, 4, 5, 6, 7, 8, 9]  # 10개 (>=5 요구조건 충족)


def run_stability(data_path: str, seeds: list[int], model_seed: int = 42) -> pd.DataFrame:
    df_raw, X, y_all, ids, label2id, id2label = load_valid_data(data_path)
    rows = []
    for s in seeds:
        cfg = RunConfig(name="baseline", cv_seed=s, model_seed=model_seed)
        y_oof, _, n_splits = run_cv_once(X, y_all, cfg, id2label, label2id)
        m = compute_metrics(y_all, y_oof, id2label)
        m["cv_seed"] = s
        m["n_splits"] = n_splits
        rows.append(m)
        print(f"  seed={s:>3}  QWK={m['qwk']:.4f}  투기recall={m['speculative_recall']:.4f}  "
              f"위험과소평가={m['risk_underestimation_count']}건")
    return pd.DataFrame(rows)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--data", required=True)
    parser.add_argument("--seeds", type=str, default=None, help="쉼표구분 정수 목록, 예: 42,1,2,3,4,5")
    parser.add_argument("--model_seed", type=int, default=42)
    parser.add_argument("--out_dir", type=str, default="experiments_out")
    args = parser.parse_args()
    os.makedirs(args.out_dir, exist_ok=True)

    seeds = [int(s) for s in args.seeds.split(",")] if args.seeds else DEFAULT_SEEDS
    print("=" * 60)
    print(f"[2단계] 안정성 확인 — CV 분할 시드 {len(seeds)}개: {seeds}")
    print("=" * 60)

    df = run_stability(args.data, seeds, model_seed=args.model_seed)

    print("\n" + "=" * 60)
    print("요약 (평균 ± 표준편차)")
    print("=" * 60)
    qwk_mean, qwk_std = df["qwk"].mean(), df["qwk"].std(ddof=1)
    rec_mean, rec_std = df["speculative_recall"].mean(), df["speculative_recall"].std(ddof=1)
    risk_mean, risk_std = df["risk_underestimation_count"].mean(), df["risk_underestimation_count"].std(ddof=1)
    print(f"QWK              : {qwk_mean:.4f} ± {qwk_std:.4f}  (min={df['qwk'].min():.4f}, max={df['qwk'].max():.4f})")
    print(f"투기등급 recall   : {rec_mean:.4f} ± {rec_std:.4f}  (min={df['speculative_recall'].min():.4f}, max={df['speculative_recall'].max():.4f})")
    print(f"위험과소평가 건수 : {risk_mean:.2f} ± {risk_std:.2f}  (min={df['risk_underestimation_count'].min()}, max={df['risk_underestimation_count'].max()})")

    out_path = os.path.join(args.out_dir, "stage2_stability_by_seed.csv")
    df.to_csv(out_path, index=False, encoding="utf-8-sig")
    print(f"\n시드별 상세 결과 저장: {out_path}")


if __name__ == "__main__":
    main()
