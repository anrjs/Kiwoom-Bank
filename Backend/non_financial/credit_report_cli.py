# -*- coding: utf-8 -*-
"""
크레딧 리포트 CLI (확장판, 자동 산업판단 기본)
 - DART 기반 비재무 핵심·사업항목 지표 추출
 - industry_credit_model로 평가 (자동 산업판단; --industry-override는 옵션)
"""

import json
import sys
import argparse
from typing import Dict, Any, Optional

from non_financial_extractor import extract_non_financial_core
from industry_credit_model import evaluate_company, classify_industry

MODEL_KEYS = [
    # 공통
    "revenue_krw", "total_assets_krw", "equity_krw",
    "num_segments", "largest_segment_share", "portfolio_hhi",
    "board_independence_ratio", "ownership_concentration_ratio",
    "domestic_share", "export_ratio",
    "inventory_days", "inventory_days_prev",
    "top1_customer_share", "top5_customer_share",
    "capex_to_revenue", "r_and_d_ratio", "rd_to_sales_ratio",

    # 업종별
    "backlog_to_revenue", "backlog_to_revenue_prev",
    "loan_to_deposit_ratio", "non_interest_income_ratio",
    "ship_tech_score", "tech_leadership_score",
    "defense_government_ratio_est", "defense_export_ratio_est",

    # 인터넷 서비스업 전용
    "gross_margin_ratio", "operating_margin_ratio", "sga_ratio", "revenue_yoy",
    "ad_share", "subscription_share", "commission_share",
    "content_share", "commerce_share", "fintech_share",
    "recurring_revenue_share_proxy",
]

def to_model_inputs(core: Dict[str, Any]) -> Dict[str, Any]:
    d = {k: core.get(k) for k in MODEL_KEYS if k in core}
    # R&D alias: 구버전 키 대응
    if d.get("r_and_d_ratio") is None and core.get("rd_to_sales_ratio") is not None:
        d["r_and_d_ratio"] = core.get("rd_to_sales_ratio")
    return d

def fmt_pct(v: Optional[float]) -> str:
    if v is None:
        return "-"
    try:
        return f"{float(v)*100:.2f}%"
    except Exception:
        return str(v)

def fmt_num(v: Optional[float]) -> str:
    if v is None:
        return "-"
    try:
        v = float(v)
    except Exception:
        return str(v)
    if abs(v) >= 1e12:
        return f"{v/1e12:.2f} 조원"
    if abs(v) >= 1e8:
        return f"{v/1e8:.2f} 억원"
    return f"{v:,.0f} 원"

def print_header(core: Dict[str, Any]):
    print("=" * 84)
    print(f"회사명: {core.get('company')} (corp_code: {core.get('corp_code')}, 사업연도: {core.get('bsns_year')})")
    print("=" * 84)

