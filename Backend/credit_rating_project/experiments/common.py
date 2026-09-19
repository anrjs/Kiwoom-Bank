# -*- coding: utf-8 -*-
"""
experiments/common.py — 3단계 실험 공용 유틸리티

⚠️ 기존 src/* 코드는 전혀 수정하지 않습니다. 여기서는 src의 기존 함수를
   그대로 import해서 재사용하고, train.py의 CV 루프만 이 모듈 안에서
   "실험용으로 파라미터화"해서 재구현합니다 (가중치 배율/손실함수/게이트
   등을 바꿔가며 비교해야 하는데, 원본 train.py는 이런 실험 옵션이 없기
   때문입니다).

핵심 함수:
  - load_valid_data(data_path): real_dataset.xlsx 로드 + 유효 클래스(>=2건) 필터링
  - run_cv_once(...): 지정한 설정으로 2-fold(자동) CV 1회 실행 → OOF 결과 반환
  - compute_metrics(...): QWK, 투자/투기 혼동행렬, precision/recall, 위험과소평가 건수
"""
import os
import sys
from collections import Counter
from dataclasses import dataclass, field
from typing import Optional

import numpy as np
import pandas as pd
from sklearn.model_selection import StratifiedKFold
from sklearn.metrics import cohen_kappa_score

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src.config import (  # noqa: E402
    RATING_ORDER, FEATURE_COLS, ID_COL, MONOTONE_SIGNS,
    AUG_ENABLED, AUG_TARGET_PER_CLASS, AUG_MAX_SYNTHETIC_RATIO,
    AUG_MIXUP_ALPHA, AUG_MIXUP_RATIO, AUG_JITTER_SCALE, AUG_LO, AUG_HI, AUG_SEED,
    CV_FOLDS,
)
from src.data_utils import load_dataframe, split_X_y  # noqa: E402
from src.features import build_feature_pipeline  # noqa: E402
from src.model import make_model, OrdinalRegressorConfig, make_sample_weights  # noqa: E402
from src.augment import AugmentConfig, augment_dataset  # noqa: E402

try:
    from catboost import CatBoostClassifier
    _HAS_CATBOOST_CLF = True
except ImportError:
    _HAS_CATBOOST_CLF = False

INVESTMENT_CUTOFF = "BBB-"  # BBB- 이상 투자등급, BB+ 이하 투기등급


def grade_rank(label: str) -> int:
    return RATING_ORDER.index(label)


def is_investment_grade(label) -> bool:
    return grade_rank(label) <= grade_rank(INVESTMENT_CUTOFF)


SPECULATIVE_CUTOFF_NOTCH = None  # 지연 계산 (id2label 필요)


# ──────────────────────────────────────────────
# 데이터 로드 (train.py / analyze_oof.py와 동일한 필터링 규칙)
# ──────────────────────────────────────────────
def load_valid_data(data_path: str):
    df_raw = load_dataframe(data_path)
    X, y, label2id, id2label = split_X_y(df_raw)
    y_all = y.astype(int).values

    y_counts = Counter(y_all)
    valid_classes = {k for k, v in y_counts.items() if v >= 2} or set(np.unique(y_all))
    mask = np.isin(y_all, list(valid_classes))
    X = X.loc[mask].reset_index(drop=True)
    y_all = y_all[mask]
    ids = (
        df_raw.loc[mask, ID_COL].reset_index(drop=True)
        if ID_COL in df_raw.columns
        else pd.Series([f"row_{i}" for i in range(len(y_all))])
    )
    return df_raw, X, y_all, ids, label2id, id2label


def auto_n_splits(y_all: np.ndarray) -> int:
    min_class_count = min(Counter(y_all).values())
    return min(CV_FOLDS, min_class_count) if min_class_count >= 2 else 2


