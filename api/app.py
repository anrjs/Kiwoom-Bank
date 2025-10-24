# api/app.py
import sys
import asyncio
import os
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Tuple

from dotenv import load_dotenv
from fastapi import FastAPI, Query
from fastapi.concurrency import run_in_threadpool
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field

# ★ DART 재무
from kiwoom_finance.batch import get_metrics_for_codes
from kiwoom_finance.dart_client import IdentifierType, find_corp, init_dart

# ★ nice_rating 크롤러(wrapper)
from nice_rating import crawler as nice_crawler

# ★ 뉴스 감성분석 서비스
from news_analytics.service import analyze_news_for_query


# ──────────────────────────────────────────────────────────────────────────────
# Windows 이벤트 루프 정책
# ──────────────────────────────────────────────────────────────────────────────
if sys.platform.startswith("win"):
    try:
        asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())
    except Exception:
        pass

# ──────────────────────────────────────────────────────────────────────────────
# .env
# ──────────────────────────────────────────────────────────────────────────────
ROOT_DIR = Path(__file__).resolve().parents[1]
load_dotenv(dotenv_path=ROOT_DIR / ".env")

app = FastAPI(title="Kiwoom Financial Metrics API")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

# ──────────────────────────────────────────────────────────────────────────────
# 서버 시작 시 DART 초기화(+선택: FinBERT 워밍업)
# ──────────────────────────────────────────────────────────────────────────────
@app.on_event("startup")
def _startup():
    init_dart()
    # FinBERT warm-up (선택)
    try:
        # 프로젝트 구조 기준(root/news_analytics/...)
        import news_analytics.sentiment_finbert as _warm  # noqa: F401
        print("✅ FinBERT ready.")
    except Exception as e:
        print("⚠️ FinBERT warm-up skipped:", e)

    print("🔑 DART_API_KEY prefix:", (os.getenv("DART_API_KEY") or "")[:6])
    print("✅ DART ready.")

# ──────────────────────────────────────────────────────────────────────────────
# 모델
# ──────────────────────────────────────────────────────────────────────────────
class MetricsResponse(BaseModel):
    data: List[Dict[str, Any]]

class NewsSentimentItem(BaseModel):
    query: str
    count: int
    aggregate: Dict[str, float]
    credit_score: float
    items: List[Dict[str, Any]]

class NewsSentimentResponse(BaseModel):
    results: List[NewsSentimentItem]
    meta: Dict[str, Any]

# ──────────────────────────────────────────────────────────────────────────────
# 내부: nice_rating 크롤러 비동기 실행(offload)
# ──────────────────────────────────────────────────────────────────────────────
async def _crawl_credit_ratings_async(queries: List[str]) -> Tuple[Dict[str, str], List[Tuple[str, str]]]:
    loop = asyncio.get_running_loop()

    def _run():
        df, skipped = nice_crawler.crawl_companies(queries)  # (DataFrame, skipped)
        mapping: Dict[str, str] = {}
        if df is not None and "회사명" in df.columns and "등급" in df.columns:
            for _, row in df.iterrows():
                q = str(row["회사명"])
                rating = (str(row["등급"]) or "").strip()
                mapping[q] = rating
        return mapping, skipped

    return await loop.run_in_executor(None, _run)

# ──────────────────────────────────────────────────────────────────────────────
# /metrics - 이름 또는 코드 기반 요약 지표 조회
# ──────────────────────────────────────────────────────────────────────────────
@app.get("/metrics", response_model=MetricsResponse)
def metrics(
    identifiers: List[str] = Query(..., alias="codes", description="종목명 또는 종목코드. 예: ?codes=삼성전자&codes=카카오"),
    all_periods: bool = False,
    percent_format: bool = True,
    search_mode: IdentifierType = Query("auto", description="검색 모드(auto|name|code)"),
):
    df = get_metrics_for_codes(
        identifiers,
        latest_only=not all_periods,
        percent_format=percent_format,
        identifier_type=search_mode,
    )
    return {"data": df.reset_index().to_dict(orient="records")}

# ──────────────────────────────────────────────────────────────────────────────
# /credit/ratings - 크롤러 직접 실행(테스트/디버그)
# ──────────────────────────────────────────────────────────────────────────────
@app.get("/credit/ratings")
async def credit_ratings(
    identifiers: List[str] = Query(..., alias="codes", description="회사/종목명 리스트")
):
    ratings_by_query, skipped = await _crawl_credit_ratings_async(identifiers)
    return {
        "queries": identifiers,
        "ratings": ratings_by_query,
        "skipped": [{"query": q, "why": why} for (q, why) in skipped],
        "meta": {"ts": datetime.utcnow().isoformat() + "Z"},
    }

# ──────────────────────────────────────────────────────────────────────────────
# /news/sentiment - 최신 뉴스 감성 점수(FinBERT+번역)
# ──────────────────────────────────────────────────────────────────────────────
@app.get("/news/sentiment", response_model=NewsSentimentResponse)
async def news_sentiment(
    identifiers: List[str] = Query(..., alias="codes", description="회사명 또는 종목코드"),
    search_mode: IdentifierType = Query("auto"),
    limit: int = 20,
    days: int = 3,
):
    # 필요 시 코드→정식회사명 매핑 로직 추가 가능. 여기선 식별자 그대로 사용.
    queries = identifiers

    results: List[NewsSentimentItem] = []
    for q in queries:
        data = await run_in_threadpool(analyze_news_for_query, q, limit, days)
        results.append(NewsSentimentItem(**data))

    return NewsSentimentResponse(
        results=results,
        meta={
            "generated_at": datetime.utcnow().isoformat() + "Z",
            "limit": limit,
            "days": days,
            "model": "FinBERT + OpenAI translate",
        },
    )

# ──────────────────────────────────────────────────────────────────────────────
# 디버그: 이름/코드 → 기업 식별
# ──────────────────────────────────────────────────────────────────────────────
@app.get("/_debug/find")
def debug_find(q: str, mode: IdentifierType = "auto"):
    c = find_corp(q, by=mode)
    if not c:
        return {"ok": False, "msg": "not found"}
    return {
        "ok": True,
        "corp_name": getattr(c, "corp_name", None),
        "corp_code": getattr(c, "corp_code", None),
        "stock_code": getattr(c, "stock_code", None),
    }
q
