from fastapi import FastAPI, Query
from typing import List
from pydantic import BaseModel
from kiwoom_finance.batch import get_metrics_for_codes

app = FastAPI(title="Kiwoom Financial Metrics API")

class MetricsResponse(BaseModel):
    data: list

@app.get("/metrics", response_model=MetricsResponse)
def metrics(
    codes: List[str] = Query(..., description="예: ?codes=005380&codes=095570"),
    all_periods: bool = False,
    percent_format: bool = True
):
    df = get_metrics_for_codes(codes, latest_only=not all_periods, percent_format=percent_format)
    return {"data": df.reset_index().to_dict(orient="records")}