# ──────────────────────────────────────────────
# 실험 설정
# ──────────────────────────────────────────────
@dataclass
class RunConfig:
    name: str = "baseline"
    cv_seed: int = 42
    model_seed: int = 42                 # 기본은 train.py처럼 cv_seed와 동일값 사용 가능
    n_splits: Optional[int] = None       # None이면 auto_n_splits 사용
    augment: bool = AUG_ENABLED
    synth_weight: float = 0.7
    max_iter: int = 3000
    learning_rate: float = 0.03
    max_depth: int = 6
    l2_reg: float = 3.0
    # ---- 3단계 개선 실험용 옵션 ----
    speculative_extra_weight: float = 1.0     # 투기등급 표본 가중치 추가 배율 (방법 A)
    loss_function: str = "RMSE"               # "RMSE" 또는 "Quantile" (방법 B)
    quantile_alpha: float = 0.7                # Quantile 손실의 alpha (0.5보다 크면 '위험 과소평가'에 더 큰 패널티)
    use_gate: bool = False                     # 2단계 게이트 사용 여부 (방법 C)
    gate_threshold: float = 0.5                # 게이트가 '투기등급'으로 판단하는 확률 임계값


def _build_monotone_constraints(pre, base_cols):
    base = [MONOTONE_SIGNS.get(c, 0) for c in base_cols]
    k = getattr(pre, "n_features_out_", len(base)) - len(base)
    if k < 0:
        k = 0
    return base + [0] * k


def _catboost_loss_kwargs(cfg: RunConfig):
    if cfg.loss_function.upper() == "RMSE":
        return {"loss_function": "RMSE", "eval_metric": "RMSE"}
    if cfg.loss_function.upper() == "QUANTILE":
        loss_str = f"Quantile:alpha={cfg.quantile_alpha}"
        return {"loss_function": loss_str, "eval_metric": loss_str}
    raise ValueError(f"지원하지 않는 loss_function: {cfg.loss_function}")


def make_model_custom(cfg: RunConfig, constraints):
    """src.model.make_model을 그대로 쓰되, loss_function만 실험용으로 바꿔치기.
    (src/model.py를 수정하지 않기 위해 CatBoostRegressor를 여기서 직접 생성)"""
    from catboost import CatBoostRegressor
    loss_kwargs = _catboost_loss_kwargs(cfg)
    return CatBoostRegressor(
        iterations=cfg.max_iter,
        learning_rate=cfg.learning_rate,
        depth=cfg.max_depth,
        l2_leaf_reg=cfg.l2_reg,
        random_seed=cfg.model_seed,
        allow_writing_files=False,
        verbose=False,
        monotone_constraints=constraints,
        **loss_kwargs,
    )


