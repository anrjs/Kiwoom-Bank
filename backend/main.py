# backend/main.py
from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
import pandas as pd

# --------------------------
# 더미 데이터 (단위: 억 원)
# --------------------------
data = [
    ("삼성전자", 2023, 240000, 20000, 15000, 430000, 170000, 260000, 150000, 85000, 2100, 30000, 26000),
    ("삼성전자", 2024, 260000, 35000, 29000, 450000, 180000, 270000, 160000, 90000, 2200, 40000, 28000),
    ("LG전자",   2023,  88000,  4800,  3300, 115000,  68000,  47000,  28000, 21000, 1300,  6800,  4300),
    ("LG전자",   2024,  90000,  5000,  3500, 120000,  70000,  50000,  30000, 22000, 1400,  7000,  4500),
    ("현대자동차",2023, 150000, 11000,  8600, 190000, 115000,  75000,  55000, 38000, 1700, 10000,  6500),
    ("현대자동차",2024, 160000, 12000,  9500, 200000, 120000,  80000,  60000, 40000, 1800, 11000,  7000),
]
cols = ["company","year","revenue","ebit","net_income","assets","liabilities","equity",
        "current_assets","current_liabilities","interest_expense","ocf","capex"]
df = pd.DataFrame(data, columns=cols)

class CompanyMetrics(BaseModel):
    company: str
    as_of_year: int
    revenue: int                 # 억 원
    revenue_growth_yoy: float    # %
    operating_margin: float      # %
    net_margin: float            # %
    roe: float                   # %
    roa: float                   # %
    debt_to_equity: float        # x
    current_ratio: float         # x
    interest_coverage: float     # x
    fcf: int                     # 억 원
    fcf_margin: float            # %

def compute_metrics(company: str, year: int) -> CompanyMetrics:
    curr = df[(df.company == company) & (df.year == year)]
    prev = df[(df.company == company) & (df.year == year-1)]
    if curr.empty or prev.empty:
        raise HTTPException(status_code=404, detail="해당 회사/연도 데이터가 없습니다.")

    c, p = curr.iloc[0], prev.iloc[0]
    revenue, ebit, net_income = int(c.revenue), c.ebit, c.net_income
    equity, assets, liabilities = c.equity, c.assets, c.liabilities
    cur_assets, cur_liab, interest = c.current_assets, c.current_liabilities, c.interest_expense
    ocf, capex = c.ocf, c.capex

    pct = lambda x: round(float(x) * 100.0, 2)

    metrics = CompanyMetrics(
        company=company,
        as_of_year=year,
        revenue=revenue,
        revenue_growth_yoy=pct((revenue - p.revenue) / p.revenue) if p.revenue else 0.0,
        operating_margin=pct(ebit / revenue) if revenue else 0.0,     # 영업이익률 = EBIT / 매출
        net_margin=pct(net_income / revenue) if revenue else 0.0,      # 순이익률 = 순이익 / 매출
        roe=pct(net_income / equity) if equity else 0.0,               # ROE = 순이익 / 자기자본
        roa=pct(net_income / assets) if assets else 0.0,               # ROA = 순이익 / 총자산
        debt_to_equity=round(liabilities / equity, 2) if equity else 0.0,  # D/E = 부채/자본
        current_ratio=round(cur_assets / cur_liab, 2) if cur_liab else 0.0, # 유동비율
        interest_coverage=round(ebit / interest, 2) if interest else 0.0,   # 이자보상배율
        fcf=int(ocf - capex),                                          # FCF = OCF - CAPEX
        fcf_margin=pct((ocf - capex) / revenue) if revenue else 0.0    # FCF 마진
    )
    return metrics

app = FastAPI(title="Company Metrics API", version="0.1.0")

# Vite(5173)와 CORS 연결
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173", "http://127.0.0.1:5173"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

@app.get("/api/company-metrics", response_model=CompanyMetrics)
def get_company_metrics(company: str = Query(..., description="회사명"), year: int = Query(2024)):
    return compute_metrics(company, year)
