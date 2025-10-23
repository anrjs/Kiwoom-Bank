# src/kiwoom_finance/batch.py
from __future__ import annotations

import time
import traceback
from concurrent.futures import ThreadPoolExecutor, ProcessPoolExecutor, as_completed, TimeoutError
from dataclasses import dataclass
from pathlib import Path
from typing import List, Optional
import hashlib
import json
import re
import sys

import pandas as pd
from tqdm import tqdm

# 내부 모듈
from .dart_client import extract_fs, find_corp, init_dart
from .preprocess import preprocess_all
from .metrics import compute_metrics_df_flat_kor

# dart_fss 특정 예외(연결재무 미발견) 식별용
try:
    from dart_fss.errors.errors import NotFoundConsolidated  # type: ignore
except Exception:  # dart_fss 미로딩 환경 대비
    NotFoundConsolidated = tuple()  # noqa: N816


# -----------------------
# 기본 산출 컬럼(존재 시에만 선택)
# -----------------------
DEFAULT_COLS = [
    "debt_ratio", "equity_ratio", "debt_dependency_ratio",
    "current_ratio", "quick_ratio", "interest_coverage_ratio",
    "ebitda_to_total_debt", "cfo_to_total_debt", "free_cash_flow",
    "operating_margin", "roa", "roe", "net_profit_margin",
    "total_asset_turnover", "accounts_receivable_turnover", "inventory_turnover",
    "sales_growth_rate", "operating_income_growth_rate", "total_asset_growth_rate",
]


@dataclass
class WorkerConfig:
    bgn_de: str
    report_tp: str
    separate: bool
    latest_only: bool
    percent_format: bool
    api_key: Optional[str] = None
    retries: int = 3
    throttle_sec: float = 1.2  # DART 부하 방지용 sleep (1.0 -> 1.2)


def _select_existing_cols(df: pd.DataFrame) -> pd.DataFrame:
    """DEFAULT_COLS 중 실제 존재하는 것만 추려서 반환"""
    keep = [c for c in DEFAULT_COLS if c in df.columns]
    return df[keep].copy() if keep else pd.DataFrame(index=df.index)


def _try_extract_with_fallback(corp, cfg: WorkerConfig):
    """
    1차: cfg.separate 설정대로 시도
    2차: NotFoundConsolidated 시 반대 separate로 폴백 시도
    """
    try:
        return extract_fs(
            corp,
            bgn_de=cfg.bgn_de,
            report_tp=cfg.report_tp,
            separate=cfg.separate,
        )
    except Exception as e:
        # 연결/별도 미발견 시 폴백
        is_nfc = False
        if NotFoundConsolidated and isinstance(e, NotFoundConsolidated):  # 정식 판별
            is_nfc = True
        elif "NotFoundConsolidated" in f"{type(e)} {e}":  # 문자열 판별(보조)
            is_nfc = True

        if is_nfc:
            alt = not cfg.separate
            tqdm.write(
                f"🔁 [{getattr(corp, 'stock_code', '???')}] "
                f"{'연결' if cfg.separate else '별도'} 재무 미발견 → "
                f"{'별도' if alt else '연결'} 재무로 재시도"
            )
            return extract_fs(
                corp,
                bgn_de=cfg.bgn_de,
                report_tp=cfg.report_tp,
                separate=alt,
            )
        raise  # 기타 예외는 상위 재시도 대상으로


# =============
# 품질/캐시 헬퍼
# =============
def _resolve_output_dir_safely(output_dir: str) -> Path:
    """
    - 상대경로를 절대경로로 강제
    - 조상 경로 중 '파일'이 끼어 있으면 자동으로 *_output 으로 우회
    - 최종 경로가 파일이면 *_dir 로 우회
    - 그래도 실패하면 .kiwoom_out/<원래마지막폴더> 로 폴백
    """
    def _abs(p: Path) -> Path:
        return p if p.is_absolute() else (Path.cwd() / p)

    try:
        p = _abs(Path(output_dir))

        # 1) 조상 경로 검사 (루트→부모 순서)
        ancestors = list(p.parents)[::-1]  # 루트에 가까운 것부터
        for anc in ancestors:
            if anc.exists() and not anc.is_dir():
                alt_anc = Path(str(anc) + "_output")
                rel = p.relative_to(anc)
                p = alt_anc / rel
                tqdm.write(f"⚠️ 조상 경로가 파일입니다: '{anc}' → '{alt_anc}'로 우회합니다.")
                break

        # 2) 최종 경로가 파일이면 *_dir로 우회
        if p.exists() and not p.is_dir():
            alt_p = Path(str(p) + "_dir")
            tqdm.write(f"⚠️ 출력 경로가 파일입니다: '{p}' → '{alt_p}'로 우회합니다.")
            p = alt_p

        # 3) 디렉터리 생성
        p.mkdir(parents=True, exist_ok=True)
        tqdm.write(f"📁 출력 경로: {p}")
        return p

    except Exception as e:
        # 4) 최종 폴백
        try:
            last = Path(output_dir).name or "by_stock"
            fallback = Path.cwd() / ".kiwoom_out" / last
            fallback.mkdir(parents=True, exist_ok=True)
            tqdm.write(f"⚠️ 경로 생성 실패({type(e).__name__}): '{output_dir}' → 폴백 '{fallback}' 사용")
            return fallback
        except Exception as e2:
            cwd = Path.cwd()
            tqdm.write(f"❗ 폴백도 실패({type(e2).__name__}). 현재 경로 사용: '{cwd}'")
            return cwd


