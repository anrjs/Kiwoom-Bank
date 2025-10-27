# kiwoom_finance/news_analytics/service.py
from __future__ import annotations
import os
import time
import math
from datetime import datetime, timedelta, timezone
from statistics import fmean
from typing import Any, Dict, List, Optional, Tuple

from news_analytics import config

from . import naver_news
from . import preprocess
from .sentiment_finbert import analyze_texts_ko, weighted_aggregate
from .utils_scoring import credit_signal, normalize_weights, weighted_stddev

KST = timezone(timedelta(hours=9))

def _now_kst() -> datetime:
    return datetime.now(tz=KST)

def get_recent_news(
    query: str,
    limit: int = 20,
    days: int = 3,
) -> List[Dict[str, Any]]:
    """
    query에 대해 최근 days일 내 상위 limit개 뉴스를 반환.
    naver_news 모듈의 검색 함수를 그대로 감싸서, 필드 정규화(title, link, published_at, press 등)만 맞춰준다.
    """
    items: List[Dict[str, Any]] = naver_news.search_news(query=query, limit=limit, days=days)
    # 기대 필드 보정(없으면 기본값)
    out: List[Dict[str, Any]] = []
    for it in items:
        out.append({
            "title": it.get("title") or it.get("headline") or "",
            "link": it.get("link") or it.get("url") or "",
            "press": it.get("press") or it.get("source") or "",
            "published_at": it.get("published_at") or it.get("pubDate") or "",
            "summary": it.get("summary") or "",
        })
    return out

def _recency_weights(items: List[Dict[str, Any]], half_life_hours: float = 36.0) -> List[float]:
    """
    최신 뉴스에 더 큰 가중치를 주기 위한 half-life 가중.
    published_at 파싱 실패 시 기본 가중 1.0
    """
    now = _now_kst()
    w: List[float] = []
    for it in items:
        ts_raw = it.get("published_at", "")
        try:
            # 날짜 파서가 네 구현에 따라 다를 수 있어 여유롭게 시도
            # ISO / RFC / 'YYYY-MM-DD HH:MM' 모두 시도
            dt = None
            for fmt in ("%Y-%m-%d %H:%M", "%Y.%m.%d %H:%M", "%Y-%m-%dT%H:%M:%S%z"):
                try:
                    dt = datetime.strptime(ts_raw, fmt)
                    if dt.tzinfo is None:
                        dt = dt.replace(tzinfo=KST)
                    break
                except Exception:
                    continue
            if not dt:
                dt = now
        except Exception:
            dt = now
        diff_h = max(0.0, (now - dt).total_seconds() / 3600.0)
        # 설정값과 동기화하려면 config.RECENCY_HALF_LIFE_HOURS 사용 가능
        half_life = getattr(config, "RECENCY_HALF_LIFE_HOURS", half_life_hours)
        w.append(0.5 ** (diff_h / float(half_life)))
    return w if w else [1.0] * len(items)

def analyze_news_for_query(
    query: str,
    limit: int = 20,
    days: int = 3,
) -> Dict[str, Any]:
    """
    단일 질의(회사명/티커 등)에 대해:
    - 뉴스 수집
    - 전처리(선택)
    - 번역 + FinBERT 감성분석
    - 시계열 가중 평균
    - credit_signal 점수 산출
    """
    news = get_recent_news(query, limit=limit, days=days)
    titles = [n.get("title", "") for n in news]

    # 필요 시 제목 전처리(불용어 제거 등) – preprocess 모듈 사용
    if hasattr(preprocess, "clean_titles"):
        titles_clean = preprocess.clean_titles(titles)
    else:
        titles_clean = titles

    # FinBERT 분석(내부에서 OpenAI 번역 호출)
    per_item_scores = analyze_texts_ko(titles_clean)  # [{POSITIVE, NEGATIVE, NEUTRAL}, ...]

    # 가중(최근일수록 더 큰 가중)
    weights = _recency_weights(news)
    weights_for_stats = weights if weights and len(weights) == len(per_item_scores) else [1.0] * len(per_item_scores)

    if per_item_scores and len(weights) != len(per_item_scores):
        weights_for_stats = [1.0] * len(per_item_scores)
    else:
        weights_for_stats = weights

    normalized_weights = normalize_weights(weights_for_stats)
    recency_weight_mean = fmean(weights_for_stats) if weights_for_stats else 0.0

    agg = weighted_aggregate(per_item_scores, weights)

    sentiment_scores: List[float] = []
    for dist in per_item_scores[:len(weights_for_stats)]:
        pos = float(dist.get("POSITIVE", dist.get("positive_ratio", 0.0)))
        neg = float(dist.get("NEGATIVE", dist.get("negative_ratio", 0.0)))
        sentiment_scores.append(pos - neg)

    sentiment_volatility = (
        weighted_stddev(sentiment_scores, normalized_weights)
        if sentiment_scores and normalized_weights
        else 0.0
    )

    # 크레딧 신호 점수로 변환(네 utils_scoring 규칙)
    score = credit_signal(agg)

    positive_ratio = (
        agg.get("positive_ratio") if isinstance(agg, dict) else None
    )
    if positive_ratio is None:
        positive_ratio = float(agg.get("POSITIVE", 0.0))

    negative_ratio = (
        agg.get("negative_ratio") if isinstance(agg, dict) else None
    )
    if negative_ratio is None:
        negative_ratio = float(agg.get("NEGATIVE", 0.0))

    return {
        "query": query,
        "count": len(news),
        "news_count": len(news),
        "aggregate": agg,            # {"POSITIVE":0.x, "NEGATIVE":0.x, "NEUTRAL":0.x}
        "credit_score": score,
        "news_sentiment_score": score,
        "positive_ratio": positive_ratio,
        "negative_ratio": negative_ratio,
        "recency_weight_mean": recency_weight_mean,
        "sentiment_volatility": sentiment_volatility,     # float (예: (pos-neg)*100)
        "items": news,               # 원문 항목들(제목/링크/언론사/게시시각 등)
    }
