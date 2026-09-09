# /kiwoom_finance/metrics.py
from __future__ import annotations

import re
import calendar
from typing import List, Optional, Tuple, Dict, Any
import numpy as np
import pandas as pd

from .aliases import (
    _normalize_name, _sum_all_aliases, _resolve_numeric_series,
    KOR_KEY_ALIASES,
    _AR_ALIASES, _BORROWINGS_ALIASES,
    _COGS_ALIASES, _sum_cf_aliases,
)

METRICS_VERSION = "2.6.2-portal-align-annual-only-safe"

TARGET_FEATURES = [
    "debt_ratio", "equity_ratio", "debt_dependency_ratio",
    "operating_margin", "net_profit_margin", "roe", "roa",
    "current_ratio", "quick_ratio", "interest_coverage_ratio",
    "cfo_to_total_debt", "free_cash_flow",
    "total_asset_turnover", "accounts_receivable_turnover", "inventory_turnover",
    "sales_growth_rate", "operating_income_growth_rate", "total_asset_growth_rate",
]

FCF_FALLBACK_TO_CFO = True
USE_CF_INTEREST_PAID = True
EQUITY_BASIS = "total"   # total | parent
QUICK_MODE = "portal"    # portal: quick = CA - Inventory

# ---------- 유틸 ----------
def _nonempty_list(x) -> bool:
    return isinstance(x, (list, tuple)) and len(x) > 0

def _safe_div(a: Optional[pd.Series], b: Optional[pd.Series], idx: pd.Index) -> Optional[pd.Series]:
    if not isinstance(a, pd.Series) or not isinstance(b, pd.Series):
        return None
    a = a.reindex(idx).astype(float); b = b.reindex(idx).astype(float)
    with np.errstate(divide="ignore", invalid="ignore"):
        out = a / b
    return out.replace([np.inf, -np.inf], np.nan)

def _looks_like_annual_label(raw_label: str) -> bool:
    s = str(raw_label)
    return bool(re.search(r"(FY|연간|Annual|/12\(?E?\)?$|\(E\))", s, re.IGNORECASE))

def _unify_df_index_yyyymmdd(df: Optional[pd.DataFrame]) -> Optional[pd.DataFrame]:
    if not isinstance(df, pd.DataFrame) or df.empty: return df
    df2 = df.copy()
    raw = df2.index.astype(str)
    new_idx, pri = [], []
    for v in raw:
        digits = re.sub(r"\D", "", v)
        if len(digits) >= 8:
            yyyymmdd = digits[:8]
        elif len(digits) == 6:
            y = int(digits[:4]); m = int(digits[4:6]); d = calendar.monthrange(y, m)[1]
            yyyymmdd = f"{y:04d}{m:02d}{d:02d}"
        elif len(digits) >= 4:
            y = int(digits[:4]); yyyymmdd = f"{y:04d}1231"
        else:
            yyyymmdd = v
        new_idx.append(yyyymmdd)
        pri.append(0 if (_looks_like_annual_label(v) or yyyymmdd[4:6] == "12") else 1)
    df2.index = pd.Index(new_idx, dtype="object")
    df2["_pri___"] = pri
    df2 = df2.sort_values(by=["_pri___"]).drop(columns=["_pri___"], errors="ignore")
    df2 = df2[~df2.index.duplicated(keep="first")]
    return df2

def _prev_year_aligned(s: Optional[pd.Series]) -> Optional[pd.Series]:
    if not isinstance(s, pd.Series) or s.empty: return None
    idx = s.index.astype(str)
    vals = []
    for key in idx:
        if len(key) >= 8 and key[:4].isdigit():
            y, m, d = int(key[:4]), int(key[4:6]), int(key[6:8])
            py = y - 1
            last = calendar.monthrange(py, m)[1]
            prev_key = f"{py:04d}{m:02d}{min(d, last):02d}"
            vals.append(float(s.get(prev_key, np.nan)))
        else:
            vals.append(np.nan)
    return pd.Series(vals, index=idx, dtype=float)

