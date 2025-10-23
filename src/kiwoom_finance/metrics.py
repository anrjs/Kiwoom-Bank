# src/kiwoom_finance/metrics.py
import re
import numpy as np
import pandas as pd
import calendar
from typing import List, Optional, Tuple, Dict, Any

from .aliases import (
    _normalize_name, _sum_all_aliases, _resolve_numeric_series, _is_financial_institution,
    KOR_KEY_ALIASES, _INVENTORY_ALIASES, _AR_ALIASES, _BORROWINGS_ALIASES,
    _COGS_ALIASES, _DA_ALIASES, _EBITDA_ALIASES, _sum_cf_aliases
)

# ============================================================
# 🔒 메트릭스 버전 (캐시 무효화 지문에 사용)
# ============================================================
METRICS_VERSION = "1.2.0"

# ============================================================
# ⚙️ 산출 대상 피처 (batch.DEFAULT_COLS와 합치)
# ============================================================
TARGET_FEATURES = [
    # 수익성/레버리지
    "debt_ratio", "equity_ratio", "debt_dependency_ratio",
    "operating_margin", "net_profit_margin", "roe", "roa",
    # 유동성/커버리지
    "current_ratio", "quick_ratio", "interest_coverage_ratio",
    # 현금흐름/부채
    "cfo_to_total_debt", "ebitda_to_total_debt", "free_cash_flow",
    # 효율성/성장성
    "total_asset_turnover", "accounts_receivable_turnover", "inventory_turnover",
    "sales_growth_rate", "operating_income_growth_rate", "total_asset_growth_rate",
]

# ============================================================
# 🧩 NaN 억제용 옵션 (필요시 조정)
# ============================================================
SOFT_IMPUTE = True          # 평균/분모 부족 시 완화(전년 없으면 당기값 사용)
FCF_FALLBACK_TO_CFO = True  # CapEx 집계 실패 시 FCF=CFO 로 보수 대체
USE_CF_INTEREST_PAID = True # 이자보상배율 대체식: EBITDA / |이자지급(CF)|

# ============================================================
# 🔧 내부 유틸리티
# ============================================================

def _ensure_series(s: Optional[pd.Series], index: pd.Index) -> Optional[pd.Series]:
    if not isinstance(s, pd.Series):
        return None
    out = s.copy()
    out.index = out.index.astype(str)
    ix = pd.Index(index.astype(str), dtype="object")
    return out.reindex(ix)

def _safe_div(a: Optional[pd.Series], b: Optional[pd.Series], idx: pd.Index) -> Optional[pd.Series]:
    a_ = _ensure_series(a, idx)
    b_ = _ensure_series(b, idx)
    if a_ is None or b_ is None:
        return None
    with np.errstate(divide="ignore", invalid="ignore"):
        out = a_.astype(float) / b_.astype(float)
        out = out.replace([np.inf, -np.inf], np.nan)
    return out

def _unify_df_index_yyyymmdd(df: pd.DataFrame) -> pd.DataFrame:
    df2 = df.copy()
    raw = df2.index.astype(str)
    new_idx = []
    for v in raw:
        digits = re.sub(r"\D", "", v)
        if len(digits) >= 8:
            new_idx.append(digits[:8])
        elif len(digits) == 6:
            y = int(digits[:4]); m = int(digits[4:6]); d = calendar.monthrange(y, m)[1]
            new_idx.append(f"{y:04d}{m:02d}{d:02d}")
        elif len(digits) >= 4:
            y = int(digits[:4]); new_idx.append(f"{y:04d}1231")
        else:
            new_idx.append(v)
    df2.index = pd.Index(new_idx, dtype="object")
    df2 = df2[~df2.index.duplicated(keep="last")]
    return df2

