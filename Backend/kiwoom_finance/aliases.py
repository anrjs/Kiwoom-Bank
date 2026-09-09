# src/kiwoom_finance/aliases.py

import re
import numpy as np
import pandas as pd
from typing import List, Optional

# ================================
# 문자열 정규화 / 기본 유틸
# ================================
def _normalize_name(s: str) -> str:
    if s is None:
        return ""
    s = str(s)
    # 공백/구분자/괄호/하이픈/슬래시 제거
    s = re.sub(r"\s+", "", s)
    s = s.replace(",", "").replace("·", "")
    # 괄호 안 텍스트는 보존하되 괄호만 제거 (기존 로직 유지)
    s = s.replace("(", "").replace(")", "")
    s = s.replace("/", "").replace("-", "")
    # 전각 → 반각
    s = s.translate(str.maketrans("％：－＋．，", "%:-+.,"))
    return s

def _to_numeric_safe_series(s: pd.Series) -> pd.Series:
    return pd.to_numeric(s, errors="coerce")

# ================================
# 컬럼 매칭 강화: 부분일치/양방향 포함 + '총계/합계/계' 허용
# ================================
def _col_matches(col_norm: str, alias_norm: str) -> bool:
    if not col_norm or not alias_norm:
        return False
    if col_norm == alias_norm:
        return True
    # '계' 변형 허용: 총계/합계/계
    def strip_gae(x: str) -> str:
        return re.sub(r"(총계|합계|계)$", "", x)
    c0 = strip_gae(col_norm)
    a0 = strip_gae(alias_norm)
    if not c0 or not a0:
        c0, a0 = col_norm, alias_norm
    # 양방향 부분 포함 허용
    if a0 in c0 or c0 in a0:
        return True
    # 숫자/기호 섞인 꾸밈 제거 후 다시 검사 (예: IFRS연결, 제55기 등)
    c1 = re.sub(r"[0-9①-⑳Ⅰ-ⅫIVXivx期기분호년월일_]+", "", c0)
    a1 = re.sub(r"[0-9①-⑳Ⅰ-ⅫIVXivx期기분호년월일_]+", "", a0)
    return (a1 in c1) or (c1 in a1)

def _pick_columns_by_aliases(df: pd.DataFrame, aliases: List[str]) -> List[str]:
    alias_norms = [_normalize_name(a) for a in aliases if a is not None]
    pick_cols: List[str] = []
    for c in df.columns:
        cn = _normalize_name(c)
        for an in alias_norms:
            if _col_matches(cn, an):
                pick_cols.append(c)
                break
    return pick_cols

# ================================
# 중복 컬럼 안전 sum (강화 매칭 적용)
# ================================
def _resolve_numeric_series(df: pd.DataFrame, colname: str) -> Optional[pd.Series]:
    """
    colname(정규화 기준)과 '부분일치 허용'으로 매칭되는 모든 컬럼을
    숫자 변환 후 행합(axis=1)으로 단일 Series 반환.
    """
    if not isinstance(df, pd.DataFrame) or df.empty:
        return None
    cols = _pick_columns_by_aliases(df, [colname])
    if not cols:
        return None
    sub = df[cols]
    if isinstance(sub, pd.DataFrame):
        sub_num = sub.apply(pd.to_numeric, errors="coerce")
        out = sub_num.sum(axis=1, min_count=1)
        return out
    return pd.to_numeric(sub, errors="coerce")

def _sum_all_aliases(df: pd.DataFrame, aliases: List[str]) -> Optional[pd.Series]:
    """
    aliases(여러 별칭)과 '부분일치 허용'으로 매칭되는 모든 컬럼을 모아
    숫자 변환 후 행합(axis=1)으로 단일 Series 반환.
    """
    if not isinstance(df, pd.DataFrame) or df.empty or not aliases:
        return None
    pick_cols = _pick_columns_by_aliases(df, aliases)
    if not pick_cols:
        return None
    sub = df[pick_cols]
    sub_num = sub.apply(pd.to_numeric, errors="coerce")
    out = sub_num.sum(axis=1, min_count=1)
    return out

