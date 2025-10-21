# src/kiwoom_finance/dart_client.py
from __future__ import annotations
from typing import Optional
import dart_fss as dart
from dotenv import load_dotenv, find_dotenv
import os

def _load_env_best_effort():
    env = find_dotenv(usecwd=True)
    if env:
        load_dotenv(env)

def init_dart(api_key: Optional[str] = None):
    _load_env_best_effort()
    key = api_key or os.getenv("DART_API_KEY", "").strip()
    if not key:
        raise RuntimeError("DART_API_KEY is not set. Put it in .env or env var.")
    dart.set_api_key(key)

def get_corp_list():
    return dart.get_corp_list()

def find_corp(code_or_name: str):
    corps = get_corp_list()
    if code_or_name.isdigit() and len(code_or_name) == 6:
        c = corps.find_by_stock_code(code_or_name)
        if c:
            return c
    m = corps.find_by_corp_name(code_or_name, exactly=True)
    if m:
        return m[0]
    raise ValueError(f"Cannot find corp for: {code_or_name}")

def extract_fs(corp, bgn_de="20170101", report_tp="annual", separate=False):
    """
    1) 연결 우선 시도
    2) 실패하면 개별(separate=True)로 폴백
    """
    try:
        return corp.extract_fs(
            bgn_de=bgn_de, report_tp=report_tp, separate=separate, progressbar=False
        )
    except Exception as e:
        # 연결 미존재(특히 중소형/스팩/특정 연도)에 자주 발생 → 개별로 재시도
        try:
            return corp.extract_fs(
                bgn_de=bgn_de, report_tp=report_tp, separate=True, progressbar=False
            )
        except Exception as e2:
            # 마지막으로 분기 보고서도 시도(간헐적 공백 보완)
            try:
                return corp.extract_fs(
                    bgn_de=bgn_de, report_tp="quarter", separate=True, progressbar=False
                )
            except Exception:
                raise
