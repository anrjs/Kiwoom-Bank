# model.py
from pydantic import BaseModel

# 클라이언트 요청 형식
class CompanyRequest(BaseModel):
    company_name: str

# 서버에서 보내줄 응답 형식
class ResultResponse(BaseModel):
    company: str
    revenue: float
    profit: float
    profit_margin: float


# 더미 데이터 & 계산
def calculate_financials(company_name: str) -> ResultResponse:
    # 더미 재무제표
    dummy_data = {
        "삼성전자": {"revenue": 300000, "profit": 50000},
        "LG전자": {"revenue": 200000, "profit": 20000},
    }

    data = dummy_data.get(company_name, {"revenue": 100000, "profit": 10000})

    # 공식 적용: 영업이익률 = 순이익 / 매출
    profit_margin = data["profit"] / data["revenue"]

    return ResultResponse(
        company=company_name,
        revenue=data["revenue"],
        profit=data["profit"],
        profit_margin=round(profit_margin * 100, 2)  # %로 환산
    )
