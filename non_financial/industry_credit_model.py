# -*- coding: utf-8 -*-
"""
Industry credit model (비재무요소 중심)
 - 공통요소: 기업규모, 사업포트폴리오(HHI), 지배구조, (옵션) 시장지배력
 - 산업요소: 건설/공기업/물류/반도체/신용카드/은행/의류/자동차/정유/제약/조선/증권/철강/호텔/방산/인터넷/음식료
 - 모든 산업요소는 DART에서 추출 가능한 지표만 사용하도록 설계
"""

from __future__ import annotations
from dataclasses import dataclass
from typing import Callable, Dict, Any, List, Optional, Tuple
import math

# ------------------------
# Small utils
# ------------------------

def clamp(v: float, lo: float = 0.0, hi: float = 100.0) -> float:
    return max(lo, min(hi, v))

def safe_get(d: Dict[str, Any], key: str, default=None):
    if d is None:
        return default
    v = d.get(key, default)
    try:
        return float(v) if v is not None else default
    except Exception:
        return default

def linear_score(x: Optional[float], min_val: float, max_val: float, higher_is_better: bool = True) -> float:
    """Map x in [min_val, max_val] to [0,100]; out-of-range clipped; None->50"""
    if x is None:
        return 50.0
    if max_val == min_val:
        return 50.0
    ratio = (x - min_val) / (max_val - min_val)
    ratio = clamp(ratio, 0.0, 1.0)
    return ratio * 100.0 if higher_is_better else (100.0 - ratio * 100.0)

def inverted_score(x: Optional[float], min_good: float, max_bad: float) -> float:
    """Score high when x is small; min_good -> 100, max_bad -> 0"""
    if x is None:
        return 50.0
    if max_bad == min_good:
        return 50.0
    ratio = (x - min_good) / (max_bad - min_good)
    ratio = clamp(ratio, 0.0, 1.0)
    return 100.0 - 100.0 * ratio

def peak_score(x: Optional[float], peak: float, spread: float) -> float:
    """Score highest near 'peak' (triangle-like); spread sets half-width"""
    if x is None:
        return 50.0
    if spread <= 0:
        return 50.0
    dist = abs(x - peak) / spread
    sc = max(0.0, 1.0 - dist) * 100.0
    return sc

def log_scale_score(x: Optional[float], min_val: float, max_val: float, higher_is_better: bool = True) -> float:
    if x is None or x <= 0:
        return 50.0
    if min_val <= 0 or max_val <= 0 or max_val == min_val:
        return 50.0
    lx, lmin, lmax = math.log10(x), math.log10(min_val), math.log10(max_val)
    if lmax == lmin:
        return 50.0
    ratio = clamp((lx - lmin) / (lmax - lmin), 0.0, 1.0)
    return ratio * 100.0 if higher_is_better else (100.0 - ratio * 100.0)

def balance_score(p: Optional[float], center: float = 0.5) -> float:
    """0~1 사이 p에서 균형(0.5)에 가까울수록 우수 (4p(1-p))"""
    if p is None:
        return 50.0
    if not (0.0 <= p <= 1.0):
        return 50.0
    return clamp(4.0 * p * (1.0 - p) * 100.0, 0.0, 100.0)

# 방산/건설/조선 보조 스코어러
def _def_backlog_scorer_flexible(x: Dict[str, Any]) -> float:
    cur = safe_get(x, "backlog_to_revenue")
    prev = safe_get(x, "backlog_to_revenue_prev")
    gov = safe_get(x, "defense_government_ratio_est")
    if gov is not None and gov >= 0.6:
        base = linear_score(cur, min_val=0.20, max_val=1.50, higher_is_better=True)
    else:
        base = linear_score(cur, min_val=0.80, max_val=3.00, higher_is_better=True)
    if cur is None or prev is None:
        return base
    improv = max(0.0, cur - prev)
    boost = min(12.0, improv * 8.0)
    return clamp(base + boost)

def _cons_backlog_scorer(x: Dict[str, Any]) -> float:
    cur = safe_get(x, "backlog_to_revenue")
    prev = safe_get(x, "backlog_to_revenue_prev")
    base = linear_score(cur, min_val=1.0, max_val=6.0, higher_is_better=True)
    if cur is None or prev is None:
        return base
    improv = max(0.0, cur - prev)
    boost = min(16.0, improv * 8.0)
    return clamp(base + boost)

def _ship_backlog_scorer(x: Dict[str, Any]) -> float:
    cur = safe_get(x, "backlog_to_revenue")
    prev = safe_get(x, "backlog_to_revenue_prev")
    base = linear_score(cur, min_val=1.5, max_val=7.0, higher_is_better=True)
    if cur is None or prev is None:
        return base
    improv = max(0.0, cur - prev)
    boost = min(20.0, improv * 10.0)
    return clamp(base + boost)

def _profitability_proxy(x: Dict[str, Any]) -> float:
    gm = safe_get(x, "gross_margin_ratio")
    opm = safe_get(x, "operating_margin_ratio")
    if gm is None and opm is None:
        return 50.0
    idx = 0.6 * gm + 0.4 * opm if (gm is not None and opm is not None) else (gm if gm is not None else opm)
    return linear_score(idx, min_val=0.20, max_val=0.45, higher_is_better=True)

