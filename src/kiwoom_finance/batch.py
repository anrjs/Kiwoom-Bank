# src/kiwoom_finance/batch.py
from __future__ import annotations

import os
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
from .dart_client import extract_fs, find_corp, init_dart, IdentifierType
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


# ======================================
# 캐시/출력 유틸 (안전 동작 보장용 헬퍼)
# ======================================

def _resolve_output_dir_safely(output_dir: str | Path) -> Path:
    """
    안전하게 출력 디렉터리를 반환.
    - 만약 같은 경로에 '파일'이 존재하면 '_dir'을 덧붙인 디렉터리로 우회 생성
    """
    p = Path(output_dir)
    if p.exists() and p.is_file():
        p = p.with_name(p.name + "_dir")
    p.mkdir(parents=True, exist_ok=True)
    return p


def _load_cached_csv(code: str, output_dir_path: Path) -> pd.DataFrame | None:
    """
    과거 저장한 CSV(코드별 1개)를 읽어서 DataFrame 반환. 없거나 실패 시 None.
    """
    csv_path = output_dir_path / f"{code}.csv"
    if not csv_path.exists():
        return None
    try:
        df = pd.read_csv(csv_path, index_col=0, encoding="utf-8-sig")
        return df
    except Exception:
        return None


def _resolve_cache_dir(cache_dir: str | Path | None) -> Path | None:
    """
    피클 캐시 루트 경로 반환. None이면 비활성.
    """
    if cache_dir is None:
        return None
    root = Path(cache_dir)
    root.mkdir(parents=True, exist_ok=True)
    return root


def _build_cache_key(
    *,
    code: str,
    bgn_de: str,
    report_tp: str,
    separate: bool,
    latest_only: bool,
    percent_format: bool,
) -> str:
    """
    파라미터 조합을 바탕으로 안정적인 캐시 키 생성
    """
    payload = {
        "code": code,
        "bgn_de": bgn_de,
        "report_tp": report_tp,
        "separate": separate,
        "latest_only": latest_only,
        "percent_format": percent_format,
        # 향후 옵션 추가 대비
    }
    raw = json.dumps(payload, sort_keys=True, ensure_ascii=False).encode("utf-8")
    return hashlib.sha256(raw).hexdigest()


def _load_cached_frame(cache_root: Path, cache_key: str, ttl_seconds: float | None) -> pd.DataFrame | None:
    """
    캐시 파일 읽기. TTL(초) 내면 반환, 초과면 None.
    """
    pkl_path = cache_root / f"{cache_key}.pkl"
    if not pkl_path.exists():
        return None
    try:
        if ttl_seconds is not None and ttl_seconds > 0:
            age = time.time() - os.stat(pkl_path).st_mtime
            if age > ttl_seconds:
                return None
        return pd.read_pickle(pkl_path)
    except Exception:
        return None


def _store_cached_frame(cache_root: Path, cache_key: str, df: pd.DataFrame) -> None:
    """
    캐시 파일 저장
    """
    pkl_path = cache_root / f"{cache_key}.pkl"
    try:
        df.to_pickle(pkl_path)
    except Exception:
        # 캐시 실패는 치명 아님
        pass


# -----------------------
# 워커/품질/후보 컬럼 선택
# -----------------------

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


@dataclass
class LookupTarget:
    identifier: str
    stock_code: str
    corp_name: str | None = None

    @property
    def label(self) -> str:
        base = self.corp_name or self.identifier
        return f"{base}({self.stock_code})"


def _normalize_stock_code(raw: str | int | None) -> str | None:
    if raw is None:
        return None
    code = str(raw).strip()
    if not code:
        return None
    if code.isdigit() and len(code) < 6:
        code = code.zfill(6)
    return code


def _select_existing_cols(df):
    keep = [c for c in DEFAULT_COLS if c in df.columns]
    return df[keep].copy() if keep else df.copy()   # ← 없으면 원본 유지


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
            # 반대 separate로 재시도
            return extract_fs(
                corp,
                bgn_de=cfg.bgn_de,
                report_tp=cfg.report_tp,
                separate=not cfg.separate,
            )
        raise


