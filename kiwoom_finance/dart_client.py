# src/kiwoom_finance/dart_client.py
from __future__ import annotations

import os
import time
import unicodedata
import re
from typing import Optional, Dict, Literal, Callable, TypeVar
import xml.parsers.expat

import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

import dart_fss as dart
from dart_fss.errors.errors import NoDataReceived  # ⬅ 추가

from dotenv import load_dotenv
load_dotenv()  # ✅ .env 파일 자동 로드

# -------- 내부 상태 (모듈 전역 캐시) --------
_CORP_BY_STOCK: Dict[str, "dart.api.corp.Corp"] = {}
_CORP_BY_NAME: Dict[str, "dart.api.corp.Corp"] = {}
_INITIALIZED = False

# 전역 캐시 (전체 corp list)
_CORP_LIST_CACHE = None


def _normalize(s: str) -> str:
    s = unicodedata.normalize("NFKC", s or "")
    s = re.sub(r"\s+", " ", s).strip()
    return s


def _build_requests_session() -> requests.Session:
    # dart_fss 내부도 requests를 쓰지만, 우리도 세션을 만들어 두면
    # 전역 어댑터 설정(백오프)을 재활용할 수 있습니다.
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
    """
    간단한 재시도 유틸: 예외 시 지수 백오프 후 재시도.
    마지막 시도에서의 예외는 그대로 전파.
    """
    last_exc: Optional[BaseException] = None
    for i in range(1, max(1, tries) + 1):
        try:
            return fn()
        except BaseException as e:  # 네트워크/파싱계 예외 전부 포함
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
    # 흔한 플레이스홀더 패턴들
    if re.fullmatch(r"(your[-_ ]?key|changeme|placeholder|xxxx+)", k, re.I):
        return True
    # 그대로 "DART_API_KEY"라는 토큰이 들어있는 문자열도 의심
    if "DART_API_KEY" in k and any(ch in k for ch in ("%","$","{","}")):
        return True
    return False


def get_corp_list(refresh: bool = False):
    """
    dart_fss.get_corp_list() thin wrapper + 간단 캐시.
    bench/validate 스크립트에서 전체 종목코드 샘플링용으로 사용.
    """
    global _CORP_LIST_CACHE
    if refresh or _CORP_LIST_CACHE is None:
        _CORP_LIST_CACHE = dart.get_corp_list()
    return _CORP_LIST_CACHE


def init_dart(api_key: Optional[str] = None):
    """
    - DART API 키 설정 (환경변수 DART_API_KEY 사용 가능)
    - 전체 법인목록을 한 번에 받아 '종목코드 -> corp', '이름 -> corp' 매핑 캐시화
    - 재시도와 유니코드 정규화 포함
    - ⚠️ 플레이스홀더/미설정 키는 즉시 에러로 안내
    """
    global _INITIALIZED, _CORP_BY_STOCK, _CORP_BY_NAME

    if _INITIALIZED:
        return

    # 1) 키 소스 합치기: 인자로 온 키가 우선, 없으면 환경변수
    key_candidate = (api_key or os.getenv("DART_API_KEY", "")).strip()

    # 2) 플레이스홀더/미설정 가드
    if _is_placeholder_key(key_candidate):
        raise RuntimeError(
            "DART API 키가 설정되지 않았습니다.\n"
            " - CMD:        set DART_API_KEY=YOUR_KEY  후  --api-key %DART_API_KEY%\n"
            " - PowerShell: $env:DART_API_KEY='YOUR_KEY' 후  --api-key $env:DART_API_KEY\n"
            " - 또는 --api-key YOUR_KEY 를 직접 전달하세요."
        )

    # 3) 키 설정
    dart.set_api_key(api_key=key_candidate)

    # 세션(백오프) 구성 — dart_fss는 자체 세션을 갖지만
    # 시스템 전체 레벨에서 연결 안정성에 도움.
    _ = _build_requests_session()

    def _load_corp_list():
        corp_list = dart.get_corp_list()  # 네트워크 1회
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
                    # 첫 매핑
                    by_name[corp_name] = corp
                else:
                    # ✅ 같은 이름이면 "상장사"를 우선으로 유지/교체
                    prev_has_code = bool(getattr(prev, "stock_code", None))
                    if (not prev_has_code) and has_code:
                        by_name[corp_name] = corp

        if not by_code:
            raise RuntimeError("Empty corp list loaded from DART")
        return by_code, by_name

    _CORP_BY_STOCK, _CORP_BY_NAME = _with_retry(_load_corp_list, tries=5, base_sleep=1.0)
    _INITIALIZED = True
    print(
        "✅ OpenDART 초기화 성공: 상장사 "
        f"{len(_CORP_BY_STOCK)}건(이름 매핑 {len(_CORP_BY_NAME)}건) 캐시됨"
    )


IdentifierType = Literal["auto", "name", "code"]


def find_corp(identifier: str, *, by: IdentifierType = "auto"):
    """
    캐시 기반 corp 조회(네트워크 호출 없음).
    - by="name"  : 종목명(공백/기호 무시)으로 검색
    - by="code"  : 종목코드(숫자 6자리)로 검색
    - by="auto"  : 이름 우선 → 코드 순으로 검색
    실패 시 None 반환.
    """
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
        """
        동일 이름 중 상장사(=stock_code 존재)만 스캔하여 반환 (fallback 용)
        """
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

    # auto: name → code
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
    # 기본 annual
    return "annual"


def extract_fs(corp, bgn_de: str, report_tp: str, separate: bool):
    """
    안정화 버전 재무제표 추출:
    - dart.fs.extract(...)를 직접 사용 (report_tp: 'annual' | 'quarter')
    - 네트워크/빈응답 재시도
    - NoDataReceived 발생 시 annual↔quarter 폴백
    """
    if corp is None:
        raise ValueError("corp is None")

    rpt_norm = _sanitize_report_tp(report_tp)

    def _do(rpt: str):
        # ✅ 공시 검색을 우회하고, FS 전용 API를 직접 사용
        return dart.fs.extract(
            corp_code=corp.corp_code,
            bgn_de=bgn_de,
            report_tp=rpt,          # 'annual' | 'quarter'
            separate=separate,      # True=별도, False=연결
        )

    # 1차 시도 (요청 모드)
    try:
        return _with_retry(lambda: _do(rpt_norm), tries=3, base_sleep=0.8)
    except NoDataReceived:
        # 2차 폴백 (annual <-> quarter 전환)
        alt = "quarter" if rpt_norm == "annual" else "annual"
        _tqdm_write(f"ℹ️ FS 빈응답(NoDataReceived) → report_tp '{rpt_norm}'→'{alt}' 폴백 시도")
        return _with_retry(lambda: _do(alt), tries=2, base_sleep=1.0)
    except (requests.RequestException, xml.parsers.expat.ExpatError) as e:
        # 네트워크/파싱 오류: 한 번 더 시도
        _tqdm_write(f"⚠️ FS 요청 오류: {type(e).__name__}: {e} → 재시도")
        return _with_retry(lambda: _do(rpt_norm), tries=2, base_sleep=1.2)