def _semi_inventory_scorer(x: Dict[str, Any]) -> float:
    cur = safe_get(x, "inventory_days")
    prev = safe_get(x, "inventory_days_prev")
    base = inverted_score(cur, min_good=90, max_bad=210)
    if cur is None or prev is None:
        return base
    improv_days = max(0.0, prev - cur)
    boost = min(20.0, (improv_days / 30.0) * 10.0)
    return clamp(base + boost)

def _portfolio_diversification_score(num_segments: Optional[float],
                                     largest_share: Optional[float],
                                     hhi: Optional[float]) -> float:
    if hhi is not None:
        s_hhi = clamp((1.0 - clamp(hhi, 0.0, 1.0)) * 100.0)
    else:
        s_hhi = 50.0
    if largest_share is not None:
        ls = float(largest_share)
        if ls > 1.0:
            ls = ls / 100.0
        s_largest = clamp((1.0 - clamp(ls, 0.0, 1.0)) * 100.0)
    else:
        s_largest = 50.0
    if num_segments is not None:
        s_seg = linear_score(float(num_segments), min_val=2.0, max_val=10.0, higher_is_better=True)
    else:
        s_seg = 50.0
    score = 0.5 * s_hhi + 0.3 * s_largest + 0.2 * s_seg
    return clamp(score, 0.0, 100.0)

# ------------------------
# Factor & IndustryConfig
# ------------------------

@dataclass
class Factor:
    key: str
    name: str
    weight: float
    desc: str
    scorer: Callable[[Dict[str, Any]], float]

@dataclass
class IndustryConfig:
    name: str
    industry_factors: List[Factor]

# ------------------------
# Base non-financial factors
# ------------------------

def make_base_factors(total_base_weight: float = 0.4) -> List[Factor]:
    def firm_size_scorer(x):
        rev = safe_get(x, "revenue_krw")
        assets = safe_get(x, "total_assets_krw")
        v = max([v for v in [rev, assets] if v is not None], default=None)
        if v is None:
            return 50.0
        return log_scale_score(v, min_val=1e12, max_val=5e13, higher_is_better=True)

    def business_portfolio_scorer(x):
        hhi = safe_get(x, "portfolio_hhi")
        if hhi is None:
            return 50.0
        return clamp((1.0 - clamp(hhi, 0.0, 1.0)) * 100.0)

    def governance_scorer(x):
        indep = safe_get(x, "board_independence_ratio")
        own = safe_get(x, "ownership_concentration_ratio")
        s_indep = linear_score(indep, 0.3, 0.7, higher_is_better=True)
        s_own = inverted_score(own, min_good=0.20, max_bad=0.60)
        return 0.6 * s_indep + 0.4 * s_own

    def market_power_scorer(x):
        ms = safe_get(x, "market_share")
        pp = safe_get(x, "pricing_power")
        if ms is None and pp is None:
            return 50.0
        s_ms = linear_score(ms, 0.05, 0.40, higher_is_better=True) if ms is not None else 50.0
        s_pp = linear_score(pp, 0.3, 0.9, higher_is_better=True) if pp is not None else 50.0
        return 0.6 * s_ms + 0.4 * s_pp

    return [
        Factor("firm_size", "기업규모", 0.12 * total_base_weight, "매출/자산 규모", firm_size_scorer),
        Factor("business_portfolio", "사업 포트폴리오", 0.12 * total_base_weight, "세그먼트 분산(HHI)", business_portfolio_scorer),
        Factor("governance", "경영구조", 0.10 * total_base_weight, "이사회 독립성, 지배력 집중도", governance_scorer),
        Factor("market_power", "시장지배력(옵션)", 0.06 * total_base_weight, "점유율/가격결정력(없으면 중립)", market_power_scorer),
    ]

# ------------------------
# Industry-specific non-financial factors
# ------------------------

def make_construction_factors(total_industry_weight: float = 0.6) -> List[Factor]:
    def backlog_scorer(x):
        cur = safe_get(x, "backlog_to_revenue")
        prev = safe_get(x, "backlog_to_revenue_prev")
        base = linear_score(cur, min_val=1.5, max_val=5.0, higher_is_better=True)
        if cur is None or prev is None:
            return base
        improv = max(0.0, cur - prev)
        boost = min(12.0, improv * 6.0)
        return clamp(base + boost)

    def export_balance_scorer(x):
        return peak_score(safe_get(x, "export_ratio"), peak=0.50, spread=0.20)

    def top1_scorer(x):
        return 100.0 - clamp(100.0 * safe_get(x, "top1_customer_share", 0.4))

    return [
        Factor("cons_backlog_cover", "수주잔고 커버리지", 0.32 * total_industry_weight, "수주잔고/매출 (전년 대비 개선 보너스 포함)", backlog_scorer),
        Factor("cons_export_balance", "국내/해외 균형", 0.16 * total_industry_weight, "수출비중(국내/해외 균형 선호)", export_balance_scorer),
        Factor("cons_customer_conc", "상위고객 집중도", 0.12 * total_industry_weight, "Top1 고객비중(낮을수록 우수)", top1_scorer),
    ]

