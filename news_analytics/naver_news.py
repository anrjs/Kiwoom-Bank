# news_analytics/naver_news.py
from __future__ import annotations
import time
import html
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional
import requests

from .config import (
    NAVER_CLIENT_ID,
    NAVER_CLIENT_SECRET,
    REQUEST_TIMEOUT,
    SLEEP_BETWEEN_CALLS,
    NEWS_PER_PAGE,
)

KST = timezone(timedelta(hours=9))

def _parse_pubdate(s: str) -> str:
    """
    Naver API pubDate 예: 'Tue, 22 Oct 2024 11:12:00 +0900'
    ISO-문자열(YYYY-mm-dd HH:MM) 로 변환하여 반환(KST 기준)
    """
    try:
        # RFC822 스타일
        dt = datetime.strptime(s, "%a, %d %b %Y %H:%M:%S %z")
        dt = dt.astimezone(KST)
        return dt.strftime("%Y-%m-%d %H:%M")
    except Exception:
        # 실패 시 원문 리턴
        return s

def search_news(query: str, limit: int = 20, days: int = 3) -> List[Dict[str, Any]]:
    """
    Naver OpenAPI로 뉴스 검색.
    반환 필드: title, link, press, published_at, summary
    """
    if not NAVER_CLIENT_ID or not NAVER_CLIENT_SECRET:
        # 키가 없을 경우 빈 결과 반환(명시적)
        return []

    endpoint = "https://openapi.naver.com/v1/search/news.json"
    headers = {
        "X-Naver-Client-Id": NAVER_CLIENT_ID,
        "X-Naver-Client-Secret": NAVER_CLIENT_SECRET,
    }

    # 네이버는 페이지네이션: start(1..), display(<=100)
    per_page = min(NEWS_PER_PAGE, 100)
    remain = max(1, limit)
    start = 1

    out: List[Dict[str, Any]] = []
    cutoff = datetime.now(tz=KST) - timedelta(days=days)

    while remain > 0:
        display = min(per_page, remain)
        params = {"query": query, "display": display, "start": start, "sort": "date"}
        resp = requests.get(endpoint, headers=headers, params=params, timeout=REQUEST_TIMEOUT)
        resp.raise_for_status()
        data = resp.json()
        items = data.get("items", []) or []

        for it in items:
            title = html.unescape(it.get("title", "")).replace("<b>", "").replace("</b>", "")
            link = it.get("link") or ""
            press = it.get("originallink") or ""  # 네이버는 언론사명 별도 필드가 없을 수 있음
            pub = _parse_pubdate(it.get("pubDate", ""))

            # 최근 days 필터(가능한 경우)
            try:
                dt = datetime.strptime(pub, "%Y-%m-%d %H:%M")
                dt = dt.replace(tzinfo=KST)
                if dt < cutoff:
                    continue
            except Exception:
                pass

            out.append({
                "title": title,
                "link": link,
                "press": press,
                "published_at": pub,
                "summary": "",
            })

        remain -= len(items)
        start += display
        if not items:
            break
        time.sleep(SLEEP_BETWEEN_CALLS)

    # 상한 적용
    return out[:limit]
