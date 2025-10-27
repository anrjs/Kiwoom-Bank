# api/features.py
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from pathlib import Path
from datetime import datetime
import pandas as pd

# /features 로 시작하는 서브 라우터
router = APIRouter(prefix="/features", tags=["features"])

# 프로젝트 루트(…/kiwoombank) 기준 저장 폴더
PROJECT_ROOT = Path(__file__).resolve().parents[1]
SAVE_DIR = PROJECT_ROOT / "comp_features"
SAVE_DIR.mkdir(parents=True, exist_ok=True)

class FeaturePayload(BaseModel):
    company: str
    debt_ratio: float | None = None
    roa: float | None = None
    total_asset_growth_rate: float | None = None
    cfo_to_total_debt: float | None = None
    current_ratio: float | None = None
    quick_ratio: float | None = None
    news_sentiment_score: float | None = None
    news_count: int | None = None
    sentiment_volatility: float | None = None
    positive_ratio: float | None = None
    negative_ratio: float | None = None
    recency_weight_mean: float | None = None
    business_report_text_score: float | None = None
    public_credit_rating: str | None = None

@router.get("/ping")
def ping():
    files = sorted([p.name for p in SAVE_DIR.glob("*.csv")])
    return {
        "ok": True,
        "cwd": str(Path.cwd()),
        "save_dir": str(SAVE_DIR),
        "exists": SAVE_DIR.exists(),
        "count": len(files),
        "items": files[:50],
    }

@router.get("/list")
def list_files():
    items = [{"name": p.name, "path": str(p)} for p in sorted(SAVE_DIR.glob("*.csv"))]
    return {"ok": True, "dir": str(SAVE_DIR), "items": items}

@router.post("/save")
def save_features(payload: FeaturePayload):
    try:
        ts = datetime.now().strftime("%Y%m%d_%H%M%S")
        safe = payload.company.replace("/", "_").replace("\\", "_")
        fpath = SAVE_DIR / f"{safe}_{ts}.csv"

        row = {
            "debt_ratio": payload.debt_ratio,
            "roa": payload.roa,
            "total_asset_growth_rate": payload.total_asset_growth_rate,
            "cfo_to_total_debt": payload.cfo_to_total_debt,
            "current_ratio": payload.current_ratio,
            "quick_ratio": payload.quick_ratio,
            "news_sentiment_score": payload.news_sentiment_score,
            "news_count": payload.news_count,
            "sentiment_volatility": payload.sentiment_volatility,
            "positive_ratio": payload.positive_ratio,
            "negative_ratio": payload.negative_ratio,
            "recency_weight_mean": payload.recency_weight_mean,
            "business_report_text_score": payload.business_report_text_score,
            "public_credit_rating": payload.public_credit_rating,
        }
        df = pd.DataFrame([row], index=[payload.company])
        # 컬럼 순서 고정 (모델과 동일)
        df = df[
            [
                "debt_ratio",
                "roa",
                "total_asset_growth_rate",
                "cfo_to_total_debt",
                "current_ratio",
                "quick_ratio",
                "news_sentiment_score",
                "news_count",
                "sentiment_volatility",
                "positive_ratio",
                "negative_ratio",
                "recency_weight_mean",
                "business_report_text_score",
                "public_credit_rating",
            ]
        ]
        df.to_csv(fpath, encoding="utf-8-sig")
        return {"ok": True, "path": str(fpath)}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
