# src/kiwoom_finance/dart_client.py
from __future__ import annotations

import os
import time
import unicodedata
import re
from typing import Optional, Dict, Literal, Callable, TypeVar, Any
import xml.parsers.expat

import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

import dart_fss as dart
from dart_fss.errors.errors import NoDataReceived  # 빈응답 예외

from dotenv import load_dotenv
load_dotenv()  # ✅ .env 파일 자동 로드

_CORP_BY_STOCK: Dict[str, "dart.api.corp.Corp"] = {}
_CORP_BY_NAME: Dict[str, "dart.api.corp.Corp"] = {}
_INITIALIZED = False
_CORP_LIST_CACHE = None

def _normalize(s: str) -> str:
    s = unicodedata.normalize("NFKC", s or "")
    s = re.sub(r"\s+", " ", s).strip()
    return s

def _build_requests_session() -> requests.Session:
    s = requests.Session()
    retry = Retry(
        total=5, connect=5, read=5,
        backoff_factor=0.8,
        status_forcelist=[429, 500, 502, 503, 504],
        allowed_methods=["GET", "POST"],
        raise_on_status=False,
    )
    s.headers.update({"User-Agent": "kiwoombank-batch/1.0"})
    adapter = HTTPAdapter(max_retries=retry, pool_connections=50, pool_maxsize=50)
    s.mount("http://", adapter)
    s.mount("https://", adapter)
    return s

T = TypeVar("T")
def _with_retry(fn: Callable[[], T], *, tries: int = 3, base_sleep: float = 0.8, factor: float = 1.7) -> T:
    last_exc: Optional[BaseException] = None
    for i in range(1, max(1, tries) + 1):
        try:
            return fn()
        except BaseException as e:
            last_exc = e
            if i >= tries:
                break
            time.sleep(base_sleep * (factor ** (i - 1)))
    assert last_exc is not None
    raise last_exc

def _is_placeholder_key(key: str | None) -> bool:
    k = (key or "").strip()
    if not k:
        return True
    if re.fullmatch(r"(your[-_ ]?key|changeme|placeholder|xxxx+)", k, re.I):
        return True
    if "DART_API_KEY" in k and any(ch in k for ch in ("%","$","{","}")):
        return True
    return False

def get_corp_list(refresh: bool = False):
    global _CORP_LIST_CACHE
    if refresh or _CORP_LIST_CACHE is None:
        _CORP_LIST_CACHE = dart.get_corp_list()
    return _CORP_LIST_CACHE

def init_dart(api_key: Optional[str] = None):
    global _INITIALIZED, _CORP_BY_STOCK, _CORP_BY_NAME
    if _INITIALIZED:
        return

    key_candidate = (api_key or os.getenv("DART_API_KEY", "")).strip()
    if _is_placeholder_key(key_candidate):
        raise RuntimeError(
            "DART API 키가 설정되지 않았습니다.\n"
            " - CMD:        set DART_API_KEY=YOUR_KEY  후  --api-key %DART_API_KEY%\n"
            " - PowerShell: $env:DART_API_KEY='YOUR_KEY' 후  --api-key $env:DART_API_KEY\n"
            " - 또는 --api-key YOUR_KEY 를 직접 전달하세요."
        )
    dart.set_api_key(api_key=key_candidate)
    _ = _build_requests_session()

    def _load_corp_list():
        corp_list = dart.get_corp_list()
        by_code: Dict[str, "dart.api.corp.Corp"] = {}
        by_name: Dict[str, "dart.api.corp.Corp"] = {}
        for corp in corp_list.corps:
            sc = getattr(corp, "stock_code", None)
            has_code = bool(sc and str(sc).strip())
            stock_code = None
            if has_code:
                stock_code = str(sc).strip()
                if stock_code.isdigit() and len(stock_code) < 6:
                    stock_code = stock_code.zfill(6)
                by_code[stock_code] = corp
            corp_name = _normalize(getattr(corp, "corp_name", ""))
            if corp_name:
                corp.corp_name = corp_name
                prev = by_name.get(corp_name)
                if prev is None:
                    by_name[corp_name] = corp
                else:
                    prev_has_code = bool(getattr(prev, "stock_code", None))
                    if (not prev_has_code) and has_code:
                        by_name[corp_name] = corp
        if not by_code:
            raise RuntimeError("Empty corp list loaded from DART")
        return by_code, by_name

    _CORP_BY_STOCK, _CORP_BY_NAME = _with_retry(_load_corp_list, tries=5, base_sleep=1.0)
    _INITIALIZED = True
    print("✅ OpenDART 초기화 성공: 상장사 "
          f"{len(_CORP_BY_STOCK)}건(이름 매핑 {len(_CORP_BY_NAME)}건) 캐시됨")