def _prev_year_aligned_to_current_strict(s: Optional[pd.Series]) -> Optional[pd.Series]:
    if not isinstance(s, pd.Series) or s.empty:
        return None
    def prev_key(yyyymmdd: str) -> Optional[str]:
        digits = re.sub(r"\D", "", str(yyyymmdd))
        if len(digits) < 8:
            return None
        y = int(digits[:4]); m = int(digits[4:6]); d = int(digits[6:8])
        py = y - 1
        last = calendar.monthrange(py, m)[1]
        pd_ = min(d, last)
        return f"{py:04d}{m:02d}{pd_:02d}"
    src_idx = set(s.index.astype(str))
    out_vals = []
    for cur in s.index.astype(str):
        pk = prev_key(cur)
        if pk is not None and pk in src_idx:
            out_vals.append(float(s.loc[pk]))
        else:
            out_vals.append(np.nan)
    return pd.Series(out_vals, index=s.index.astype(str), dtype=float)

def _avg_with_prev_year(s: Optional[pd.Series]) -> Optional[pd.Series]:
    """엄격: 전년 없으면 NaN."""
    if not isinstance(s, pd.Series) or s.empty:
        return None
    prev = _prev_year_aligned_to_current_strict(s)
    if not isinstance(prev, pd.Series):
        return None
    out = (s.astype(float) + prev.astype(float)) / 2.0
    out[prev.isna()] = np.nan
    return out

def _avg_with_prev_year_soft(s: Optional[pd.Series]) -> Optional[pd.Series]:
    """완화: 전년 없으면 당기값으로 평균 대체."""
    if not isinstance(s, pd.Series) or s.empty:
        return None
    prev = _prev_year_aligned_to_current_strict(s)
    if not isinstance(prev, pd.Series):
        # 전부 당기값으로라도 반환
        return s.astype(float)
    out = (s.astype(float) + prev.astype(float)) / 2.0
    # 전년이 NaN이면 당기값으로 대체
    mask = prev.isna()
    out[mask] = s.astype(float)[mask]
    return out

def _growth_rate_safe_strict(cur: Optional[pd.Series], union_idx: pd.Index) -> Optional[pd.Series]:
    if not isinstance(cur, pd.Series) or cur.empty:
        return None
    prev = _prev_year_aligned_to_current_strict(cur)
    cur_e  = _ensure_series(cur,  union_idx)
    prev_e = _ensure_series(prev, union_idx) if isinstance(prev, pd.Series) else None
    if cur_e is None or prev_e is None:
        return None
    diff = cur_e - prev_e
    out = _safe_div(diff, prev_e, union_idx)
    if isinstance(prev_e, pd.Series):
        out = out.where(prev_e.notna())
    return out

def _pick_first_valid(*args):
    for a in args:
        if isinstance(a, pd.Series) and a.notna().any():
            return a
    return None

def _coalesce_series(*cands: Optional[pd.Series]) -> Optional[pd.Series]:
    """값이 충분한 첫 번째 Series를 선택"""
    for s in cands:
        if isinstance(s, pd.Series) and s.notna().any():
            return s
    return None

def _safe_series_abs(s: Optional[pd.Series]) -> Optional[pd.Series]:
    return s.abs() if isinstance(s, pd.Series) else None


# ============================================================
# 📊 메인 계산 함수
# ============================================================

