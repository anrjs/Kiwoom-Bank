import sys
import asyncio
import os
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Tuple

from dotenv import load_dotenv
from fastapi import FastAPI, Query
from fastapi.concurrency import run_in_threadpool
from pydantic import BaseModel, Field

# ★ DART 재무
from kiwoom_finance.batch import get_metrics_for_codes
from kiwoom_finance.dart_client import IdentifierType, find_corp, init_dart

# ★ nice_rating 크롤러(wrapper)
from nice_rating import crawler as nice_crawler

# ★ 뉴스 감성분석 서비스
from news_analytics.service import analyze_news_for_query

# ★ 비재무(공시기반) 스코어
from non_financial import extract_non_financial_core
from non_financial.industry_credit_model import evaluate_company, classify_industry

from fastapi.middleware.cors import CORSMiddleware

app = FastAPI(title="Kiwoom Financial Metrics API")

# ⬇️ 프론트 도메인/포트에 맞춰 수정하세요. (개발 중엔 "*"도 가능)
app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost:3000",
        "http://127.0.0.1:3000",
        "http://<프론트PC-IP>:3000",
        "http://<프론트-도메인>",    # 배포 시
    ],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ──────────────────────────────────────────────────────────────
if sys.platform.startswith("win"):
    try:
        asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())
    except Exception:
        pass

ROOT_DIR = Path(__file__).resolve().parents[1]
load_dotenv(dotenv_path=ROOT_DIR / ".env")

# ──────────────────────────────────────────────────────────────
@app.on_event("startup")
def _startup():
    init_dart()
    # FinBERT warm-up (선택)
    try:
        import news_analytics.sentiment_finbert as _warm
        _ = getattr(_warm, "MODEL_READY", True)
        print("✅ FinBERT ready.")
    except Exception as e:
        print("⚠️ FinBERT warm-up skipped:", e)

    print("🔑 DART_API_KEY prefix:", (os.getenv("DART_API_KEY") or "")[:6])
    print("✅ DART ready.")

# ──────────────────────────────────────────────────────────────
# Models
# ──────────────────────────────────────────────────────────────
class CompanySummaryItem(BaseModel):
    query: str
    stock_code: str | None = None
    corp_name: str | None = None
    metrics: Dict[str, Any] | None = None
    credit_rating: str | None = None
    notes: List[str] = Field(default_factory=list)
    error: str | None = None

class CompanySummaryResponse(BaseModel):
    results: List[CompanySummaryItem]
    errors: List[Dict[str, Any]]
    meta: Dict[str, Any]

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

# ★ 비재무
class NonFinancialCoreItem(BaseModel):
    company: str
    core: Dict[str, Any]
    score: Dict[str, Any] | None = None
    error: str | None = None

class NonFinancialResponse(BaseModel):
    results: List[NonFinancialCoreItem]
    meta: Dict[str, Any]

# ──────────────────────────────────────────────────────────────
async def _crawl_credit_ratings_async(queries: List[str]) -> Tuple[Dict[str, str], List[Tuple[str, str]]]:
    loop = asyncio.get_running_loop()
    def _run():
        df, skipped = nice_crawler.crawl_companies(queries)
        mapping: Dict[str, str] = {}
        if df is not None and "회사명" in df.columns and "등급" in df.columns:
            for _, row in df.iterrows():
                q = str(row["회사명"])
                rating = (str(row["등급"]) or "").strip()
                mapping[q] = rating
        return mapping, skipped
    return await loop.run_in_executor(None, _run)

# ──────────────────────────────────────────────────────────────
@app.get("/metrics", response_model=MetricsResponse)
def metrics(
    identifiers: List[str] = Query(..., alias="codes"),
    all_periods: bool = False,
    percent_format: bool = True,
    search_mode: IdentifierType = Query("auto"),
):
    df = get_metrics_for_codes(
        identifiers,
        latest_only=not all_periods,
        percent_format=percent_format,
        identifier_type=search_mode,
    )
    return {"data": df.reset_index().to_dict(orient="records")}

# ──────────────────────────────────────────────────────────────
@app.get("/credit/ratings")
async def credit_ratings(
    identifiers: List[str] = Query(..., alias="codes")
):
    ratings_by_query, skipped = await _crawl_credit_ratings_async(identifiers)
    return {
        "queries": identifiers,
        "ratings": ratings_by_query,
        "skipped": [{"query": q, "why": why} for (q, why) in skipped],
        "meta": {"ts": datetime.utcnow().isoformat() + "Z"},
    }

# ──────────────────────────────────────────────────────────────
@app.get("/news/sentiment", response_model=NewsSentimentResponse)
async def news_sentiment(
    identifiers: List[str] = Query(..., alias="codes"),
    search_mode: IdentifierType = Query("auto"),
    limit: int = 20,
    days: int = 3,
):
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

# ──────────────────────────────────────────────────────────────
# ★ 신규: 비재무(공시기반) 코어 & 스코어
# ──────────────────────────────────────────────────────────────
@app.get("/credit/nonfinancial", response_model=NonFinancialResponse)
async def non_financial(
    identifiers: List[str] = Query(..., alias="companies", description="회사명 리스트"),
    year: int | None = Query(None, description="사업연도(미입력시 직전년도)"),
    industry_override: str | None = Query(None, description="산업 수동 지정(선택)"),
    include_score: bool = Query(True, description="점수/등급 계산 포함 여부"),
):
    out: List[NonFinancialCoreItem] = []
    for name in identifiers:
        try:
            core = await run_in_threadpool(extract_non_financial_core, name, year, industry_override)
            item = NonFinancialCoreItem(company=name, core=core)
            if include_score and core.get("corp_code"):
                # 모델 입력값 구성
                model_inputs = {k: core.get(k) for k in core.keys()}
                res = await run_in_threadpool(
                    evaluate_company, name, model_inputs, industry_override, None, industry_override
                )
                item.score = res
            out.append(item)
        except Exception as e:
            out.append(NonFinancialCoreItem(company=name, core={}, error=str(e)))

    return NonFinancialResponse(
        results=out,
        meta={"ts": datetime.utcnow().isoformat() + "Z", "year": year, "include_score": include_score}
    )

# ──────────────────────────────────────────────────────────────
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