IdentifierType = Literal["auto", "name", "code"]

def find_corp(identifier: str, *, by: IdentifierType = "auto"):
    if not _INITIALIZED:
        init_dart()
    if identifier is None:
        return None
    token = str(identifier).strip()
    if not token:
        return None

    def _lookup_code(code: str):
        if not code:
            return None
        if code.isdigit() and len(code) < 6:
            code = code.zfill(6)
        return _CORP_BY_STOCK.get(code)

    def _lookup_name_first(name: str):
        if not name:
            return None
        return _CORP_BY_NAME.get(_normalize(name))

    def _lookup_name_listed(name: str):
        if not name:
            return None
        norm = _normalize(name)
        for c in _CORP_BY_STOCK.values():
            if getattr(c, "corp_name", None) == norm:
                return c
        return None

    if by == "code":
        return _lookup_code(token)
    if by == "name":
        corp = _lookup_name_first(token)
        if corp and getattr(corp, "stock_code", None):
            return corp
        return _lookup_name_listed(token)

    corp = _lookup_name_first(token)
    if corp and getattr(corp, "stock_code", None):
        return corp
    corp2 = _lookup_name_listed(token)
    return corp2 or _lookup_code(token)

def _tqdm_write(msg: str):
    try:
        from tqdm import tqdm as _tqdm
        _tqdm.write(msg)
    except Exception:
        print(msg)

def _sanitize_report_tp(rpt: str) -> str:
    r = (rpt or "").strip().lower()
    if r in ("annual", "a", "y", "year", "yearly"):
        return "annual"
    if r in ("quarter", "q", "qr", "quater", "quarterly"):
        return "quarter"
    return "annual"

def _fs_to_dict(fs_obj: Any) -> Dict[str, Any]:
    if isinstance(fs_obj, dict):
        out = {
            "bs": fs_obj.get("bs") or fs_obj.get("balance_sheet") or fs_obj.get("BalanceSheet"),
            "is": fs_obj.get("is") or fs_obj.get("income_statement") or fs_obj.get("IncomeStatement"),
            "cis": fs_obj.get("cis") or fs_obj.get("comprehensive_income") or fs_obj.get("ComprehensiveIncome"),
            "cf": fs_obj.get("cf") or fs_obj.get("cash_flows") or fs_obj.get("CashFlows"),
        }
        return out

    def _get(obj, *names):
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

    out = {
        "bs":  _get(fs_obj, "bs", "balance_sheet", "BalanceSheet"),
        "is":  _get(fs_obj, "is", "income_statement", "IncomeStatement"),
        "cis": _get(fs_obj, "cis", "comprehensive_income", "ComprehensiveIncome"),
        "cf":  _get(fs_obj, "cf", "cash_flows", "CashFlows"),
    }
    return out

def extract_fs(corp, bgn_de: str, report_tp: str, separate: bool):
    """
    dart.fs.extract(...) 호출 → dict({'bs','is','cis','cf'}) 표준화 반환.
    빈응답/네트워크 예외는 재시도 + annual↔quarter 폴백.
    """
    if corp is None:
        raise ValueError("corp is None")

    rpt_norm = _sanitize_report_tp(report_tp)

    def _do(rpt: str):
        return dart.fs.extract(
            corp_code=corp.corp_code,
            bgn_de=bgn_de,
            report_tp=rpt,          # 'annual' | 'quarter'
            separate=separate,      # True=별도, False=연결
        )

    try:
        fs = _with_retry(lambda: _do(rpt_norm), tries=3, base_sleep=0.8)
    except NoDataReceived:
        alt = "quarter" if rpt_norm == "annual" else "annual"
        _tqdm_write(f"ℹ️ FS 빈응답(NoDataReceived) → report_tp '{rpt_norm}'→'{alt}' 폴백 시도")
        fs = _with_retry(lambda: _do(alt), tries=2, base_sleep=1.0)
    except (requests.RequestException, xml.parsers.expat.ExpatError) as e:
        _tqdm_write(f"⚠️ FS 요청 오류: {type(e).__name__}: {e} → 재시도")
        fs = _with_retry(lambda: _do(rpt_norm), tries=2, base_sleep=1.2)

    return _fs_to_dict(fs)