# augment.py
from dataclasses import dataclass
from typing import Tuple, Dict
import numpy as np
import pandas as pd

@dataclass
class AugmentConfig:
    target_per_class: int = 30
    max_synth_ratio: float = 1.5
    mixup_alpha: float = 0.4
    mixup_ratio: float = 0.6
    jitter_scale: float = 0.10
    lower_q: float = 0.005
    upper_q: float = 0.995
    seed: int = 42

def _compute_bounds(X: pd.DataFrame, lo_q: float, hi_q: float) -> Tuple[pd.Series, pd.Series]:
    lo = X.quantile(lo_q)
    hi = X.quantile(hi_q)
    return lo, hi

def _clip_to_bounds(X: pd.DataFrame, lo: pd.Series, hi: pd.Series) -> pd.DataFrame:
    return X.clip(lower=lo, upper=hi, axis='columns')

def _cov_jitter(Xc: pd.DataFrame, n_new: int, scale: float, rng: np.random.Generator) -> pd.DataFrame:
    if len(Xc) == 0 or n_new <= 0:
        return pd.DataFrame(columns=Xc.columns)
    mu = Xc.mean(axis=0).values
    S = np.cov(Xc.values, rowvar=False)
    if not np.all(np.isfinite(S)):
        S = np.nan_to_num(S, nan=0.0, posinf=0.0, neginf=0.0)
    d = S.shape[0]
    S = S + (1e-6 * np.trace(S) / d) * np.eye(d)
    try:
        L = np.linalg.cholesky(S)
    except np.linalg.LinAlgError:
        L = np.diag(np.sqrt(np.maximum(np.diag(S), 1e-6)))
    rows = []
    idx = rng.integers(0, len(Xc), size=n_new)
    for i in idx:
        base = Xc.iloc[i].values
        eps = rng.normal(size=d)
        x_new = base + scale * (L @ eps)
        rows.append(x_new)
    return pd.DataFrame(rows, columns=Xc.columns)

def _mixup_pairs(X: pd.DataFrame, y: np.ndarray, n_new: int, alpha: float,
                 rng: np.random.Generator, prefer_adjacent: bool=True) -> Tuple[pd.DataFrame, np.ndarray]:
    if n_new <= 0:
        return pd.DataFrame(columns=X.columns), np.empty((0,), dtype=float)
    y = y.astype(float)
    labels = np.unique(y)
    rows = []
    ys = []
    for _ in range(n_new):
        if prefer_adjacent and len(labels) > 1 and rng.random() < 0.8:
            c = int(rng.choice(labels))
            neigh = [v for v in labels if abs(v - c) <= 1 and v != c]
            j = int(rng.choice(neigh)) if neigh else int(rng.choice(labels))
            i_idx = np.where(y == c)[0]
            j_idx = np.where(y == j)[0]
            i = int(rng.choice(i_idx))
            j = int(rng.choice(j_idx))
        else:
            i, j = rng.choice(len(X), size=2, replace=True)
        lam = rng.beta(alpha, alpha)
        xi = X.iloc[i].values
        xj = X.iloc[j].values
        yi = y[i]; yj = y[j]
        x_new = lam * xi + (1.0 - lam) * xj
        y_new = lam * yi + (1.0 - lam) * yj
        rows.append(x_new); ys.append(y_new)
    return pd.DataFrame(rows, columns=X.columns), np.array(ys, dtype=float)

def augment_dataset(
    X: pd.DataFrame,
    y: np.ndarray,
    cfg: AugmentConfig
) -> Tuple[pd.DataFrame, np.ndarray, Dict[int, int]]:
    rng = np.random.default_rng(cfg.seed)
    y = y.astype(int)
    lo, hi = _compute_bounds(X, cfg.lower_q, cfg.upper_q)
    X_aug_list = [X.copy()]
    y_aug_list = [y.copy()]
    class_new_counts: Dict[int, int] = {}
    classes = np.unique(y)
    total_cap = int(cfg.max_synth_ratio * len(X))
    made = 0
    for c in classes:
        idx = np.where(y == c)[0]
        n_now = len(idx)
        n_target = max(cfg.target_per_class, n_now)
        n_need = max(0, n_target - n_now)
        if n_need == 0:
            class_new_counts[c] = 0
            continue
        n_mix = int(round(cfg.mixup_ratio * n_need))
        n_jit = n_need - n_mix
        Xm, ym = _mixup_pairs(X, y, n_mix, cfg.mixup_alpha, rng, prefer_adjacent=True)
        Xc = X.iloc[idx]
        Xj = _cov_jitter(Xc, n_jit, cfg.jitter_scale, rng)
        yj = np.full((len(Xj),), float(c), dtype=float)
        X_new = pd.concat([Xm, Xj], axis=0, ignore_index=True)
        y_new = np.concatenate([ym, yj], axis=0)
        X_new = _clip_to_bounds(X_new, lo, hi)
        X_aug_list.append(X_new)
        y_aug_list.append(y_new.astype(int))
        class_new_counts[c] = int(len(X_new))
        made += int(len(X_new))
        if made >= total_cap:
            break
    X_aug = pd.concat(X_aug_list, axis=0, ignore_index=True)
    y_aug = np.concatenate(y_aug_list, axis=0)
    return X_aug, y_aug, class_new_counts
