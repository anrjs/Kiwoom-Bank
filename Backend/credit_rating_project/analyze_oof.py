# -*- coding: utf-8 -*-
"""
analyze_oof.py — OOF 예측 분석 스크립트 (자소서용 정량 수치 추출)

⚠️ 이 파일은 기존 파이프라인 코드(src/*)를 전혀 수정하지 않는 "읽기 전용" 분석 도구입니다.
   src.train, src.data_utils, src.features, src.model, src.augment의 기존 함수를
   그대로 import해서 재사용하며, train.py의 CV 루프 로직만 이 스크립트 안에서
   동일하게 재현합니다 (train.py는 OOF 예측 자체를 파일로 저장하지 않기 때문).

사용법 (credit_rating_project/ 디렉터리에서 실행):

  # 1) predictions.xlsx가 OOF인지 최종모델 예측인지만 점검
  python analyze_oof.py --predictions path/to/predictions.xlsx

  # 2) OOF가 없다고 판단되면, train.py와 동일 설정으로 CV를 재실행해 OOF 재생성
  python analyze_oof.py --data data/real_dataset.xlsx

  # 3) 둘 다 있으면 함께 점검 + 두 파일이 같은 값인지 대조
  python analyze_oof.py --data data/real_dataset.xlsx --predictions path/to/predictions.xlsx

  # fold 수를 강제로 지정하고 싶을 때 (예: 2-fold로 재현 검증)
  python analyze_oof.py --data data/real_dataset.xlsx --n_splits 2

옵션:
  --seed        기본 42 (train.py 기본값과 동일)
  --target_qwk  재현 목표 QWK (기본 0.6975)
  --out_dir     결과 저장 폴더 (기본 analysis_out/)
"""
import argparse
import os
import sys
from collections import Counter

import numpy as np
import pandas as pd
from sklearn.model_selection import StratifiedKFold
from sklearn.metrics import cohen_kappa_score

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from src.config import (  # noqa: E402
    RATING_ORDER, FEATURE_COLS, ID_COL, TARGET_COL, MONOTONE_SIGNS,
    AUG_ENABLED, AUG_TARGET_PER_CLASS, AUG_MAX_SYNTHETIC_RATIO,
    AUG_MIXUP_ALPHA, AUG_MIXUP_RATIO, AUG_JITTER_SCALE, AUG_LO, AUG_HI, AUG_SEED,
    CV_FOLDS,
)
from src.data_utils import load_dataframe, split_X_y  # noqa: E402
from src.features import build_feature_pipeline  # noqa: E402
from src.model import make_model, OrdinalRegressorConfig, make_sample_weights  # noqa: E402
from src.augment import AugmentConfig, augment_dataset  # noqa: E402

INVESTMENT_CUTOFF = "BBB-"  # BBB- 이상 = 투자등급, BB+ 이하 = 투기등급


# ──────────────────────────────────────────────
# 등급 <-> 투자/투기 이진화 (RATING_ORDER 기준)
# ──────────────────────────────────────────────
def grade_rank(label: str) -> int:
    return RATING_ORDER.index(label)


def is_investment_grade(label: str) -> bool:
    return grade_rank(label) <= grade_rank(INVESTMENT_CUTOFF)


