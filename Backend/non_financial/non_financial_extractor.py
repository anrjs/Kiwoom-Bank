# -*- coding: utf-8 -*-
"""
DART 비재무요소/산업별 지표 추출기 (실데이터 기반)
 - 공통: 매출/자산, 포트폴리오(HHI), 지배구조(사외이사비율/최대주주)
 - 추가: 수출비중, 상위고객 집중도, 재고일수, CAPEX/매출, R&D/매출
 - 업종특화: 건설/조선/방산 backlog, 은행/카드 지표 등
"""

import os
import re
import io
import json
import math
import zipfile
import logging
import datetime as dt
from dataclasses import dataclass, asdict
from typing import Any, Dict, List, Optional, Tuple

import requests
import pandas as pd
from bs4 import BeautifulSoup, XMLParsedAsHTMLWarning
import dart_fss as dart
import warnings

# XML을 HTML로 파싱할 때 뜨는 경고 억제(실제 XML은 _soup에서 XML 파서로 처리)
warnings.filterwarnings("ignore", category=XMLParsedAsHTMLWarning)

# ----------------------------
# Configuration
# ----------------------------

API_KEY = os.getenv("DART_API_KEY", "3999da61d8ac43fcf60ffbac6108f77f085be762")  # 운영에선 환경변수 사용 권장

REPRT_CODE_BUSINESS = "11011"  # 사업보고서
PBLNTF_TY_REGULAR = "A"        # 정기공시
DETAIL_TYPES = ["A001", "A002", "A003"]  # 일반/정정

# ----------------------------
# Utils
# ----------------------------

def _year_default() -> int:
    today = dt.date.today()
    return today.year - 1

def _setup_dart():
    dart.set_api_key(api_key=API_KEY)

def _to_float(x: Any) -> Optional[float]:
    if x is None:
        return None
    if isinstance(x, (int, float)):
        return float(x)
    s = str(x).strip()
    if s == "" or s == "-" or s.lower() == "nan":
        return None
    neg = False
    if s.startswith("(") and s.endswith(")"):
        neg = True
        s = s[1:-1]
    if any(u in s for u in ["조", "억", "천만", "백만", "십만", "만"]):
        m = re.search(r"(-?\d+(?:\.\d+)?)\s*(조|억|천만|백만|십만|만)?", s)
        if m:
            val = float(m.group(1))
            unit = m.group(2)
            mul = {"조":1e12, "억":1e8, "천만":1e7, "백만":1e6, "십만":1e5, "만":1e4}.get(unit, 1.0)
            v = val * mul
            return -v if neg else v
    s = s.replace(",", "").replace(" ", "").replace("원","")
    if s.endswith("%"):
        try:
            v = float(s[:-1])
            return v / 100.0
        except Exception:
            return None
    try:
        v = float(s)
        return -v if neg else v
    except Exception:
        m = re.search(r"-?\d+(?:\.\d+)?", s)
        if m:
            v = float(m.group(0))
            return -v if neg else v
        return None

def _nan_to_none(x: Any) -> Any:
    try:
        if x is None:
            return None
        if isinstance(x, float) and (math.isnan(x)):
            return None
        return x
    except Exception:
        return None

def _safe_div(a: Optional[float], b: Optional[float]) -> Optional[float]:
    if a is None or b in (None, 0):
        return None
    return a / b

# ----------------------------
# HTML/XML soup helper
# ----------------------------

def _soup(text: str) -> BeautifulSoup:
    """
    입력 텍스트가 XML(XBRL 포함)로 보이면 lxml-xml 파서,
    아니면 HTML 파서를 자동 선택합니다.
    """
    parser = "lxml-xml" if re.search(r"<\?xml|<xbrl", text, re.IGNORECASE) else "lxml"
    return BeautifulSoup(text, parser)

# ----------------------------
# Corp lookup
# ----------------------------

def get_corp_code(company: str) -> Optional[str]:
    corp_list = dart.get_corp_list()
    try:
        corps = corp_list.find_by_corp_name(company, exactly=True)
    except Exception:
        corps = None
    if not corps:
        try:
            corps = corp_list.find_by_corp_name(company, exactly=False)
        except Exception:
            corps = None
    if not corps:
        return None
    corp = corps[0] if isinstance(corps, list) else corps
    try:
        return corp.corp_code
    except Exception:
        try:
            return corp["corp_code"]
        except Exception:
            return None

# ----------------------------
# Financial scale (매출/자산/자본)
# ----------------------------

REVENUE_KEYS_NM = {"매출액", "수익", "영업수익", "Revenue", "Sales"}
REVENUE_KEYS_ID = {"ifrs-full_Revenue", "Revenue", "ifrs_Revenue"}

ASSETS_KEYS_NM  = {"자산총계", "총자산", "Assets", "Total assets"}
ASSETS_KEYS_ID  = {"ifrs-full_Assets", "Assets", "ifrs_Assets"}

EQUITY_KEYS_NM = {"자본총계", "총자본", "Equity", "Total equity"}
EQUITY_KEYS_ID = {"ifrs-full_Equity", "Equity", "ifrs_Equity"}

def _pick_account_amount(rows: List[Dict[str, Any]], names: set, ids: set) -> Optional[float]:
    if not rows:
        return None
    for r in rows:
        aid = (r.get("account_id") or "").strip()
        anm = (r.get("account_nm") or "").strip()
        if (aid in ids) or (anm in names):
            val = _to_float(r.get("thstrm_amount"))
            if val is None:
                val = _to_float(r.get("frmtrm_amount"))
            if val is not None:
                return val
    for r in rows:
        anm = (r.get("account_nm") or "").lower()
        if any(k.lower() in anm for k in [k for k in names if len(k) >= 2]):
            val = _to_float(r.get("thstrm_amount"))
            if val is None:
                val = _to_float(r.get("frmtrm_amount"))
            if val is not None:
                return val
    return None

def get_financial_scale(corp_code: str, bsns_year: int, prefer_fs: str = "CFS") -> Tuple[Optional[float], Optional[float]]:
    for fs_div in ([prefer_fs] + (["OFS"] if prefer_fs != "OFS" else [])):
        try:
            data = dart.api.finance.fnltt_singl_acnt_all(
                corp_code=corp_code,
                bsns_year=str(bsns_year),
                reprt_code=REPRT_CODE_BUSINESS,
                fs_div=fs_div
            )
            rows = data.get("list", [])
            revenue = _pick_account_amount(rows, REVENUE_KEYS_NM, REVENUE_KEYS_ID)
            assets  = _pick_account_amount(rows, ASSETS_KEYS_NM, ASSETS_KEYS_ID)
            if revenue is not None or assets is not None:
                return revenue, assets
        except Exception:
            continue
    return None, None

def get_equity_total(corp_code: str, bsns_year: int, prefer_fs: str = "CFS") -> Optional[float]:
    for fs_div in ([prefer_fs] + (["OFS"] if prefer_fs != "OFS" else [])):
        try:
            data = dart.api.finance.fnltt_singl_acnt_all(
                corp_code=corp_code,
                bsns_year=str(bsns_year),
                reprt_code=REPRT_CODE_BUSINESS,
                fs_div=fs_div
            )
            rows = data.get("list", [])
            equity = _pick_account_amount(rows, EQUITY_KEYS_NM, EQUITY_KEYS_ID)
            if equity is not None:
                return equity
        except Exception:
            continue
    return None

# ----------------------------
# Governance
# ----------------------------

OUTSIDE_KEYWORDS = {"사외이사"}
DIRECTOR_KEYWORDS = {"이사"}

def get_governance(corp_code: str, bsns_year: int) -> Tuple[Optional[float], Optional[float]]:
    outside = 0
    directors = 0
    try:
        ex = dart.api.info.exctv_sttus(corp_code=corp_code,
                                       bsns_year=str(bsns_year),
                                       reprt_code=REPRT_CODE_BUSINESS)
        for row in ex.get("list", []) or []:
            ofcps = (row.get("ofcps") or "").strip()
            if any(k in ofcps for k in DIRECTOR_KEYWORDS) and ("감사" not in ofcps):
                directors += 1
                if any(k in ofcps for k in OUTSIDE_KEYWORDS):
                    outside += 1
    except Exception:
        pass
    board_independence_ratio = _safe_div(outside, directors)

    ownership_concentration_ratio = None
    try:
        hs = dart.api.info.hyslr_sttus(corp_code=corp_code,
                                       bsns_year=str(bsns_year),
                                       reprt_code=REPRT_CODE_BUSINESS)
        max_rt = None
        for row in hs.get("list", []) or []:
            for k in ["hold_stkrt", "qota_rt", "bsis_posesn_stock_qota_rt",
                      "trmend_hold_stock_co_qota_rt", "posesn_rate", "rate"]:
                v = _to_float(row.get(k))
                if v is None:
                    continue
                if v > 1.0:
                    v = v / 100.0
                max_rt = max(max_rt, v) if max_rt is not None else v
        ownership_concentration_ratio = max_rt
    except Exception:
        pass

    if (board_independence_ratio is None) or (board_independence_ratio == 0):
        try:
            ranges = [(f"{bsns_year}0101", f"{bsns_year+1}0630"),
                      (f"{bsns_year-1}0101", f"{bsns_year}0630"),
                      (f"{bsns_year}0701", f"{bsns_year+1}1231")]
            def _extract_ratio_from_text(text: str) -> Optional[float]:
                t = re.sub(r"\s+", " ", text)
                m_out = re.search(r"사외이사[^0-9]*([0-9]+)\s*명", t)
                m_in  = re.search(r"사내이사[^0-9]*([0-9]+)\s*명", t)
                if not (m_out or m_in):
                    return None
                out_n = int(m_out.group(1)) if m_out else 0
                in_n  = int(m_in.group(1)) if m_in else 0
                tot = out_n + in_n
                if tot > 0:
                    return out_n / tot
                return None
            fb_ratio = None
            for bgn_de, end_de in ranges:
                text = _find_file_text(corp_code, bsns_year, bgn_de, end_de)
                if not text:
                    continue
                fb_ratio = _extract_ratio_from_text(text)
                if fb_ratio is not None:
                    break
            if fb_ratio is not None:
                board_independence_ratio = fb_ratio
        except Exception:
            pass

    return board_independence_ratio, ownership_concentration_ratio

