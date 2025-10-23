# kiwoom_finance/dart_client.py
from __future__ import annotations

import os
import time
import unicodedata
import re
from typing import Optional, Dict
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


def _with_retry(fn, tries=3, base_sleep=1.2):
    last = None
    for i in range(tries):
        try:
            return fn()
        except (xml.parsers.expat.ExpatError, requests.RequestException, RuntimeError) as e:
            last = e
            time.sleep(base_sleep * (i + 1))
    if last:
        raise last


def _is_placeholder_key(key: str | None) -> bool:
    """
    사용자가 CMD/PowerShell 플레이스홀더 그대로 전달한 케이스를 식별:
    - "%DART_API_KEY%" (CMD)
    - "$DART_API_KEY"   (PowerShell/Unix)
    - "${DART_API_KEY}" (쉘)
    """
    if not key:
        return True
    k = key.strip()
    if not k:
        return True
    # 대표적인 플레이스홀더 패턴들
    placeholder_patterns = [
        r"^%DART_API_KEY%$",      # CMD
        r"^\$DART_API_KEY$",      # PowerShell/Unix
        r"^\$\{?DART_API_KEY\}?$",# ${DART_API_KEY}
    ]
    if any(re.match(p, k) for p in placeholder_patterns):
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
    - 전체 법인목록을 한 번에 받아 '종목코드 -> corp' 매핑 캐시화
    - 재시도와 유니코드 정규화 포함
    - ⚠️ 플레이스홀더/미설정 키는 즉시 에러로 안내
    """
    global _INITIALIZED, _CORP_BY_STOCK

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
        mapping = {}
        for corp in corp_list.corps:
            sc = getattr(corp, "stock_code", None)
            if sc:
                corp.corp_name = _normalize(getattr(corp, "corp_name", ""))
                mapping[sc] = corp
        if not mapping:
            raise RuntimeError("Empty corp list loaded from DART")
        return mapping

    _CORP_BY_STOCK = _with_retry(_load_corp_list, tries=5, base_sleep=1.0)
    _INITIALIZED = True
    print(f"✅ OpenDART 초기화 성공: 상장사 {len(_CORP_BY_STOCK)}건 캐시됨")


def find_corp(stock_code: str):
    """캐시 기반 corp 조회(네트워크 호출 없음). 실패 시 None 반환."""
    if not _INITIALIZED:
        init_dart()
    return _CORP_BY_STOCK.get(str(stock_code))


def _tqdm_write(msg: str):
    try:
        from tqdm import tqdm as _tqdm
        _tqdm.write(msg)
    except Exception:
        print(msg)


def extract_fs(corp, bgn_de: str, report_tp: str, separate: bool):
    """
    안정화 버전 재무제표 추출:
    - dart.fs.extract(...)를 직접 사용 (report_tp: 'annual' | 'quarter')
    - 네트워크/빈응답 재시도
    - NoDataReceived 발생 시 annual↔quarter 폴백
    """
    if corp is None:
        raise ValueError("corp is None")

    def _do():
        # ✅ 공시 검색을 우회하고, FS 전용 API를 직접 사용
        return dart.fs.extract(
            corp_code=corp.corp_code,
            bgn_de=bgn_de,
            report_tp=report_tp,   # 'annual' or 'quarter'
            separate=separate
        )

    try:
        return _with_retry(_do, tries=4, base_sleep=1.5)

    except NoDataReceived:
        # 보수적 폴백: 연간이 없으면 분기, 분기가 없으면 연간도 한 번 더 시도
        alt = "quarter" if report_tp == "annual" else "annual"
        _tqdm_write(f"⚠️ {corp.corp_name}({corp.stock_code}) {report_tp} 데이터 없음 → {alt}로 폴백 시도")

        def _alt():
            return dart.fs.extract(
                corp_code=corp.corp_code,
                bgn_de=bgn_de,
                report_tp=alt,
                separate=separate
            )

        return _with_retry(_alt, tries=3, base_sleep=1.5)
