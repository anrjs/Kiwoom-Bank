import time
import requests
from urllib.parse import urlparse
from datetime import datetime, timezone
from typing import List, Dict


from config import NAVER_CLIENT_ID, NAVER_CLIENT_SECRET, REQUEST_TIMEOUT, SLEEP_BETWEEN_CALLS, NEWS_PER_PAGE


NAVER_NEWS_URL = "https://openapi.naver.com/v1/search/news.json"


HEADERS = {
"X-Naver-Client-Id": NAVER_CLIENT_ID or "",
"X-Naver-Client-Secret": NAVER_CLIENT_SECRET or "",
}




def get_naver_news(query: str, display: int = NEWS_PER_PAGE, start: int = 1, sort: str = "sim") -> List[Dict]:
    params = {"query": query, "display": display, "start": start, "sort": sort}
    r = requests.get(NAVER_NEWS_URL, headers=HEADERS, params=params, timeout=REQUEST_TIMEOUT)
    r.raise_for_status()
    data = r.json().get("items", [])
    # pubDate 예시: 'Mon, 23 Sep 2024 10:30:00 +0900'
    # 그대로 전달하고, 가중치 계산은 preprocess에서 처리
    return data




def collect_news(query: str, max_pages: int, per_page: int) -> List[Dict]:
    all_items = []
    start = 1
    for _ in range(max_pages):
        items = get_naver_news(query, display=per_page, start=start, sort="sim")
        if not items:
            break
        all_items.extend(items)
        start += per_page
        time.sleep(SLEEP_BETWEEN_CALLS)
    return all_items