def _avg_two_point(s: Optional[pd.Series]) -> Optional[pd.Series]:
    if not isinstance(s, pd.Series) or s.empty: return None
    prev = _prev_year_aligned(s)
    if not isinstance(prev, pd.Series): return None
    out = (s.astype(float) + prev.astype(float)) / 2.0
    out[prev.isna()] = np.nan
    return out

def _growth_yoy(cur: Optional[pd.Series], idx: pd.Index) -> Optional[pd.Series]:
    if not isinstance(cur, pd.Series) or cur.empty: return None
    prev = _prev_year_aligned(cur)
    if prev is None: return None
    cur = cur.reindex(idx).astype(float); prev = prev.reindex(idx).astype(float)
    with np.errstate(divide="ignore", invalid="ignore"):
        out = (cur - prev) / prev
    return out.replace([np.inf, -np.inf], np.nan)

# ---------- IS 선택기 ----------
_STRICT_SALES = ["매출액", "수익(매출액)", "매출", "매출수익", "매출액(수익)"]

def _pick_revenue_strict(isf: Optional[pd.DataFrame], cis: Optional[pd.DataFrame]) -> Optional[pd.Series]:
    def _from(df: Optional[pd.DataFrame]) -> Optional[pd.Series]:
        if not isinstance(df, pd.DataFrame) or df.empty:
            return None
        cols = list(df.columns)
        cand = [c for c in cols if ("매출액" in str(c)) or (str(c) in _STRICT_SALES)]
        if not (isinstance(cand, list) and len(cand) > 0):
            return None
        # "매출액" 포함 → 그 외 순으로 우선
        cand = sorted(cand, key=lambda c: (0 if "매출액" in str(c) else 1, -len(str(c))))
        for c in cand:
            s = pd.to_numeric(df[c], errors="coerce")
            if int(s.notna().sum()) > 0:
                return s
        return None

    # ❌ Series에 대해 or 사용 금지 → 명시적으로 선택
    s1 = _from(isf)
    if isinstance(s1, pd.Series) and int(s1.notna().sum()) > 0:
        return s1
    s2 = _from(cis)
    if isinstance(s2, pd.Series) and int(s2.notna().sum()) > 0:
        return s2
    return None

def _pick_single_best(df: Optional[pd.DataFrame], aliases: List[str], prefer_kw: List[str] | None = None, avoid_kw: List[str] | None = None) -> Optional[pd.Series]:
    if not isinstance(df, pd.DataFrame) or df.empty or not _nonempty_list(aliases): return None
    norm_alias = {_normalize_name(a) for a in aliases if a}
    cols = list(df.columns)
    cand = [c for c in cols if _normalize_name(c) in norm_alias]
    if not _nonempty_list(cand): return None
    if _nonempty_list(avoid_kw):
        filtered = [c for c in cand if not any(k in str(c) for k in avoid_kw)]
        cand = filtered if _nonempty_list(filtered) else cand
    best, score = None, (-1, -1, -10**9)
    for c in cand:
        s = pd.to_numeric(df[c], errors="coerce"); nn = int(s.notna().sum())
        prefer_hit = 1 if (_nonempty_list(prefer_kw) and any(k in str(c) for k in prefer_kw)) else 0
        sc = (nn, prefer_hit, -len(str(c)))
        if sc > score: best, score = s, sc
    return best

def _pick_total_else_components(df: Optional[pd.DataFrame], total_aliases: List[str], component_aliases: List[str]) -> Optional[pd.Series]:
    if not isinstance(df, pd.DataFrame) or df.empty: return None
    cols = list(df.columns)
    norm_total = {_normalize_name(a) for a in total_aliases if a}
    tcols = [c for c in cols if _normalize_name(c) in norm_total]
    if len(tcols) > 0:
        best, cnt = None, -1
        for c in tcols:
            s = pd.to_numeric(df[c], errors="coerce"); n = int(s.notna().sum())
            if n > cnt: best, cnt = s, n
        return best
    norms = {_normalize_name(a) for a in component_aliases if a}
    pick = [c for c in cols if _normalize_name(c) in norms]
    if len(pick) == 0: return None
    return df[pick].apply(pd.to_numeric, errors="coerce").sum(axis=1, min_count=1)