def make_public_enterprise_factors(total_industry_weight: float = 0.6) -> List[Factor]:
    return [
        Factor("soe_portfolio_div", "사업다각화(포트폴리오)", 0.2 * total_industry_weight, "HHI 기반 분산도(낮을수록 우수)",
               lambda x: clamp((1.0 - clamp(safe_get(x, "portfolio_hhi", 0.6), 0.0, 1.0)) * 100.0)),
        Factor("soe_customer_conc", "고객 집중도", 0.2 * total_industry_weight, "Top5 고객비중(낮을수록 우수)",
               lambda x: 100.0 - clamp(100.0 * safe_get(x, "top5_customer_share", 0.5))),
    ]

def make_logistics_factors(total_industry_weight: float = 0.6) -> List[Factor]:
    return [
        Factor("log_export_balance", "국내/해외 네트워크", 0.22 * total_industry_weight, "수출/해외 매출 비중(균형 선호)",
               lambda x: peak_score(safe_get(x, "export_ratio"), peak=0.5, spread=0.25)),
        Factor("log_portfolio_div", "사업다변화(HHI)", 0.2 * total_industry_weight, "세그먼트 분산(HHI 낮을수록 우수)",
               lambda x: clamp((1.0 - clamp(safe_get(x, "portfolio_hhi", 0.6), 0.0, 1.0)) * 100.0)),
        Factor("log_top5_conc", "상위고객 집중도", 0.18 * total_industry_weight, "Top5 고객비중(낮을수록 우수)",
               lambda x: 100.0 - clamp(100.0 * safe_get(x, "top5_customer_share", 0.5))),
    ]

def make_semiconductor_factors(total_industry_weight: float = 0.6) -> List[Factor]:
    def capex_scorer(x):
        v = safe_get(x, "capex_to_revenue")
        sc = peak_score(v, peak=0.26, spread=0.12)
        return max(60.0, sc)

    return [
        Factor("semi_inventory_days", "재고일수", 0.16 * total_industry_weight, "재고일수(사이클/추세 보정 포함)", _semi_inventory_scorer),
        Factor("semi_capex_intensity", "CAPEX/매출", 0.20 * total_industry_weight, "CAPEX/매출 (0.18~0.35 최적, 하한 60점)", capex_scorer),
        Factor("semi_top1_conc", "상위고객 집중도", 0.10 * total_industry_weight, "Top1 고객비중(낮을수록 우수)",
               lambda x: 100.0 - clamp(100.0 * safe_get(x, "top1_customer_share", 0.4))),
        Factor("semi_rnd_ratio", "R&D/매출", 0.22 * total_industry_weight, "R&D/매출(높을수록 우수)",
               lambda x: linear_score(safe_get(x, "r_and_d_ratio"), 0.04, 0.14, True)),
        Factor("semi_tech_leadership", "기술리더십(키워드 근사)", 0.14 * total_industry_weight,
               "HBM/DDR5/GDDR 등 고부가 메모리·인터커넥트 언급도",
               lambda x: linear_score(safe_get(x, "tech_leadership_score"), 0.05, 0.30, True)),
    ]

def make_creditcard_factors(total_industry_weight: float = 0.6) -> List[Factor]:
    return [
        Factor("card_fee_income_ratio", "수수료이익비중", 0.28 * total_industry_weight, "비이자/수수료이익 비중(높을수록 우수)",
               lambda x: linear_score(safe_get(x, "non_interest_income_ratio"), 0.30, 0.90, True)),
        Factor("card_capex_intensity", "CAPEX/매출", 0.16 * total_industry_weight, "CAPEX/매출(중간값 선호)",
               lambda x: peak_score(safe_get(x, "capex_to_revenue"), 0.2, 0.15)),
        Factor("card_customer_conc", "상위고객 집중도", 0.16 * total_industry_weight, "Top5 고객비중(낮을수록 우수)",
               lambda x: 100.0 - clamp(100.0 * safe_get(x, "top5_customer_share", 0.4))),
    ]

def make_banking_factors(total_industry_weight: float = 0.6) -> List[Factor]:
    def size_bonus(x):
        eq = safe_get(x, "equity_krw")
        return 8.0 if (eq is not None and eq >= 5e13) else 0.0

    return [
        Factor("bank_ldr", "LDR(대출/예금)", 0.26 * total_industry_weight, "대출/예금 (낮을수록 우수, 0.85~1.15)",
               lambda x: inverted_score(safe_get(x, "loan_to_deposit_ratio"), 0.85, 1.15)),
        Factor("bank_non_interest_ratio", "비이자이익비중", 0.22 * total_industry_weight, "비이자이익/영업수익 (높을수록 우수, 20~50%)",
               lambda x: linear_score(safe_get(x, "non_interest_income_ratio"), 0.20, 0.50, True)),
        Factor("bank_safety", "건전성 신호 (BIS/ROA/ROE)", 0.12 * total_industry_weight, "BIS/ROA/ROE 키워드 빈도",
               lambda x: linear_score(safe_get(x, "bank_safety_score"), 0.05, 0.25, True)),
        Factor("bank_scale_bonus", "규모 보정", 0.06 * total_industry_weight, "자기자본 대형 보너스", size_bonus),
    ]

