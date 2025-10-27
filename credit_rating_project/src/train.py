# train_with_augmentation.py (Updated for complete classification evaluation)

import os
import json
import argparse
import numpy as np
import pandas as pd
from collections import Counter
from joblib import dump
from sklearn.metrics import (
    classification_report, confusion_matrix,
    f1_score, balanced_accuracy_score, mean_absolute_error,
    cohen_kappa_score
)
import matplotlib.pyplot as plt

from src.config import (
    DATA_PATH, ARTIFACTS_DIR, RATING_ORDER, MIN_CLASSES_FOR_QWK,
    FEATURE_COLS, MONOTONE_SIGNS,
    AUG_ENABLED, AUG_TARGET_PER_CLASS, AUG_MAX_SYNTHETIC_RATIO,
    AUG_MIXUP_ALPHA, AUG_MIXUP_RATIO, AUG_JITTER_SCALE, AUG_LO, AUG_HI, AUG_SEED,
    CV_FOLDS
)
from src.data_utils import load_dataframe, split_X_y
from src.features import build_feature_pipeline
from src.split import make_cv
from src.model import make_model, OrdinalRegressorConfig, make_sample_weights
from src.augment import AugmentConfig, augment_dataset

def save_confusion_matrix(y_true, y_pred, classes, out_path):
    cm = confusion_matrix(y_true, y_pred, labels=range(len(classes)))
    fig, ax = plt.subplots()
    im = ax.imshow(cm, interpolation='nearest', cmap='Blues')
    ax.set_title('Confusion Matrix')
    tick_marks = np.arange(len(classes))
    ax.set_xticks(tick_marks); ax.set_yticks(tick_marks)
    ax.set_xticklabels(classes, rotation=45, ha='right'); ax.set_yticklabels(classes)
    for i in range(cm.shape[0]):
        for j in range(cm.shape[1]):
            ax.text(j, i, format(cm[i, j], 'd'), ha="center", va="center")
    fig.tight_layout(); ax.set_ylabel('True'); ax.set_xlabel('Predicted')
    fig.savefig(out_path, bbox_inches='tight'); plt.close(fig)

def _build_monotone_constraints(pre, base_cols):
    base = [MONOTONE_SIGNS.get(c, 0) for c in base_cols]
    k = getattr(pre, "n_features_out_", len(base)) - len(base)
    if k < 0: k = 0
    return base + [0]*k