def _resolve_cache_dir(cache_dir: str | Path | None) -> Path | None:
    if cache_dir is None:
        return None
    cache_root = Path(cache_dir).expanduser()
    cache_root.mkdir(parents=True, exist_ok=True)
    return cache_root

def _build_cache_key(
    code: str,
    bgn_de: str,
    report_tp: str,
    separate: bool,
    latest_only: bool,
    percent_format: bool,
) -> str:
    safe_code = re.sub(r"[^0-9A-Za-z]+", "_", code).strip("_") or "code"
    payload = {
        "code": code,
        "bgn_de": bgn_de,
        "report_tp": report_tp,
        "separate": separate,
        "latest_only": latest_only,
        "percent_format": percent_format,
    }
    raw = json.dumps(payload, sort_keys=True, separators=(",", ":"))
    digest = hashlib.sha1(raw.encode("utf-8")).hexdigest()
    return f"{safe_code}_{digest}"

def build_cache_key_public(**kwargs) -> str:
    """외부 도구/스크립트에서 캐시 키가 필요할 때 사용하세요."""
    return _build_cache_key(**kwargs)

def _cache_file_path(cache_root: Path, cache_key: str) -> Path:
    return cache_root / f"{cache_key}.pkl"

def _load_cached_frame(
    cache_root: Path,
    cache_key: str,
    ttl_seconds: float | None,
) -> pd.DataFrame | None:
    cache_path = _cache_file_path(cache_root, cache_key)
    if not cache_path.exists():
        return None
    if ttl_seconds is not None:
        age = time.time() - cache_path.stat().st_mtime
        if age > ttl_seconds:
            return None
    try:
        cached = pd.read_pickle(cache_path)
    except Exception:
        return None
    if not isinstance(cached, pd.DataFrame):
        return None
    return cached

def _store_cached_frame(cache_root: Path, cache_key: str, df: pd.DataFrame) -> None:
    cache_path = _cache_file_path(cache_root, cache_key)
    tmp_path = cache_path.parent / f"{cache_path.name}.tmp"
    df.to_pickle(tmp_path)
    tmp_path.replace(cache_path)

def _load_cached_csv(code: str, output_dir_path: Path) -> pd.DataFrame | None:
    """by_stock/<code>.csv 최신본 읽기 시도 + 숫자 캐스팅"""
    csv_path = output_dir_path / f"{code}.csv"
    if not csv_path.exists():
        return None
    try:
        # 인덱스/문자 보존
        df = pd.read_csv(csv_path, index_col=0, dtype=str)
        if df is None or df.empty:
            return None
        # 숫자 칼럼만 다시 float로 캐스팅
        num_cols = [c for c in df.columns if c != "stock_code"]
        df[num_cols] = df[num_cols].apply(pd.to_numeric, errors="coerce")
        return df
    except Exception:
        return None


def _quality_ok(df: pd.DataFrame, nan_ratio_limit: float, min_non_null: int) -> bool:
    """
    숫자형으로 해석 가능한 열을 기준으로 가장 '잘 채워진' 행을 보며
    NaN 비율이 임계값 이하이고, 최소 채워진 열 수를 만족하면 통과.
    """
    if df is None or df.empty:
        return False

    # 숫자형 후보 컬럼 선정
    cand: list[str] = []
    for c in df.columns:
        if c == "stock_code":
            continue
        ser = pd.to_numeric(df[c], errors="coerce")
        if ser.notna().any():
            cand.append(c)

    if not cand:
        return False

    sub = df[cand].apply(pd.to_numeric, errors="coerce")
    non_null_max = int(sub.notna().sum(axis=1).max())
    nan_ratio = 1.0 - (non_null_max / len(cand))
    return (nan_ratio <= nan_ratio_limit) and (non_null_max >= min_non_null)