def make_apparel_factors(total_industry_weight: float = 0.6) -> List[Factor]:
    return [
        Factor("apparel_export_ratio", "수출비중", 0.22 * total_industry_weight, "해외 매출 비중(중간~높음 선호)",
               lambda x: linear_score(safe_get(x, "export_ratio"), 0.1, 0.8, True)),
        Factor("apparel_portfolio_div", "제품/브랜드 포트폴리오", 0.20 * total_industry_weight, "세그먼트 HHI(낮을수록 우수)",
               lambda x: clamp((1.0 - clamp(safe_get(x, "portfolio_hhi", 0.6), 0.0, 1.0)) * 100.0)),
        Factor("apparel_top5_conc", "상위고객 집중도", 0.18 * total_industry_weight, "Top5 고객비중(낮을수록 우수)",
               lambda x: 100.0 - clamp(100.0 * safe_get(x, "top5_customer_share", 0.5))),
    ]

def make_auto_factors(total_industry_weight: float = 0.6) -> List[Factor]:
    def capex_scorer(x):
        v = safe_get(x, "capex_to_revenue")
        return linear_score(v, 0.02, 0.10, True)

    def rnd_scorer(x):
        v = safe_get(x, "r_and_d_ratio")
        return linear_score(v, 0.02, 0.06, True)

    def export_scorer(x):
        v = safe_get(x, "export_ratio")
        return linear_score(v, 0.30, 0.90, True)

    def portfolio_scorer(x):
        hhi = safe_get(x, "portfolio_hhi")
        return linear_score(hhi, 0.25, 0.05, False)

    def size_bonus(x):
        rev = safe_get(x, "revenue_krw")
        assets = safe_get(x, "total_assets_krw")
        v = max([v for v in [rev, assets] if v is not None], default=None)
        return 10.0 if (v is not None and v >= 1e14) else 0.0

    return [
        Factor("auto_capex_intensity", "CAPEX/매출", 0.20 * total_industry_weight, "CAPEX/매출 (4~10% 구간 우수)", capex_scorer),
        Factor("auto_rnd_ratio", "R&D/매출", 0.20 * total_industry_weight, "R&D/매출 (2~6% 구간 우수)", rnd_scorer),
        Factor("auto_export_ratio", "수출비중", 0.16 * total_industry_weight, "해외 매출 비중(높을수록 우수)", export_scorer),
        Factor("auto_portfolio_div", "제품/시장 다변화", 0.20 * total_industry_weight, "세그먼트 HHI 낮을수록 우수", portfolio_scorer),
        Factor("auto_global_scale_bonus", "글로벌 스케일 보정", 0.08 * total_industry_weight, "매출/자산 대형 보너스", size_bonus),
    ]

def make_refining_factors(total_industry_weight: float = 0.6) -> List[Factor]:
    return [
        Factor("ref_export_ratio", "수출비중", 0.28 * total_industry_weight, "수출 비중(중간~높음 선호)",
               lambda x: peak_score(safe_get(x, "export_ratio"), 0.6, 0.25)),
        Factor("ref_capex_intensity", "CAPEX/매출", 0.20 * total_industry_weight, "CAPEX/매출(중간값 선호)",
               lambda x: peak_score(safe_get(x, "capex_to_revenue"), 0.2, 0.15)),
        Factor("ref_top5_conc", "상위고객 집중도", 0.12 * total_industry_weight, "Top5 고객비중(낮을수록 우수)",
               lambda x: 100.0 - clamp(100.0 * safe_get(x, "top5_customer_share", 0.5))),
    ]

def make_pharma_factors(total_industry_weight: float = 0.6) -> List[Factor]:
    return [
        Factor("pharma_rnd_ratio", "R&D/매출", 0.28 * total_industry_weight, "연구개발비/매출 (8~30%)",
               lambda x: linear_score(safe_get(x, "r_and_d_ratio"), 0.08, 0.30, True)),
        Factor("pharma_innovation", "신약/임상 혁신도", 0.22 * total_industry_weight, "사업보고서 임상/허가/신약 키워드 빈도",
               lambda x: linear_score(safe_get(x, "pharma_innovation_score"), 0.06, 0.24, True)),
        Factor("pharma_portfolio_div", "품목 포트폴리오", 0.18 * total_industry_weight, "세그먼트 HHI 낮을수록 우수",
               lambda x: clamp((1.0 - clamp(safe_get(x, "portfolio_hhi", 0.6), 0.0, 1.0)) * 100.0)),
        Factor("pharma_export_ratio", "수출 비중", 0.12 * total_industry_weight, "수출/총매출",
               lambda x: linear_score(safe_get(x, "export_ratio"), 0.10, 0.60, True)),
        Factor("pharma_top5_conc", "상위고객 집중도", 0.10 * total_industry_weight, "Top5 고객비중(낮을수록 우수)",
               lambda x: 100.0 - clamp(100.0 * safe_get(x, "top5_customer_share", 0.5))),
    ]

