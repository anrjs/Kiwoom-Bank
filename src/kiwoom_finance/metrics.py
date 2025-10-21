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
    if not isinstance(s, pd.Series) or s.empty:
        return None
    prev = _prev_year_aligned_to_current_strict(s)
    if not isinstance(prev, pd.Series):
        return None
    out = (s.astype(float) + prev.astype(float)) / 2.0
    out[prev.isna()] = np.nan
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

def _fallback_if_all_nan(cur: Optional[pd.Series], alt: Optional[pd.Series]) -> Optional[pd.Series]:
    if cur is None:
        return alt
    if isinstance(cur, pd.Series) and cur.notna().any():
        return cur
    return alt

def _match_cols(df: pd.DataFrame, aliases: List[str]) -> list:
    if not isinstance(df, pd.DataFrame) or df.empty:
        return []
    norms = {_normalize_name(a) for a in aliases}
    return [c for c in df.columns if _normalize_name(c) in norms]

# ===== 총계성 항목: 별칭 후보 중 '단일 컬럼' 선택 (합산 금지) =====
def _pick_single_from_aliases(df: Optional[pd.DataFrame], aliases: List[str]) -> Tuple[Optional[pd.Series], list]:
    """
    유동자산/유동부채/자산총계/부채총계/자본총계처럼 총계·합계 계정은 여러 별칭이 매칭되어도
    '한 열만' 고른다. (합산하면 중복가산 오류 발생)
    선택 기준:
    1) 별칭 정규화 매칭되는 후보만 수집
    2) non-null 개수가 가장 많은 열
    3) 동률이면 중앙값(|median|) 절대값이 큰 열
    반환: (선택된 Series or None, 후보 컬럼 리스트)
    """
    if not isinstance(df, pd.DataFrame) or df.empty:
        return None, []
    norms = {_normalize_name(a) for a in aliases if a}
    candidates = [c for c in df.columns if _normalize_name(c) in norms]
    if not candidates:
        return None, []

    sub = df[candidates].apply(pd.to_numeric, errors="coerce")
    nn = sub.notna().sum(axis=0)
    top = sub.loc[:, nn == nn.max()]
    med = top.median(axis=0, skipna=True).abs()
    pick_col = med.idxmax()
    return top[pick_col], candidates

# ------- 느슨한 총계 탐색: 단일 선택 + 선택된 후보 목록 리턴 -------
def _pick_relaxed_total_with_cols(bs_df: pd.DataFrame, want: str) -> Tuple[Optional[pd.Series], list]:
    """
    want: '유동자산', '유동부채', '자산총계', '부채총계', '자본총계' 등.
    공백/기호 제거 정규화 이름 기준으로 시작/포함 + ('총계','총액','합계','계') 토큰 포함을 우선.
    후보 중 '단일 컬럼'만 선택(합산 X): non-null 최다 → median(|.|) 최대.
    """
    if not isinstance(bs_df, pd.DataFrame) or bs_df.empty:
        return None, []
    def norm(s: str) -> str:
        s = re.sub(r"\s+", "", str(s))
        s = s.replace(",", "").replace("·", "")
        s = s.replace("(", "").replace(")", "").replace("/", "").replace("-", "")
        return s
    cols = list(bs_df.columns)
    nmap = {col: norm(col) for col in cols}
    want_n = norm(want)
    KEY_TOKENS = ["총계", "총액", "합계", "계"]

    primary = []
    for col, ncol in nmap.items():
        if ncol.startswith(want_n) or (want_n in ncol):
            if any(tok in ncol for tok in KEY_TOKENS):
                primary.append(col)
    winners = primary[:]
    if not winners:
        for col, ncol in nmap.items():
            if ncol.startswith(want_n) or (want_n in ncol):
                winners.append(col)
    if not winners:
        return None, []

    sub = bs_df[winners].apply(pd.to_numeric, errors="coerce")
    nn = sub.notna().sum(axis=0)
    top = sub.loc[:, nn == nn.max()]
    med = top.median(axis=0, skipna=True).abs()
    pick_col = med.idxmax()
    return top[pick_col], winners