# ----------------------------
# Business portfolio via report files
# ----------------------------

def _search_latest_business_report_rcept_no(corp_code: str, bgn_de: str, end_de: str) -> Optional[str]:
    try:
        all_items = []
        for dtl in DETAIL_TYPES:
            try:
                res = dart.api.filings.search_filings(
                    corp_code=corp_code,
                    bgn_de=bgn_de,
                    end_de=end_de,
                    pblntf_ty=PBLNTF_TY_REGULAR,
                    pblntf_detail_ty=dtl,
                    sort="date",
                    sort_mth="desc",
                    page_count=100
                )
                all_items.extend(res.get("list", []) or [])
            except Exception:
                continue
        if not all_items:
            return None
        all_items.sort(key=lambda x: (x.get("rcept_dt",""), x.get("rcept_no","")), reverse=True)
        return all_items[0].get("rcept_no")
    except Exception:
        return None

def _download_best_text(rcept_no: str) -> Optional[str]:
    try:
        tmp_dir = os.path.join(os.getcwd(), "dart_docs")
        os.makedirs(tmp_dir, exist_ok=True)
        zip_path = dart.api.filings.download_document(path=tmp_dir, rcept_no=rcept_no)
        best_text = None
        with zipfile.ZipFile(zip_path, "r") as zf:
            candidates = [n for n in zf.namelist() if n.lower().endswith((".xml", ".xhtml", ".html", ".htm"))]
            if not candidates:
                candidates = sorted(zf.namelist(), key=lambda n: zf.getinfo(n).file_size, reverse=True)[:3]
            for n in candidates:
                try:
                    with zf.open(n) as f:
                        text = f.read().decode("utf-8", errors="ignore")
                        score = (text.count("<table") + text.count("<TABLE")) * 1000 + len(text)
                        if best_text is None or score > best_text[0]:
                            best_text = (score, text)
                except Exception:
                    continue
        return best_text[1] if best_text else None
    except Exception as e:
        logging.exception("공시 ZIP 스캔 실패: %s", e)
        return None

def _table_quality_score(tbl: BeautifulSoup) -> int:
    text = tbl.get_text(" ", strip=True)
    rows = tbl.find_all("tr")
    r = len(rows)
    c = max([len(tr.find_all(["td","th"])) for tr in rows] or [0])
    nums = len(re.findall(r"\d", text))
    kw = 0
    if any(k in text for k in ["사업부문","영업부문","부문별","부문","세그먼트","Segment"]):
        kw += 10
    if any(k in text for k in ["매출","매출액","금액","Revenue","Sales"]):
        kw += 10
    return r*c + nums + kw

def _parse_unit_from_caption_or_nearby(tbl: BeautifulSoup) -> float:
    def find_unit(text: str) -> Optional[str]:
        if not text:
            return None
        m = re.search(r"(단위|Unit)\s*[:：]\s*([^\n<\r]+)", text, flags=re.IGNORECASE)
        if not m:
            return None
        token = m.group(2)
        token = re.split(r"[,\)\]]", token)[0]
        token = token.replace(" ", "").replace(".", "")
        return token

    texts = [tbl.get_text(" ", strip=True)]
    if tbl.parent:
        texts.append(tbl.parent.get_text(" ", strip=True))
    prev = tbl.previous_sibling.get_text(" ", strip=True) if getattr(tbl, "previous_sibling", None) and hasattr(tbl.previous_sibling, "get_text") else ""
    nxt  = tbl.next_sibling.get_text(" ", strip=True) if getattr(tbl, "next_sibling", None) and hasattr(tbl.next_sibling, "get_text") else ""
    texts.extend([prev, nxt])

    unit = None
    for t in texts:
        unit = find_unit(t)
        if unit:
            break

    unit_map = {
        "원":1.0, "KRW":1.0,
        "천원":1e3, "천KRW":1e3,
        "만원":1e4,
        "백만원":1e6, "백만":1e6, "백만KRW":1e6,
        "십억원":1e9, "백억원":1e10, "천억원":1e11,
        "억원":1e8, "억":1e8, "억KRW":1e8,
        "조원":1e12, "조":1e12
    }
    return unit_map.get(unit, 1.0)

def _normalize_colnames(df: pd.DataFrame) -> pd.DataFrame:
    df = df.copy()
    df.columns = [str(c).strip() for c in df.columns]
    return df

SEGMENT_NAME_HINTS = ["부문","사업","영업","Segment","제품","품목","사업부","건설","주택","토목","건축","플랜트","인프라","해외","국내"]
SALES_COL_HINTS   = ["매출","매출액","금액","Revenue","Sales","외부매출","외부매출액","부문매출","Segment revenue","External","수익","영업수익"]

def _pick_name_col(df: pd.DataFrame) -> Optional[str]:
    for c in df.columns:
        if any(h in str(c) for h in SEGMENT_NAME_HINTS):
            return c
    return df.columns[0] if len(df.columns) else None

def _pick_sales_col(df: pd.DataFrame) -> Optional[str]:
    cands = [c for c in df.columns if any(h in str(c) for h in SALES_COL_HINTS)]
    if not cands:
        num_scores = {}
        for c in df.columns:
            s = pd.to_numeric(df[c].astype(str).str.replace(",", "").str.replace(" ", ""), errors="coerce")
            num_scores[c] = s.notna().sum()
        if num_scores:
            cands = sorted(num_scores, key=num_scores.get, reverse=True)[:3]
    if not cands:
        return None
    best_col, best_sum = None, None
    for c in cands:
        s = pd.to_numeric(df[c].astype(str).str.replace(",", "").str.replace(" ", "").str.replace("원",""), errors="coerce").fillna(0).sum()
        if best_sum is None or s > best_sum:
            best_sum, best_col = float(s), c
    return best_col

def _clean_segment_df(df: pd.DataFrame, unit_mul: float) -> Optional[pd.DataFrame]:
    if df is None or df.empty or len(df.columns) < 2:
        return None
    df = _normalize_colnames(df)
    name_col = _pick_name_col(df)
    sales_col = _pick_sales_col(df)
    if not name_col or not sales_col:
        return None
    work = df[[name_col, sales_col]].copy()
    work.columns = ["name","sales"]
    sales = (work["sales"].astype(str).str.replace(",", "").str.replace(" ", "").str.replace("원",""))
    work["sales"] = pd.to_numeric(sales, errors="coerce") * unit_mul
    drop_keywords = ["합계","총계","기타","내부","연결조정","조정","내부거래"]
    work = work[~work["name"].astype(str).apply(lambda x: any(k in str(x) for k in drop_keywords))]
    work = work.dropna(subset=["sales"])
    work = work[work["sales"] > 0]
    if work.empty:
        return None
    work = work.groupby("name", as_index=False)["sales"].sum()
    total = float(work["sales"].sum())
    if total <= 0:
        return None
    work["share"] = work["sales"] / total
    return work

def compute_portfolio_from_text(text: str) -> Tuple[Optional[int], Optional[float], Optional[float]]:
    soup = _soup(text)
    tables = soup.find_all("table")
    if not tables:
        return None, None, None
    tables_sorted = sorted(tables, key=_table_quality_score, reverse=True)
    best = None
    for tbl in tables_sorted[:15]:
        unit_mul = _parse_unit_from_caption_or_nearby(tbl)
        try:
            dfs = pd.read_html(io.StringIO(str(tbl)), flavor="lxml")
        except Exception:
            continue
        for df in dfs:
            seg = _clean_segment_df(df, unit_mul)
            if seg is None:
                continue
            if seg.shape[0] >= 2 and seg["share"].between(0,1).all():
                num_segments = int(seg.shape[0])
                largest_share = float(seg["share"].max())
                hhi = float((seg["share"]**2).sum())
                quality = num_segments*10 + (1-largest_share)*50 + (1-hhi)*50
                if (best is None) or (quality > best[0]):
                    best = (quality, num_segments, largest_share, hhi)
    if best is None:
        return None, None, None
    _, n, ls, h = best
    return n, ls, h

# ---- Internet service: revenue mix by keywords on segment table ----
AD_KWS        = ["광고","Advertising","Ads","AD"]
SUBS_KWS      = ["구독","멤버십","Subscription","Membership","정액"]
COMM_FEE_KWS  = ["수수료","Commission","플랫폼수수료","결제수수료","PG"]
CONTENT_KWS   = ["콘텐츠","Contents","컨텐츠","게임","Game","아이템","웹툰","음원","영상","VOD"]
COMMERCE_KWS  = ["커머스","Commerce","쇼핑","리테일","스토어","마켓","e-commerce","EC"]
FINTECH_KWS   = ["페이","Pay","결제","송금","지급","금융","대출","보험","증권"]

def _extract_best_segment_df(text: str) -> Optional[pd.DataFrame]:
    soup = _soup(text)
    tables = soup.find_all("table")
    if not tables:
        return None
    best_seg = None
    best_score = None
    for tbl in sorted(tables, key=_table_quality_score, reverse=True)[:20]:
        unit_mul = _parse_unit_from_caption_or_nearby(tbl)
        for df in _dfs_from_table(tbl):
            seg = _clean_segment_df(df, unit_mul)
            if seg is None:
                continue
            if seg.shape[0] >= 2 and seg["share"].between(0,1).all():
                q = seg.shape[0]*10 + (1-float(seg["share"].max()))*50
                if best_score is None or q > best_score:
                    best_score, best_seg = q, seg
    return best_seg