def make_food_beverage_factors(total_industry_weight: float = 0.6) -> List[Factor]:
    return [
        Factor("fnb_portfolio_div", "다각화(브랜드/제품/지역)", 0.20 * total_industry_weight, "세그먼트 HHI 낮을수록 우수",
               lambda x: _portfolio_diversification_score(safe_get(x, "num_segments"),
                                                          safe_get(x, "largest_segment_share"),
                                                          safe_get(x, "portfolio_hhi"))),
        Factor("fnb_channel_power", "유통채널/거래처 분산", 0.20 * total_industry_weight, "Top5 고객비중 낮을수록 우수",
               lambda x: 100.0 - clamp(100.0 * safe_get(x, "top5_customer_share", 0.5))),
        Factor("fnb_market_power", "브랜드/가격결정력(수익성 proxy)", 0.10 * total_industry_weight, "총마진/영업이익률 기반",
               _profitability_proxy),
        Factor("fnb_inventory_turn", "재고 회전", 0.10 * total_industry_weight, "재고일수 낮을수록 우수(20~90일)",
               lambda x: inverted_score(safe_get(x, "inventory_days"), 20, 90)),
        Factor("fnb_export_balance", "지역 포트폴리오(수출)", 0.10 * total_industry_weight, "수출 45%±30% 선호",
               lambda x: peak_score(safe_get(x, "export_ratio"), 0.45, 0.30)),
        Factor("fnb_capex_intensity", "CAPEX/매출", 0.10 * total_industry_weight, "중간값 선호(약 8%±5%)",
               lambda x: peak_score(safe_get(x, "capex_to_revenue"), 0.08, 0.05)),
    ]

def make_shipbuilding_factors(total_industry_weight: float = 0.6) -> List[Factor]:
    def backlog_scorer(x):
        cur = safe_get(x, "backlog_to_revenue")
        prev = safe_get(x, "backlog_to_revenue_prev")
        base = linear_score(cur, min_val=2.5, max_val=8.0, higher_is_better=True)
        if cur is None or prev is None:
            return base
        improv = max(0.0, cur - prev)
        boost = min(20.0, improv * 10.0)
        return clamp(base + boost)

    return [
        Factor("ship_backlog_cover", "수주잔고 커버리지", 0.28 * total_industry_weight, "수주잔고/매출 (개선 보너스)", backlog_scorer),
        Factor("ship_export_ratio", "수출 비중", 0.16 * total_industry_weight, "수출/총매출 (높을수록 우수)",
               lambda x: linear_score(safe_get(x, "export_ratio"), 0.60, 0.95, True)),
        Factor("ship_portfolio", "선종 다변화(근사)", 0.14 * total_industry_weight, "HHI 낮을수록 우수",
               lambda x: _portfolio_diversification_score(safe_get(x, "num_segments"),
                                                          safe_get(x, "largest_segment_share"),
                                                          safe_get(x, "portfolio_hhi"))),
        Factor("ship_tech_complexity", "기술 복잡도(키워드 근사)", 0.14 * total_industry_weight, "LNG/친환경연료 언급도",
               lambda x: linear_score(safe_get(x, "ship_tech_score"), 0.05, 0.30, True)),
        Factor("ship_customer_conc", "상위고객 집중", 0.08 * total_industry_weight, "Top5 고객 비중 낮을수록 우수",
               lambda x: 100.0 - clamp((safe_get(x, "top5_customer_share", 0.6)) * 100.0)),
    ]

def make_securities_factors(total_industry_weight: float = 0.6) -> List[Factor]:
    return [
        Factor("sec_equity_size", "자기자본 규모", 0.20 * total_industry_weight / 0.6, "자본총계(로그 스케일)",
               lambda x: log_scale_score(safe_get(x, "equity_krw"), 2e12, 2e14, True)),
        Factor("sec_fee_ratio", "수수료수익 비중", 0.20 * total_industry_weight / 0.6, "수수료수익/영업수익",
               lambda x: linear_score(safe_get(x, "fee_income_ratio"), 0.20, 0.70, True)),
        Factor("sec_business_div", "사업 다변화(근사)", 0.20 * total_industry_weight / 0.6, "세그먼트 HHI 낮을수록 우수",
               lambda x: _portfolio_diversification_score(safe_get(x, "num_segments"),
                                                          safe_get(x, "largest_segment_share"),
                                                          safe_get(x, "portfolio_hhi"))),
    ]

def make_steel_factors(total_industry_weight: float = 0.6) -> List[Factor]:
    return [
        Factor("steel_capacity", "생산능력(톤/년)", 0.18 * total_industry_weight / 0.6, "연산 CAPA (로그 스케일)",
               lambda x: log_scale_score(safe_get(x, "steel_capacity_tpy"), 1e6, 6e7, True)),
        Factor("steel_export", "수출 비중", 0.14 * total_industry_weight / 0.6, "수출/총매출",
               lambda x: linear_score(safe_get(x, "export_ratio"), 0.2, 0.8, True)),
        Factor("steel_portfolio", "제품 다변화(근사)", 0.14 * total_industry_weight / 0.6, "세그먼트 HHI 낮을수록 우수",
               lambda x: _portfolio_diversification_score(safe_get(x, "num_segments"),
                                                          safe_get(x, "largest_segment_share"),
                                                          safe_get(x, "portfolio_hhi"))),
        Factor("steel_inventory_cyc", "재고관리", 0.14 * total_industry_weight / 0.6, "재고일수 낮을수록 우수",
               lambda x: inverted_score(safe_get(x, "inventory_days"), 30, 120)),
    ]