def print_core(core: Dict[str, Any]):
    print("\n[공통 지표 (DART)]")
    print(f" - 매출액: {fmt_num(core.get('revenue_krw'))}")
    print(f" - 자산총계 / 자본총계: {fmt_num(core.get('total_assets_krw'))} / {fmt_num(core.get('equity_krw'))}")
    print(f" - 세그먼트 수 / 최대비중 / HHI: {core.get('num_segments') or '-'} / {fmt_pct(core.get('largest_segment_share'))} / {core.get('portfolio_hhi') or '-'}")
    print(f" - 이사회 독립성 / 최대주주 지분율: {fmt_pct(core.get('board_independence_ratio'))} / {fmt_pct(core.get('ownership_concentration_ratio'))}")
    print(f" - 국내매출비중 / 수출비중: {fmt_pct(core.get('domestic_share'))} / {fmt_pct(core.get('export_ratio'))}")
    if core.get('inventory_days') is not None:
        print(f" - 재고일수(근사): {core.get('inventory_days'):.1f} 일")
    else:
        print(" - 재고일수(근사): -")

    print("\n[사업항목 관련 지표]")
    if core.get("top1_customer_share") is not None or core.get("top5_customer_share") is not None:
        print(f" - 고객 집중도: Top1 {fmt_pct(core.get('top1_customer_share'))} / Top5 {fmt_pct(core.get('top5_customer_share'))}")
    if core.get("refining_capacity_bpd") is not None:
        print(f" - 정제설비 규모: {core.get('refining_capacity_bpd'):,.0f} B/D")
    if core.get("steel_capacity_tpy") is not None:
        print(f" - 철강 CAPA: {core.get('steel_capacity_tpy'):,.0f} 톤/년")
    if core.get("auto_production_capacity_units") is not None:
        print(f" - 자동차 생산능력: {core.get('auto_production_capacity_units'):,.0f} 대/년")
    if core.get("loan_to_deposit_ratio") is not None:
        print(f" - LDR(대출/예수금): {core.get('loan_to_deposit_ratio'):.2f}")
    if core.get("fee_income_ratio") is not None:
        print(f" - 수수료수익 비중: {fmt_pct(core.get('fee_income_ratio'))}")
    if core.get("rd_to_sales_ratio") is not None:
        print(f" - R&D/매출 비중(구표기): {fmt_pct(core.get('rd_to_sales_ratio'))}")
    if core.get("hotel_occupancy_rate") is not None:
        print(f" - 호텔 객실점유율: {fmt_pct(core.get('hotel_occupancy_rate'))}")
    if core.get("ebitda_to_capex") is not None:
        print(f" - EBITDA/CAPEX: {core.get('ebitda_to_capex'):.2f} 배")

    if core.get("capex_to_revenue") is not None:
        print(f" - CAPEX/매출: {fmt_pct(core.get('capex_to_revenue'))}")
    if core.get("r_and_d_ratio") is not None:
        print(f" - R&D/매출: {fmt_pct(core.get('r_and_d_ratio'))}")
    if core.get("tech_leadership_score") is not None:
        print(f" - 기술 리더십(키워드 근사): {fmt_pct(core.get('tech_leadership_score'))}")
    if core.get("backlog_to_revenue") is not None:
        print(f" - 수주잔고/매출 비율: {core.get('backlog_to_revenue'):.2f} 배")
    if core.get("backlog_to_revenue_prev") is not None:
        print(f"   · 전기 수주잔고/매출: {core.get('backlog_to_revenue_prev'):.2f} 배")
    if core.get("ship_tech_score") is not None:
        print(f" - 조선 기술 복잡도(키워드 근사): {fmt_pct(core.get('ship_tech_score'))}")

    # 인터넷 서비스 지표
    if core.get("gross_margin_ratio") is not None:
        print(f" - 총마진: {core['gross_margin_ratio']*100:.2f}%")
    if core.get("operating_margin_ratio") is not None:
        print(f" - 영업이익률: {core['operating_margin_ratio']*100:.2f}%")
    if core.get("sga_ratio") is not None:
        print(f" - 판관비/매출: {core['sga_ratio']*100:.2f}%")
    if core.get("revenue_yoy") is not None:
        print(f" - 매출 YoY: {core['revenue_yoy']*100:.2f}%")
    if core.get("recurring_revenue_share_proxy") is not None:
        print(f" - 반복매출(구독·수수료·핀테크) 비중: {core['recurring_revenue_share_proxy']*100:.2f}%")

    # 은행/카드 출력 키 일치
    if core.get("non_interest_income_ratio") is not None:
        print(f" - 수수료/비이자이익 비중: {fmt_pct(core.get('non_interest_income_ratio'))}")

def print_result(res: Dict[str, Any]):
    print("\n[모델 결과]")
    print(f" - 산업 분류: {res.get('industry')} (방법: {res.get('industry_classification_method')})")
    print(f" - 비재무 종합 점수(0~100): {res.get('non_financial_weighted_score')}")
    print(f" - 최종 점수: {res.get('final_score')}")
    print(f" - 등급: {res.get('implied_rating')}")

    details = res.get("factor_details", {})
    if details:
        print("\n[요소별 점수 상세]")
        print(f"{'요소':<26} {'가중치':>8} {'점수':>8}  설명")
        print("-" * 84)
        for _, it in details.items():
            name = it.get('name', '')
            w = it.get('weight', 0.0)
            s = it.get('score', 0.0)
            desc = it.get('desc', '')
            print(f"{name:<26} {w:>8.3f} {s:>8.2f}  {desc}")

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--company", required=True, help="회사명")
    ap.add_argument("--year", type=int, default=None, help="사업연도 (미입력시 직전년도)")
    ap.add_argument("--industry-override", default=None, help="산업 수동지정(옵션)")
    ap.add_argument("--save-json", default=None, help="전체 결과 JSON 저장 경로")
    args = ap.parse_args()

    # 자동 산업판단(override 문자열도 힌트로 활용)
    hint_industry, _ = classify_industry(args.company, hint_text=args.industry_override)

    # extractor에는 사람이 넣은 override가 있으면 그걸, 없으면 자동힌트를 넘김
    core = extract_non_financial_core(
        args.company,
        year=args.year,
        industry_hint=(args.industry_override or hint_industry)
    )

    if not core.get("corp_code"):
        print_header(core)
        print("회사 코드를 찾지 못했습니다.")
        sys.exit(1)

    raw_inputs = to_model_inputs(core)
    res = evaluate_company(args.company, raw_inputs, industry_override=args.industry_override)

    print_header(core)
    print_core(core)
    print_result(res)

    if args.save_json:
        payload = {"inputs_core": core, "raw_inputs": raw_inputs, "result": res}
        with open(args.save_json, "w", encoding="utf-8") as f:
            json.dump(payload, f, ensure_ascii=False, indent=2)
        print(f"\n[저장] JSON → {args.save_json}")

if __name__ == "__main__":
    main()