# ──────────────────────────────────────────────
# 1) predictions.xlsx가 OOF인지 최종모델 예측인지 점검
# ──────────────────────────────────────────────
def inspect_predictions_file(path: str) -> pd.DataFrame:
    df = pd.read_excel(path)
    print(f"\n[1] predictions 파일 점검: {path}")
    print(f"    - 행 수: {len(df)}")
    print(f"    - 컬럼: {list(df.columns)}")

    hints = []
    cols = set(df.columns)

    # predict_single.py가 만드는 산출물의 전형적 컬럼명
    if {"predicted_notch", "predicted_label"} & cols:
        hints.append(
            "컬럼명이 predict_single.py의 출력(predicted_notch/predicted_label)과 일치 "
            "→ '전체 데이터로 학습한 최종 모델'의 추론 결과일 가능성이 매우 높음 (OOF 아님)."
        )
    if "fold" in cols:
        hints.append("'fold' 컬럼 존재 → CV 파이프라인에서 직접 저장한 OOF일 가능성이 있음.")
    if TARGET_COL in cols:
        hints.append(
            f"'{TARGET_COL}'(실제 라벨) 컬럼이 포함되어 있음 → 학습에 쓴 real_dataset.xlsx와 "
            "행이 겹치는지 --data 옵션으로 대조 권장 (겹치면 훈련셋 재현일 위험이 있음)."
        )

    if hints:
        print("    - 판별 단서:")
        for h in hints:
            print(f"      · {h}")
    else:
        print("    - 컬럼명만으로는 OOF/최종모델 여부를 특정할 단서가 부족함. --data로 대조 필요.")

    return df


# ──────────────────────────────────────────────
# 2) train.py의 CV 루프를 동일 설정으로 재현 → OOF 재생성
#    (src.train.main()과 동일한 로직이지만, y_oof/회사명을 그대로 반환한다는 점만 다름)
# ──────────────────────────────────────────────
def rerun_cv_oof(data_path: str, seed: int = 42, augment: bool = AUG_ENABLED,
                  n_splits_override: int | None = None,
                  max_iter: int = 3000, learning_rate: float = 0.03,
                  max_depth: int = 6, l2_reg: float = 3.0,
                  synth_weight: float = 0.7):
    df_raw = load_dataframe(data_path)
    X, y, label2id, id2label = split_X_y(df_raw)
    y_all = y.astype(int).values

    y_counts = Counter(y_all)
    valid_classes = {k for k, v in y_counts.items() if v >= 2} or set(np.unique(y_all))
    mask = np.isin(y_all, list(valid_classes))
    X = X.loc[mask].reset_index(drop=True)
    y_all = y_all[mask]
    ids = df_raw.loc[mask, ID_COL].reset_index(drop=True) if ID_COL in df_raw.columns else pd.Series(
        [f"row_{i}" for i in range(len(y_all))]
    )

    min_class_count = min(Counter(y_all).values())
    auto_n_splits = min(CV_FOLDS, min_class_count) if min_class_count >= 2 else 2
    n_splits = n_splits_override if n_splits_override else auto_n_splits

    print(f"\n[2] CV 재실행 설정")
    print(f"    - 유효 표본 수: {len(y_all)}건, 클래스 수: {len(np.unique(y_all))}")
    print(f"    - 클래스별 최소 표본 수: {min_class_count}")
    print(f"    - CV_FOLDS(config.py): {CV_FOLDS} / 자동 계산된 n_splits: {auto_n_splits} "
          f"/ 실제 사용 n_splits: {n_splits}"
          + (" (수동 지정)" if n_splits_override else ""))
    if auto_n_splits != 2:
        print(f"    ⚠ train.py 기본 로직대로면 n_splits={auto_n_splits}이며, "
              f"'2-fold'가 되려면 가장 적은 클래스가 정확히 2건이어야 합니다. "
              f"목표했던 2-fold와 다르면 QWK 재현이 어긋나는 주된 원인일 수 있습니다.")

    cv = StratifiedKFold(n_splits=n_splits, shuffle=True, random_state=seed)
    y_oof = np.zeros_like(y_all)

    for fold, (tr_idx, va_idx) in enumerate(cv.split(X, y_all), 1):
        X_tr_real, y_tr = X.iloc[tr_idx].copy(), y_all[tr_idx]
        X_va_real, y_va = X.iloc[va_idx].copy(), y_all[va_idx]

        pre = build_feature_pipeline()
        pre.fit(X_tr_real, y_tr)

        if augment:
            aug_cfg = AugmentConfig(
                target_per_class=AUG_TARGET_PER_CLASS,
                max_synth_ratio=AUG_MAX_SYNTHETIC_RATIO,
                mixup_alpha=AUG_MIXUP_ALPHA,
                mixup_ratio=AUG_MIXUP_RATIO,
                jitter_scale=AUG_JITTER_SCALE,
                lower_q=AUG_LO, upper_q=AUG_HI, seed=AUG_SEED,
            )
            X_tr_aug, y_tr_aug, _ = augment_dataset(X_tr_real, y_tr, aug_cfg)
            is_synth = np.array([0] * len(X_tr_real) + [1] * (len(X_tr_aug) - len(X_tr_real)))
        else:
            X_tr_aug, y_tr_aug = X_tr_real, y_tr
            is_synth = np.zeros(len(X_tr_aug))

        X_tr = pre.transform(X_tr_aug)
        X_va = pre.transform(X_va_real)

        base_weights, _ = make_sample_weights(y_tr_aug)
        sample_weights = base_weights * np.where(is_synth == 1, synth_weight, 1.0)

        base_signs = [MONOTONE_SIGNS.get(c, 0) for c in FEATURE_COLS]
        k_extra = getattr(pre, "n_features_out_", len(base_signs)) - len(base_signs)
        constraints = base_signs + [0] * max(0, k_extra)

        model = make_model(OrdinalRegressorConfig(
            iterations=max_iter, learning_rate=learning_rate,
            depth=max_depth if max_depth > 0 else None,
            l2_leaf_reg=l2_reg, random_state=seed, verbose=False,
            monotone_constraints=constraints,
        ))
        model.fit(X_tr, y_tr_aug, sample_weight=sample_weights,
                  eval_set=(X_va, y_va), early_stopping_rounds=100)

        y_pred = np.clip(np.rint(model.predict(X_va)), 0, len(label2id) - 1).astype(int)
        y_oof[va_idx] = y_pred
        print(f"    - fold {fold}/{n_splits}: val {len(va_idx)}건 완료")

    qwk = cohen_kappa_score(y_all, y_oof, weights="quadratic")
    return X, y_all, y_oof, ids, id2label, qwk, n_splits