def get_internet_service_mix(corp_code: str, bsns_year: int) -> Dict[str, Optional[float]]:
    ranges = [
        (f"{bsns_year}0101", f"{bsns_year+1}0630"),
        (f"{bsns_year-1}0101", f"{bsns_year}0630"),
        (f"{bsns_year}0701", f"{bsns_year+1}1231"),
    ]
    for bgn_de, end_de in ranges:
        text = _find_file_text(corp_code, bsns_year, bgn_de, end_de)
        if not text:
            continue
        seg = _extract_best_segment_df(text)
        if seg is None or seg.empty:
            continue
        name = seg["name"].astype(str)
        def _share(kws):
            mask = name.apply(lambda s: any(k.lower() in s.lower() for k in kws))
            return float(seg.loc[mask, "sales"].sum()) / float(seg["sales"].sum())
        try:
            ad_share        = _share(AD_KWS)
            subs_share      = _share(SUBS_KWS)
            fee_share       = _share(COMM_FEE_KWS)
            content_share   = _share(CONTENT_KWS)
            commerce_share  = _share(COMMERCE_KWS)
            fintech_share   = _share(FINTECH_KWS)
            recurring_proxy = min(1.0, max(0.0, subs_share + fee_share + fintech_share))
            return {
                "ad_share": ad_share, "subscription_share": subs_share, "commission_share": fee_share,
                "content_share": content_share, "commerce_share": commerce_share,
                "fintech_share": fintech_share, "recurring_revenue_share_proxy": recurring_proxy
            }
        except Exception:
            continue
    return {
        "ad_share": None, "subscription_share": None, "commission_share": None,
        "content_share": None, "commerce_share": None, "fintech_share": None,
        "recurring_revenue_share_proxy": None
    }

def get_business_portfolio(corp_code: str, bsns_year: int) -> Tuple[Optional[int], Optional[float], Optional[float]]:
    ranges = [
        (f"{bsns_year}0101", f"{bsns_year+1}0630"),
        (f"{bsns_year-1}0101", f"{bsns_year}0630"),
        (f"{bsns_year}0701", f"{bsns_year+1}1231"),
        (f"{bsns_year-2}0101", f"{bsns_year-1}1231"),
        (f"{bsns_year+1}0101", f"{bsns_year+2}0630"),
    ]
    for bgn_de, end_de in ranges:
        rcept_no = _search_latest_business_report_rcept_no(corp_code, bgn_de, end_de)
        if not rcept_no:
            continue
        text = _download_best_text(rcept_no)
        if not text:
            continue
        n, ls, h = compute_portfolio_from_text(text)
        if n is not None:
            return n, ls, h
    return None, None, None

# ----------------------------
# Additional industry-extractable metrics
# ----------------------------

def _all_tables_from_text(text: str):
    soup = _soup(text)
    return soup.find_all("table")

def _dfs_from_table(tbl):
    try:
        return pd.read_html(io.StringIO(str(tbl)), flavor="lxml")
    except Exception:
        return []

def _numeric_series(series: pd.Series) -> pd.Series:
    s = series.astype(str).str.replace(",", "").str.replace(" ", "").str.replace("원","")
    return pd.to_numeric(s, errors="coerce")

def _find_file_text(corp_code: str, bsns_year: int, bgn_de: str, end_de: str) -> Optional[str]:
    rcept_no = _search_latest_business_report_rcept_no(corp_code, bgn_de, end_de)
    if not rcept_no:
        return None
    return _download_best_text(rcept_no)

def _compute_export_ratio_from_tables(tables) -> Optional[float]:
    best_ratio = None
    for tbl in tables:
        txt = tbl.get_text(" ", strip=True)
        if not any(k in txt for k in ["수출","내수","해외","국내","Domestic","Export","Overseas"]):
            continue
        unit_mul = _parse_unit_from_caption_or_nearby(tbl)
        dfs = _dfs_from_table(tbl)
        for df in dfs:
            df = _normalize_colnames(df)
            dom_cols = [c for c in df.columns if any(k in str(c) for k in ["국내","내수","Domestic","Korea"])]
            exp_cols = [c for c in df.columns if any(k in str(c) for k in ["해외","수출","Export","Overseas"])]
            if dom_cols or exp_cols:
                try:
                    dom_sum = float(sum(_numeric_series(df[c]).fillna(0).sum() for c in dom_cols)) * unit_mul
                    exp_sum = float(sum(_numeric_series(df[c]).fillna(0).sum() for c in exp_cols)) * unit_mul
                    tot = dom_sum + exp_sum
                    if tot > 0:
                        ratio = exp_sum / tot
                        if best_ratio is None or ratio > best_ratio:
                            best_ratio = ratio
                except Exception:
                    continue
            else:
                name_col = _pick_name_col(df)
                if name_col and name_col in df.columns and len(df.columns) >= 2:
                    name_series = df[name_col].astype(str)
                    val_cols = [c for c in df.columns if c != name_col]
                    if name_series.str.contains("|".join(["국내","내수","Domestic","Korea"]), regex=True).any() and \
                       name_series.str.contains("|".join(["해외","수출","Export","Overseas"]), regex=True).any():
                        for c in val_cols:
                            vals = _numeric_series(df[c]) * unit_mul
                            dom_val = float(vals[name_series.str.contains("|".join(["국내","내수","Domestic","Korea"]), regex=True)].fillna(0).sum())
                            exp_val = float(vals[name_series.str.contains("|".join(["해외","수출","Export","Overseas"]), regex=True)].fillna(0).sum())
                            tot = dom_val + exp_val
                            if tot > 0:
                                ratio = exp_val / tot
                                if best_ratio is None or ratio > best_ratio:
                                    best_ratio = ratio
    return best_ratio

# ===== Internet/Service 공통 수익성 & 성장 지표 =====

REV_IDS = {"ifrs-full_Revenue", "Revenue", "ifrs_Revenue"}
REV_NMS = {"매출액", "수익", "영업수익"}

COGS_IDS = {"ifrs-full_CostOfSales", "CostOfSales"}
COGS_NMS = {"매출원가", "Cost of sales", "Cost of Sales"}

GP_IDS = {"ifrs-full_GrossProfit", "GrossProfit"}
GP_NMS = {"매출총이익", "매출총이익(손실)"}

OP_IDS = {
    "ifrs-full_ProfitLossFromOperatingActivities",
    "ProfitLossFromOperatingActivities",
    "OperatingProfitLoss"
}
OP_NMS = {"영업이익", "영업손실", "영업이익(손실)"}

SGA_IDS = {"ifrs-full_DistributionCosts", "ifrs-full_AdministrativeExpense",
           "ifrs-full_DistributionCostsAndAdministrativeExpenses"}
SGA_NMS = {"판매비와관리비", "판매비와 관리비", "판관비"}

def _pick_cur_prev(rows, names_nm: set, names_id: set) -> Tuple[Optional[float], Optional[float]]:
    cur, prev = None, None
    for r in rows or []:
        aid = (r.get("account_id") or "").strip()
        anm = (r.get("account_nm") or "").strip()
        if (aid in names_id) or (anm in names_nm) or any(k in anm for k in names_nm):
            th = _to_float(r.get("thstrm_amount"))
            fr = _to_float(r.get("frmtrm_amount"))
            if cur is None and th is not None:
                cur = th
            if prev is None and fr is not None:
                prev = fr
    return cur, prev

def get_profitability_metrics(corp_code: str, bsns_year: int) -> Dict[str, Optional[float]]:
    out = {
        "gross_margin_ratio": None,
        "operating_margin_ratio": None,
        "sga_ratio": None,
        "revenue_yoy": None,
    }
    try:
        data = dart.api.finance.fnltt_singl_acnt_all(
            corp_code=corp_code, bsns_year=str(bsns_year),
            reprt_code=REPRT_CODE_BUSINESS, fs_div="CFS"
        )
        rows = data.get("list", []) or []

        rev_cur, rev_prev = _pick_cur_prev(rows, REV_NMS, REV_IDS)
        cogs_cur, _ = _pick_cur_prev(rows, COGS_NMS, COGS_IDS)
        gp_cur, _   = _pick_cur_prev(rows, GP_NMS, GP_IDS)
        op_cur, _   = _pick_cur_prev(rows, OP_NMS, OP_IDS)
        sga_cur, _  = _pick_cur_prev(rows, SGA_NMS, SGA_IDS)

        if rev_cur and rev_prev and rev_prev > 0:
            out["revenue_yoy"] = (rev_cur - rev_prev) / rev_prev

        if rev_cur and rev_cur > 0:
            if gp_cur is not None:
                out["gross_margin_ratio"] = gp_cur / rev_cur
            elif cogs_cur is not None:
                out["gross_margin_ratio"] = max(0.0, (rev_cur - cogs_cur) / rev_cur)

            if op_cur is not None:
                out["operating_margin_ratio"] = op_cur / rev_cur
            if sga_cur is not None:
                out["sga_ratio"] = sga_cur / rev_cur

    except Exception:
        pass
    return out

# ===== Internet/Service 매출 믹스 =====

CAT_KWS = {
    "ad": ["광고", "AD", "Advertising"],
    "subscription": ["구독", "멤버십", "Membership", "Subscription", "정기"],
    "commission": ["수수료", "커미션", "Commission", "수수료수익", "플랫폼수수료"],
    "content": ["콘텐츠", "Contents", "게임", "Game", "디지털콘텐츠"],
    "commerce": ["커머스", "쇼핑", "Commerce", "e-commerce", "거래", "판매"],
    "fintech": ["핀테크", "페이", "결제", "Payment", "금융", "송금", "대출"],
}

