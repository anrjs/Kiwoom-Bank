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

import glob
import re
import pandas as pd
import numpy as np

# NaN/inf JSON 직렬화 보강
from fastapi.encoders import jsonable_encoder
from fastapi.responses import JSONResponse

app = FastAPI(title="Kiwoom Financial Metrics API")

# CORS (개발 편의용 전체 허용)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

@app.get("/", tags=["meta"])
def root():
    return {
        "service": "Kiwoom Financial Metrics API",
        "status": "ok",
        "docs": "/docs",
        "redoc": "/redoc",
        "endpoints": [
            "/metrics",
            "/credit",
            "/news/sentiment",
            "/nonfinancial",
            "/analyze",
            "/analyze_many",
            "/aci/history",
            "/aci/history_predicted",
            "/analyze/diag",
            "/_debug/find",
        ],
    }

@app.get("/health", tags=["meta"])
def health():
    return {"ok": True}

# Windows 이벤트 루프 정책
if sys.platform.startswith("win"):
    try:
        asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())
    except Exception:
        pass

ROOT_DIR = Path(__file__).resolve().parents[1]
load_dotenv(dotenv_path=ROOT_DIR / ".env")

# ── 내부 모듈 ────────────────────────────────────────────────
from kiwoom_finance.batch import get_metrics_for_codes
from kiwoom_finance.dart_client import IdentifierType, find_corp, init_dart
from nice_rating import crawler as nice_crawler
from news_analytics.service import analyze_news_for_query
from non_financial import extract_non_financial_core
from non_financial.industry_credit_model import evaluate_company

from api.features import router as features_router, FeaturePayload, save_features as _save_features
from api.credit_model import (
    predict_for_company,
    CreditModelNotReady,
    find_latest_feature_file,
    load_feature_rows,
    FEATURE_COLS,
)

# /features/* 라우터 등록
app.include_router(features_router)

# ── Startup ──────────────────────────────────────────────────
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

# ── Pydantic 모델 ────────────────────────────────────────────
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

# ── 공용 유틸 ────────────────────────────────────────────────
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

# ── 엔드포인트 ────────────────────────────────────────────────
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
async def credit_ratings(identifiers: List[str] = Query(..., alias="codes")):
    ratings_by_query, skipped = await _crawl_credit_ratings_async(identifiers)
    return {
        "queries": identifiers,
        "ratings": ratings_by_query,
        "skipped": [{"query": q, "why": why} for (q, why) in skipped],
        "meta": {"ts": datetime.utcnow().isoformat() + "Z"},
    }

# 프런트 호환 POST /credit
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
    results: List[NewsSentimentItem] = []
    for q in identifiers:
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
    return NonFinancialResponse(
        results=out,
        meta={"ts": datetime.utcnow().isoformat() + "Z", "year": year, "include_score": include_score}
    )

# 프런트 호환 GET /nonfinancial?company=...
@app.get("/nonfinancial", response_model=NonFinancialResponse)
async def non_financial_alias(
    company: str = Query(...),
    include_score: bool = Query(True),
    year: int | None = Query(None),
    industry_override: str | None = Query(None),
):
    return await non_financial([company], year, industry_override, include_score)

# ACI 등급 추론 (모델 기반)
@app.post("/analyze")
async def analyze_credit(payload: Dict[str, Any] = Body(...)):
    name = (payload or {}).get("company_name")
    if not name:
        raise HTTPException(status_code=400, detail="company_name is required")
    try:
        prediction = await run_in_threadpool(predict_for_company, name)
    except FileNotFoundError as exc:
        # 특징 CSV가 없을 때 404 반환 (프런트에서 graceful 처리)
        raise HTTPException(status_code=404, detail=str(exc))
    except CreditModelNotReady as exc:
        raise HTTPException(status_code=503, detail=str(exc))
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=f"invalid features: {exc}")
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"credit analysis failed: {exc}")
    prediction.setdefault("company", name)
    prediction["updated_at"] = datetime.utcnow().isoformat() + "Z"
    return prediction

@app.post("/analyze_many")
async def analyze_many(payload: Dict[str, Any]):
    companies = payload.get("companies", [])
    if not companies:
        raise HTTPException(status_code=400, detail="companies list required")

    results = []
    for name in companies:
        try:
            res = await run_in_threadpool(predict_for_company, name)
            res["company"] = name
            res["updated_at"] = datetime.utcnow().isoformat() + "Z"
            results.append(res)
        except Exception as e:
            results.append({"company": name, "error": str(e)})
    return {"results": results, "count": len(results)}

# 프런트 호환: POST /comp_features → 내부 /features/save 사용
@app.post("/comp_features")
def comp_features_alias(payload: FeaturePayload):
    print("➡️ [/comp_features] 프론트 호환 호출")
    return _save_features(payload)