# ──────────────────────────────────────────────
# 3~4) 투자/투기 이진화 + 혼동행렬 + notch tolerance
# ──────────────────────────────────────────────
def summarize(y_true_ids: np.ndarray, y_pred_ids: np.ndarray, id2label: dict, ids: pd.Series):
    id2label = {int(k): v for k, v in id2label.items()}
    y_true_label = [id2label[i] for i in y_true_ids]
    y_pred_label = [id2label[i] for i in y_pred_ids]

    true_inv = np.array([is_investment_grade(l) for l in y_true_label])
    pred_inv = np.array([is_investment_grade(l) for l in y_pred_label])

    tp = int(np.sum(true_inv & pred_inv))          # 실제투자 & 예측투자
    fn = int(np.sum(true_inv & ~pred_inv))         # 실제투자 & 예측투기
    fp = int(np.sum(~true_inv & pred_inv))         # 실제투기 & 예측투자
    tn = int(np.sum(~true_inv & ~pred_inv))        # 실제투기 & 예측투기
    n = len(y_true_ids)

    inv_precision = tp / (tp + fp) if (tp + fp) > 0 else float("nan")
    inv_recall = tp / (tp + fn) if (tp + fn) > 0 else float("nan")
    spec_precision = tn / (tn + fn) if (tn + fn) > 0 else float("nan")
    spec_recall = tn / (tn + fp) if (tn + fp) > 0 else float("nan")

    actual_inv_ratio = true_inv.mean()
    baseline_all_inv_acc = actual_inv_ratio  # 전부 투자등급으로 찍었을 때 정확도 = 실제 투자등급 비율

    notch_diff = np.abs(np.array(y_true_ids) - np.array(y_pred_ids))
    within1 = float(np.mean(notch_diff <= 1))
    within2 = float(np.mean(notch_diff <= 2))

    result = {
        "n": n,
        "confusion_2x2": {
            "실제투자_예측투자(TP)": tp, "실제투자_예측투기(FN)": fn,
            "실제투기_예측투자(FP)": fp, "실제투기_예측투기(TN)": tn,
        },
        "investment_precision": inv_precision,
        "investment_recall": inv_recall,
        "speculative_precision": spec_precision,
        "speculative_recall": spec_recall,
        "actual_investment_ratio": actual_inv_ratio,
        "baseline_all_investment_accuracy": baseline_all_inv_acc,
        "within_1_notch_ratio": within1,
        "within_2_notch_ratio": within2,
    }

    per_row = pd.DataFrame({
        "회사명": ids.values if len(ids) == n else np.arange(n),
        "실제등급": y_true_label,
        "예측등급": y_pred_label,
        "실제_투자등급여부": true_inv,
        "예측_투자등급여부": pred_inv,
        "notch_diff": notch_diff,
    })
    return result, per_row