def _sum_by_categories(df: pd.DataFrame, unit_mul: float) -> Dict[str, float]:
    name_col = _pick_name_col(df)
    if not name_col or name_col not in df.columns:
        return {}
    value_cols = [c for c in df.columns if c != name_col]
    best_col, best_sum = None, None
    for c in value_cols:
        s = float(_numeric_series(df[c]).fillna(0).sum())
        if best_sum is None or s > best_sum:
            best_sum, best_col = s, c
    if not best_col:
        return {}

    work = df[[name_col, best_col]].copy()
    work.columns = ["name","value"]
    work["value"] = _numeric_series(work["value"]) * unit_mul
    work = work.dropna()
    work = work[work["value"] > 0]
    if work.empty:
        return {}

    drop_kw = ["합계","총계","기타","내부","조정"]
    work = work[~work["name"].astype(str).apply(lambda s: any(k in s for k in drop_kw))]

    sums = {k: 0.0 for k in CAT_KWS.keys()}
    for _, row in work.iterrows():
        n = str(row["name"])
        v = float(row["value"])
        for cat, kws in CAT_KWS.items():
            if any(kw.lower() in n.lower() for kw in kws):
                sums[cat] += v
                break
    return sums

def get_internet_revenue_mix(corp_code: str, bsns_year: int) -> Dict[str, Optional[float]]:
    out = {
        "ad_share": None, "subscription_share": None, "commission_share": None,
        "content_share": None, "commerce_share": None, "fintech_share": None,
        "recurring_revenue_share_proxy": None,
    }
    ranges = [
        (f"{bsns_year}0101", f"{bsns_year+1}0630"),
        (f"{bsns_year-1}0101", f"{bsns_year}0630"),
        (f"{bsns_year}0701", f"{bsns_year+1}1231"),
    ]
    best = None
    for bgn_de, end_de in ranges:
        text = _find_file_text(corp_code, bsns_year, bgn_de, end_de)
        if not text:
            continue
        for tbl in _all_tables_from_text(text):
            unit_mul = _parse_unit_from_caption_or_nearby(tbl)
            for df in _dfs_from_table(tbl):
                df = _normalize_colnames(df)
                sums = _sum_by_categories(df, unit_mul)
                total = sum(sums.values())
                if total and total > 0:
                    best = sums if (best is None or total > sum(best.values())) else best
    if best:
        total = float(sum(best.values()))
        if total > 0:
            for k, v in best.items():
                out[f"{k}_share"] = v / total if v > 0 else 0.0
            rec = (out["subscription_share"] or 0.0) + (out["commission_share"] or 0.0) + (out["fintech_share"] or 0.0)
            out["recurring_revenue_share_proxy"] = rec
    return out

def get_export_ratio(corp_code: str, bsns_year: int) -> Optional[float]:
    ranges = [
        (f"{bsns_year}0101", f"{bsns_year+1}0630"),
        (f"{bsns_year-1}0101", f"{bsns_year}0630"),
        (f"{bsns_year}0701", f"{bsns_year+1}1231"),
    ]
    for bgn_de, end_de in ranges:
        text = _find_file_text(corp_code, bsns_year, bgn_de, end_de)
        if not text:
            continue
        tables = _all_tables_from_text(text)
        ratio = _compute_export_ratio_from_tables(tables)
        if ratio is not None:
            return ratio
    return None

def _compute_customer_concentration_from_tables(tables, topn=5) -> Tuple[Optional[float], Optional[float]]:
    best = (None, None)
    for tbl in tables:
        txt = tbl.get_text(" ", strip=True)
        if not any(k in txt for k in ["매출처","고객","거래처","매출 거래처","매출처현황","Customer"]):
            continue
        unit_mul = _parse_unit_from_caption_or_nearby(tbl)
        dfs = _dfs_from_table(tbl)
        for df in dfs:
            df = _normalize_colnames(df)
            name_cols = [c for c in df.columns if any(k in str(c) for k in ["매출처","고객","거래처","상대방","Customer"])]
            value_cols = [c for c in df.columns if any(k in str(c) for k in ["매출","금액","Amount","Sales","수익"])]
            if not name_cols or not value_cols:
                continue
            name_col = name_cols[0]
            best_val_col = None
            best_sum = None
            for c in value_cols:
                s = float(_numeric_series(df[c]).fillna(0).sum())
                if best_sum is None or s > best_sum:
                    best_sum, best_val_col = s, c
            work = df[[name_col, best_val_col]].copy()
            work.columns = ["name","value"]
            work["value"] = _numeric_series(work["value"]) * unit_mul
            work = work.dropna()
            work = work[work["value"] > 0]
            if work.empty:
                continue
            drop_keywords = ["합계","총계","기타","내부","조정"]
            work = work[~work["name"].astype(str).apply(lambda s: any(k in s for k in drop_keywords))]
            work = work.groupby("name", as_index=False)["value"].sum()
            if work.shape[0] < 3:
                continue
            work = work.sort_values("value", ascending=False)
            total = float(work["value"].sum())
            top1 = float(work.iloc[0]["value"]) / total if total > 0 else None
            topn_share = float(work.head(topn)["value"].sum()) / total if total > 0 else None
            if top1 is not None and topn_share is not None and top1 >= 0.95 and abs(topn_share - top1) < 1e-6:
                continue
            if top1 is not None and topn_share is not None:
                return top1, topn_share
    return best

def get_customer_concentration(corp_code: str, bsns_year: int, topn=5) -> Tuple[Optional[float], Optional[float]]:
    ranges = [
        (f"{bsns_year}0101", f"{bsns_year+1}0630"),
        (f"{bsns_year-1}0101", f"{bsns_year}0630"),
        (f"{bsns_year}0701", f"{bsns_year+1}1231"),
    ]
    for bgn_de, end_de in ranges:
        text = _find_file_text(corp_code, bsns_year, bgn_de, end_de)
        if not text:
            continue
        tables = _all_tables_from_text(text)
        t1, t5 = _compute_customer_concentration_from_tables(tables, topn=topn)
        if t1 is not None or t5 is not None:
            return t1, t5
    return None, None

TECH_KWS = ["HBM","HBM2","HBM3","HBM3E","HBM2E","DDR5","GDDR7","CXL","High Bandwidth Memory","AI 메모리"]

def get_tech_leadership_score(corp_code: str, bsns_year: int) -> Optional[float]:
    ranges = [
        (f"{bsns_year}0101", f"{bsns_year+1}0630"),
        (f"{bsns_year-1}0101", f"{bsns_year}0630"),
        (f"{bsns_year}0701", f"{bsns_year+1}1231"),
    ]
    for bgn_de, end_de in ranges:
        text = _find_file_text(corp_code, bsns_year, bgn_de, end_de)
        if not text:
            continue
        t = text.upper()
        cnt = sum(t.count(k.upper()) for k in TECH_KWS)
        norm = cnt / max(1.0, len(t) / 10000.0)
        score = min(1.0, norm / 8.0)
        if score > 0:
            return score
    return None

SHIP_TECH_KWS = [
    "LNG", "LPG", "VLCC", "Dual-fuel", "Methanol", "Ammonia",
    "Ice-class", "FSRU", "FLNG", "FPSO", "Containership", "TEU"
]

def get_ship_tech_score(corp_code: str, bsns_year: int) -> Optional[float]:
    ranges = [
        (f"{bsns_year}0101", f"{bsns_year+1}0630"),
        (f"{bsns_year-1}0101", f"{bsns_year}0630"),
        (f"{bsns_year}0701", f"{bsns_year+1}1231"),
    ]
    for bgn_de, end_de in ranges:
        text = _find_file_text(corp_code, bsns_year, bgn_de, end_de)
        if not text:
            continue
        t = text.upper()
        cnt = sum(t.count(k.upper()) for k in SHIP_TECH_KWS)
        norm = cnt / max(1.0, len(t) / 10000.0)
        score = min(1.0, norm / 6.0)
        if score > 0:
            return score
    return None

DEF_GOV_KWS = ["방위사업청","국방부","육군","해군","공군","정부","군","DAPA",
               "Ministry of National Defense","Defense Acquisition Program Administration","ROK"]
DEF_EXP_KWS = ["수출","해외","Export","Overseas","Foreign"]

def _defense_mix_from_customer_tables(tables) -> Tuple[Optional[float], Optional[float]]:
    best_gov, best_exp = None, None
    for tbl in tables:
        txt = tbl.get_text(" ", strip=True)
        if not any(k in txt for k in ["매출처","고객","거래처","Customer","Sales"]):
            continue
        unit_mul = _parse_unit_from_caption_or_nearby(tbl)
        for df in _dfs_from_table(tbl):
            df = _normalize_colnames(df)
            name_cols = [c for c in df.columns if any(k in str(c) for k in ["매출처","고객","거래처","상대방","Customer","매입처"])]
            value_cols = [c for c in df.columns if any(k in str(c) for k in ["매출","금액","Amount","Sales","수익"])]
            if not name_cols or not value_cols:
                continue
            name_col = name_cols[0]
            best_val_col, best_sum = None, None
            for c in value_cols:
                s = float(_numeric_series(df[c]).fillna(0).sum())
                if best_sum is None or s > best_sum:
                    best_sum, best_val_col = s, c
            if not best_val_col:
                continue
            work = df[[name_col, best_val_col]].copy()
            work.columns = ["name","value"]
            work["value"] = _numeric_series(work["value"]) * unit_mul
            work = work.dropna()
            work = work[~work["name"].astype(str).str.contains("|".join(["합계","총계","기타","내부","조정"])) ]
            if work.empty:
                continue
            total = float(work["value"].sum())
            if total <= 0:
                continue
            name_ser = work["name"].astype(str)
            gov_val = float(work.loc[name_ser.apply(lambda s: any(k in s for k in DEF_GOV_KWS)), "value"].sum())
            exp_val = float(work.loc[name_ser.apply(lambda s: any(k in s for k in DEF_EXP_KWS)), "value"].sum())
            if (gov_val + exp_val) > 0:
                g = gov_val / (gov_val + exp_val)
                e = exp_val / (gov_val + exp_val)
                best_gov = g if best_gov is None else max(best_gov, g)
                best_exp = e if best_exp is None else max(best_exp, e)
    return best_gov, best_exp