def _quality_ok(df: pd.DataFrame, nan_ratio_limit: float, min_non_null: int) -> bool:
    """
    결과 품질 판정:
    - NaN 비율이 허용치 이하
    - 단일 행 기준 채워진(숫자) 지표 개수 ≥ min_non_null
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
def _run_worker(code: str, cfg: WorkerConfig, identifier: str | None = None) -> pd.DataFrame | None:
    """
    개별 종목 처리:
    - (멀티프로세스 호환) 워커 내부에서 DART 초기화
    - corp 조회 → filings 추출(연결→별도 폴백) → 전처리 → 지표 산출 → 컬럼 필터
    - latest_only면 최신 1개만
    실패 시 None
    """
    # 프로세스/스레드 어디서든 안전하게 초기화
    init_dart(cfg.api_key)

    label = identifier or code

    for attempt in range(1, cfg.retries + 1):
        try:
            # 부하 방지
            time.sleep(cfg.throttle_sec)

            corp = find_corp(code, by="code")
            if corp is None:
                raise ValueError(f"corp not found for {label}")

            corp_code = _normalize_stock_code(getattr(corp, "stock_code", None)) or code

            # FS 추출(연결→별도 폴백 내장)
            fs = _try_extract_with_fallback(corp, cfg)

            # 표준화된 4표 생성
            bs, is_, cis, cf = preprocess_all(fs)

            # 지표 계산
            df = compute_metrics_df_flat_kor(bs, is_, cis, cf, key_cols=None)

            # 요청된 컬럼만 추림(존재하는 것만)
            df = _select_existing_cols(df)

            if df.empty:
                tqdm.write(f"⚠️ [{label}] 데이터 없음 (빈 DataFrame)")
                return None

            # 최신 1개만
            if cfg.latest_only:
                df = df.sort_index(ascending=False).iloc[[0]]
                df.index = [corp_code]
            else:
                df.index = [f"{corp_code}_{i}" for i in range(len(df))]

            df.index.name = "stock_code"
            return df

        except Exception as e:
            tqdm.write(
                f"⚠️ [{label}] 시도 {attempt}/{cfg.retries} 실패: {type(e).__name__}: {e}"
            )
            traceback.print_exc(limit=1)  # 스택 추적 과다 출력 방지
            time.sleep(0.9 * attempt)     # 지수 백오프(소폭 상향)

    tqdm.write(f"❌ [{label}] {cfg.retries}회 실패 후 건너뜀.")
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
    identifier_type: IdentifierType = "auto",
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
    - identifier_type="auto"(기본)면 종목명을 우선 검색 후 종목코드를 시도
    """
    if not codes:
        return pd.DataFrame(columns=DEFAULT_COLS)

    # 이름 검색을 위해 메인 프로세스에서도 초기화(api_key 우선 적용)
    init_dart(api_key)

    # 🔧 안전한 디렉터리 생성 (artifacts가 파일이어도 우회)
    output_dir_path = _resolve_output_dir_safely(output_dir)

    frames: list[pd.DataFrame] = []
    failed: list[tuple[str, str | None, str]] = []  # (identifier, stock_code, reason)
    skipped: list[tuple[str, str | None, str]] = []

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

    # 0) 입력 식별자 → 실제 종목코드 매핑
    targets: list[LookupTarget] = []
    for raw in codes:
        if raw is None:
            continue
        identifier = str(raw).strip()
        if not identifier:
            continue

        corp = find_corp(identifier, by=identifier_type)
        if corp is None:
            failed.append((identifier, None, "not_found"))
            tqdm.write(f"❌ [{identifier}] 종목을 찾을 수 없습니다.")
            continue

        stock_code = _normalize_stock_code(getattr(corp, "stock_code", None))
        if not stock_code:
            failed.append((identifier, None, "no_stock_code"))
            tqdm.write(f"❌ [{identifier}] 종목코드를 확인할 수 없습니다.")
            continue

        corp_name = getattr(corp, "corp_name", None)
        if corp_name is not None:
            corp_name = str(corp_name).strip() or None

        targets.append(LookupTarget(identifier=identifier, stock_code=stock_code, corp_name=corp_name))

    # ===== 피클 캐시 우선 조회 =====
    cache_root = _resolve_cache_dir(cache_dir)
    ttl_seconds = float(cache_ttl) if cache_ttl is not None else None

    # 제출 대상 결정: CSV 캐시 → 피클 캐시 → API
    submit_targets: list[LookupTarget] = []

    # 1) CSV 캐시 체크 (하위 호환)
    if save_each:
        for target in targets:
            csv_df = _load_cached_csv(target.stock_code, output_dir_path)
            if csv_df is not None:
                if (not skip_nan_heavy) or _quality_ok(csv_df, nan_ratio_limit, min_non_null):
                    frames.append(csv_df)
                    tqdm.write(f"✅ [CSV 캐시 사용] {target.label}")
                    continue
                else:
                    tqdm.write(f"⚠️ [CSV 캐시 품질불량] {target.label} → 재시도 예정")
            submit_targets.append(target)
    else:
        submit_targets = list(targets)

    # 2) 피클 캐시 체크
    frames_ordered: list[pd.DataFrame | None] = [None] * len(submit_targets)
    cache_keys: dict[int, str] = {}
    targets_to_fetch: list[tuple[int, LookupTarget]] = []

    if cache_root is not None:
        for idx, target in enumerate(submit_targets):
            ck = _build_cache_key(
                code=target.stock_code,
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
                        tqdm.write(f"✅ [피클 캐시 히트] {target.label}")
                        continue
                    else:
                        tqdm.write(f"⚠️ [피클 캐시 품질불량] {target.label} → 재시도 예정")
            targets_to_fetch.append((idx, target))
    else:
        targets_to_fetch = list(enumerate(submit_targets))

    # 3) API 병렬 처리
    def _submit_and_collect(to_fetch: list[tuple[int, LookupTarget]]):
        if not to_fetch:
            return

        Executor = ProcessPoolExecutor if (prefer_process and sys.platform != "win32") else ThreadPoolExecutor

        with Executor(max_workers=max_workers) as executor:
            futures = {
                executor.submit(_run_worker, target.stock_code, cfg, target.identifier): (idx, target)
                for idx, target in to_fetch
            }
            pbar = tqdm(total=len(futures), desc="📊 종목 처리 중", ncols=100, dynamic_ncols=False)
            for future in as_completed(futures):
                idx, target = futures[future]
                try:
                    if per_code_timeout_sec and per_code_timeout_sec > 0:
                        df = future.result(timeout=per_code_timeout_sec)
                    else:
                        df = future.result()

                    if df is not None and not df.empty:
                        # 품질 필터
                        if skip_nan_heavy and not _quality_ok(df, nan_ratio_limit, min_non_null):
                            skipped.append((target.identifier, target.stock_code, "nan_heavy"))
                            tqdm.write(f"⏭️  [{target.label}] NaN 과다로 스킵")
                        else:
                            frames_ordered[idx] = df
                            # 피클 캐시 저장
                            if cache_root is not None:
                                ck = cache_keys.get(idx)
                                if ck:
                                    _store_cached_frame(cache_root, ck, df)
                            # CSV 캐시 저장(옵션)
                            if save_each:
                                out_path = output_dir_path / f"{target.stock_code}.csv"
                                out_path.parent.mkdir(parents=True, exist_ok=True)
                                df.to_csv(out_path, encoding="utf-8-sig")
                    else:
                        failed.append((target.identifier, target.stock_code, "empty"))
                except TimeoutError:
                    failed.append((target.identifier, target.stock_code, "timeout"))
                    tqdm.write(f"⏱️  [{target.label}] 타임아웃({per_code_timeout_sec}s)으로 실패 처리")
                except Exception as e:
                    tqdm.write(f"❌ [{target.label}] 예외 발생: {type(e).__name__}: {e}")
                    failed.append((target.identifier, target.stock_code, type(e).__name__))
                finally:
                    pbar.update(1)
            pbar.close()

    _submit_and_collect(targets_to_fetch)

    # 실패/스킵 목록 저장
    report_dir = _resolve_output_dir_safely("artifacts")
    if failed:
        fail_path = report_dir / "failed_codes.csv"
        fail_df = pd.DataFrame(failed, columns=["identifier", "stock_code", "reason"])
        fail_df["failed_code"] = fail_df["stock_code"].fillna(fail_df["identifier"])
        fail_df.to_csv(fail_path, index=False, encoding="utf-8-sig")
        print(f"\n⚠️ 실패한 종목 {len(fail_df)}개 → {fail_path} 저장됨")
    if skipped:
        skip_path = report_dir / "skipped_codes.csv"
        skip_df = pd.DataFrame(skipped, columns=["identifier", "stock_code", "reason"])
        skip_df.to_csv(skip_path, index=False, encoding="utf-8-sig")
        print(f"ℹ️ 스킵된 종목 {len(skip_df)}개 → {skip_path} 저장됨")

    # 결과 병합
    from_cache = [f for f in frames_ordered if f is not None]
    frames.extend(from_cache)

    if not frames:
        print("❗ 유효한 데이터가 없습니다.")
        return pd.DataFrame(columns=DEFAULT_COLS)

    result = pd.concat(frames)
    print(f"\n✅ 완료! 총 {len(result)}개 데이터 수집 성공.")
    return result
