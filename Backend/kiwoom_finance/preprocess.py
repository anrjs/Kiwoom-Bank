## preprocess.py
from __future__ import annotations
import re, math
import pandas as pd
from typing import Any, Tuple, Optional, List

_UNIT_PATTERNS = [
    (r"원",1),(r"천원",10**3),(r"만원",10**4),(r"백만원",10**6),
    (r"천만원",10**7),(r"억원",10**8),(r"십억원",10**9),
    (r"백억원",10**10),(r"천억원",10**11),(r"조원",10**12),
]
_NEG_PREFIXES = ("-", "−", "‐", "‒", "–", "—", "－", "△")
_num_token_pat = re.compile(r"[0-9,.\(\)]+")  # 숫자/괄호 허용

def _detect_unit_multiplier(df_like: pd.DataFrame) -> int:
    if not isinstance(df_like, pd.DataFrame) or df_like.empty:
        return 1
    texts: list[str] = []
    try:
        if hasattr(df_like.columns, "levels"):
            for lvl in range(len(df_like.columns.levels)):
                texts.extend([str(x) for x in df_like.columns.get_level_values(lvl)[:8]])
        else:
            texts.extend([str(x) for x in df_like.columns[:8]])
    except Exception:
        pass
    for i in range(min(8, len(df_like))):
        try:
            for v in df_like.iloc[i, :min(8, len(df_like.columns))]:
                s = str(v)
                if s and s != "nan":
                    texts.append(s)
        except Exception:
            break
    unit_hint = next((t for t in texts if "단위" in str(t)), None)
    candidates = [unit_hint] if unit_hint else []
    candidates.extend(texts)
    for s in candidates:
        s_norm = re.sub(r"\s+", "", str(s)).replace("：", ":")
        for pat, mul in _UNIT_PATTERNS:
            if re.search(pat, s_norm):
                return mul
    return 1

def _to_number(x: Any) -> float | float("nan"):
    if x is None:
        return math.nan
    s = str(x).strip()
    if s == "" or s in {"-", "‐", "—", "–", "－", "N/A", "na", "NaN"}:
        return math.nan
    neg = False
    for p in _NEG_PREFIXES:
        if s.startswith(p):
            neg = True
            s = s[len(p):].strip()
            break
    if s.startswith("(") and s.endswith(")"):
        neg = True; s = s[1:-1].strip()
    if not _num_token_pat.fullmatch(s):
        return math.nan
    s = s.replace(",", "")
    try:
        v = float(s)
        return -v if neg else v
    except Exception:
        return math.nan

def _clean_numeric_df(df: pd.DataFrame, multiplier: int) -> pd.DataFrame:
    def conv(col: pd.Series) -> pd.Series:
        if getattr(col, "dtype", None) is not None and col.dtype.kind in ("i","u","f"):
            return col.astype(float) * float(multiplier)
        return col.map(_to_number).astype(float) * float(multiplier)
    out = df.copy()
    for c in out.columns:
        out[c] = conv(out[c])
    return out

def _norm(s: str) -> str:
    if s is None:
        return ""
    s = str(s)
    s = re.sub(r"\s+", "", s)
    s = s.replace(",", "").replace("·", "")
    s = s.replace("(", "").replace(")", "")
    s = s.replace("/", "").replace("-", "")
    s = s.translate(str.maketrans("％：－＋．，", "%:-+.,"))
    return s

# 표 유형별 헤더 키워드
_BS_KEYS = {
    "ta": ["자산총계","자산총액","자산합계","자산계","부채및자본총계","부채와자본총계","자본과부채총계"],
    "tl": ["부채총계","부채총액","부채합계","부채계"],
    "eq": ["자본총계","자본총액","자본합계","자본계"],
    "ca": ["유동자산","유동자산총계","유동자산합계","유동자산계"],
    "cl": ["유동부채","유동부채총계","유동부채합계","유동부채계","단기부채","단기부채총계"],
}
_IS_KEYS = {
    "rev": ["매출액","영업수익","수익","매출","매출수익"],
    "oi" : ["영업이익","영업손익","영업이익(손실)","영업(손)익","영업이익손실"],
    "ni" : ["당기순이익","분기순이익","반기순이익","연결당기순이익","지배기업의소유주에게귀속되는당기순이익"],
}
_CF_KEYS = {
    "cfo": ["영업활동현금흐름","영업활동으로부터의현금흐름","영업현금흐름","영업으로부터창출된현금흐름"],
}

def _flatten_columns(df: pd.DataFrame) -> pd.DataFrame:
    if not isinstance(df, pd.DataFrame):
        return df
    if hasattr(df.columns, "levels"):  # MultiIndex
        def _join(t):
            vals = [str(x) for x in t if str(x) not in ("","nan","None")]
            return " / ".join(vals) if vals else ""
        df = df.copy()
        df.columns = [_join(t if isinstance(t, tuple) else (t,)) for t in df.columns]
    return df

def _score_header_row(df_T: pd.DataFrame, row_idx: int, key_map: dict) -> int:
    cols = df_T.iloc[row_idx].astype(str).tolist()
    cols_norm = [_norm(c) for c in cols]
    score = 0
    # 핵심 키워드 다수 포함될수록 가점
    for patterns in key_map.values():
        hit = any(any((_norm(p) in cn) or (cn in _norm(p)) for p in patterns) for cn in cols_norm)
        score += 5 if hit else 0
    if any("단위" in str(x) for x in cols):
        score -= 3
    numish = sum(1 for x in cols if _num_token_pat.fullmatch(str(x).strip()))
    score -= int(0.4 * numish)
    return score