# ------- CapEx 유출 자동 판별 -------
def _capex_outflow_from_raw(capex_raw: Optional[pd.Series]) -> Optional[pd.Series]:
    """보고서 CapEx 부호 표기가 제각각이라 자동 판별:
       - 음수(유출) 표기 비중이 더 크면: outflow = (-)값의 절대치
       - 양수(유출) 표기 비중이 더 크면: outflow = (+)값 그대로
    """
    if not isinstance(capex_raw, pd.Series) or capex_raw.empty:
        return None
    s = pd.to_numeric(capex_raw, errors="coerce")
    pos = (s > 0).sum()
    neg = (s < 0).sum()
    if neg >= pos:
        out = s.where(s < 0, 0.0).abs()
    else:
        out = s.where(s > 0, 0.0)
    return out if out.notna().any() and (out != 0).any() else None

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
        cols = [
            "debt_ratio","equity_ratio","debt_dependency_ratio",
            "current_ratio","quick_ratio","interest_coverage_ratio",
            "ebitda_to_total_debt","cfo_to_total_debt","free_cash_flow",
            "operating_margin","roa","roe","net_profit_margin",
            "total_asset_turnover","accounts_receivable_turnover","inventory_turnover",
            "sales_growth_rate","operating_income_growth_rate","total_asset_growth_rate",
        ]
        out = pd.DataFrame(columns=cols)
        return (out, {"notes": ["empty bs_flat_df"]}) if return_debug else out

    dbg: Dict[str, Any] = {"notes": []}

    # 인덱스 정규화
    bs  = _unify_df_index_yyyymmdd(bs_flat_df.copy())
    isf = _unify_df_index_yyyymmdd(is_flat_df.copy())  if isinstance(is_flat_df,  pd.DataFrame) and not is_flat_df.empty  else None
    cis = _unify_df_index_yyyymmdd(cis_flat_df.copy()) if isinstance(cis_flat_df, pd.DataFrame) and not cis_flat_df.empty else None
    cf  = _unify_df_index_yyyymmdd(cf_flat_df.copy())  if isinstance(cf_flat_df,  pd.DataFrame) and not cf_flat_df.empty  else None

    # =========================
    # BS 핵심 계정: '단일 컬럼' 선택 (합산 금지) + 느슨한 폴백
    # =========================
    ca,  ca_alias_cols  = _pick_single_from_aliases(bs, KOR_KEY_ALIASES["current_assets"])
    cl,  cl_alias_cols  = _pick_single_from_aliases(bs, KOR_KEY_ALIASES["current_liabilities"])
    ncl, ncl_alias_cols = _pick_single_from_aliases(bs, KOR_KEY_ALIASES["noncurrent_liabilities"])
    tl,  tl_alias_cols  = _pick_single_from_aliases(bs, KOR_KEY_ALIASES["total_liabilities"])
    eqt, eq_alias_cols  = _pick_single_from_aliases(bs, KOR_KEY_ALIASES["equity_total"])
    ta,  ta_alias_cols  = _pick_single_from_aliases(bs, KOR_KEY_ALIASES["total_assets"])

    ca_rel, ca_rel_cols = _pick_relaxed_total_with_cols(bs, "유동자산")   if ca  is None else (None, [])
    cl_rel, cl_rel_cols = _pick_relaxed_total_with_cols(bs, "유동부채")   if cl  is None else (None, [])
    ta_rel, ta_rel_cols = _pick_relaxed_total_with_cols(bs, "자산총계")   if ta  is None else (None, [])
    tl_rel, tl_rel_cols = _pick_relaxed_total_with_cols(bs, "부채총계")   if tl  is None else (None, [])
    eq_rel, eq_rel_cols = _pick_relaxed_total_with_cols(bs, "자본총계")   if eqt is None else (None, [])

    ca  = _fallback_if_all_nan(ca,  ca_rel)
    cl  = _fallback_if_all_nan(cl,  cl_rel)
    ta  = _fallback_if_all_nan(ta,  ta_rel)
    tl  = _fallback_if_all_nan(tl,  tl_rel)
    eqt = _fallback_if_all_nan(eqt, eq_rel)

    # 총부채 보정: 유동+비유동
    if tl is None and (cl is not None or ncl is not None):
        basis_idx = getattr(cl, "index", getattr(ncl, "index", bs.index))
        tl = pd.Series(0.0, index=pd.Index(basis_idx.astype(str), dtype="object"), dtype=float)
        if cl is not None:  tl = tl.add(_ensure_series(cl, tl.index),  fill_value=0.0)
        if ncl is not None: tl = tl.add(_ensure_series(ncl, tl.index), fill_value=0.0)

    # 자본총계 = 자산 - 부채 (없을 때)
    if eqt is not None:
        eq = eqt
    elif (ta is not None) and (tl is not None):
        eq = ta.sub(tl, fill_value=np.nan)
    else:
        eq = None

    # 🔧 의심치 교정: 부채가 유의미한데 eq ≈ ta 이면 eq가 잘못 매칭된 것
    if isinstance(eq, pd.Series) and isinstance(ta, pd.Series) and isinstance(tl, pd.Series):
        eq_e = _ensure_series(eq, bs.index)
        ta_e = _ensure_series(ta, bs.index)
        tl_e = _ensure_series(tl, bs.index)
        if eq_e is not None and ta_e is not None and tl_e is not None:
            with np.errstate(invalid="ignore", divide="ignore"):
                close_eq_ta = (ta_e.astype(float) != 0) & (np.abs(eq_e - ta_e) / ta_e <= 0.01)
                debt_meaningful = (tl_e.astype(float) / ta_e.astype(float)) >= 0.01
                fix_mask = close_eq_ta & debt_meaningful
            if fix_mask.any():
                eq = eq_e.copy()
                eq.loc[fix_mask] = (ta_e - tl_e).loc[fix_mask]

    # =========================
    # PL 추출 (IS 우선, 없으면 CIS)
    # =========================
    def _extract_pl(df):
        if not isinstance(df, pd.DataFrame) or df.empty:
            return (None, None, None, None, None, None, df)
        r   = _sum_all_aliases(df, KOR_KEY_ALIASES["revenue"])
        rp  = None
        oi  = _sum_all_aliases(df, KOR_KEY_ALIASES["operating_income"])
        oi0 = _sum_all_aliases(df, KOR_KEY_ALIASES["operating_income_preLLP"])
        clo = _sum_all_aliases(df, KOR_KEY_ALIASES["credit_loss"])
        fc  = _sum_all_aliases(df, KOR_KEY_ALIASES["finance_costs"])
        return (r, rp, oi, oi0, clo, fc, df)

    r1, rp1, oi1, oi01, clo1, fc1, is_pl  = _extract_pl(isf)
    r2, rp2, oi2, oi02, clo2, fc2, cis_pl = _extract_pl(cis)

    r   = _pick_first_valid(r1, r2)
    rp  = _pick_first_valid(rp1, rp2)
    oi  = _pick_first_valid(oi1, oi2)
    oi0 = _pick_first_valid(oi01, oi02)
    clo = _pick_first_valid(clo1, clo2)
    fc  = _pick_first_valid(fc1, fc2)

    pl_any = is_pl if (isinstance(is_pl, pd.DataFrame) and not is_pl.empty) else cis_pl

    # 영업이익 보정
    if oi is None and oi0 is not None:
        oi = oi0 if clo is None else oi0.sub(clo, fill_value=0.0)

    if (rp is None) or (not isinstance(rp, pd.Series)) or rp.isna().all():
        rp = _prev_year_aligned_to_current_strict(r)

    # =========================
    # CF / 기타
    # =========================
    cfo       = _sum_cf_aliases(cf, "cfo") if isinstance(cf, pd.DataFrame) else None
    da_cf     = _sum_cf_aliases(cf, "da")  if isinstance(cf, pd.DataFrame) else None
    capex_raw = _sum_cf_aliases(cf, "capex") if isinstance(cf, pd.DataFrame) else None

    inv   = _sum_all_aliases(bs, _INVENTORY_ALIASES)
    ar    = _sum_all_aliases(bs, _AR_ALIASES)
    debt  = _sum_all_aliases(bs, _BORROWINGS_ALIASES)
    cogs  = _sum_all_aliases(pl_any, _COGS_ALIASES)
    da_pl = _sum_all_aliases(pl_any, _DA_ALIASES)
    ebitda_direct = _sum_all_aliases(pl_any, _EBITDA_ALIASES)

    _ = _is_financial_institution(bs, cf)  # 현재는 참고만

    # EBITDA
    da = da_pl if isinstance(da_pl, pd.Series) else da_cf
    if ebitda_direct is not None:
        ebitda = ebitda_direct
    elif (oi is not None) and (da is not None):
        ebitda = oi.add(da, fill_value=0.0)
    else:
        ebitda = None

    # CapEx: 유출 자동 판별
    capex_outflow = _capex_outflow_from_raw(capex_raw)

    # 공통 인덱스 (BS 기준 고정)
    union_idx = pd.Index(bs.index.astype(str), dtype="object")
    def _on_idx(s): return _ensure_series(s, union_idx)

    ca  = _on_idx(ca);  cl  = _on_idx(cl);  ta  = _on_idx(ta);  tl  = _on_idx(tl);  eq  = _on_idx(eq)
    r   = _on_idx(r);   rp  = _on_idx(rp);  oi  = _on_idx(oi);  fc  = _on_idx(fc)
    inv = _on_idx(inv); ar  = _on_idx(ar);  debt= _on_idx(debt); cogs = _on_idx(cogs)
    ebitda = _on_idx(ebitda); cfo = _on_idx(cfo); capex_outflow = _on_idx(capex_outflow)

    # 평균 (없으면 기말값으로 폴백)
    avg_assets  = _on_idx(_avg_with_prev_year(ta))
    if avg_assets is None or avg_assets.isna().all():
        avg_assets = ta
        dbg["notes"].append("avg_assets_fallback_to_period_end")

    avg_equity  = _on_idx(_avg_with_prev_year(eq))
    if avg_equity is None or avg_equity.isna().all():
        avg_equity = eq
        dbg["notes"].append("avg_equity_fallback_to_period_end")

    avg_ar      = _on_idx(_avg_with_prev_year(ar))
    if avg_ar is None or (isinstance(avg_ar, pd.Series) and avg_ar.isna().all()):
        avg_ar = ar
        dbg["notes"].append("avg_ar_fallback_to_period_end")

    avg_inv     = _on_idx(_avg_with_prev_year(inv))
    if avg_inv is None or (isinstance(avg_inv, pd.Series) and avg_inv.isna().all()):
        avg_inv = inv
        dbg["notes"].append("avg_inv_fallback_to_period_end")

    # Quick 자산 = 유동자산 - 재고(없으면 0)
    if isinstance(ca, pd.Series) and isinstance(cl, pd.Series):
        inv_zero = inv.fillna(0) if isinstance(inv, pd.Series) else pd.Series(0.0, index=union_idx, dtype=float)
        quick_assets = ca.sub(inv_zero, fill_value=0.0)
    else:
        quick_assets = None

    # =========================
    # 지표 계산
    # =========================
    debt_ratio            = _safe_div(tl, eq, union_idx)
    equity_ratio          = _safe_div(eq, ta, union_idx)
    debt_dependency_ratio = _safe_div(debt, ta, union_idx)

    current_ratio         = _safe_div(ca, cl, union_idx)
    quick_ratio           = _safe_div(quick_assets, cl, union_idx)
    interest_coverage_ratio = _safe_div(oi, fc, union_idx)

    ebitda_to_total_debt  = _safe_div(ebitda, tl, union_idx)
    cfo_to_total_debt     = _safe_div(cfo, tl, union_idx)

    # FCF = CFO - CapExOutflow
    free_cash_flow = None
    if isinstance(cfo, pd.Series) and isinstance(capex_outflow, pd.Series):
        free_cash_flow = cfo.sub(capex_outflow, fill_value=0.0)

    # 당기순이익: IS > CIS 우선
    net_income_is  = _on_idx(_sum_all_aliases(isf, KOR_KEY_ALIASES.get("net_income", []))) if isinstance(isf, pd.DataFrame) else None
    net_income_cis = _on_idx(_sum_all_aliases(cis, KOR_KEY_ALIASES.get("net_income", []))) if isinstance(cis, pd.DataFrame) else None
    net_income = _pick_first_valid(net_income_is, net_income_cis)

    # ⭐ 최후 폴백: 순이익이 끝내 없으면 '총포괄손익'을 대용으로 사용 (주의: 완전 동치는 아님)
    if (net_income is None) or (isinstance(net_income, pd.Series) and net_income.isna().all()):
        tci = _on_idx(_sum_all_aliases(cis, KOR_KEY_ALIASES.get("tci_total", []))) if isinstance(cis, pd.DataFrame) else None
        if isinstance(tci, pd.Series) and tci.notna().any():
            net_income = tci.copy()
            dbg["notes"].append("net_income_fallback_to_TCI")  # (return_debug=True 때 진단에 남김)

    operating_margin   = _safe_div(oi, r, union_idx)
    roa                = _safe_div(net_income, avg_assets, union_idx)
    roe                = _safe_div(net_income, avg_equity, union_idx)
    net_profit_margin  = _safe_div(net_income, r, union_idx)

    total_asset_turnover         = _safe_div(r, avg_assets, union_idx)
    accounts_receivable_turnover = _safe_div(r, avg_ar, union_idx)
    inventory_turnover           = _safe_div(cogs if isinstance(cogs, pd.Series) else r, avg_inv, union_idx)

    sales_growth_rate            = _growth_rate_safe_strict(r, union_idx)
    operating_income_growth_rate = _growth_rate_safe_strict(oi, union_idx)
    total_asset_growth_rate      = _growth_rate_safe_strict(ta, union_idx)

    # =========================
    # 출력 + 디버그
    # =========================
    out = pd.DataFrame(index=union_idx)
    out.index.name = "date"

    out["debt_ratio"] = debt_ratio
    out["equity_ratio"] = equity_ratio
    out["debt_dependency_ratio"] = debt_dependency_ratio

    out["current_ratio"] = current_ratio
    out["quick_ratio"] = quick_ratio
    out["interest_coverage_ratio"] = interest_coverage_ratio
    out["ebitda_to_total_debt"] = ebitda_to_total_debt
    out["cfo_to_total_debt"] = cfo_to_total_debt
    out["free_cash_flow"] = free_cash_flow

    out["operating_margin"] = operating_margin
    out["roa"] = roa
    out["roe"] = roe
    out["net_profit_margin"] = net_profit_margin

    out["total_asset_turnover"] = total_asset_turnover
    out["accounts_receivable_turnover"] = accounts_receivable_turnover
    out["inventory_turnover"] = inventory_turnover

    out["sales_growth_rate"] = sales_growth_rate
    out["operating_income_growth_rate"] = operating_income_growth_rate
    out["total_asset_growth_rate"] = total_asset_growth_rate

    try:
        out = out.sort_index(ascending=False, key=lambda s: pd.to_datetime(s, format="%Y%m%d", errors="coerce"))
    except Exception:
        out = out.sort_index(ascending=False)

    if return_debug:
        latest_key = out.index.max() if len(out.index) else None
        dbg["latest_key"] = latest_key
        if latest_key is not None:
            def _at(series: Optional[pd.Series]):
                return (series.loc[latest_key] if isinstance(series, pd.Series) and latest_key in series.index else np.nan)
            dbg["latest_raw_values"] = {
                "CA": _at(ca), "CL": _at(cl), "TA": _at(ta), "TL": _at(tl), "EQ": _at(eq),
                "INV": _at(inv), "AR": _at(ar), "OI": _at(oi), "R": _at(r), "FC": _at(fc),
                "EBITDA": _at(ebitda), "CFO": _at(cfo), "CapexOutflow": _at(capex_outflow),
                "NetIncome": _at(net_income),
            }
            dbg["latest_ratios_numeric"] = {
                "current_ratio": _at(current_ratio),
                "quick_ratio": _at(quick_ratio),
                "debt_ratio": _at(debt_ratio),
                "equity_ratio": _at(equity_ratio),
                "roa": _at(roa),
                "roe": _at(roe),
            }

        dbg["chosen_cols"] = {
            "CA_alias_candidates": ca_alias_cols,
            "CL_alias_candidates": cl_alias_cols,
            "TA_alias_candidates": ta_alias_cols,
            "TL_alias_candidates": tl_alias_cols,
            "EQ_alias_candidates": eq_alias_cols,
            "CA_relaxed": ca_rel_cols or [],
            "CL_relaxed": cl_rel_cols or [],
            "TA_relaxed": ta_rel_cols or [],
            "TL_relaxed": tl_rel_cols or [],
            "EQ_relaxed": eq_rel_cols or [],
            "INVENTORY_cols": _match_cols(bs, _INVENTORY_ALIASES),
            "AR_cols": _match_cols(bs, _AR_ALIASES),
            "BORROWINGS_cols": _match_cols(bs, _BORROWINGS_ALIASES),
        }

        return out, dbg

    return out
