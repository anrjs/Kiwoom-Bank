# -*- coding: utf-8 -*-
"""
experiments/reval_histgb_baseline.py — ACI 재검증 [3. 공정 비교용 베이스라인]

교정 라벨 데이터에서, CatBoost 파이프라인과 "같은 피처(전처리 파이프라인)"를 쓰되
증강 없음 / 클래스 가중치 없음 / 단조제약 없음의 기본 설정으로 HistGradientBoostingRegressor를
학습해 QWK를 산출합니다. CatBoost+증강+가중치+단조제약 조합이 얼마나 더 나은지(혹은
안 나은지) 볼 수 있는 "군더더기 없는" 대조군입니다.

같은 10개 CV 분할 시드로 반복하여 QWK 평균±표준편차를 냅니다.

사용법:
  python experiments/reval_histgb_baseline.py \
      --data real_dataset.xlsx \
      --labels experiments_out/stage1_corrected_labels.csv
"""
import argparse
import os
import sys

import numpy as np
import pandas as pd
from sklearn.ensemble import HistGradientBoostingRegressor
from sklearn.model_selection import StratifiedKFold
from sklearn.metrics import cohen_kappa_score

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from experiments.common import auto_n_splits  # noqa: E402  (기존 규칙 재사용, 수정 없음)
from experiments.reval_common import load_corrected_data  # noqa: E402
from src.features import build_feature_pipeline  # noqa: E402  (동일 전처리 파이프라인 재사용)

DEFAULT_SEEDS = [42, 1, 2, 3, 4, 5, 6, 7, 8, 9]


def run_histgb_oof(X: pd.DataFrame, y_all: np.ndarray, n_classes: int, cv_seed: int, model_seed: int = 42):
    n_splits = auto_n_splits(y_all)
    cv = StratifiedKFold(n_splits=n_splits, shuffle=True, random_state=cv_seed)
    y_oof = np.zeros_like(y_all)

    for tr_idx, va_idx in cv.split(X, y_all):
        X_tr, y_tr = X.iloc[tr_idx].copy(), y_all[tr_idx]
        X_va = X.iloc[va_idx].copy()

        pre = build_feature_pipeline()   # 동일 피처 전처리 (증강/가중치와 무관한 부분)
        pre.fit(X_tr, y_tr)
        X_tr_p = pre.transform(X_tr)
        X_va_p = pre.transform(X_va)

        # 증강 없음 / sample_weight 없음 / 단조제약 없음 / 기본 하이퍼파라미터
        model = HistGradientBoostingRegressor(random_state=model_seed)
        model.fit(X_tr_p, y_tr)

        y_pred = np.clip(np.rint(model.predict(X_va_p)), 0, n_classes - 1).astype(int)
        y_oof[va_idx] = y_pred

    qwk = cohen_kappa_score(y_all, y_oof, weights="quadratic")
    return qwk, n_splits


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--data", required=True)
    parser.add_argument("--labels", required=True)
    parser.add_argument("--seeds", type=str, default=None)
    parser.add_argument("--model_seed", type=int, default=42)
    parser.add_argument("--out_dir", type=str, default="experiments_out")
    args = parser.parse_args()
    os.makedirs(args.out_dir, exist_ok=True)

    seeds = [int(s) for s in args.seeds.split(",")] if args.seeds else DEFAULT_SEEDS
    print("=" * 60)
    print(f"[3단계] HistGradientBoostingRegressor 공정비교 베이스라인 (교정 라벨, 시드 {len(seeds)}개)")
    print("=" * 60)

    X, y_all, ids, label2id, id2label = load_corrected_data(args.data, args.labels)
    n_classes = len(label2id)

    rows = []
    for s in seeds:
        qwk, n_splits = run_histgb_oof(X, y_all, n_classes, cv_seed=s, model_seed=args.model_seed)
        rows.append({"cv_seed": s, "qwk": qwk, "n_splits": n_splits})
        print(f"  seed={s:>3}  QWK={qwk:.4f}  (n_splits={n_splits})")

    df = pd.DataFrame(rows)
    qwk_mean, qwk_std = df["qwk"].mean(), df["qwk"].std(ddof=1)
    print("\n" + "=" * 60)
    print(f"HistGB QWK (교정 라벨, n={len(y_all)}): {qwk_mean:.4f} ± {qwk_std:.4f} "
          f"(min={df['qwk'].min():.4f}, max={df['qwk'].max():.4f})")

    out_path = os.path.join(args.out_dir, "stage3_histgb_baseline.csv")
    df.to_csv(out_path, index=False, encoding="utf-8-sig")
    print(f"\n저장: {out_path}")


if __name__ == "__main__":
    main()