def get_defense_mix_estimates(corp_code: str, bsns_year: int) -> Tuple[Optional[float], Optional[float]]:
    ranges = [
        (f"{bsns_year}0101", f"{bsns_year+1}0630"),
        (f"{bsns_year-1}0101", f"{bsns_year}0630"),
        (f"{bsns_year}0701", f"{bsns_year+1}1231"),
    ]
    for bgn_de, end_de in ranges:
        text = _find_file_text(corp_code, bsns_year, bgn_de, end_de)
        if not text:
            continue
        tables = _all_tables_from_text(text)
        g, e = _defense_mix_from_customer_tables(tables)
        if (g is not None) or (e is not None):
            return g, e
    for bgn_de, end_de in ranges:
        text = _find_file_text(corp_code, bsns_year, bgn_de, end_de)
        if not text:
            continue
        tables = _all_tables_from_text(text)
        g, e = (None, None)  # placeholder if 보조 추정기를 붙일 경우
        if (g is not None) or (e is not None):
            return g, e
    try:
        text = _find_file_text(corp_code, bsns_year, f"{bsns_year}0101", f"{bsns_year+1}0630") or ""
        gov_cnt = sum(text.count(k) for k in DEF_GOV_KWS)
        exp_cnt = sum(text.count(k) for k in DEF_EXP_KWS)
        tot = max(1, gov_cnt + exp_cnt)
        return (gov_cnt / tot if gov_cnt else None), (exp_cnt / tot if exp_cnt else None)
    except Exception:
        return None, None

COGS_KEYS = {"매출원가","Cost of sales","Cost of Sales","ifrs-full_CostOfSales","CostOfSales"}
INVENTORIES_KEYS = {"재고자산","Inventories","ifrs-full_Inventories","Inventories"}

def get_inventory_days(corp_code: str, bsns_year: int) -> Optional[float]:
    try:
        data = dart.api.finance.fnltt_singl_acnt_all(
            corp_code=corp_code, bsns_year=str(bsns_year),
            reprt_code=REPRT_CODE_BUSINESS, fs_div="CFS"
        )
        rows = data.get("list", [])
        cogs, inv = None, None
        for r in rows:
            anm = (r.get("account_nm") or "")
            aid = (r.get("account_id") or "")
            if (aid in COGS_KEYS) or (anm in COGS_KEYS) or ("매출원가" in anm) or ("Cost of sales" in anm):
                cogs = _to_float(r.get("thstrm_amount")) or _to_float(r.get("frmtrm_amount"))
            if (aid in INVENTORIES_KEYS) or (anm in INVENTORIES_KEYS) or ("재고자산" in anm) or ("Inventories" in anm):
                inv = _to_float(r.get("thstrm_amount")) or _to_float(r.get("frmtrm_amount"))
        if cogs and inv and cogs > 0:
            return (inv / cogs) * 365.0
    except Exception:
        pass
    return None

def get_inventory_days_pair(corp_code: str, bsns_year: int) -> Tuple[Optional[float], Optional[float]]:
    try:
        data = dart.api.finance.fnltt_singl_acnt_all(
            corp_code=corp_code, bsns_year=str(bsns_year),
            reprt_code=REPRT_CODE_BUSINESS, fs_div="CFS"
        )
        rows = data.get("list", []) or []
        cogs_th = cogs_fr = inv_th = inv_fr = None
        for r in rows:
            anm = (r.get("account_nm") or "")
            aid = (r.get("account_id") or "")
            if (aid in COGS_KEYS) or (anm in COGS_KEYS) or ("매출원가" in anm) or ("Cost of sales" in anm):
                cogs_th = cogs_th or _to_float(r.get("thstrm_amount"))
                cogs_fr = cogs_fr or _to_float(r.get("frmtrm_amount"))
            if (aid in INVENTORIES_KEYS) or (anm in INVENTORIES_KEYS) or ("재고자산" in anm) or ("Inventories" in anm):
                inv_th = inv_th or _to_float(r.get("thstrm_amount"))
                inv_fr = inv_fr or _to_float(r.get("frmtrm_amount"))
        cur = (inv_th / cogs_th * 365.0) if inv_th and cogs_th and cogs_th > 0 else None
        prev = (inv_fr / cogs_fr * 365.0) if inv_fr and cogs_fr and cogs_fr > 0 else None
        return cur, prev
    except Exception:
        return None, None

CAPEX_KEYS = {
    "ifrs-full_PurchaseOfPropertyPlantAndEquipment",
    "AcquisitionsOfPropertyPlantAndEquipment",
    "유형자산의 취득","유형자산취득","유형자산의취득","유형자산의 증가"
}
RND_KEYS = {
    "ifrs-full_ResearchAndDevelopmentExpense",
    "ResearchAndDevelopmentExpense",
    "연구개발비","연구 개발비","연구개발 비용"
}

def get_capex_to_revenue(corp_code: str, bsns_year: int) -> Optional[float]:
    revenue, _ = get_financial_scale(corp_code, bsns_year)
    if not revenue or revenue <= 0:
        return None
    try:
        data = dart.api.finance.fnltt_singl_acnt_all(
            corp_code=corp_code, bsns_year=str(bsns_year),
            reprt_code=REPRT_CODE_BUSINESS, fs_div="CFS"
        )
        rows = data.get("list", []) or []
        CAPEX_IDS = {
            "ifrs-full_PurchaseOfPropertyPlantAndEquipment",
            "ifrs-full_PaymentsToAcquirePropertyPlantAndEquipment",
            "AcquisitionsOfPropertyPlantAndEquipment",
            "ifrs-full_PurchaseOfIntangibleAssets",
            "ifrs-full_PaymentsToAcquireIntangibleAssets",
        }
        CAPEX_NAME_PATTS = ["유형자산의 취득","유형자산 취득","무형자산의 취득","유무형자산의 취득","설비투자","CAPEX"]
        def is_cfs(r):
            s = (r.get("sj_nm") or "").lower()
            return ("현금" in s) or ("cash" in s)
        cand = []
        for r in rows:
            aid = (r.get("account_id") or "").strip()
            anm = (r.get("account_nm") or "").strip().replace(" ", "")
            hit = (aid in CAPEX_IDS) or any(p.replace(" ","") in anm for p in CAPEX_NAME_PATTS)
            if not hit:
                continue
            v = _to_float(r.get("thstrm_amount")) or _to_float(r.get("frmtrm_amount"))
            if v is not None:
                if is_cfs(r):
                    cand.append(abs(v))
                else:
                    cand.append(abs(v))
        if cand:
            capex = float(max(cand))
            return capex / revenue
    except Exception:
        pass
    return None

# ---- R&D robust table extractor (보조 루틴) ----
RND_TABLE_HINTS = [
    "연구개발", "연구·개발", "R&D", "R & D",
    "Research and development", "research & development", "technology development", "기술개발"
]
RND_TOTAL_ROW_HINTS = ["합계", "총계", "계", "합계금액", "Total", "TOTAL"]
RND_VALUE_COL_HINTS = ["금액", "비용", "expense", "amount", "합계", "누계", "당기", "Current"]

_YEAR_RE = re.compile(r"(20\d{2})(?:[.\-/]\d{1,2}[.\-/]\d{1,2})?")
_THIS_RE = re.compile(r"(당기|당기말|현재|기말|This|Current)", re.IGNORECASE)
_PREV_RE = re.compile(r"(전기|전기말|이전)", re.IGNORECASE)

def _looks_like_percent_col(hdr: str, series: pd.Series) -> bool:
    hdr_l = hdr.lower()
    if any(k in hdr_l for k in ["율", "비율", "rate", "%", "percent"]):
        return True
    vals = _numeric_series(series)
    n = vals.notna().sum()
    if n >= 3:
        small = ((vals >= 0) & (vals <= 1)).sum()
        if (small / n) >= 0.6:
            return True
    return False

def _score_rnd_value_col(df: pd.DataFrame, col: str, prefer_year: Optional[int], rows_mask: Optional[pd.Series]) -> Tuple[int, float]:
    hdr = str(col)
    score = 0
    if prefer_year and str(prefer_year) in hdr:
        score += 6
    elif prefer_year and any(y for y in _YEAR_RE.findall(hdr) if abs(int(y) - prefer_year) <= 1):
        score += 4
    if _THIS_RE.search(hdr):
        score += 3
    if any(k in hdr for k in RND_VALUE_COL_HINTS):
        score += 2
    scope = df.loc[rows_mask, col] if (rows_mask is not None) else df[col]
    ssum = float(_numeric_series(scope).fillna(0).abs().sum())
    return score, ssum

def _compute_rnd_total_from_tables(tables, prefer_year: Optional[int] = None) -> Optional[float]:
    best_total = None
    for tbl in tables:
        txt = tbl.get_text(" ", strip=True)
        if not any(k in txt for k in RND_TABLE_HINTS):
            continue
        unit_mul = _parse_unit_from_caption_or_nearby(tbl)
        dfs = _dfs_from_table(tbl)
        for df in dfs:
            df = _normalize_colnames(df)
            if df is None or df.empty or len(df.columns) < 2:
                continue
            name_col = _pick_name_col(df)
            cand_cols = []
            for c in df.columns:
                if c == name_col:
                    continue
                series = df[c]
                if series is None:
                    continue
                if _looks_like_percent_col(str(c), series):
                    continue
                if _numeric_series(series).notna().sum() == 0:
                    continue
                cand_cols.append(c)
            if not cand_cols:
                continue
            rows_mask = None
            if name_col and name_col in df.columns:
                name_ser = df[name_col].astype(str)
                total_mask = name_ser.str.contains("|".join(RND_TOTAL_ROW_HINTS))
                if total_mask.any():
                    rows_mask = total_mask
                else:
                    rows_mask = ~name_ser.str.contains("|".join(["기타","내부","조정"]))
            best_col, best_score, best_sum = None, -10**9, -1.0
            for c in cand_cols:
                sc, ssum = _score_rnd_value_col(df, c, prefer_year, rows_mask)
                if (sc > best_score) or (sc == best_score and ssum > best_sum):
                    best_score, best_sum, best_col = sc, ssum, c
            if not best_col:
                continue
            scope = df.loc[rows_mask, best_col] if (rows_mask is not None) else df[best_col]
            total = float(_numeric_series(scope).fillna(0).abs().sum()) * unit_mul
            if total and (best_total is None or total > best_total):
                best_total = total
    return best_total