def run_cv_once(X: pd.DataFrame, y_all: np.ndarray, cfg: RunConfig, id2label: dict, label2id: dict):
    """train.py의 CV 루프를 cfg 설정대로 실험용으로 재현. OOF notch 예측(및 게이트 확률)을 반환."""
    id2label_int = {int(k): v for k, v in id2label.items()}
    spec_class_ids = {i for i, lbl in id2label_int.items() if not is_investment_grade(lbl)}
    spec_cutoff_notch = min(
        (i for i, lbl in id2label_int.items() if not is_investment_grade(lbl)),
        default=None,
    )  # 가장 안전한(=notch가 가장 낮은) 투기등급 notch. 게이트 오버라이드 시 이 값으로 끌어올림.

    n_splits = cfg.n_splits or auto_n_splits(y_all)
    cv = StratifiedKFold(n_splits=n_splits, shuffle=True, random_state=cfg.cv_seed)

    y_oof = np.zeros_like(y_all)
    gate_spec_proba = np.zeros(len(y_all), dtype=float)

    for tr_idx, va_idx in cv.split(X, y_all):
        X_tr_real, y_tr = X.iloc[tr_idx].copy(), y_all[tr_idx]
        X_va_real, y_va = X.iloc[va_idx].copy(), y_all[va_idx]

        pre = build_feature_pipeline()
        pre.fit(X_tr_real, y_tr)

        if cfg.augment:
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
        sample_weights = base_weights * np.where(is_synth == 1, cfg.synth_weight, 1.0)

        # ---- 방법 A: 투기등급 표본 가중치 추가 상향 ----
        if cfg.speculative_extra_weight != 1.0:
            spec_mask = np.isin(y_tr_aug, list(spec_class_ids))
            sample_weights = sample_weights * np.where(spec_mask, cfg.speculative_extra_weight, 1.0)

        constraints = _build_monotone_constraints(pre, FEATURE_COLS)
        model = make_model_custom(cfg, constraints)
        model.fit(X_tr, y_tr_aug, sample_weight=sample_weights,
                  eval_set=(X_va, y_va), early_stopping_rounds=100)

        y_pred = np.clip(np.rint(model.predict(X_va)), 0, len(label2id) - 1).astype(int)

        # ---- 방법 C: 투자/투기 이진 게이트로 저위험 오판 보정 ----
        if cfg.use_gate:
            if not _HAS_CATBOOST_CLF:
                raise ImportError("CatBoostClassifier가 필요합니다 (catboost 패키지에 포함).")
            y_tr_bin = np.array([0 if is_investment_grade(id2label_int[v]) else 1 for v in y_tr_aug])
            gate = CatBoostClassifier(
                iterations=1000, learning_rate=0.05, depth=4,
                random_seed=cfg.model_seed, verbose=False, allow_writing_files=False,
                auto_class_weights="Balanced",
            )
            gate.fit(X_tr, y_tr_bin, sample_weight=np.where(is_synth == 1, cfg.synth_weight, 1.0))
            spec_proba = gate.predict_proba(X_va)[:, 1]
            gate_spec_proba[va_idx] = spec_proba

            flagged_spec = spec_proba >= cfg.gate_threshold
            currently_investment = np.array([is_investment_grade(id2label_int[v]) for v in y_pred])
            override_mask = flagged_spec & currently_investment
            if spec_cutoff_notch is not None:
                y_pred = y_pred.copy()
                y_pred[override_mask] = spec_cutoff_notch

        y_oof[va_idx] = y_pred

    return y_oof, gate_spec_proba, n_splits


# ──────────────────────────────────────────────
# 지표 계산 (analyze_oof.py의 summarize()와 동일한 정의)
# ──────────────────────────────────────────────
def compute_metrics(y_all: np.ndarray, y_oof: np.ndarray, id2label: dict) -> dict:
    id2label_int = {int(k): v for k, v in id2label.items()}
    y_true_label = [id2label_int[i] for i in y_all]
    y_pred_label = [id2label_int[i] for i in y_oof]

    true_inv = np.array([is_investment_grade(l) for l in y_true_label])
    pred_inv = np.array([is_investment_grade(l) for l in y_pred_label])

    tp = int(np.sum(true_inv & pred_inv))
    fn = int(np.sum(true_inv & ~pred_inv))
    fp = int(np.sum(~true_inv & pred_inv))   # = 위험 과소평가 건수 (실제투기 -> 예측투자)
    tn = int(np.sum(~true_inv & ~pred_inv))

    qwk = cohen_kappa_score(y_all, y_oof, weights="quadratic")

    return {
        "qwk": qwk,
        "tp": tp, "fn": fn, "fp": fp, "tn": tn,
        "investment_precision": tp / (tp + fp) if (tp + fp) > 0 else float("nan"),
        "investment_recall": tp / (tp + fn) if (tp + fn) > 0 else float("nan"),
        "speculative_precision": tn / (tn + fn) if (tn + fn) > 0 else float("nan"),
        "speculative_recall": tn / (tn + fp) if (tn + fp) > 0 else float("nan"),
        "risk_underestimation_count": fp,  # 실제 투기등급을 투자등급으로 오판한 건수
        "n": len(y_all),
    }


def mean_std_table(rows: list, group_col: str, value_cols: list) -> pd.DataFrame:
    df = pd.DataFrame(rows)
    agg = df.groupby(group_col)[value_cols].agg(["mean", "std"])
    agg.columns = [f"{c}_{stat}" for c, stat in agg.columns]
    return agg.reset_index()