def _pick_trade_ar_strict(bs: Optional[pd.DataFrame]) -> Optional[pd.Series]:
    if not isinstance(bs, pd.DataFrame) or bs.empty: return None
    cols = list(bs.columns)
    pure = [c for c in cols if ("매출채권" in str(c)) and ("기타" not in str(c))]
    if len(pure) > 0:
        best, cnt = None, -1
        for c in pure:
            s = pd.to_numeric(bs[c], errors="coerce"); n = int(s.notna().sum())
            if n > cnt: best, cnt = s, n
        return best
    return _sum_all_aliases(bs, _AR_ALIASES)

# ---------- 메인 ----------
def compute_metrics_df_flat_kor(
    bs_flat_df: Optional[pd.DataFrame],
    is_flat_df: Optional[pd.DataFrame] = None,
    cis_flat_df: Optional[pd.DataFrame] = None,
    cf_flat_df: Optional[pd.DataFrame] = None,
    key_cols: Optional[List[str]] = None,
    return_debug: bool = False,
):
    if not isinstance(bs_flat_df, pd.DataFrame) or bs_flat_df.empty:
        out = pd.DataFrame(columns=TARGET_FEATURES)
        return (out, {"notes": ["empty bs_flat_df"]}) if return_debug else out

    # 0) 인덱스 통일
    bs  = _unify_df_index_yyyymmdd(bs_flat_df)
    isf = _unify_df_index_yyyymmdd(is_flat_df)  if isinstance(is_flat_df,  pd.DataFrame) else None
    cis = _unify_df_index_yyyymmdd(cis_flat_df) if isinstance(cis_flat_df, pd.DataFrame) else None
    cf  = _unify_df_index_yyyymmdd(cf_flat_df)  if isinstance(cf_flat_df,  pd.DataFrame) else None

    # 0-1) 연간(12월)만
    def _annual_only(df: Optional[pd.DataFrame]) -> Optional[pd.DataFrame]:
        if not isinstance(df, pd.DataFrame) or df.empty: return df
        m = df.index.to_series().astype(str).str[4:6] == "12"
        return df.loc[m].copy()
    bs = _annual_only(bs)
    if isinstance(isf, pd.DataFrame): isf = _annual_only(isf)
    if isinstance(cis, pd.DataFrame): cis = _annual_only(cis)
    if isinstance(cf,  pd.DataFrame): cf  = _annual_only(cf)

    if not isinstance(bs, pd.DataFrame) or bs.empty:
        out = pd.DataFrame(columns=TARGET_FEATURES)
        return (out, {"notes": ["no annual rows"]}) if return_debug else out

    union_idx = pd.Index(bs.index.astype(str), dtype="object")

    # 1) BS 핵심
    ca  = _pick_total_else_components(bs, KOR_KEY_ALIASES["current_assets"], [])
    cl  = _pick_total_else_components(bs, KOR_KEY_ALIASES["current_liabilities"], [])
    ta  = _pick_total_else_components(bs, KOR_KEY_ALIASES["total_assets"], [])
    tl  = _pick_total_else_components(bs, KOR_KEY_ALIASES["total_liabilities"], [])
    eq_parent = _pick_total_else_components(bs, KOR_KEY_ALIASES.get("equity_parent", []), [])
    eq_total  = _pick_total_else_components(bs, KOR_KEY_ALIASES["equity_total"], [])
    if EQUITY_BASIS == "parent" and isinstance(eq_parent, pd.Series) and int(eq_parent.notna().sum()) > 0:
        eq = eq_parent
    else:
        eq = eq_total

    # 2) 재고 / AR / 차입
    inventory = _pick_total_else_components(bs, ["재고자산","재고자산총계","재고자산 총계"],
                                                ["상품","제품","원재료","재공품","반제품","저장품"])
    if isinstance(inventory, pd.Series) and isinstance(ca, pd.Series):
        # cap: 재고 ≤ 유동자산
        inventory = pd.concat([inventory.astype(float), ca.astype(float)], axis=1).min(axis=1)
    ar_turn = _pick_trade_ar_strict(bs)
    borrowings = _sum_all_aliases(bs, _BORROWINGS_ALIASES)

    # 3) IS/CIS
    r   = _pick_revenue_strict(isf, cis)
    oi  = _pick_single_best(isf, KOR_KEY_ALIASES["operating_income"], prefer_kw=["영업이익"], avoid_kw=["총포괄"]) if isinstance(isf, pd.DataFrame) else None
    cogs= _pick_single_best(isf, _COGS_ALIASES) if isinstance(isf, pd.DataFrame) else None

    net_is  = _pick_single_best(isf, KOR_KEY_ALIASES["net_income"], prefer_kw=["지배","소유주"], avoid_kw=["총포괄","포괄"]) if isinstance(isf, pd.DataFrame) else None
    net_cis = _pick_single_best(cis, KOR_KEY_ALIASES["net_income"], prefer_kw=["지배","소유주"], avoid_kw=["총포괄","포괄"]) if isinstance(cis, pd.DataFrame) else None
    net_income = net_is if (isinstance(net_is, pd.Series) and int(net_is.notna().sum()) > 0) else net_cis

    # 금융비용: 이자비용 우선
    fin_pref = _pick_single_best(isf, ["이자비용","이자비용(손실)","이자비용및유사비용"]) if isinstance(isf, pd.DataFrame) else None
    finance_costs = fin_pref if (isinstance(fin_pref, pd.Series) and int(fin_pref.notna().sum()) > 0) else (
        _pick_single_best(isf, KOR_KEY_ALIASES["finance_costs"]) if isinstance(isf, pd.DataFrame) else None
    )

    # 4) CF (중복 호출 방지)
    if isinstance(cf, pd.DataFrame):
        cfo_series = _sum_cf_aliases(cf, "cfo")
        capex_series = _sum_cf_aliases(cf, "capex")
        int_paid_series = _sum_cf_aliases(cf, "interest_paid")
        cfo = cfo_series if isinstance(cfo_series, pd.Series) else None
        capex = capex_series if isinstance(capex_series, pd.Series) else None
        interest_paid_cf = int_paid_series.abs() if isinstance(int_paid_series, pd.Series) else None
    else:
        cfo = capex = interest_paid_cf = None

    # 5) 인덱스 맞추기
    def _on_idx(x): return x.reindex(union_idx) if isinstance(x, pd.Series) else None
    ca, cl, ta, tl, eq = map(_on_idx, [ca, cl, ta, tl, eq])
    r, oi, cogs, net_income, finance_costs = map(_on_idx, [r, oi, cogs, net_income, finance_costs])
    ar_turn, inventory = map(_on_idx, [ar_turn, inventory])
    cfo, capex, interest_paid_cf = map(_on_idx, [cfo, capex, interest_paid_cf])

    # 6) 평균(2점 평균)
    avg_assets = _avg_two_point(ta)
    avg_equity = _avg_two_point(eq)
    avg_ar     = _avg_two_point(ar_turn)
    avg_inv    = _avg_two_point(inventory)

    # 7) 당좌자산
    if QUICK_MODE == "portal":
        if isinstance(ca, pd.Series):
            inv0 = inventory if isinstance(inventory, pd.Series) else pd.Series(0.0, index=union_idx, dtype=float)
            quick_assets = ca.astype(float) - inv0.astype(float)
        else:
            quick_assets = None
        quick_dbg = {"mode": "portal"}
    else:
        quick_assets, quick_dbg = None, {"mode": "n/a"}

    # 8) 부채 분모
    debt_den = borrowings if (isinstance(borrowings, pd.Series) and int(borrowings.notna().sum()) > 0) else tl
    if not isinstance(debt_den, pd.Series): debt_den = pd.Series(0.0, index=union_idx, dtype=float)
    capex_abs = capex.abs() if isinstance(capex, pd.Series) else None

    # 9) 지표 계산
    metrics: Dict[str, Optional[pd.Series]] = {}
    metrics["debt_ratio"]   = _safe_div(tl, eq, union_idx)
    metrics["equity_ratio"] = _safe_div(eq, ta, union_idx)
    metrics["debt_dependency_ratio"] = _safe_div(tl, ta, union_idx)

    metrics["operating_margin"]  = _safe_div(oi, r, union_idx)
    metrics["net_profit_margin"] = _safe_div(net_income, r, union_idx)
    metrics["roe"]               = _safe_div(net_income, avg_equity, union_idx)
    metrics["roa"]               = _safe_div(net_income, avg_assets, union_idx)

    metrics["total_asset_turnover"]         = _safe_div(r, avg_assets, union_idx)
    metrics["accounts_receivable_turnover"] = _safe_div(r, avg_ar, union_idx)
    metrics["inventory_turnover"]           = _safe_div(cogs, avg_inv, union_idx)

    metrics["sales_growth_rate"]            = _growth_yoy(r,  union_idx)
    metrics["operating_income_growth_rate"] = _growth_yoy(oi, union_idx)
    metrics["total_asset_growth_rate"]      = _growth_yoy(ta, union_idx)

    metrics["cfo_to_total_debt"] = _safe_div(cfo, debt_den, union_idx)
    metrics["current_ratio"]     = _safe_div(ca,  cl, union_idx)
    metrics["quick_ratio"]       = _safe_div(quick_assets, cl, union_idx)

    icr_primary = _safe_div(oi, finance_costs, union_idx)
    icr_alt = _safe_div(oi, interest_paid_cf, union_idx) if USE_CF_INTEREST_PAID else None
    metrics["interest_coverage_ratio"] = icr_primary if (isinstance(icr_primary, pd.Series) and int(icr_primary.notna().sum()) > 0) else icr_alt

    if isinstance(cfo, pd.Series) and isinstance(capex_abs, pd.Series):
        metrics["free_cash_flow"] = cfo.astype(float) - capex_abs.astype(float)
    elif isinstance(cfo, pd.Series) and FCF_FALLBACK_TO_CFO:
        metrics["free_cash_flow"] = cfo.astype(float)
    else:
        metrics["free_cash_flow"] = None

    # 10) 출력
    out = pd.DataFrame(index=union_idx); out.index.name = "date"
    for k in TARGET_FEATURES: out[k] = metrics.get(k, np.nan)
    try:
        out = out.sort_index(ascending=False, key=lambda s: pd.to_datetime(s, format="%Y%m%d", errors="coerce"))
    except Exception:
        out = out.sort_index(ascending=False)

    if return_debug:
        debug: Dict[str, Any] = {
            "version": METRICS_VERSION,
            "basis": {"equity_basis": EQUITY_BASIS, "quick_mode": QUICK_MODE, "avg_method": "two_point", "annual_only": True},
            "quick": quick_dbg,
            "picks": {
                "CA": ca, "CL": cl, "TA": ta, "TL": tl, "EQ": eq,
                "REV": r, "OI": oi, "COGS": cogs,
                "NET": net_income, "FIN_COSTS": finance_costs,
                "AR": ar_turn, "INV": inventory,
                "CFO": cfo, "CAPEX": capex, "INT_PAID": interest_paid_cf,
                "DEBT_DEN": debt_den,
            },
        }
        try:
            bal_err = (ta.astype(float) - (tl.astype(float) + eq.astype(float))).abs()
            debug["balance_identity_error"] = (bal_err / ta.replace(0, np.nan))
        except Exception:
            debug["balance_identity_error"] = "n/a"
        return out, debug

    return out