def _pick_best_header(df_T: pd.DataFrame, key_map: dict, top_n: int = 8) -> int:
    best_i, best_score = 0, -10**9
    for i in range(min(top_n, len(df_T))):
        sc = _score_header_row(df_T, i, key_map)
        if sc > best_score:
            best_score = sc; best_i = i
    return best_i

def _digits_index(df: pd.DataFrame) -> pd.DataFrame:
    if not isinstance(df, pd.DataFrame) or df.empty:
        return df
    df2 = df.copy()
    idx = df2.index.astype(str)
    idx = idx.str.replace(r"제\s*\d+\s*기", "", regex=True)
    idx = idx.str.split("-").str[-1]
    idx = idx.str.replace(r"\D", "", regex=True)
    df2.index = idx
    return df2

def _prefer_full_year(df: pd.DataFrame) -> pd.DataFrame:
    """같은 연도 내 여러 키가 있으면 12월말(또는 12월)을 우선 보존."""
    if not isinstance(df, pd.DataFrame) or df.empty:
        return df
    ser = pd.Series(df.index.astype(str), index=df.index.astype(str))
    years = ser.str.slice(0,4)
    months = ser.str.slice(4,6).fillna("")
    # 우선순위 낮은 것부터 드랍: 03/06/09 등
    order = pd.DataFrame({"y": years, "m": months})
    # 12월=0(최우선), 그 외는 1
    pri = (order["m"] != "12").astype(int)
    kept = []
    for y, grp in pri.groupby(order["y"]):
        sub = grp.index
        # 같은 연도에서 pri가 0이 있으면 그것만 남김, 없으면 첫 번째
        if (grp == 0).any():
            idx = grp[grp == 0].index[0]
        else:
            idx = sub[0]
        kept.append(idx)
    return df.loc[kept]

def _prep_one(frame_like) -> pd.DataFrame | None:
    if frame_like is None:
        return None
    if isinstance(frame_like, pd.DataFrame):
        return frame_like
    try:
        return pd.DataFrame(frame_like)
    except Exception:
        return None

def _prep_one_statement(df_raw: pd.DataFrame, key_map: dict) -> pd.DataFrame:
    if not isinstance(df_raw, pd.DataFrame) or df_raw.empty:
        return df_raw
    mul = _detect_unit_multiplier(df_raw)
    df_T = _flatten_columns(df_raw).T
    hdr_idx = _pick_best_header(df_T, key_map, top_n=8)
    df = df_T.copy()
    df.columns = df.iloc[hdr_idx].astype(str)
    df = df.drop(df.index[hdr_idx])
    df = df.loc[:, [c for c in df.columns if "단위" not in str(c)]]
    df = _clean_numeric_df(df, mul)
    df.index = df.index.astype(str)
    df = _digits_index(df)
    df = df[df.index.str.len()>=4]
    df = _prefer_full_year(df)
    return df

def _pick(obj: Any, *names: str):
    if isinstance(obj, dict):
        for n in names:
            if n in obj:
                return obj[n]
    for n in names:
        if hasattr(obj, n):
            try:
                return getattr(obj, n)
            except Exception:
                pass
    try:
        for n in names:
            return obj[n]  # type: ignore[index]
    except Exception:
        return None

def preprocess_all(fs: Any) -> Tuple[pd.DataFrame, pd.DataFrame | None, pd.DataFrame | None, pd.DataFrame | None]:
    bs_raw  = _pick(fs, "bs", "balance_sheet", "BalanceSheet")
    is_raw  = _pick(fs, "is", "income_statement", "IncomeStatement")
    cis_raw = _pick(fs, "cis", "comprehensive_income", "ComprehensiveIncome")
    cf_raw  = _pick(fs, "cf", "cash_flows", "CashFlows")

    bs_df0  = _prep_one(bs_raw)   if bs_raw  is not None else None
    is_df0  = _prep_one(is_raw)   if is_raw  is not None else None
    cis_df0 = _prep_one(cis_raw)  if cis_raw is not None else None
    cf_df0  = _prep_one(cf_raw)   if cf_raw  is not None else None

    bs_flat  = _prep_one_statement(bs_df0,  _BS_KEYS) if isinstance(bs_df0,  pd.DataFrame) else None
    is_flat  = _prep_one_statement(is_df0,  _IS_KEYS) if isinstance(is_df0,  pd.DataFrame) else None
    cis_flat = _prep_one_statement(cis_df0, _IS_KEYS) if isinstance(cis_df0, pd.DataFrame) else None
    cf_flat  = _prep_one_statement(cf_df0,  _CF_KEYS) if isinstance(cf_df0,  pd.DataFrame) else None

    if not isinstance(bs_flat, pd.DataFrame) or bs_flat.empty:
        print("[PP][DBG] BS raw head:\n", (bs_df0.head(3) if isinstance(bs_df0, pd.DataFrame) else "<none>"))
        raise ValueError("preprocess_all: BS empty.")

    try:
        print("[PP][DBG] BS columns(sample):", list(bs_flat.columns)[:18])
        print("[PP][DBG] IS columns(sample):", (list(is_flat.columns)[:18] if isinstance(is_flat,pd.DataFrame) else "<none>"))
        print("[PP][DBG] CF columns(sample):", (list(cf_flat.columns)[:18] if isinstance(cf_flat,pd.DataFrame) else "<none>"))
    except Exception:
        pass

    return bs_flat, is_flat, cis_flat, cf_flat