def get_revenue_yoy(corp_code: str, bsns_year: int) -> Optional[float]:
    try:
        data = dart.api.finance.fnltt_singl_acnt_all(
            corp_code=corp_code, bsns_year=str(bsns_year),
            reprt_code=REPRT_CODE_BUSINESS, fs_div="CFS"
        )
        rows = data.get("list", []) or []
        cur = prev = None
        for r in rows:
            aid = (r.get("account_id") or "").strip()
            anm = (r.get("account_nm") or "").strip()
            if (aid in REVENUE_KEYS_ID) or (anm in REVENUE_KEYS_NM) or ("매출" in anm) or ("Revenue" in anm):
                cur  = cur  or _to_float(r.get("thstrm_amount"))
                prev = prev or _to_float(r.get("frmtrm_amount"))
        if cur is not None and prev not in (None, 0):
            return (cur - prev) / prev
    except Exception:
        pass
    return None

_OP_KEYS = {
    "ifrs-full_ProfitLossFromOperatingActivities",
    "ProfitLossFromOperatingActivities",
    "영업이익","영업손익","Operating profit","Operating income"
}
_SGA_KEYS = {
    "판매비와관리비","판매비 및 관리비","SG&A",
    "Selling, general and administrative expenses",
    "ifrs-full_DistributionCosts","ifrs-full_AdministrativeExpense"
}

def get_profitability_ratios(corp_code: str, bsns_year: int) -> Tuple[Optional[float], Optional[float], Optional[float]]:
    revenue, _ = get_financial_scale(corp_code, bsns_year)
    if not revenue or revenue <= 0:
        return None, None, None
    try:
        data = dart.api.finance.fnltt_singl_acnt_all(
            corp_code=corp_code, bsns_year=str(bsns_year),
            reprt_code=REPRT_CODE_BUSINESS, fs_div="CFS"
        )
        rows = data.get("list", []) or []

        cogs = None
        op   = None
        sga  = None
        for r in rows:
            anm = (r.get("account_nm") or "")
            aid = (r.get("account_id") or "")
            if (aid in COGS_KEYS) or (anm in COGS_KEYS) or ("매출원가" in anm) or ("Cost of sales" in anm):
                cogs = cogs or (_to_float(r.get("thstrm_amount")) or _to_float(r.get("frmtrm_amount")))
            if (aid in _OP_KEYS) or (anm in _OP_KEYS) or ("영업" in anm and "이익" in anm):
                v = _to_float(r.get("thstrm_amount")) or _to_float(r.get("frmtrm_amount"))
                if v is not None:
                    op = v
            if (aid in _SGA_KEYS) or (anm in _SGA_KEYS) or ("판매비" in anm and "관리비" in anm):
                v = _to_float(r.get("thstrm_amount")) or _to_float(r.get("frmtrm_amount"))
                if v is not None:
                    sga = v

        gross_margin = None
        if cogs is not None and revenue:
            gross_margin = max(0.0, min(1.0, (revenue - cogs) / revenue))
        operating_margin = None
        if op is not None and revenue:
            operating_margin = max(-1.0, min(1.0, op / revenue))
        sga_ratio = None
        if sga is not None and revenue:
            sga_ratio = max(0.0, min(2.0, sga / revenue))
        return gross_margin, operating_margin, sga_ratio
    except Exception:
        return None, None, None

def get_rnd_ratio(corp_code: str, bsns_year: int) -> Optional[float]:
    revenue, _ = get_financial_scale(corp_code, bsns_year)
    if not revenue or revenue <= 0:
        return None
    try:
        data = dart.api.finance.fnltt_singl_acnt_all(
            corp_code=corp_code, bsns_year=str(bsns_year),
            reprt_code=REPRT_CODE_BUSINESS, fs_div="CFS"
        )
        rows = data.get("list", []) or []
        RND_IDS = {"ifrs-full_ResearchAndDevelopmentExpense", "ResearchAndDevelopmentExpense"}
        RND_NAME_PATTS = {"연구개발비","연구 개발비","연구개발 비용","연구개발비용","R&D","R & D","연구·개발비","기술개발비"}

        def is_pl(r):
            s = (r.get("sj_nm") or "").lower()
            return ("손익" in s) or ("포괄" in s) or ("profit" in s) or ("income" in s)

        for r in rows:
            aid = (r.get("account_id") or "").strip()
            anm = (r.get("account_nm") or "").strip()
            if not is_pl(r):
                continue
            if (aid in RND_IDS) or (anm in RND_NAME_PATTS) or (("연구" in anm) and ("개발" in anm)):
                v = _to_float(r.get("thstrm_amount")) or _to_float(r.get("frmtrm_amount"))
                if v is not None and v >= 0:
                    ratio = v / revenue
                    if 0 <= ratio < 1.0:
                        return ratio
    except Exception:
        pass

    ranges = [(f"{bsns_year}0101", f"{bsns_year+1}0630"),
              (f"{bsns_year-1}0101", f"{bsns_year}0630"),
              (f"{bsns_year}0701", f"{bsns_year+1}1231")]
    best_ratio = None
    for bgn_de, end_de in ranges:
        text = _find_file_text(corp_code, bsns_year, bgn_de, end_de)
        if not text:
            continue
        tables = _all_tables_from_text(text)
        rnd_total = _compute_rnd_total_from_tables(tables, prefer_year=bsns_year)
        if rnd_total and rnd_total > 0:
            r = rnd_total / revenue
            if 0 <= r < 1.0:
                best_ratio = r if (best_ratio is None or r > best_ratio) else best_ratio
    if best_ratio is not None:
        return best_ratio

    for bgn_de, end_de in ranges:
        text = _find_file_text(corp_code, bsns_year, bgn_de, end_de)
        if not text:
            continue
        tables = _all_tables_from_text(text)
        best = None
        for tbl in tables:
            txt = tbl.get_text(" ", strip=True)
            if not any(k in txt for k in ["연구개발", "R&D"]):
                continue
            unit_mul = _parse_unit_from_caption_or_nearby(tbl)
            for df in _dfs_from_table(tbl):
                df = _normalize_colnames(df)
                rd_cols = [c for c in df.columns if any(k in str(c) for k in ["연구개발비","R&D","연구 개발비","연구개발 비용","연구개발비용","연구·개발비","기술개발비"])]
                if not rd_cols:
                    continue
                s = 0.0
                for c in rd_cols:
                    s += float(_numeric_series(df[c]).fillna(0).sum())
                rd = s * unit_mul
                if rd > 0:
                    r = rd / revenue
                    if 0 <= r < 1.0:
                        best = r if best is None else max(best, r)
        if best is not None:
            return best

    return None

_MIX_KOR = [
    (re.compile(r"(\d+)\s*조"), 1e12),
    (re.compile(r"(\d+)\s*천\s*억"), 1e11),
    (re.compile(r"(\d+)\s*백\s*억"), 1e10),
    (re.compile(r"(\d+)\s*십\s*억"), 1e9),
    (re.compile(r"(\d+)\s*억"), 1e8),
    (re.compile(r"(\d+)\s*백\s*만"), 1e6),
    (re.compile(r"(\d+)\s*만"), 1e4),
]

def _parse_mixed_korean_amount(fragment: str) -> Optional[float]:
    if not fragment:
        return None
    total = 0.0
    for patt, mul in _MIX_KOR:
        for m in patt.finditer(fragment):
            try:
                total += float(m.group(1)) * mul
            except Exception:
                continue
    return total if total > 0 else None

# ---- Backlog (건설/조선/방산) ----

BACKLOG_ROW_KWS = [
    "수주", "잔고", "잔량", "수주잔고", "수주 잔고", "수주잔액", "수주잔량",
    "계약잔고", "계약잔액", "남은수행의무", "잔여수행의무",
    "Order", "Backlog", "Order book", "Orderbook", "Order backlog",
    "Remaining", "Remaining orders", "Remaining order"
]
BACKLOG_COL_PREFER = ["잔고", "잔액", "Final", "Ending", "Year-end", "기말", "말", "Backlog", "Order book", "Orderbook", "Order backlog"]
BACKLOG_COL_EXCLUDE = ["신규", "수주액", "신규수주", "인도", "출고", "매출", "매출액", "매출인식", "Revenue", "Sales", "Recognized", "Delivered"]

def _pick_backlog_col(df: pd.DataFrame, prefer_year: int, name_col: Optional[str], rows_mask: Optional[pd.Series]) -> Optional[str]:
    cand_cols = [c for c in df.columns if (name_col is None or c != name_col)]
    if not cand_cols:
        return None
    scored = []
    for c in cand_cols:
        hdr = str(c)
        score = 0
        if any(ex in hdr for ex in BACKLOG_COL_EXCLUDE) and not any(p in hdr for p in BACKLOG_COL_PREFER):
            continue
        yr_hits = _YEAR_RE.findall(hdr)
        if str(prefer_year) in hdr:
            score += 6
        elif any(y for y in yr_hits if abs(int(y) - prefer_year) <= 1):
            score += 4
        if _THIS_RE.search(hdr):
            score += 5
        if any(p in hdr for p in BACKLOG_COL_PREFER):
            score += 3
        if _PREV_RE.search(hdr):
            score -= 1
        scope = df.loc[rows_mask, c] if (rows_mask is not None) else df[c]
        ssum = float(_numeric_series(scope).fillna(0).abs().sum())
        scored.append((score, ssum, c))
    if not scored:
        return None
    scored.sort(key=lambda t: (t[0], t[1]), reverse=True)
    return scored[0][2]

