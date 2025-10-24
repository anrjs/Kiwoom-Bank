# -*- coding: utf-8 -*-
import numpy as np
from typing import Optional

def quadratic_weighted_kappa(y_true, y_pred, n_classes: Optional[int]=None):
    """Compute QWK between integer ratings y_true and y_pred (0..K-1)."""
    y_true = np.asarray(y_true, dtype=int)
    y_pred = np.asarray(y_pred, dtype=int)
    if n_classes is None:
        n_classes = max(y_true.max(), y_pred.max()) + 1
    # Confusion matrix O
    O = np.zeros((n_classes, n_classes), dtype=float)
    for a, b in zip(y_true, y_pred):
        if 0 <= a < n_classes and 0 <= b < n_classes:
            O[a, b] += 1
    # Expected matrix E
    act_hist = O.sum(axis=1)
    pred_hist = O.sum(axis=0)
    E = np.outer(act_hist, pred_hist) / O.sum() if O.sum() > 0 else np.zeros_like(O)
    # Weight matrix W (quadratic)
    W = np.zeros((n_classes, n_classes), dtype=float)
    for i in range(n_classes):
        for j in range(n_classes):
            W[i, j] = ((i - j) ** 2) / ((n_classes - 1) ** 2) if n_classes > 1 else 0.0
    # QWK
    num = (W * O).sum()
    den = (W * E).sum() if E.sum() > 0 else 1.0
    return 1.0 - num/den if den != 0 else 0.0