# 디버그: 종목 찾기
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

# 진단 엔드포인트 (NaN-safe JSON)
@app.get("/analyze/diag")
def analyze_diagnose(company: str):
    p = find_latest_feature_file(company)
    if not p:
        raise HTTPException(status_code=404, detail=f"No feature CSV found for '{company}'")
    df = load_feature_rows(p)
    # NaN/inf/-inf → None 치환
    df = df.replace([np.nan, np.inf, -np.inf], None)
    payload = {
        "company": company,
        "file": str(p),
        "shape": list(df.shape),
        "columns": list(df.columns),
        "required_FEATURE_COLS": FEATURE_COLS,
        "head": df.head(5).to_dict(orient="records"),
    }
    return JSONResponse(content=jsonable_encoder(payload))

# ── ACI 히스토리 (predicted 폴더) ────────────────────────────
_RATING_ORDER = [
    "AAA","AA+","AA","AA-",
    "A+","A","A-",
    "BBB+","BBB","BBB-",
    "BB+","BB","BB-",
    "B+","B","B-",
    "CCC","CC","C","D",
]

# 예측 등급이 들어 있을 수 있는 후보 컬럼들
_PRED_COLS = [
    "predicted_grade", "aci_predicted", "aci_grade",
    "predicted_rating", "aci_rating", "aci_grade_label", "grade",
    "public_credit_rating",  # 최후 보루
]

# 파일명: 회사명.YYYYMMDD.HHMMSS.csv
_PRED_NAME_RE = re.compile(r".*\.(\d{8})\.(\d{6})\.csv$", re.I)

def _pred_ts_from_name(path: str) -> int | None:
    m = _PRED_NAME_RE.match(Path(path).name)
    if not m:
        return None
    ymd, hms = m.group(1), m.group(2)
    try:
        dt = datetime.strptime(ymd + hms, "%Y%m%d%H%M%S")
        return int(dt.timestamp() * 1000)
    except Exception:
        return None

def _to_notch(grade: str) -> int | None:
    g = (grade or "").strip().upper()
    return _RATING_ORDER.index(g) if g in _RATING_ORDER else None

@app.get("/aci/history_predicted")
def aci_history_predicted(company: str = Query(..., description="회사명(예: 삼성전자)")):
    """
    credit_rating_project/predicted/{회사명}.YYYYMMDD.HHMMSS.csv 파일들을 읽어
    ACI 예측등급(label)과 notch(score), 타임스탬프(time)를 시계열로 반환.
    """
    pred_dir = ROOT_DIR / "credit_rating_project" / "predicted"
    if not pred_dir.exists():
        raise HTTPException(status_code=404, detail=f"predicted directory not found: {pred_dir}")

    def _safe(name: str) -> str:
        return name.replace("/", "_").replace("\\", "_")

    safe = _safe(company)
    # 공백이 포함된 파일명/미포함 파일명 모두 탐색
    patterns = [
        str(pred_dir / f"{safe}.*.csv"),
        str(pred_dir / f"{safe.replace(' ', '')}.*.csv"),
    ]
    files: list[str] = []
    for pat in patterns:
        files.extend(glob.glob(pat))

    if not files:
        # 파일이 없어도 라우트는 존재하므로 200 + 빈 배열 반환 (프론트에서 graceful 처리)
        return {"company": company, "points": []}

    points: list[dict] = []
    for fp in sorted(files):
        try:
            ts = _pred_ts_from_name(fp)
            if ts is None:
                ts = int(Path(fp).stat().st_mtime * 1000)  # 파일명 파싱 실패시 수정시각으로 대체

            # ⬇⬇ 인코딩 폴백: utf-8-sig → utf-8 → cp949
            df = None
            for enc in ("utf-8-sig", "utf-8", "cp949"):
                try:
                    df = pd.read_csv(fp, encoding=enc)
                    break
                except Exception:
                    continue
            if df is None:
                # 손상/인코딩 불일치 파일은 조용히 스킵
                continue

            label: str | None = None
            for col in _PRED_COLS:
                if col in df.columns and len(df[col].dropna()) > 0:
                    label = str(df[col].iloc[0]).strip()
                    if label:
                        break
            if not label:
                continue

            notch = _to_notch(label)
            if notch is None:
                continue

            points.append({"time": ts, "label": label, "score": notch})
        except Exception:
            # 손상/스키마 불일치 파일은 조용히 스킵
            continue

    points.sort(key=lambda x: x["time"])
    return {"company": company, "points": points}

# 🔁 /aci/history 에일리어스 (프런트가 이 경로를 호출해도 동작)
@app.get("/aci/history")
def aci_history(company: str = Query(..., description="회사명(예: 삼성전자)")):
    return aci_history_predicted(company)  # type: ignore[arg-type]