def main(args):
    os.makedirs(args.output_dir, exist_ok=True)

    df = load_dataframe(args.input)
    X, y, label2id, id2label = split_X_y(df)
    y_all = y.astype(int).values

    y_counts = Counter(y_all)
    valid_classes = {k for k, v in y_counts.items() if v >= 2} or set(np.unique(y_all))
    mask = np.isin(y_all, list(valid_classes))
    X = X.loc[mask].reset_index(drop=True)
    y_all = y_all[mask]

    min_class_count = min(Counter(y_all).values())
    n_splits = min(CV_FOLDS, min_class_count) if min_class_count >= 2 else 2
    if n_splits < 2:
        raise ValueError("At least 2 samples per class are required for cross-validation.")
    from sklearn.model_selection import StratifiedKFold
    cv = StratifiedKFold(n_splits=n_splits, shuffle=True, random_state=args.seed)

    y_oof = np.zeros_like(y_all)

    for fold, (tr_idx, va_idx) in enumerate(cv.split(X, y_all), 1):
        X_tr_real, y_tr = X.iloc[tr_idx].copy(), y_all[tr_idx]
        X_va_real, y_va = X.iloc[va_idx].copy(), y_all[va_idx]

        pre = build_feature_pipeline()
        pre.fit(X_tr_real, y_tr)

        if args.augment:
            aug_cfg = AugmentConfig(
                target_per_class=args.aug_target_per_class,
                max_synth_ratio=args.aug_max_synth_ratio,
                mixup_alpha=args.aug_mixup_alpha,
                mixup_ratio=args.aug_mixup_ratio,
                jitter_scale=args.aug_jitter_scale,
                lower_q=AUG_LO, upper_q=AUG_HI, seed=AUG_SEED
            )
            X_tr_aug, y_tr_aug, _ = augment_dataset(X_tr_real, y_tr, aug_cfg)
            is_synth = np.array([0]*len(X_tr_real) + [1]*(len(X_tr_aug) - len(X_tr_real)))
        else:
            X_tr_aug, y_tr_aug = X_tr_real, y_tr
            is_synth = np.zeros(len(X_tr_aug))

        X_tr = pre.transform(X_tr_aug)
        X_va = pre.transform(X_va_real)

        base_weights, _ = make_sample_weights(y_tr_aug)
        sample_weights = base_weights * np.where(is_synth == 1, args.synth_weight, 1.0)

        constraints = _build_monotone_constraints(pre, FEATURE_COLS)
        model = make_model(OrdinalRegressorConfig(
            iterations=args.max_iter,
            learning_rate=args.learning_rate,
            depth=args.max_depth if args.max_depth > 0 else None,
            l2_leaf_reg=args.l2_reg,
            random_state=args.seed,
            verbose=False,
            monotone_constraints=constraints
        ))

        model.fit(X_tr, y_tr_aug, sample_weight=sample_weights,
                  eval_set=(X_va, y_va), early_stopping_rounds=100)

        y_pred = np.clip(np.rint(model.predict(X_va)), 0, len(label2id)-1).astype(int)
        y_oof[va_idx] = y_pred

    pre_final = build_feature_pipeline()
    pre_final.fit(X, y_all)

    if args.augment:
        aug_cfg = AugmentConfig(
            target_per_class=args.aug_target_per_class,
            max_synth_ratio=args.aug_max_synth_ratio,
            mixup_alpha=args.aug_mixup_alpha,
            mixup_ratio=args.aug_mixup_ratio,
            jitter_scale=args.aug_jitter_scale,
            lower_q=AUG_LO, upper_q=AUG_HI, seed=AUG_SEED
        )
        X_aug_full, y_aug_full, _ = augment_dataset(X, y_all, aug_cfg)
        is_synth = np.array([0]*len(X) + [1]*(len(X_aug_full) - len(X)))
    else:
        X_aug_full, y_aug_full = X, y_all
        is_synth = np.zeros(len(X_aug_full))

    Xp_full = pre_final.transform(X_aug_full)
    base_weights, class_weights = make_sample_weights(y_aug_full)
    sample_weights = base_weights * np.where(is_synth == 1, args.synth_weight, 1.0)

    constraints = _build_monotone_constraints(pre_final, FEATURE_COLS)
    model_final = make_model(OrdinalRegressorConfig(
        iterations=args.max_iter,
        learning_rate=args.learning_rate,
        depth=args.max_depth if args.max_depth > 0 else None,
        l2_leaf_reg=args.l2_reg,
        random_state=args.seed,
        verbose=False,
        monotone_constraints=constraints
    ))
    model_final.fit(Xp_full, y_aug_full, sample_weight=sample_weights)

    mae = mean_absolute_error(y_all, y_oof)
    qwk = cohen_kappa_score(y_all, y_oof, weights="quadratic")
    f1_macro = f1_score(y_all, y_oof, average='macro')
    f1_weighted = f1_score(y_all, y_oof, average='weighted')
    bal_acc = balanced_accuracy_score(y_all, y_oof)

    print(f"[METRIC] MAE: {mae:.4f}  QWK: {qwk:.4f}  Macro-F1: {f1_macro:.4f}  Weighted-F1: {f1_weighted:.4f}  BalAcc: {bal_acc:.4f}")

    os.makedirs(args.output_dir, exist_ok=True)
    dump({"preprocessor": pre_final, "model": model_final}, os.path.join(args.output_dir, "model.joblib"))
    with open(os.path.join(args.output_dir, "label_mapping.json"), "w", encoding="utf-8") as f:
        json.dump({"label2id": label2id, "id2label": id2label}, f, ensure_ascii=False, indent=2)

    with open(os.path.join(args.output_dir, "metrics.json"), "w", encoding="utf-8") as f:
        json.dump({
            "mae": mae, "qwk": qwk, "macro_f1": f1_macro,
            "weighted_f1": f1_weighted, "balanced_accuracy": bal_acc,
            "class_weights": class_weights
        }, f, ensure_ascii=False, indent=2)

    # ✅ 유효 클래스 전체 반영: 예측에 등장한 클래스도 포함
    labels_union = sorted(set(y_all.tolist()) | set(y_oof.tolist()))
    # 안전하게 dict 키 타입 보정
    id2label = {int(k): v for k, v in id2label.items()}
    target_names_union = [id2label[i] for i in labels_union]


    with open(os.path.join(args.output_dir, "classification_report.txt"), "w", encoding="utf-8") as f:
        report = classification_report(
            y_all, y_oof,
            labels=labels_union,
            target_names=target_names_union,
            zero_division=0
        )
        f.write(report)

    save_confusion_matrix(y_all, y_oof, target_names_union, os.path.join(args.output_dir, "confusion_matrix.png"))

if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument('--input', type=str, default=DATA_PATH)
    parser.add_argument('--output_dir', type=str, default=ARTIFACTS_DIR)
    parser.add_argument('--seed', type=int, default=42)
    parser.add_argument('--max_iter', type=int, default=3000)
    parser.add_argument('--learning_rate', type=float, default=0.03)
    parser.add_argument('--max_depth', type=int, default=6)
    parser.add_argument('--l2_reg', type=float, default=3.0)
    parser.add_argument('--augment', action='store_true', default=AUG_ENABLED)
    parser.add_argument('--synth_weight', type=float, default=0.7)
    parser.add_argument('--aug_target_per_class', type=int, default=AUG_TARGET_PER_CLASS)
    parser.add_argument('--aug_max_synth_ratio', type=float, default=AUG_MAX_SYNTHETIC_RATIO)
    parser.add_argument('--aug_mixup_alpha', type=float, default=AUG_MIXUP_ALPHA)
    parser.add_argument('--aug_mixup_ratio', type=float, default=AUG_MIXUP_RATIO)
    parser.add_argument('--aug_jitter_scale', type=float, default=AUG_JITTER_SCALE)
    parser.add_argument('--cv_folds', type=int, default=CV_FOLDS)
    args = parser.parse_args()
    main(args)