def make_hotel_factors(total_industry_weight: float = 0.6) -> List[Factor]:
    return [
        Factor("hotel_occupancy", "객실점유율(가동률)", 0.22 * total_industry_weight / 0.6, "객실점유율 80%±10% 우수",
               lambda x: peak_score(safe_get(x, "hotel_occupancy_rate"), 0.80, 0.10)),
        Factor("hotel_portfolio", "사업 다변화(호텔·면세·리조트 등)", 0.20 * total_industry_weight / 0.6, "세그먼트 HHI 낮을수록 우수",
               lambda x: _portfolio_diversification_score(safe_get(x, "num_segments"),
                                                          safe_get(x, "largest_segment_share"),
                                                          safe_get(x, "portfolio_hhi"))),
        Factor("hotel_size", "매출규모", 0.18 * total_industry_weight / 0.6, "매출(로그 스케일)",
               lambda x: log_scale_score(safe_get(x, "revenue_krw"), 1e11, 3e13, True)),
    ]

def make_defense_factors(total_industry_weight: float = 0.6) -> List[Factor]:
    return [
        Factor("def_backlog_cover", "수주잔고 커버리지", 0.26 * total_industry_weight, "기업 유형별 스케일 보정 + 개선 보너스",
               _def_backlog_scorer_flexible),
        Factor("def_rd_intensity", "R&D 집약도", 0.22 * total_industry_weight, "R&D/매출 비중",
               lambda x: linear_score(safe_get(x, "r_and_d_ratio", safe_get(x, "rd_to_sales_ratio")), 0.03, 0.20, True)),
        Factor("def_gov_stability", "정부매출 안정성", 0.14 * total_industry_weight, "정부/군납 매출 비중 추정",
               lambda x: linear_score(safe_get(x, "defense_government_ratio_est"), 0.50, 0.95, True)),
        Factor("def_export_growth", "수출 성장성", 0.12 * total_industry_weight, "방산 수출 비중 추정",
               lambda x: peak_score(safe_get(x, "defense_export_ratio_est", safe_get(x, "export_ratio")), 0.35, 0.25)),
        Factor("def_customer_conc", "상위고객 집중도", 0.06 * total_industry_weight, "Top1 고객 비중(낮을수록 우수)",
               lambda x: 100.0 - clamp((safe_get(x, "top1_customer_share", 0.5)) * 100.0)),
        Factor("def_scale_bonus", "규모 보정(선택)", 0.04 * total_industry_weight, "대규모 backlog/매출 또는 매출/자산 보너스",
               lambda x: min(10.0, (safe_get(x, "backlog_to_revenue", 0.0)) * 2.0) if safe_get(x, "backlog_to_revenue")
               else (10.0 if max([v for v in [safe_get(x, "revenue_krw"), safe_get(x, "total_assets_krw")] if v is not None], default=0.0) >= 5e13 else 0.0)),
    ]

def make_internet_service_factors(total_industry_weight: float = 0.60) -> List[Factor]:
    scale = total_industry_weight / 0.40

    def _yoy_scorer(x):
        return linear_score(safe_get(x, "revenue_yoy"), -0.05, 0.25, True)

    def _portfolio_scorer(x):
        return linear_score(safe_get(x, "portfolio_hhi"), 0.35, 0.05, False)

    def _market_power_scorer(x):
        gm = safe_get(x, "gross_margin_ratio")
        opm = safe_get(x, "operating_margin_ratio")
        idx = 0.6 * gm + 0.4 * opm if (gm is not None and opm is not None) else (gm if gm is not None else opm)
        return linear_score(idx, 0.35, 0.70, True) if idx is not None else 50.0

    def _captive_scorer(x):
        top1 = safe_get(x, "top1_customer_share")
        rec = safe_get(x, "recurring_revenue_share_proxy")
        s1 = linear_score(top1, 0.50, 0.05, False)
        s2 = linear_score(rec, 0.30, 0.80, True)
        return clamp(0.6 * s1 + 0.4 * s2)

    def _service_mgmt_scorer(x):
        opm = safe_get(x, "operating_margin_ratio")
        sga = safe_get(x, "sga_ratio")
        rnd = safe_get(x, "r_and_d_ratio")
        a = linear_score(opm, 0.05, 0.25, True)
        b = linear_score(None if sga is None else (1.0 - sga), 0.30, 0.70, True)
        c = linear_score(rnd, 0.02, 0.20, True)
        return clamp(0.5 * a + 0.3 * b + 0.2 * c)

    return [
        Factor("net_growth", "산업 매력도(성장성)", 0.05 * scale, "YoY 매출 성장률(높을수록 우수)", _yoy_scorer),
        Factor("net_portfolio", "사업 포트폴리오", 0.10 * scale, "세그먼트 다각화(HHI 낮을수록 우수)", _portfolio_scorer),
        Factor("net_market_power", "시장 지배력(네트워크/마진)", 0.10 * scale, "총마진/영업이익률 기반", _market_power_scorer),
        Factor("net_captive", "고정거래처 안정성", 0.05 * scale, "Top1 고객의존도↓ + 반복매출 비중↑", _captive_scorer),
        Factor("net_service_mgmt", "서비스관리 역량", 0.10 * scale, "영업이익률/SG&A 효율/R&D 집약도", _service_mgmt_scorer),
    ]

# ------------------------
# Industry registry & classifier
# ------------------------