# ============
# 워커 (단일 종목)
# ============
def _run_worker(code: str, cfg: WorkerConfig) -> pd.DataFrame | None:
    """
    개별 종목 처리:
    - (멀티프로세스 호환) 워커 내부에서 DART 초기화
    - corp 조회 → filings 추출(연결→별도 폴백) → 전처리 → 지표 산출 → 컬럼 필터
    - latest_only면 최신 1개만
    실패 시 None
    """
    # 프로세스/스레드 어디서든 안전하게 초기화
    init_dart(cfg.api_key)

    for attempt in range(1, cfg.retries + 1):
        try:
            # 부하 방지
            time.sleep(cfg.throttle_sec)

            corp = find_corp(code)
            if corp is None:
                raise ValueError(f"corp not found for {code}")

            # FS 추출(연결→별도 폴백 내장)
            fs = _try_extract_with_fallback(corp, cfg)

            # 표준화된 4표 생성
            bs, is_, cis, cf = preprocess_all(fs)

            # 지표 계산
            df = compute_metrics_df_flat_kor(bs, is_, cis, cf, key_cols=None)

            # 요청된 컬럼만 추림(존재하는 것만)
            df = _select_existing_cols(df)

            if df.empty:
                tqdm.write(f"⚠️ [{code}] 데이터 없음 (빈 DataFrame)")
                return None

            # 최신 1개만
            if cfg.latest_only:
                df = df.sort_index(ascending=False).iloc[[0]]
                df.index = [code]
            else:
                df.index = [f"{code}_{i}" for i in range(len(df))]

            df.index.name = "stock_code"
            return df

        except Exception as e:
            tqdm.write(f"⚠️ [{code}] 시도 {attempt}/{cfg.retries} 실패: {type(e).__name__}: {e}")
            traceback.print_exc(limit=1)  # 스택 추적 과다 출력 방지
            time.sleep(0.9 * attempt)     # 지수 백오프(소폭 상향)

    tqdm.write(f"❌ [{code}] {cfg.retries}회 실패 후 건너뜀.")
    return None


