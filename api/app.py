# api/app.py
import sys, asyncio
if sys.platform.startswith("win"):
    try:
        asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())
    except Exception:
        pass

from fastapi import FastAPI, Query
from typing import List
from pydantic import BaseModel

from pathlib import Path
from dotenv import load_dotenv
import os

from kiwoom_finance.batch import get_metrics_for_codes
from kiwoom_finance.dart_client import IdentifierType, init_dart, find_corp

# ──────────────────────────────────────────────────────────────────────────────
# .env (프로젝트 루트) 명시 로드
# ──────────────────────────────────────────────────────────────────────────────
ROOT_DIR = Path(__file__).resolve().parents[1]
load_dotenv(dotenv_path=ROOT_DIR / ".env")

app = FastAPI(title="Kiwoom Financial Metrics API")


# ──────────────────────────────────────────────────────────────────────────────
# 서버 시작 시점에 DART 초기화 (키 미설정이면 즉시 예외 발생)
# ──────────────────────────────────────────────────────────────────────────────
@app.on_event("startup")
def _startup():
    init_dart()
    print("🔑 DART_API_KEY prefix:", (os.getenv("DART_API_KEY") or "")[:6])
    print("✅ DART ready.")


class MetricsResponse(BaseModel):
    data: list


@app.get("/metrics", response_model=MetricsResponse)
def metrics(
    identifiers: List[str] = Query(
        ...,
        alias="codes",
        description="종목명 또는 종목코드. 예: ?codes=삼성전자&codes=카카오",
    ),
    all_periods: bool = False,
    percent_format: bool = True,
    search_mode: IdentifierType = Query(
        "auto", description="검색 모드(auto|name|code)"
    ),
):
    df = get_metrics_for_codes(
        identifiers,
        latest_only=not all_periods,
        percent_format=percent_format,
        identifier_type=search_mode,
    )
    return {"data": df.reset_index().to_dict(orient="records")}


# ──────────────────────────────────────────────────────────────────────────────
# 디버그: 이름/코드 매칭 확인용
#   예) /_debug/find?q=삼성전자&mode=name
#       /_debug/find?q=005930&mode=code
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