def compute_metrics_df_flat_kor(
    bs_flat_df: Optional[pd.DataFrame],
    is_flat_df: Optional[pd.DataFrame] = None,
    cis_flat_df: Optional[pd.DataFrame] = None,
    cf_flat_df: Optional[pd.DataFrame] = None,
    key_cols: Optional[List[str]] = None,
    return_debug: bool = False,
) -> pd.DataFrame | Tuple[pd.DataFrame, Dict[str, Any]]:

    if not isinstance(bs_flat_df, pd.DataFrame) or bs_flat_df.empty:
        out = pd.DataFrame(columns=TARGET_FEATURES)
        return (out, {"notes": ["empty bs_flat_df"]}) if return_debug else out

    # 인덱스 정규화
    bs  = _unify_df_index_yyyymmdd(bs_flat_df.copy())
    isf = _unify_df_index_yyyymmdd(is_flat_df.copy())  if isinstance(is_flat_df,  pd.DataFrame) else None
    cis = _unify_df_index_yyyymmdd(cis_flat_df.copy()) if isinstance(cis_flat_df, pd.DataFrame) else None
    cf  = _unify_df_index_yyyymmdd(cf_flat_df.copy())  if isinstance(cf_flat_df,  pd.DataFrame) else None

    # 핵심 계정 (BS)
    ca  = _sum_all_aliases(bs, KOR_KEY_ALIASES["current_assets"])
    cl  = _sum_all_aliases(bs, KOR_KEY_ALIASES["current_liabilities"])
    ta  = _sum_all_aliases(bs, KOR_KEY_ALIASES["total_assets"])
    tl  = _sum_all_aliases(bs, KOR_KEY_ALIASES["total_liabilities"])
    eq  = _sum_all_aliases(bs, KOR_KEY_ALIASES["equity_total"])

    inv = _sum_all_aliases(bs, _INVENTORY_ALIASES)
    ar  = _sum_all_aliases(bs, _AR_ALIASES)
    borrowings = _sum_all_aliases(bs, _BORROWINGS_ALIASES)  # 총차입금 후보

    # 손익 (IS/CIS)
    r   = _sum_all_aliases(isf, KOR_KEY_ALIASES["revenue"]) if isinstance(isf, pd.DataFrame) else None
    oi  = _sum_all_aliases(isf, KOR_KEY_ALIASES["operating_income"]) if isinstance(isf, pd.DataFrame) else None
    net_income = _sum_all_aliases(isf, KOR_KEY_ALIASES["net_income"]) if isinstance(isf, pd.DataFrame) else None
    if net_income is None:
        net_income = _sum_all_aliases(cis, KOR_KEY_ALIASES["net_income"]) if isinstance(cis, pd.DataFrame) else None

    finance_costs = _sum_all_aliases(isf, KOR_KEY_ALIASES["finance_costs"]) if isinstance(isf, pd.DataFrame) else None

    # 현금흐름 (CF)
    cfo   = _sum_cf_aliases(cf, "cfo") if isinstance(cf, pd.DataFrame) else None
    da_cf = _sum_cf_aliases(cf, "da") if isinstance(cf, pd.DataFrame) else None
    capex = _sum_cf_aliases(cf, "capex") if isinstance(cf, pd.DataFrame) else None
    # ⬇️ 이자지급(유출) 후보(CF) — aliases.py에 interest_paid 묶음이 있어야 함
    interest_paid_cf = _sum_cf_aliases(cf, "interest_paid") if isinstance(cf, pd.DataFrame) else None
    interest_paid_cf = _safe_series_abs(interest_paid_cf)

    # D&A (IS/CF 혼합)
    da_is = _sum_all_aliases(isf, _DA_ALIASES) if isinstance(isf, pd.DataFrame) else None
    da = _pick_first_valid(da_is, da_cf)

    # EBITDA
    ebitda_direct = _sum_all_aliases(isf, _EBITDA_ALIASES) if isinstance(isf, pd.DataFrame) else None
    if ebitda_direct is not None and ebitda_direct.notna().any():
        ebitda = ebitda_direct
    else:
        # EBITDA = 영업이익 + D&A (가능할 때)
        ebitda = None
        if isinstance(oi, pd.Series) and oi.notna().any():
            if isinstance(da, pd.Series) and da.notna().any():
                ebitda = oi.astype(float) + da.astype(float)

    # 인덱스 통일
    union_idx = pd.Index(bs.index.astype(str), dtype="object")
    def _on_idx(s): return _ensure_series(s, union_idx)

    ca, cl, ta, tl, eq = map(_on_idx, [ca, cl, ta, tl, eq])
    inv, ar, borrowings = map(_on_idx, [inv, ar, borrowings])
    r, oi, net_income, cfo, finance_costs, ebitda, capex = map(_on_idx, [r, oi, net_income, cfo, finance_costs, ebitda, capex])
    interest_paid_cf = _on_idx(interest_paid_cf)

    # 평균 계산 (soft/strict 선택)
    if SOFT_IMPUTE:
        avg_assets = _on_idx(_avg_with_prev_year_soft(ta))
        avg_equity = _on_idx(_avg_with_prev_year_soft(eq))
        avg_ar     = _on_idx(_avg_with_prev_year_soft(ar))
        avg_inv    = _on_idx(_avg_with_prev_year_soft(inv))
    else:
        avg_assets = _on_idx(_avg_with_prev_year(ta))
        avg_equity = _on_idx(_avg_with_prev_year(eq))
        avg_ar     = _on_idx(_avg_with_prev_year(ar))
        avg_inv    = _on_idx(_avg_with_prev_year(inv))

    # Quick 자산 (안전 처리)
    if isinstance(ca, pd.Series):
        inv0 = inv.fillna(0.0) if isinstance(inv, pd.Series) else pd.Series(0.0, index=ca.index, dtype=float)
        quick_assets = ca.astype(float).sub(inv0.astype(float), fill_value=0.0)
    else:
        quick_assets = None

    # 분모: 총차입금 → 부채총계 → 0
    debt_den = _pick_first_valid(borrowings, tl)
    if not isinstance(debt_den, pd.Series):
        debt_den = pd.Series(0.0, index=union_idx, dtype=float)

    # Capex 절대지출로 처리(부호 무관)
    capex_abs = capex.abs() if isinstance(capex, pd.Series) else None

    # =========================
    # 피처 계산
    # =========================
    metrics: Dict[str, Optional[pd.Series]] = {}

    # 레버리지/자본구조
    metrics["debt_ratio"]            = _safe_div(tl, eq, union_idx)
    metrics["equity_ratio"]          = _safe_div(eq, ta, union_idx)
    metrics["debt_dependency_ratio"] = _safe_div(tl, ta, union_idx)

    # 수익성/효율성
    metrics["operating_margin"]          = _safe_div(oi, r, union_idx)
    metrics["net_profit_margin"]         = _safe_div(net_income, r, union_idx)
    metrics["roe"]                       = _safe_div(net_income, avg_equity, union_idx)
    metrics["roa"]                       = _safe_div(net_income, avg_assets, union_idx)
    metrics["total_asset_turnover"]      = _safe_div(r, avg_assets, union_idx)
    metrics["accounts_receivable_turnover"] = _safe_div(r, avg_ar, union_idx)
    metrics["inventory_turnover"]        = _safe_div(r, avg_inv, union_idx)

    # 성장성 (엄격 성장률: 전년 키가 정확히 매칭될 때만)
    metrics["sales_growth_rate"]            = _growth_rate_safe_strict(r,  union_idx)
    metrics["operating_income_growth_rate"] = _growth_rate_safe_strict(oi, union_idx)
    metrics["total_asset_growth_rate"]      = _growth_rate_safe_strict(ta, union_idx)

    # 현금흐름/커버리지
    metrics["cfo_to_total_debt"] = _safe_div(cfo, debt_den, union_idx)
    metrics["current_ratio"]     = _safe_div(ca,  cl, union_idx)
    metrics["quick_ratio"]       = _safe_div(quick_assets, cl, union_idx)

    # 이자보상배율: 1) OI / 금융비용  2) (옵션) EBITDA / |이자지급(CF)|
    icr_primary = _safe_div(oi, finance_costs, union_idx)
    icr_alt = _safe_div(ebitda, interest_paid_cf, union_idx) if USE_CF_INTEREST_PAID else None
    metrics["interest_coverage_ratio"] = _coalesce_series(icr_primary, icr_alt)

    # EBITDA / 총부채
    metrics["ebitda_to_total_debt"] = _safe_div(ebitda, debt_den, union_idx)

    # FCF = CFO - |CapEx|; CapEx 없으면 선택적으로 FCF=CFO
    if isinstance(cfo, pd.Series) and isinstance(capex_abs, pd.Series):
        metrics["free_cash_flow"] = (cfo.astype(float) - capex_abs.astype(float))
    elif isinstance(cfo, pd.Series) and FCF_FALLBACK_TO_CFO:
        metrics["free_cash_flow"] = cfo.astype(float)
    else:
        metrics["free_cash_flow"] = None

    # =========================
    # 출력
    # =========================
    out = pd.DataFrame(index=union_idx)
    out.index.name = "date"

    for k in TARGET_FEATURES:
        out[k] = metrics.get(k, np.nan)

    try:
        out = out.sort_index(ascending=False, key=lambda s: pd.to_datetime(s, format="%Y%m%d", errors="coerce"))
    except Exception:
        out = out.sort_index(ascending=False)

    return out