# =============
# 메인 엔트리
# =============
def get_metrics_for_codes(
    codes: List[str],
    bgn_de: str = "20210101",
    report_tp: str = "annual",
    separate: bool = True,
    latest_only: bool = False,
    percent_format: bool = False,  # 현재 숫자형 유지 기본
    api_key: Optional[str] = None,
    max_workers: int = 6,
    save_each: bool = False,
    output_dir: str = "artifacts/by_stock",
    # ── 새 옵션: 품질/타임아웃/실행기 ─────────────────────────────────
    per_code_timeout_sec: int | None = 150,   # 종목당 하드 타임아웃(초). None/0이면 미적용
    skip_nan_heavy: bool = True,              # NaN 과다 결과 스킵
    nan_ratio_limit: float = 0.60,            # NaN ≤ 60%
    min_non_null: int = 5,                    # 최소 채워진 지표 5개
    prefer_process: bool = False,             # 🔧 Windows 기본: ThreadPool (ProcessPool은 __main__ 가드 필요)
    # ── 피클 캐시 옵션 ─────────────────────────────────────────────
    cache_dir: str | Path | None = None,
    cache_ttl: float | int | None = None,
    force_refresh: bool = False,
) -> pd.DataFrame:
    """
    복수 종목 재무지표를 병렬 수집
    - CSV 저장 캐시(save_each+output_dir) + 피클 캐시(cache_dir) 혼용 지원
    - 품질 필터로 NaN 과다 종목 스킵 가능
    - 종목별 하드 타임아웃
    - Windows 기본 ThreadPool 사용(멀티프로세스는 __main__ 보호 필요)
    """
    if not codes:
        return pd.DataFrame(columns=DEFAULT_COLS)

    # 🔧 안전한 디렉터리 생성 (artifacts가 파일이어도 우회)
    output_dir_path = _resolve_output_dir_safely(output_dir)

    frames: list[pd.DataFrame] = []
    failed: list[str] = []
    skipped: list[tuple[str, str]] = []  # (code, reason)

    cfg = WorkerConfig(
        bgn_de=bgn_de,
        report_tp=report_tp,
        separate=separate,
        latest_only=latest_only,
        percent_format=percent_format,
        api_key=api_key,
        retries=3,
        throttle_sec=1.2,
    )

    # ===== 피클 캐시 우선 조회 =====
    cache_root = _resolve_cache_dir(cache_dir)
    ttl_seconds = float(cache_ttl) if cache_ttl is not None else None

    # 제출 대상 결정: CSV 캐시 → 피클 캐시 → API
    submit_codes: list[str] = []

    # 1) CSV 캐시 체크 (하위 호환)
    if save_each:
        for code in codes:
            csv_df = _load_cached_csv(code, output_dir_path)
            if csv_df is not None:
                if (not skip_nan_heavy) or _quality_ok(csv_df, nan_ratio_limit, min_non_null):
                    frames.append(csv_df)
                    tqdm.write(f"✅ [CSV 캐시 사용] {code}")
                    continue
                else:
                    tqdm.write(f"⚠️ [CSV 캐시 품질불량] {code} → 재시도 예정")
            submit_codes.append(code)
    else:
        submit_codes = list(codes)

    # 2) 피클 캐시 체크
    frames_ordered: list[pd.DataFrame | None] = [None] * len(submit_codes)
    cache_keys: dict[int, str] = {}
    codes_to_fetch: list[tuple[int, str]] = []

    if cache_root is not None:
        for idx, code in enumerate(submit_codes):
            ck = _build_cache_key(
                code=code,
                bgn_de=bgn_de,
                report_tp=report_tp,
                separate=separate,
                latest_only=latest_only,
                percent_format=percent_format,
            )
            cache_keys[idx] = ck
            if not force_refresh:
                cached_df = _load_cached_frame(cache_root, ck, ttl_seconds)
                if cached_df is not None:
                    if (not skip_nan_heavy) or _quality_ok(cached_df, nan_ratio_limit, min_non_null):
                        frames_ordered[idx] = cached_df
                        tqdm.write(f"✅ [피클 캐시 히트] {code}")
                        continue
                    else:
                        tqdm.write(f"⚠️ [피클 캐시 품질불량] {code} → 재시도 예정")
            codes_to_fetch.append((idx, code))
    else:
        codes_to_fetch = list(enumerate(submit_codes))

    # 3) API 병렬 처리
    def _submit_and_collect(to_fetch: list[tuple[int, str]]):
        if not to_fetch:
            return

        Executor = ProcessPoolExecutor if (prefer_process and sys.platform != "win32") else ThreadPoolExecutor

        with Executor(max_workers=max_workers) as executor:
            futures = {
                executor.submit(_run_worker, code, cfg): (idx, code)
                for idx, code in to_fetch
            }
            pbar = tqdm(total=len(futures), desc="📊 종목 처리 중", ncols=100, dynamic_ncols=False)
            for future in as_completed(futures):
                idx, code = futures[future]
                try:
                    if per_code_timeout_sec and per_code_timeout_sec > 0:
                        df = future.result(timeout=per_code_timeout_sec)
                    else:
                        df = future.result()

                    if df is not None and not df.empty:
                        # 품질 필터
                        if skip_nan_heavy and not _quality_ok(df, nan_ratio_limit, min_non_null):
                            skipped.append((code, "nan_heavy"))
                            tqdm.write(f"⏭️  [{code}] NaN 과다로 스킵")
                        else:
                            frames_ordered[idx] = df
                            # 피클 캐시 저장
                            if cache_root is not None:
                                _store_cached_frame(cache_root, cache_keys[idx], df)
                            # CSV 캐시 저장(옵션)
                            if save_each:
                                (output_dir_path / f"{code}.csv").parent.mkdir(parents=True, exist_ok=True)
                                df.to_csv(output_dir_path / f"{code}.csv", encoding="utf-8-sig")
                    else:
                        failed.append(code)
                except TimeoutError:
                    failed.append(code)
                    tqdm.write(f"⏱️  [{code}] 타임아웃({per_code_timeout_sec}s)으로 실패 처리")
                except Exception as e:
                    tqdm.write(f"❌ [{code}] 예외 발생: {type(e).__name__}: {e}")
                    failed.append(code)
                finally:
                    pbar.update(1)
            pbar.close()

    _submit_and_collect(codes_to_fetch)

    # 실패/스킵 목록 저장
    report_dir = _resolve_output_dir_safely("artifacts")
    if failed:
        fail_path = report_dir / "failed_codes.csv"
        pd.DataFrame({"failed_code": failed}).to_csv(fail_path, index=False, encoding="utf-8-sig")
        print(f"\n⚠️ 실패한 종목 {len(failed)}개 → {fail_path} 저장됨")
    if skipped:
        skip_path = report_dir / "skipped_codes.csv"
        pd.DataFrame(skipped, columns=["code", "reason"]).to_csv(skip_path, index=False, encoding="utf-8-sig")
        print(f"ℹ️ 스킵된 종목 {len(skipped)}개 → {skip_path} 저장됨")

    # 결과 병합
    from_cache = [f for f in frames_ordered if f is not None]
    frames.extend(from_cache)

    if not frames:
        print("❗ 유효한 데이터가 없습니다.")
        return pd.DataFrame(columns=DEFAULT_COLS)

    result = pd.concat(frames)
    print(f"\n✅ 완료! 총 {len(result)}개 데이터 수집 성공.")
    return result