INDUSTRY_REGISTRY: Dict[str, IndustryConfig] = {
    "건설업": IndustryConfig("건설업", make_construction_factors()),
    "공기업": IndustryConfig("공기업", make_public_enterprise_factors()),
    "물류업": IndustryConfig("물류업", make_logistics_factors()),
    "반도체업": IndustryConfig("반도체업", make_semiconductor_factors()),
    "신용카드업": IndustryConfig("신용카드업", make_creditcard_factors()),
    "은행업": IndustryConfig("은행업", make_banking_factors()),
    "의류업": IndustryConfig("의류업", make_apparel_factors()),
    "자동차업": IndustryConfig("자동차업", make_auto_factors()),
    "정유업": IndustryConfig("정유업", make_refining_factors()),
    "제약업": IndustryConfig("제약업", make_pharma_factors()),
    "조선업": IndustryConfig("조선업", make_shipbuilding_factors()),
    "증권업": IndustryConfig("증권업", make_securities_factors()),
    "철강업": IndustryConfig("철강업", make_steel_factors()),
    "호텔업": IndustryConfig("호텔업", make_hotel_factors()),
    "방산업": IndustryConfig("방산업", make_defense_factors()),
    "기타_인터넷 서비스업": IndustryConfig("기타_인터넷 서비스업", make_internet_service_factors()),
    "음식료업": IndustryConfig("음식료업", make_food_beverage_factors()),
}

COMPANY_TO_INDUSTRY = {
    "삼성전자": "반도체업",
    "SK하이닉스": "반도체업",
    "DB하이텍": "반도체업",
    "한솔테크닉스": "반도체업",
    "두산퓨얼셀": "반도체업",
    "현대건설": "건설업",
    "대우건설": "건설업",
    "GS건설": "건설업",
    "DL이앤씨": "건설업",
    "DL E&C": "건설업",
    "에코프로": "정유업",
    "에쓰오일": "정유업",
    "GS칼텍스": "정유업",
    "SK에너지": "정유업",
    "현대오일뱅크": "정유업",
    "KB국민은행": "은행업",
    "신한은행": "은행업",
    "하나은행": "은행업",
    "우리은행": "은행업",
    "삼성카드": "신용카드업",
    "롯데카드": "신용카드업",
    "비씨카드": "신용카드업",
    "CJ대한통운": "물류업",
    "롯데글로벌로지스": "물류업",
    "엘엑스판토스": "물류업",
    "세운메디칼": "제약업",
    "녹십자": "제약업",
    "유한양행": "제약업",
    "대웅제약": "제약업",
    "한미약품": "제약업",
    "HD현대중공업": "조선업",
    "삼성중공업": "조선업",
    "한화오션": "조선업",
    "케이조선": "조선업",
    "미래에셋증권": "증권업",
    "NH투자증권": "증권업",
    "키움증권": "증권업",
    "삼성증권": "증권업",
    "대한제강": "철강업",
    "포스코": "철강업",
    "현대제철": "철강업",
    "동국제강": "철강업",
    "호텔신라": "호텔업",
    "호텔롯데": "호텔업",
    "풍산": "방산업",
    "한화에어로스페이스": "방산업",
    "LIG넥스원": "방산업",
    "한국항공우주": "방산업",
    "현대로템": "방산업",
    "현대자동차": "자동차업",
    "기아": "자동차업",
    "디에이치오토리드": "자동차업",
    "핸즈코퍼레이션": "자동차업",
    "BYC": "의류업",
    "대한방직": "의류업",
    "F&F": "의류업",
    "영원무역": "의류업",
    "롯데쇼핑": "의류업",
    "한국전력": "공기업",
    "한국가스공사": "공기업",
    "인천국제공항공사": "공기업",
    "네이버": "기타_인터넷 서비스업",
    "카카오": "기타_인터넷 서비스업",
    "엔씨소프트": "기타_인터넷 서비스업",
    "넷마블": "기타_인터넷 서비스업",
    "크래프톤": "기타_인터넷 서비스업",
    "펄어비스": "기타_인터넷 서비스업",
    "대한항공": "물류업",
    "오뚜기": "음식료업",
    "농심": "음식료업",
    "CJ제일제당": "음식료업",
    "삼양식품": "음식료업",
    "동서": "음식료업",
    "롯데칠성": "음식료업",
    "하이트진로": "음식료업",
    "빙그레": "음식료업",
    "매일유업": "음식료업",
    "남양유업": "음식료업",
    "대상": "음식료업",
    "풀무원": "음식료업",
    "동원F&B": "음식료업",
}

KEYWORD_TO_INDUSTRY = [
    (["반도체", "웨이퍼", "파운드리", "메모리", "칩"], "반도체업"),
    (["건설", "토목", "플랜트", "주택", "건축", "이앤씨"], "건설업"),
    (["정유", "리파이너리", "석유", "정제", "석화"], "정유업"),
    (["은행", "금융지주", "리테일뱅킹", "여수신"], "은행업"),
    (["카드", "신용카드", "결제"], "신용카드업"),
    (["물류", "택배", "운송", "포워딩"], "물류업"),
    (["의류", "패션", "섬유"], "의류업"),
    (["자동차", "완성차", "오토모티브"], "자동차업"),
    (["제약", "바이오", "의약품"], "제약업"),
    (["공기업", "공사", "공단"], "공기업"),
    (["인터넷", "플랫폼", "포털", "게임", "콘텐츠", "웹툰", "커머스", "페이"], "기타_인터넷 서비스업"),
    (["음식료", "식품", "음료", "주류", "라면", "과자", "제과", "유업", "커피믹스", "식품제조"], "음식료업"),
]