def print_report(result: dict, qwk: float, target_qwk: float, n_splits: int):
    print("\n" + "=" * 60)
    print("측정 결과 요약 (OOF 기준)")
    print("=" * 60)
    print(f"- 표본 수: {result['n']}건, CV n_splits: {n_splits}")
    print(f"- QWK(재현): {qwk:.4f}  (목표: {target_qwk:.4f}, 차이: {qwk - target_qwk:+.4f})")

    cm = result["confusion_2x2"]
    print("\n[투자/투기 2x2 혼동행렬]")
    print(f"                예측:투자    예측:투기")
    print(f"  실제:투자      {cm['실제투자_예측투자(TP)']:>8}    {cm['실제투자_예측투기(FN)']:>8}")
    print(f"  실제:투기      {cm['실제투기_예측투자(FP)']:>8}    {cm['실제투기_예측투기(TN)']:>8}")

    print("\n[정밀도/재현율]")
    print(f"  투자등급  precision={result['investment_precision']:.4f}  recall={result['investment_recall']:.4f}")
    print(f"  투기등급  precision={result['speculative_precision']:.4f}  recall={result['speculative_recall']:.4f}")

    print("\n[기준선 비교]")
    print(f"  실제 투자등급 비율: {result['actual_investment_ratio']:.4f}")
    print(f"  전부 투자등급으로 찍었을 때 정확도(베이스라인): {result['baseline_all_investment_accuracy']:.4f}")

    print("\n[노치 오차 허용 비율]")
    print(f"  ±1 notch 이내: {result['within_1_notch_ratio']:.4f}")
    print(f"  ±2 notch 이내: {result['within_2_notch_ratio']:.4f}")

    print("\n" + "=" * 60)
    print("⚠ 자소서 작성 시 과장 위험 체크리스트 (자동 생성)")
    print("=" * 60)
    warnings = []
    if n_splits < 3:
        warnings.append(
            f"n_splits={n_splits}로 매우 적은 fold 수입니다. fold 수가 적으면 validation 셋이 커지는 "
            "대신 시드에 따른 QWK 변동폭도 커집니다. 단일 시드 QWK 하나만 '성능'으로 못박기보다, "
            "여러 시드 평균±표준편차를 함께 적는 것이 안전합니다."
        )
    if result["n"] < 100:
        warnings.append(
            f"표본 수가 {result['n']}건으로 적습니다. 특히 투기등급처럼 표본이 적은 쪽의 "
            "precision/recall은 몇 건만 바뀌어도 수치가 크게 흔들립니다. 자소서에 비율만 쓰지 말고 "
            "분모(n)를 함께 명시하세요 (예: 'recall 83% (5건 중 4건 정탐)')."
        )
    cm = result["confusion_2x2"]
    spec_n = cm["실제투기_예측투자(FP)"] + cm["실제투기_예측투기(TN)"]
    if spec_n > 0 and spec_n < 10:
        warnings.append(
            f"실제 투기등급 표본이 {spec_n}건뿐입니다. 투기등급 precision/recall은 통계적 신뢰도가 "
            "낮으니 '투기등급도 잘 잡아낸다'는 식의 일반화된 표현은 과장이 될 수 있습니다."
        )
    if result["baseline_all_investment_accuracy"] > 0.8:
        warnings.append(
            f"실제 데이터의 투자등급 비율이 {result['baseline_all_investment_accuracy']:.1%}로 매우 높습니다. "
            "이 경우 '전부 투자등급'이라고만 찍어도 정확도가 이미 그만큼 나오므로, 모델 정확도를 "
            "베이스라인과 비교하지 않고 단독으로 자소서에 쓰면 실제 개선폭보다 부풀려 보일 수 있습니다."
        )
    if result["within_2_notch_ratio"] - result["within_1_notch_ratio"] > 0.15:
        warnings.append(
            "±2 notch 이내 비율이 ±1 notch보다 크게 높습니다. ±2 notch는 등급 2단계 차이까지 '맞다'고 "
            "치는 느슨한 기준이므로, 자소서에는 반드시 '±2 notch(등급 2단계 이내) 기준'이라고 "
            "명시하고 '정확도'라는 표현만 단독으로 쓰지 않는 것을 권장합니다."
        )
    warnings.append(
        "학습 파이프라인은 데이터 증강(synthetic mixup/jitter)을 사용합니다. 증강 후 학습 표본 수를 "
        "마치 실제 수집 데이터 규모인 것처럼 쓰면 과장입니다 — '실측 N건 + 증강 M건'처럼 구분해서 "
        "표기하세요."
    )
    for w in warnings:
        print(f"  ⚠ {w}")


