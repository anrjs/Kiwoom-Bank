# news_analytics/utils_scoring.py
from __future__ import annotations
from typing import Dict
from .config import POS_WEIGHT, NEG_WEIGHT

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