def classify_industry(company: str, hint_text: Optional[str] = None) -> Tuple[str, str]:
    if company in COMPANY_TO_INDUSTRY:
        return COMPANY_TO_INDUSTRY[company], "map"
    if hint_text:
        t = hint_text
        for kws, ind in KEYWORD_TO_INDUSTRY:
            if any(k in t for k in kws):
                return ind, "keyword"
    for kws, ind in KEYWORD_TO_INDUSTRY:
        if any(k in company for k in kws):
            return ind, "keyword"
    return "반도체업", "default"

# ------------------------
# Scoring / Aggregation
# ------------------------

RATING_BINS = [
    (90, "AAA"), (85, "AA+"), (80, "AA"), (75, "AA-"),
    (72, "A+"), (68, "A"), (64, "A-"),
    (60, "BBB+"), (55, "BBB"), (50, "BBB-"),
    (45, "BB+"), (40, "BB"), (35, "BB-"),
    (30, "B+"), (25, "B"), (0, "B-")
]

def to_rating(score: float) -> str:
    for th, r in RATING_BINS:
        if score >= th:
            return r
    return "B-"

def calibrate_non_financial_score(company: str,
                                  industry: str,
                                  raw_inputs: Dict[str, Any],
                                  base_score: float) -> float:
    s = float(base_score)

    # (A) 밴드 스트레치
    if s < 40:
        s += 0.0
    elif s < 60:
        s += 2.0
    elif s < 70:
        s += 4.0
    elif s < 80:
        s += 6.0
    else:
        s += 7.0

    # (B) size-lift
    anchor = max([v for v in [
        safe_get(raw_inputs, "revenue_krw"),
        safe_get(raw_inputs, "total_assets_krw"),
        safe_get(raw_inputs, "equity_krw"),
    ] if v is not None] or [0.0])
    if anchor > 0:
        l = math.log10(anchor)
        size_bonus = clamp((l - 12.0) / (14.5 - 12.0) * 20.0, 0.0, 20.0)
        s += size_bonus

    # (C) 산업 프리미엄
    industry_premium = {
        "자동차업": 6.0,
        "은행업": 6.0,
        "공기업": 5.0,
        "정유업": 3.0,
        "방산업": 3.0,
        "음식료업": 3.0,
    }
    s += industry_premium.get(industry, 0.0)

    return clamp(s, 0.0, 99.0)

def score_non_financial(company: str,
                        raw_inputs: Dict[str, Any],
                        industry_override: Optional[str] = None,
                        weight_overrides: Optional[Dict[str, float]] = None,
                        hint_text: Optional[str] = None) -> Dict[str, Any]:

    industry, how = classify_industry(company, hint_text=hint_text)
    if industry_override:
        industry, how = industry_override, "override"

    base_factors = make_base_factors(total_base_weight=0.4)
    ind_cfg = INDUSTRY_REGISTRY.get(industry) or INDUSTRY_REGISTRY["반도체업"]
    industry_factors = ind_cfg.industry_factors

    if weight_overrides:
        for f in base_factors + industry_factors:
            if f.key in weight_overrides:
                f.weight = weight_overrides[f.key]

    def normalize(factors: List[Factor], target_sum: float):
        s = sum(max(0.0, f.weight) for f in factors) or 1.0
        for f in factors:
            f.weight = max(0.0, f.weight) / s * target_sum

    normalize(base_factors, 0.4)
    normalize(industry_factors, 0.6)

    details = {}
    total = 0.0
    for f in base_factors + industry_factors:
        s = f.scorer(raw_inputs)
        details[f.key] = {"name": f.name, "weight": f.weight, "score": s, "desc": f.desc}
        total += f.weight * s

    composite = total
    return {
        "industry": industry,
        "industry_classification_method": how,
        "non_financial_weighted_score": round(composite, 2),
        "factor_details": details
    }

def evaluate_company(company: str,
                     raw_inputs: Dict[str, Any],
                     industry_override: Optional[str] = None,
                     weight_overrides: Optional[Dict[str, float]] = None,
                     hint_text: Optional[str] = None,
                     external_scores: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:

    nf = score_non_financial(company, raw_inputs, industry_override, weight_overrides, hint_text)
    final_score = nf["non_financial_weighted_score"]
    industry_for_calib = nf.get("industry")
    final_score = calibrate_non_financial_score(company, industry_for_calib, raw_inputs, final_score)

    if external_scores and isinstance(external_scores, dict):
        w = external_scores.get("weights", {"non_financial": 1.0})
        nf_w = float(w.get("non_financial", 1.0))
        fin = external_scores.get("financial_score")
        news = external_scores.get("news_sentiment_score")
        fin_w = float(w.get("financial", 0.0))
        news_w = float(w.get("news", 0.0))
        weight_sum = nf_w + fin_w + news_w
        if weight_sum > 0:
            num = nf_w * final_score + (fin_w * fin if fin is not None else 0.0) + (news_w * news if news is not None else 0.0)
            final_score = num / weight_sum

    implied = to_rating(final_score)

    return {
        **nf,
        "final_score": round(final_score, 2),
        "implied_rating": implied
    }
