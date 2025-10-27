# news_analytics/sentiment_finbert.py
from __future__ import annotations
from typing import Any, Dict, List
import math

# transformers, torch는 느리니 지연 로드
_finbert = None

from .config import (
    FINBERT_MODEL,
    OPENAI_API_KEY,
    OPENAI_TRANSLATE_MODEL,
    OPENAI_TRANSLATE_TEMPERATURE,
    OPENAI_TRANSLATE_BATCH,
)

def _ensure_finbert():
    global _finbert
    if _finbert is None:
        from transformers import pipeline  # lazy import
        _finbert = pipeline(
            "text-classification",
            model=FINBERT_MODEL,
            return_all_scores=True,
            truncation=True
        )
    return _finbert

def _translate_ko_to_en_batch(texts: List[str]) -> List[str]:
    """
    OpenAI 키가 있으면 간단히 번역. 없으면 원문 그대로 사용.
    번역 실패 시에도 원문 유지.
    """
    if not OPENAI_API_KEY:
        return texts

    try:
        from openai import OpenAI
        client = OpenAI(api_key=OPENAI_API_KEY)
    except Exception:
        return texts

    out: List[str] = []
    batch = max(1, OPENAI_TRANSLATE_BATCH)
    for i in range(0, len(texts), batch):
        chunk = texts[i:i+batch]
        try:
            prompt = (
                "Translate the following Korean headlines to concise English, "
                "preserving financial tone and meaning. Return one translation per line in order.\n\n" +
                "\n".join(f"- {t}" for t in chunk)
            )
            resp = client.chat.completions.create(
                model=OPENAI_TRANSLATE_MODEL,
                temperature=float(OPENAI_TRANSLATE_TEMPERATURE),
                messages=[{"role": "user", "content": prompt}],
            )
            content = (resp.choices[0].message.content or "").strip()
            lines = [l.strip("- ").strip() for l in content.splitlines() if l.strip()]
            if len(lines) >= len(chunk):
                out.extend(lines[:len(chunk)])
            else:
                # 라인 수 불일치: 안전하게 원문 사용
                out.extend(chunk)
        except Exception:
            out.extend(chunk)

    return out

def analyze_texts_ko(titles_ko: List[str]) -> List[Dict[str, float]]:
    """
    한국어 제목 리스트 → (번역) → FinBERT 확률 {POSITIVE, NEGATIVE, NEUTRAL}
    """
    if not titles_ko:
        return []

    titles_en = _translate_ko_to_en_batch(titles_ko)
    clf = _ensure_finbert()

    results: List[Dict[str, float]] = []
    for t in titles_en:
        scores = clf(t)  # [{'label':'Positive','score':0.7}, ...]
        # FinBERT 라벨 표준화
        dist = {"POSITIVE": 0.0, "NEGATIVE": 0.0, "NEUTRAL": 0.0}
        for d in scores[0] if isinstance(scores, list) else scores:
            lab = (d["label"] or "").upper()
            if "POS" in lab:
                dist["POSITIVE"] = float(d["score"])
            elif "NEG" in lab:
                dist["NEGATIVE"] = float(d["score"])
            else:
                dist["NEUTRAL"] = float(d["score"])
        # 정규화(합이 1이 되도록)
        s = sum(dist.values()) or 1.0
        for k in dist:
            dist[k] = dist[k] / s
        results.append(dist)
    return results

def weighted_aggregate(per_item: List[Dict[str, float]], weights: List[float]) -> Dict[str, float]:
    """
    항목별 확률과 가중치를 받아 가중평균 확률 분포 반환.
    """
    if not per_item:
        return {"POSITIVE": 0.0, "NEGATIVE": 0.0, "NEUTRAL": 1.0}
    if not weights or len(weights) != len(per_item):
        weights = [1.0] * len(per_item)

    acc = {"POSITIVE": 0.0, "NEGATIVE": 0.0, "NEUTRAL": 0.0}
    wsum = 0.0
    for d, w in zip(per_item, weights):
        acc["POSITIVE"] += d.get("POSITIVE", 0.0) * w
        acc["NEGATIVE"] += d.get("NEGATIVE", 0.0) * w
        acc["NEUTRAL"]  += d.get("NEUTRAL",  0.0) * w
        wsum += w
    if wsum <= 0:
        wsum = 1.0
    for k in acc:
        acc[k] = acc[k] / wsum
    # 재정규화 안전장치
    s = sum(acc.values()) or 1.0
    for k in list(acc.keys()):
        acc[k] = acc[k] / s
        acc["positive_ratio"] = acc.get("POSITIVE", 0.0)
        acc["negative_ratio"] = acc.get("NEGATIVE", 0.0)
        acc["neutral_ratio"] = acc.get("NEUTRAL", 0.0)
    return acc