def _compute_backlog_from_tables(tables, prefer_year: Optional[int] = None) -> Optional[float]:
    best_total = None
    for tbl in tables:
        txt = tbl.get_text(" ", strip=True)
        if not any(k in txt for k in BACKLOG_ROW_KWS):
            continue
        unit_mul = _parse_unit_from_caption_or_nearby(tbl)
        dfs = _dfs_from_table(tbl)
        for df in dfs:
            df = _normalize_colnames(df)
            name_col = _pick_name_col(df)
            rows_mask = None
            if name_col and name_col in df.columns:
                name_ser = df[name_col].astype(str)
                rows_mask = name_ser.apply(lambda s: any(k in s for k in BACKLOG_ROW_KWS + ["기말","말"]))
                if not bool(rows_mask.any()):
                    rows_mask = ~name_ser.str.contains("|".join(["기타","내부","조정"]))
            pick = _pick_backlog_col(df, prefer_year or 9999, name_col, rows_mask)
            if not pick:
                num_cols = [c for c in df.columns if c != name_col]
                best_col, best_sum = None, None
                for c in num_cols:
                    vals = (_numeric_series(df.loc[rows_mask, c]) if rows_mask is not None else _numeric_series(df[c])) * unit_mul
                    ssum = float(vals.fillna(0).abs().sum())
                    if best_sum is None or ssum > best_sum:
                        best_sum, best_col = ssum, c
                pick = best_col
            if pick:
                vals = (_numeric_series(df.loc[rows_mask, pick]) if rows_mask is not None else _numeric_series(df[pick])) * unit_mul
                total = float(vals.fillna(0).abs().sum())
                if total and (best_total is None or total > best_total):
                    best_total = total
    return best_total

def _compute_backlog_from_tables_raw(tables, prefer_year: Optional[int] = None) -> Optional[float]:
    best_raw = None
    for tbl in tables:
        txt = tbl.get_text(" ", strip=True)
        if not any(k in txt for k in BACKLOG_ROW_KWS):
            continue
        dfs = _dfs_from_table(tbl)
        for df in dfs:
            df = _normalize_colnames(df)
            name_col = _pick_name_col(df)
            rows_mask = None
            if name_col and name_col in df.columns:
                name_ser = df[name_col].astype(str)
                rows_mask = name_ser.apply(lambda s: any(k in s for k in BACKLOG_ROW_KWS + ["기말","말"]))
                if not bool(rows_mask.any()):
                    rows_mask = ~name_ser.str.contains("|".join(["기타","내부","조정"]))
            pick = _pick_backlog_col(df, prefer_year or 9999, name_col, rows_mask)
            if not pick:
                num_cols = [c for c in df.columns if c != name_col]
                best_col, best_sum = None, None
                for c in num_cols:
                    vals = _numeric_series(df.loc[rows_mask, c]) if rows_mask is not None else _numeric_series(df[c])
                    ssum = float(vals.fillna(0).abs().sum())
                    if best_sum is None or ssum > best_sum:
                        best_sum, best_col = ssum, c
                pick = best_col
            if pick:
                vals = _numeric_series(df.loc[rows_mask, pick]) if rows_mask is not None else _numeric_series(df[pick])
                total = float(vals.fillna(0).abs().sum())
                if total and (best_raw is None or total > best_raw):
                    best_raw = total
    return best_raw

def _autoscale_backlog_to_plausible(raw_total: Optional[float], revenue: Optional[float], text: str) -> Optional[float]:
    if not raw_total or not revenue or revenue <= 0:
        return None
    base_ratio = raw_total / revenue
    hits = sum(text.count(k) for k in ["수주잔", "계약잔", "Order book", "Orderbook", "Order backlog", "Backlog"])
    if base_ratio >= 0.2 or hits < 2:
        return None
    multipliers = [1e6, 1e8, 1e9, 1e10, 1e11, 1e12]
    target = 2.0
    best_val, best_diff = None, None
    for mul in multipliers:
        r = (raw_total * mul) / revenue
        if 0.5 <= r <= 8.0:
            d = abs(r - target)
            if best_diff is None or d < best_diff:
                best_val, best_diff = raw_total * mul, d
    return best_val

def get_construction_backlog_to_revenue(corp_code: str, bsns_year: int) -> Optional[float]:
    revenue, _ = get_financial_scale(corp_code, bsns_year)
    if not revenue or revenue <= 0:
        return None
    ranges = [
        (f"{bsns_year}0101", f"{bsns_year+1}0630"),
        (f"{bsns_year-1}0101", f"{bsns_year}0630"),
        (f"{bsns_year}0701", f"{bsns_year+1}1231"),
    ]
    best_ratio = None
    for bgn_de, end_de in ranges:
        text = _find_file_text(corp_code, bsns_year, bgn_de, end_de)
        if not text:
            continue
        tables = _all_tables_from_text(text)

        backlog_tbl = _compute_backlog_from_tables(tables, prefer_year=bsns_year)
        ratio_tbl = (backlog_tbl / revenue) if (backlog_tbl and revenue) else None
        backlog_txt = _compute_backlog_from_text(text)
        ratio_txt = (backlog_txt / revenue) if (backlog_txt and revenue) else None

        raw_total = _compute_backlog_from_tables_raw(tables, prefer_year=bsns_year)
        scaled = _autoscale_backlog_to_plausible(raw_total, revenue, text)
        ratio_scaled = (scaled / revenue) if (scaled and revenue) else None

        cand = [r for r in [ratio_tbl, ratio_txt, ratio_scaled] if r is not None]
        cand = [min(r, 12.0) for r in cand]
        pick = max(cand) if cand else None
        if pick is not None:
            best_ratio = pick if (best_ratio is None or pick > best_ratio) else best_ratio

    return best_ratio

def _compute_backlog_from_text(text: str) -> Optional[float]:
    if not text:
        return None
    unit_map = {
        "원":1.0,"KRW":1.0,
        "천원":1e3,"만원":1e4,"백만원":1e6,"백만":1e6,
        "억원":1e8,"억":1e8,
        "십억원":1e9,"백억원":1e10,"천억원":1e11,
        "조원":1e12,"조":1e12
    }
    anchors = list(re.finditer(r"(수주잔고|계약잔[고량]|남은수행의무|잔여수행의무|Order\s*book|Order\s*backlog|Backlog)", text, flags=re.IGNORECASE))
    cands = []
    for a in anchors:
        s = max(0, a.start()-50); e = min(len(text), a.end()+150)
        frag = text[s:e]
        mixed = _parse_mixed_korean_amount(frag)
        if mixed and mixed > 0:
            cands.append(mixed)
    if cands:
        return max(cands)

    pat = re.compile(
        r"(수주잔고|계약잔고|수주잔량|남은수행의무|잔여수행의무|Order\s*book|Order\s*backlog|Backlog)"
        r"[^\d]{0,50}([0-9][0-9,\.]*)\s*(조원|조|천억원|백억원|십억원|억원|억|백만원|만원|천원|원|KRW)",
        re.IGNORECASE
    )
    cands2 = []
    for m in pat.finditer(text):
        num = m.group(2).replace(",", "")
        unit = m.group(3).replace(" ", "")
        try:
            v = float(num) * unit_map.get(unit, 1.0)
            cands2.append(v)
        except Exception:
            continue
    return max(cands2) if cands2 else None

def get_backlog_to_revenue_pair(corp_code: str, bsns_year: int) -> Tuple[Optional[float], Optional[float]]:
    cur = get_construction_backlog_to_revenue(corp_code, bsns_year)
    prev = get_construction_backlog_to_revenue(corp_code, bsns_year - 1)
    return cur, prev

# Bank/Card metrics

def _pick_amount(rows, names: List[str], partial_ok=True) -> Optional[float]:
    for r in rows:
        anm = (r.get("account_nm") or "").strip()
        aid = (r.get("account_id") or "").strip()
        if (anm in names) or (aid in names) or (partial_ok and any(k.lower() in anm.lower() for k in names)):
            v = _to_float(r.get("thstrm_amount")) or _to_float(r.get("frmtrm_amount"))
            if v is not None:
                return v
    return None

def get_bank_non_interest_income_ratio(corp_code: str, bsns_year: int) -> Optional[float]:
    try:
        data = dart.api.finance.fnltt_singl_acnt_all(
            corp_code=corp_code, bsns_year=str(bsns_year),
            reprt_code=REPRT_CODE_BUSINESS, fs_div="CFS"
        )
        rows = data.get("list", [])
        non_interest = _pick_amount(rows, ["비이자이익","Net fee and commission income","Fee and commission income","Other operating income"])
        operating_rev = _pick_amount(rows, ["영업수익","Operating revenue","Revenue"])
        if non_interest is not None and operating_rev and operating_rev > 0:
            return non_interest / operating_rev
    except Exception:
        pass
    return None

def get_bank_loan_to_deposit_ratio(corp_code: str, bsns_year: int) -> Optional[float]:
    try:
        data = dart.api.finance.fnltt_singl_acnt_all(
            corp_code=corp_code, bsns_year=str(bsns_year),
            reprt_code=REPRT_CODE_BUSINESS, fs_div="CFS"
        )
        rows = data.get("list", [])
        loans = _pick_amount(rows, ["대출채권","Loans","Loans and receivables","ifrs-full_LoansAndReceivables"])
        deposits = _pick_amount(rows, ["예수금","고객예수금","Deposits","Deposits from customers","ifrs-full_DepositsFromCustomers"])
        if loans and deposits and deposits > 0:
            return loans / deposits
    except Exception:
        pass
    return None

# ----------------------------
# Orchestrator
# ----------------------------

