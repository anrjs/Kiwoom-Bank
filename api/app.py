# api/app.py
import sys
import asyncio
import os
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Tuple

from dotenv import load_dotenv
from fastapi import FastAPI, Query, Body, HTTPException
from fastapi.concurrency import run_in_threadpool
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field



app = FastAPI(title="Kiwoom Financial Metrics API")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

if sys.platform.startswith("win"):
    try:
        asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())
    except Exception:
        pass

ROOT_DIR = Path(__file__).resolve().parents[1]
load_dotenv(dotenv_path=ROOT_DIR / ".env")

# ── internal imports ──────────────────────────────────────────
from kiwoom_finance.batch import get_metrics_for_codes
from kiwoom_finance.dart_client import IdentifierType, find_corp, init_dart
from nice_rating import crawler as nice_crawler
from news_analytics.service import analyze_news_for_query
from non_financial import extract_non_financial_core
from non_financial.industry_credit_model import evaluate_company, classify_industry

from api.features import router as features_router, FeaturePayload, save_features as _save_features
from api.credit_model import (
    predict_for_company,
    CreditModelNotReady,
)
app.include_router(features_router)  # /features/*

@app.on_event("startup")
def _startup():
    init_dart()
    try:
        import news_analytics.sentiment_finbert as _warm
        _ = getattr(_warm, "MODEL_READY", True)
        print("✅ FinBERT ready.")
    except Exception as e:
        print("⚠️ FinBERT warm-up skipped:", e)
    print("🔑 DART_API_KEY prefix:", (os.getenv("DART_API_KEY") or "")[:6])
    print("✅ DART ready.")

# ── models ────────────────────────────────────────────────────
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
    news_count: int
    aggregate: Dict[str, float]
    news_sentiment_score: float
    sentiment_volatility: float
    positive_ratio: float
    negative_ratio: float
    recency_weight_mean: float
    items: List[Dict[str, Any]]

class NewsSentimentResponse(BaseModel):
    results: List[NewsSentimentItem]
    meta: Dict[str, Any]

class NonFinancialCoreItem(BaseModel):
    company: str
    core: Dict[str, Any]
    score: Dict[str, Any] | None = None
    error: str | None = None

class NonFinancialResponse(BaseModel):
    results: List[NonFinancialCoreItem]
    meta: Dict[str, Any]

# ── utils ─────────────────────────────────────────────────────
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

# ── endpoints ─────────────────────────────────────────────────
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

@app.post("/credit")
async def credit_ratings_alias(payload: Dict[str, Any] = Body(...)):
    queries = payload.get("queries") or []
    if not isinstance(queries, list) or not queries:
        raise HTTPException(status_code=400, detail="queries must be a non-empty list")
    ratings_by_query, skipped = await _crawl_credit_ratings_async(queries)
    return {
        "queries": queries,
        "ratings": ratings_by_query,
        "skipped": [{"query": q, "why": why} for (q, why) in skipped],
        "meta": {"ts": datetime.utcnow().isoformat() + "Z"},
    }

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
        meta={"generated_at": datetime.utcnow().isoformat() + "Z", "limit": limit, "days": days, "model": "FinBERT + OpenAI translate"},
    )

@app.get("/credit/nonfinancial", response_model=NonFinancialResponse)
async def non_financial(
    identifiers: List[str] = Query(..., alias="companies"),
    year: int | None = Query(None),
    industry_override: str | None = Query(None),
    include_score: bool = Query(True),
):
    out: List[NonFinancialCoreItem] = []
    for name in identifiers:
        try:
            core = await run_in_threadpool(extract_non_financial_core, name, year, industry_override)
            item = NonFinancialCoreItem(company=name, core=core)
            if include_score and core.get("corp_code"):
                model_inputs = {k: core.get(k) for k in core.keys()}
                res = await run_in_threadpool(evaluate_company, name, model_inputs, industry_override, None, industry_override)
                item.score = res
            out.append(item)
        except Exception as e:
            out.append(NonFinancialCoreItem(company=name, core={}, error=str(e)))

    return NonFinancialResponse(results=out, meta={"ts": datetime.utcnow().isoformat() + "Z", "year": year, "include_score": include_score})

@app.get("/nonfinancial", response_model=NonFinancialResponse)
async def non_financial_alias(
    company: str = Query(...),
    include_score: bool = Query(True),
    year: int | None = Query(None),
    industry_override: str | None = Query(None),
):
    return await non_financial(identifiers=[company], year=year, industry_override=industry_override, include_score=include_score)


@app.post("/analyze")
async def analyze_credit(payload: Dict[str, Any] = Body(...)):
    name = (payload or {}).get("company_name")
    if not name:
        raise HTTPException(status_code=400, detail="company_name is required")

    try:
        prediction = await run_in_threadpool(predict_for_company, name)
    except FileNotFoundError as exc:
        # CSV 자체가 없는 경우
        raise HTTPException(status_code=404, detail=str(exc))
    except CreditModelNotReady as exc:
        # model.joblib, label_mapping.json 없을 때
        raise HTTPException(status_code=503, detail=str(exc))
    except ValueError as exc:
        # 컬럼 불일치/파싱 오류 등 사용자가 조치 가능한 문제
        raise HTTPException(status_code=422, detail=f"invalid features: {exc}")
    except Exception as exc:
        # 마지막 안전망: 원인 표시
        raise HTTPException(status_code=500, detail=f"credit analysis failed: {exc}")

    prediction.setdefault("company", name)
    prediction["updated_at"] = datetime.utcnow().isoformat() + "Z"
    return prediction

# 프론트 호환: POST /comp_features  → 내부 /features/save 사용
@app.post("/comp_features")
def comp_features_alias(payload: FeaturePayload):
    print("➡️ [/comp_features] 프론트 호환 호출")
    return _save_features(payload)

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

from api.credit_model import find_latest_feature_file, load_feature_rows, FEATURE_COLS

@app.get("/analyze/diag")
def analyze_diagnose(company: str):
    p = find_latest_feature_file(company)
    if not p:
        raise HTTPException(status_code=404, detail=f"No feature CSV found for '{company}'")
    df = load_feature_rows(p)
    return {
        "company": company,
        "file": str(p),
        "shape": df.shape,
        "columns": list(df.columns),
        "required_FEATURE_COLS": FEATURE_COLS,
        "head": df.head(3).to_dict(orient="records"),
    }