# ================================
# 별칭 사전 (BS/IS/CIS/CF)
# ================================
KOR_KEY_ALIASES = {
    # ===== BS =====
    "current_assets": [
        "유동자산", "유동자산총계", "유동자산 총계", "유동자산총액", "유동자산 합계", "유동자산계"
    ],
    "current_liabilities": [
        # 총계/대체총계만 허용 (부분항목 제외)
        "유동부채", "유동부채총계", "유동부채 총계", "유동부채총액", "유동부채 합계", "유동부채계",
        "단기부채", "단기부채총계", "단기부채 총계"
    ],
    "noncurrent_liabilities": ["비유동부채"],
    "total_liabilities": [
        "부채총계", "부채 총계", "부채총액", "부채 합계", "부채계"
    ],
    "equity_total": [
        "자본총계", "자본 총계", "자본총액", "자본 합계", "자본계"
    ],
    "equity_parent": [
        "지배기업소유주지분", "지배기업 소유주지분", "지배기업의소유주에게귀속되는자본",
        "지배기업의 소유주에게 귀속되는 자본", "지배기업의소유지분", "지배기업 소유지분"
    ],
    "equity_nci": ["비지배지분", "비지배주주지분"],
    "total_assets": [
        "자산총계", "자산 총계", "자산총액", "자산 합계", "자산계",
        "부채와자본총계", "부채와 자본 총계", "자산과부채총계", "부채및자본총계", "자본과부채총계"
    ],

    # ===== IS / CIS =====
    "revenue": [
        "매출액", "영업수익", "수익", "수익(매출액)", "매출", "매출액(수익)", "매출수익"
    ],
    "operating_income": [
        "영업이익", "영업손익", "영업이익(손실)", "영업(손)익", "영업이익손실"
    ],
    "operating_income_preLLP": [
        "신용손실충당금전영업이익", "대손충당금전영업이익", "신용손실충당금반영전영업이익"
    ],
    "credit_loss": [
        "신용손실충당금전입액", "대손충당금전입액", "대손상각비"
    ],
    "finance_costs": [
        # 이자비용 계정을 우선(순액/합계는 후순위)
        "이자비용", "이자비용(손실)", "이자비용및유사비용",
        "이자비용및수수료", "이자비용등",
        "금융비용", "금융원가", "금융비용합계", "이자비용순액"
    ],
    "net_income": [
        "당기순이익", "당기순손익", "당기순이익(손실)",
        "분기순이익", "분기순손익", "반기순이익", "반기순손익",
        "연결당기순이익", "연결당기순손익",
        "지배기업의소유주에게귀속되는당기순이익",
        "지배기업의 소유주에게 귀속되는 당기순이익",
        "지배기업의 소유주에게 귀속되는 당기순이익(손실)",
        "지배주주지분순이익", "지배주주순이익",
        "지배기업 소유주지분 순이익"
    ],
    "tci_total": [
        "총포괄손익", "총포괄손익(손실)", "당기총포괄손익",
        "지배기업의 소유주에게 귀속되는 총포괄손익",
        "지배기업의 소유주에게 귀속되는 총포괄손익(손실)",
    ],

    # (금융업 세부 – 필요 시 확장)
    "interest_income": ["이자이익", "이자수익"],
    "fee_income": ["수수료이익", "수수료수익"],
    "insurance_revenue": ["보험료수익", "보험수익"],
}

# ================================
# 회전율/차입 등 기타 별칭
# ================================
_INVENTORY_TOTAL_ALIASES = ["재고자산", "재고자산총계", "재고자산 총계", "재고자산합계", "재고자산계"]
_INVENTORY_COMPONENT_ALIASES = ["상품", "제품", "원재료", "재공품"]

_AR_ALIASES = [
    "매출채권", "외상매출금", "장기성매출채권", "기타채권",
    "매출채권및기타채권", "유동매출채권", "비유동매출채권",
    "단기매출채권", "장기매출채권",
    "기타수취채권"
]

_BORROWINGS_ALIASES = [
    "차입금", "단기차입금", "장기차입금", "유동차입금", "비유동차입금",
    "유동성장기부채", "유동성장기차입금",
    "사채", "유동성사채",
    "리스부채", "단기리스부채", "장기리스부채", "유동리스부채",
    "기타금융부채", "단기금융부채", "장기금융부채",
    "장기성미지급금", "사채및차입금"
]

_COGS_ALIASES = ["매출원가"]

_DA_ALIASES = [
    "감가상각비", "무형자산상각비", "상각비",
    "감가상각및무형자산상각비", "감가상각및무형자산상각", "감가상각비등",
    "감가상각비(+)", "무형자산상각비(+)", "상각", "무형자산상각"
]

_EBITDA_ALIASES = ["EBITDA", "상각전영업이익"]

# ================================
# 금융업 판정 키워드
# ================================
_FIN_MARKERS = [
    "대출채권", "보험계약부채", "재보험계약부채", "투자계약부채", "예수부채", "보험계약자산"
]

def _is_financial_institution(bs: Optional[pd.DataFrame], cf: Optional[pd.DataFrame]) -> bool:
    def _norms(df: Optional[pd.DataFrame]):
        if not isinstance(df, pd.DataFrame) or df.empty:
            return set()
        return {_normalize_name(c) for c in df.columns}
    cols = _norms(bs) | _norms(cf)
    for m in _FIN_MARKERS:
        if _normalize_name(m) in cols:
            return True
    return False

# ================================
# CF 별칭
# ================================
CF_KEY_ALIASES = {
    "cfo": [
        "영업활동현금흐름", "영업활동 현금흐름",
        "영업으로부터 창출된 현금흐름", "영업에서창출된현금흐름",
        "영업활동으로인한현금흐름", "영업활동으로 인한 현금흐름",
        "영업활동으로부터의현금흐름(순액)", "영업활동으로부터의현금흐름",
        "영업활동으로부터의순현금흐름",
        "영업활동현금흐름간접법", "영업활동현금흐름직접법",
        "영업현금흐름",
        "영업으로부터창출된현금", "영업으로부터창출된현금흐름",
        "영업으로부터창출된현금흐름(순액)"
    ],
    "da": [
        "감가상각비", "무형자산상각비", "상각비",
        "감가상각및무형자산상각", "감가상각비(+)", "무형자산상각비(+)"
    ],
    "capex": [
        "유형자산의 취득", "유형자산의취득",
        "무형자산의 취득", "무형자산의취득",
        "투자부동산의 취득", "투자부동산의취득",
        "기타유형자산의 취득", "기타유형자산의취득"
    ],
    "interest_paid": [
        "이자의 지급", "이자의지급", "이자지급", "이자지급액",
        "이자비용의 지급", "이자비용지급",
        "이자지급(영업)", "이자의 지급(영업)", "이자지급(영업활동)",
        "이자지급(재무활동)",
        "이자지급액(순액)", "이자지급(순액)"
    ],
}

def _sum_cf_aliases(df: Optional[pd.DataFrame], key: str) -> Optional[pd.Series]:
    if not isinstance(df, pd.DataFrame) or df.empty:
        return None
    aliases = CF_KEY_ALIASES.get(key, [])
    return _sum_all_aliases(df, aliases)