def main():
    parser = argparse.ArgumentParser(description="OOF 예측 분석 (읽기 전용)")
    parser.add_argument("--data", type=str, default=None, help="real_dataset.xlsx 경로 (CV 재실행용)")
    parser.add_argument("--predictions", type=str, default=None, help="기존 predictions.xlsx 경로 (점검용)")
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--n_splits", type=int, default=None, help="강제 지정 시 사용 (예: 2)")
    parser.add_argument("--target_qwk", type=float, default=0.6975)
    parser.add_argument("--no_augment", action="store_true")
    parser.add_argument("--out_dir", type=str, default="analysis_out")
    args = parser.parse_args()

    if not args.data and not args.predictions:
        parser.error("--data 또는 --predictions 중 최소 하나는 지정해야 합니다.")

    os.makedirs(args.out_dir, exist_ok=True)

    if args.predictions:
        inspect_predictions_file(args.predictions)

    if args.data:
        X, y_all, y_oof, ids, id2label, qwk, n_splits = rerun_cv_oof(
            args.data, seed=args.seed, augment=not args.no_augment,
            n_splits_override=args.n_splits,
        )
        result, per_row = summarize(y_all, y_oof, id2label, ids)
        print_report(result, qwk, args.target_qwk, n_splits)

        per_row_path = os.path.join(args.out_dir, "oof_predictions_regenerated.csv")
        per_row.to_csv(per_row_path, index=False, encoding="utf-8-sig")
        print(f"\n재생성된 OOF 예측 {len(per_row)}건 저장: {per_row_path}")

        if args.predictions:
            pred_df = pd.read_excel(args.predictions)
            print(f"\n[대조] --predictions 파일 행 수({len(pred_df)}) vs 재생성 OOF 행 수({len(per_row)})"
                  + ("  → 동일" if len(pred_df) == len(per_row) else "  → 불일치, 서로 다른 산출물일 가능성"))
    else:
        print("\n--data가 없어 CV 재실행은 생략합니다. --predictions만 점검했습니다.")


if __name__ == "__main__":
    main()