@dataclass
class NonFinancialCore:
    company: str
    corp_code: Optional[str]
    bsns_year: int
    revenue_krw: Optional[float]
    total_assets_krw: Optional[float]
    num_segments: Optional[int]
    largest_segment_share: Optional[float]
    portfolio_hhi: Optional[float]
    board_independence_ratio: Optional[float]
    ownership_concentration_ratio: Optional[float]
    equity_krw: Optional[float] = None
    export_ratio: Optional[float] = None
    top1_customer_share: Optional[float] = None
    top5_customer_share: Optional[float] = None
    inventory_days: Optional[float] = None
    inventory_days_prev: Optional[float] = None
    capex_to_revenue: Optional[float] = None
    r_and_d_ratio: Optional[float] = None
    backlog_to_revenue: Optional[float] = None
    backlog_to_revenue_prev: Optional[float] = None
    non_interest_income_ratio: Optional[float] = None
    loan_to_deposit_ratio: Optional[float] = None
    tech_leadership_score: Optional[float] = None
    ship_tech_score: Optional[float] = None
    pharma_innovation_score: Optional[float] = None
    bank_safety_score: Optional[float] = None
    defense_government_ratio_est: Optional[float] = None
    defense_export_ratio_est: Optional[float] = None
    # internet service (optional)
    gross_margin_ratio: Optional[float] = None
    operating_margin_ratio: Optional[float] = None
    sga_ratio: Optional[float] = None
    revenue_yoy: Optional[float] = None
    ad_share: Optional[float] = None
    subscription_share: Optional[float] = None
    commission_share: Optional[float] = None
    content_share: Optional[float] = None
    commerce_share: Optional[float] = None
    fintech_share: Optional[float] = None
    recurring_revenue_share_proxy: Optional[float] = None

def extract_industry_specific_metrics(corp_code: str, bsns_year: int, industry_hint: Optional[str] = None) -> Dict[str, Any]:
    out: Dict[str, Any] = {}

    # 공통
    out["export_ratio"] = get_export_ratio(corp_code, bsns_year)
    t1, t5 = get_customer_concentration(corp_code, bsns_year, topn=5)
    out["top1_customer_share"] = t1
    out["top5_customer_share"] = t5
    cur_inv, prev_inv = get_inventory_days_pair(corp_code, bsns_year)
    out["inventory_days"] = cur_inv
    out["inventory_days_prev"] = prev_inv
    out["capex_to_revenue"] = get_capex_to_revenue(corp_code, bsns_year)
    out["r_and_d_ratio"] = get_rnd_ratio(corp_code, bsns_year)
    out["tech_leadership_score"] = get_tech_leadership_score(corp_code, bsns_year)

    out.update(get_profitability_metrics(corp_code, bsns_year) or {})

    hint = (industry_hint or "").strip()
    if not hint:
        hint = _guess_industry_hint(corp_code, bsns_year) or ""

    if any(k in hint for k in ["건설","조선","방산"]):
        cur_bl, prev_bl = get_backlog_to_revenue_pair(corp_code, bsns_year)
        out["backlog_to_revenue"] = out.get("backlog_to_revenue") or cur_bl
        out["backlog_to_revenue_prev"] = prev_bl
    if out.get("backlog_to_revenue") is None:
        out["backlog_to_revenue"] = get_construction_backlog_to_revenue(corp_code, bsns_year)

    if "조선" in hint:
        out["ship_tech_score"] = get_ship_tech_score(corp_code, bsns_year)

    if ("은행" in hint) or ("카드" in hint):
        out["non_interest_income_ratio"] = get_bank_non_interest_income_ratio(corp_code, bsns_year)
    if "은행" in hint:
        out["loan_to_deposit_ratio"] = get_bank_loan_to_deposit_ratio(corp_code, bsns_year)
        try:
            text = _find_file_text(corp_code, bsns_year, f"{bsns_year}0101", f"{bsns_year+1}0630") or ""
            kw = ["BIS", "자기자본비율", "ROA", "ROE"]
            cnt = sum(text.count(k) for k in kw)
            norm = cnt / max(1.0, len(text) / 10000.0)
            out["bank_safety_score"] = min(1.0, norm / 4.0) if norm > 0 else None
        except Exception:
            out["bank_safety_score"] = None

    if any(k in hint for k in ["인터넷", "인터넷서비스", "인터넷 서비스", "플랫폼", "포털", "게임"]):
        from_mix = get_internet_revenue_mix(corp_code, bsns_year)
        out.update(from_mix or {})
    if any(k in hint for k in ["인터넷", "플랫폼", "포털", "게임", "Internet", "Platform"]):
        gm, opm, sga = get_profitability_ratios(corp_code, bsns_year)
        out["gross_margin_ratio"] = gm
        out["operating_margin_ratio"] = opm
        out["sga_ratio"] = sga
        out["revenue_yoy"] = get_revenue_yoy(corp_code, bsns_year)
        mix = get_internet_service_mix(corp_code, bsns_year)
        out.update(mix)

    if "제약" in hint:
        try:
            text = _find_file_text(corp_code, bsns_year, f"{bsns_year}0101", f"{bsns_year+1}0630") or ""
            kw = ["임상", "신약", "허가", "승인", "Clinical", "Approval"]
            cnt = sum(text.count(k) for k in kw)
            norm = cnt / max(1.0, len(text) / 10000.0)
            out["pharma_innovation_score"] = min(1.0, norm / 6.0) if norm > 0 else None
        except Exception:
            out["pharma_innovation_score"] = None

    need_def_mix = ("방산" in hint) or (out.get("defense_government_ratio_est") is None and out.get("defense_export_ratio_est") is None)
    if need_def_mix:
        g, e = get_defense_mix_estimates(corp_code, bsns_year)
        out["defense_government_ratio_est"] = g
        out["defense_export_ratio_est"] = e

    for k in [
        "backlog_to_revenue", "backlog_to_revenue_prev",
        "top1_customer_share", "top5_customer_share",
        "defense_government_ratio_est", "defense_export_ratio_est"
    ]:
        out[k] = _nan_to_none(out.get(k))

    return out

_GUESS_KWS = {
    "방산": ["방위사업청","국방부","유도무기","레이더","유도탄","미사일","DAPA","K-방산","K-defense","군납"],
    "은행": ["예수금","대출채권","BIS","ROA","ROE","LDR"],
    "제약": ["임상","신약","허가","승인","FDA","Clinical","Approval"],
    "조선": ["선박","LNG","Dual-fuel","조선소","VLCC","컨테이너선","Order book"],
    "건설": ["수주잔고","도급","분양","주택사업","플랜트","Civil","건축"]
}
def _guess_industry_hint(corp_code: str, bsns_year: int) -> Optional[str]:
    try:
        text = _find_file_text(corp_code, bsns_year, f"{bsns_year}0101", f"{bsns_year+1}0630") or ""
    except Exception:
        text = ""
    t = text
    for ind, kws in _GUESS_KWS.items():
        hits = sum(t.count(k) for k in kws)
        if hits >= 2:
            return ind
    return None

def extract_non_financial_core(company: str, year: Optional[int] = None, industry_hint: Optional[str] = None) -> Dict[str, Any]:
    _setup_dart()
    bsns_year = year or _year_default()
    corp_code = get_corp_code(company)

    if not corp_code:
        return {
            "company": company,
            "corp_code": None,
            "bsns_year": bsns_year,
            "error": "회사 코드(corp_code)를 찾지 못했습니다."
        }

    revenue, assets = get_financial_scale(corp_code, bsns_year)
    num_seg, largest_share, hhi = get_business_portfolio(corp_code, bsns_year)
    board_ratio, own_conc = get_governance(corp_code, bsns_year)
    equity = get_equity_total(corp_code, bsns_year)

    auto_hint = (industry_hint or "") or _guess_industry_hint(corp_code, bsns_year) or ""
    extras = extract_industry_specific_metrics(corp_code, bsns_year, industry_hint=auto_hint)

    core = NonFinancialCore(
        company=company,
        corp_code=corp_code,
        bsns_year=bsns_year,
        revenue_krw=revenue,
        total_assets_krw=assets,
        num_segments=num_seg,
        largest_segment_share=largest_share,
        portfolio_hhi=hhi,
        board_independence_ratio=board_ratio,
        ownership_concentration_ratio=own_conc,
        equity_krw=equity,
        export_ratio=extras.get("export_ratio"),
        top1_customer_share=extras.get("top1_customer_share"),
        top5_customer_share=extras.get("top5_customer_share"),
        inventory_days=extras.get("inventory_days"),
        inventory_days_prev=extras.get("inventory_days_prev"),
        capex_to_revenue=extras.get("capex_to_revenue"),
        r_and_d_ratio=extras.get("r_and_d_ratio"),
        backlog_to_revenue=extras.get("backlog_to_revenue"),
        backlog_to_revenue_prev=extras.get("backlog_to_revenue_prev"),
        non_interest_income_ratio=extras.get("non_interest_income_ratio"),
        loan_to_deposit_ratio=extras.get("loan_to_deposit_ratio"),
        tech_leadership_score=extras.get("tech_leadership_score"),
        ship_tech_score=extras.get("ship_tech_score"),
        pharma_innovation_score=extras.get("pharma_innovation_score"),
        bank_safety_score=extras.get("bank_safety_score"),
        defense_government_ratio_est=extras.get("defense_government_ratio_est"),
        defense_export_ratio_est=extras.get("defense_export_ratio_est"),
    )
    res = asdict(core)
    for k, v in extras.items():
        if v is not None and k not in res:
            res[k] = v
    return res

# ----------------------------
# CLI (optional)
# ----------------------------

def _main():
    import argparse
    p = argparse.ArgumentParser()
    p.add_argument("--company", required=True, help="회사명 (예: 현대건설)")
    p.add_argument("--year", type=int, default=None, help="사업연도 (미입력시 직전년도 자동)")
    p.add_argument("--industry-hint", default=None, help="업종 힌트 (예: 건설/은행/카드/정유/반도체 등)")
    args = p.parse_args()

    res = extract_non_financial_core(args.company, year=args.year, industry_hint=args.industry_hint)
    print(json.dumps(res, ensure_ascii=False, indent=2))

if __name__ == "__main__":
    _main()
