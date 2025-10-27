# news_analytics/utils_scoring.py
from __future__ import annotations
from typing import Dict
import math
from typing import Dict, Sequence, List

from .config import POS_WEIGHT, NEG_WEIGHT

def _uniform_weights(n: int) -> List[float]:
    if n <= 0:
        return []
    return [1.0 / float(n)] * n

def normalize_weights(weights: Sequence[float]) -> List[float]:
    """Return weights scaled to sum to 1.0. Falls back to uniform when invalid."""
    if not weights:
        return []

    total = math.fsum(float(w) for w in weights)
    if not math.isfinite(total) or total <= 0.0:
        return _uniform_weights(len(weights))

    return [float(w) / total for w in weights]

def weighted_mean(values: Sequence[float], weights: Sequence[float]) -> float:
    if not values:
        return 0.0

    if not weights or len(weights) != len(values):
        norm = _uniform_weights(len(values))
    else:
        norm = normalize_weights(weights)

    return math.fsum(v * w for v, w in zip(values, norm))

def weighted_variance(values: Sequence[float], weights: Sequence[float]) -> float:
    if not values:
        return 0.0

    if not weights or len(weights) != len(values):
        norm = _uniform_weights(len(values))
    else:
        norm = normalize_weights(weights)

    mean = weighted_mean(values, norm)
    var = math.fsum(w * (v - mean) ** 2 for v, w in zip(values, norm))
    return var

def weighted_stddev(values: Sequence[float], weights: Sequence[float]) -> float:
    variance = weighted_variance(values, weights)
    if variance <= 0.0:
        return 0.0
    return math.sqrt(variance)
def credit_signal(agg: Dict[str, float]) -> float:
    """
    간단 점수화: (POS*pos_w - NEG*neg_w) * 100
    필요하면 더 정교한 맵핑/클리핑 로직 추가
    """
    pos = float(agg.get("POSITIVE", 0.0))
    neg = float(agg.get("NEGATIVE", 0.0))
    score = (pos * POS_WEIGHT - neg * NEG_WEIGHT) * 100.0
    # 클리핑
    if score > 100.0: score = 100.0
    if score < -100.0: score = -100.0
    return round(score, 2)
