import html
from urllib.parse import urlparse
from datetime import datetime, timezone
from typing import List, Dict, Tuple
import math


from config import SOURCE_WEIGHT, RECENCY_HALF_LIFE_DAYS




def clean_text(t: str) -> str:
    if not t:
        return ""
    t = t.replace("<b>", "").replace("</b>", "")
    t = html.unescape(t)
    return t.strip()




def parse_pubdate(pubdate_str: str) -> datetime:
# 예: 'Mon, 23 Sep 2024 10:30:00 +0900'
    try:
        return datetime.strptime(pubdate_str, "%a, %d %b %Y %H:%M:%S %z")
    except Exception:
        return datetime.now(timezone.utc)




def dedup_by_title_host(items: List[Dict]) -> List[Dict]:
    seen = set()
    out = []
    for it in items:
        title = clean_text(it.get("title", ""))
        host = urlparse(it.get("link", "")).netloc
        key = (title, host)
        if key in seen:
            continue
        seen.add(key)
        it["_clean_title"] = title
        it["_host"] = host
        out.append(it)
    return out




def recency_weight(pub_dt: datetime, now: datetime) -> float:
# 반감기 기반 가중치: w = 0.5 ** (delta_days / half_life)
    delta_days = max(0.0, (now - pub_dt).total_seconds() / 86400.0)
    return 0.5 ** (delta_days / float(RECENCY_HALF_LIFE_DAYS))




def source_weight(host: str) -> float:
    return SOURCE_WEIGHT.get(host, 1.0)




def build_inputs(items: List[Dict]) -> Tuple[List[str], List[float]]:
# 제목 + 요약을 합쳐서 입력 문장 구성, 가중치 계산
    now = datetime.now(timezone.utc)
    texts, weights = [], []
    for it in items:
        title = clean_text(it.get("title", ""))
        desc = clean_text(it.get("description", ""))
        text = (title + " " + desc).strip()
        if not text:
            continue
        pub = parse_pubdate(it.get("pubDate", ""))
        w = recency_weight(pub, now) * source_weight(it.get("_host", ""))
        texts.append(text)
        weights.append(w)
    return texts, weights