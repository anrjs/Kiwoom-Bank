# -*- coding: utf-8 -*-
from dataclasses import dataclass
from typing import Dict, Tuple
import numpy as np
from typing import Optional, List  # 상단에 추가

# CatBoostRegressor 사용 (설치 필요: pip install catboost)
try:
    from catboost import CatBoostRegressor
    _HAS_CATBOOST = True
except ImportError:
    _HAS_CATBOOST = False
    CatBoostRegressor = None

from sklearn.utils.class_weight import compute_class_weight


@dataclass
class OrdinalRegressorConfig:
    iterations: int = 3000
    learning_rate: float = 0.03
    depth: int = 6
    l2_leaf_reg: float = 3.0
    random_state: int = 42
    verbose: bool = False
    monotone_constraints: Optional[List[int]] = None  # ✅ 추가


def make_model(cfg: OrdinalRegressorConfig):
    """
    CatBoostRegressor 모델 생성
    순서형 등급 문제이므로 RMSE 기반 회귀로 처리
    """
    if not _HAS_CATBOOST:
        raise ImportError(
            "CatBoost 라이브러리가 설치되어 있지 않습니다. "
            "다음 명령어를 실행하세요:\n\n    pip install catboost>=1.2.5,<2.0\n"
        )

    model = CatBoostRegressor(
        iterations=cfg.iterations,
        learning_rate=cfg.learning_rate,
        depth=cfg.depth,
        l2_leaf_reg=cfg.l2_leaf_reg,
        loss_function="RMSE",
        eval_metric="RMSE",
        random_seed=cfg.random_state,
        allow_writing_files=False,
        verbose=cfg.verbose,
        monotone_constraints=cfg.monotone_constraints  # ✅ 추가
    )
    return model


def make_sample_weights(y_train: np.ndarray) -> Tuple[np.ndarray, Dict[int, float]]:
    """
    클래스 불균형 대응용 sample_weight 계산
    CatBoostRegressor의 fit(..., sample_weight=weights)로 전달
    """
    valid_mask = ~np.isnan(y_train)
    classes = np.unique(y_train[valid_mask].astype(int))

    if len(classes) == 0:
        return None, {}

    # 클래스별 균형 weight 계산
    cw = compute_class_weight(
        class_weight="balanced",
        classes=classes,
        y=y_train[valid_mask].astype(int)
    )
    class_weights = {int(c): float(w) for c, w in zip(classes, cw)}

    # 각 샘플별 가중치 생성
    weights = np.array([
        class_weights.get(int(v), 1.0) if not np.isnan(v) else 1.0
        for v in y_train
    ], dtype=float)

    return weights, class_weights