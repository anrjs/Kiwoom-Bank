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

try:
    from dart_fss.errors.errors import NotFoundConsolidated  # type: ignore
except Exception:
    NotFoundConsolidated = tuple()  # noqa: N816

DEFAULT_COLS = [
    "debt_ratio", "equity_ratio", "debt_dependency_ratio",
    "current_ratio", "quick_ratio", "interest_coverage_ratio",
    "ebitda_to_total_debt", "cfo_to_total_debt", "free_cash_flow",
    "operating_margin", "roa", "roe", "net_profit_margin",
    "total_asset_turnover", "accounts_receivable_turnover", "inventory_turnover",
    "sales_growth_rate", "operating_income_growth_rate", "total_asset_growth_rate",
]

def _resolve_output_dir_safely(output_dir: str | Path) -> Path:
    p = Path(output_dir)
    if p.exists() and p.is_file():
        p = p.with_name(p.name + "_dir")
    p.mkdir(parents=True, exist_ok=True)
    return p

def _load_cached_csv(code: str, output_dir_path: Path) -> pd.DataFrame | None:
    csv_path = output_dir_path / f"{code}.csv"
    if not csv_path.exists():
        return None
    try:
        df = pd.read_csv(csv_path, index_col=0, encoding="utf-8-sig")
        return df
    except Exception:
        return None

def _resolve_cache_dir(cache_dir: str | Path | None) -> Path | None:
    if cache_dir is None:
        return None
    root = Path(cache_dir)
    root.mkdir(parents=True, exist_ok=True)
    return root

def _build_cache_key(*, code: str, bgn_de: str, report_tp: str, separate: bool, latest_only: bool, percent_format: bool) -> str:
    payload = {
        "code": code,
        "bgn_de": bgn_de,
        "report_tp": report_tp,
        "separate": separate,
        "latest_only": latest_only,
        "percent_format": percent_format,
    }
    raw = json.dumps(payload, sort_keys=True, ensure_ascii=False).encode("utf-8")
    return hashlib.sha256(raw).hexdigest()

def _load_cached_frame(cache_root: Path, cache_key: str, ttl_seconds: float | None) -> pd.DataFrame | None:
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
    pkl_path = cache_root / f"{cache_key}.pkl"
    try:
        df.to_pickle(pkl_path)
    except Exception:
        pass

@dataclass
class WorkerConfig:
    bgn_de: str
    report_tp: str
    separate: bool
    latest_only: bool
    percent_format: bool
    api_key: Optional[str] = None
    retries: int = 3
    throttle_sec: float = 1.2

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
    return df[keep].copy() if keep else df.copy()

def _try_extract_with_fallback(corp, cfg: WorkerConfig):
    try:
        return extract_fs(
            corp,
            bgn_de=cfg.bgn_de,
            report_tp=cfg.report_tp,
            separate=cfg.separate,
        )
    except Exception as e:
        is_nfc = False
        if NotFoundConsolidated and isinstance(e, NotFoundConsolidated):
            is_nfc = True
        elif "NotFoundConsolidated" in f"{type(e)} {e}":
            is_nfc = True
        if is_nfc:
            return extract_fs(
                corp,
                bgn_de=cfg.bgn_de,
                report_tp=cfg.report_tp,
                separate=not cfg.separate,
            )
        raise

def _quality_ok(df: pd.DataFrame, nan_ratio_limit: float, min_non_null: int) -> bool:
    """
    완화 버전 품질 판정:
    - 핵심 BS 지표(유동/당좌/부채/자본비율) 중 하나라도 있으면 통과
    - 그 외에는 NaN 비율/최소 채워진 개수 기준
    """
    if df is None or df.empty:
        return False

    bs_core = ["current_ratio", "quick_ratio", "debt_ratio", "equity_ratio"]
    for k in bs_core:
        if k in df.columns:
            ser = pd.to_numeric(df[k], errors="coerce")
            if ser.notna().any():
                return True

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

def _run_worker(code: str, cfg: WorkerConfig, identifier: str | None = None) -> pd.DataFrame | None:
    init_dart(cfg.api_key)
    label = identifier or code
    for attempt in range(1, cfg.retries + 1):
        try:
            time.sleep(cfg.throttle_sec)
            corp = find_corp(code, by="code")
            if corp is None:
                raise ValueError(f"corp not found for {label}")

            corp_code = _normalize_stock_code(getattr(corp, "stock_code", None)) or code
            fs = _try_extract_with_fallback(corp, cfg)
            bs, is_, cis, cf = preprocess_all(fs)
            df = compute_metrics_df_flat_kor(bs, is_, cis, cf, key_cols=None)

            df = _select_existing_cols(df)
            if df.empty:
                tqdm.write(f"⚠️ [{label}] 데이터 없음 (빈 DataFrame)")
                return None

            if cfg.latest_only:
                df = df.sort_index(ascending=False).iloc[[0]]
                df.index = [corp_code]
            else:
                df.index = [f"{corp_code}_{i}" for i in range(len(df))]
            df.index.name = "stock_code"
            return df

        except Exception as e:
            tqdm.write(f"⚠️ [{label}] 시도 {attempt}/{cfg.retries} 실패: {type(e).__name__}: {e}")
            traceback.print_exc(limit=1)
            time.sleep(0.9 * attempt)

    tqdm.write(f"❌ [{label}] {cfg.retries}회 실패 후 건너뜀.")
    return None

def get_metrics_for_codes(
    codes: List[str],
    bgn_de: str = "20210101",
    report_tp: str = "annual",
    separate: bool = False,
    latest_only: bool = False,
    percent_format: bool = False,
    identifier_type: IdentifierType = "auto",
    api_key: Optional[str] = None,
    max_workers: int = 6,
    save_each: bool = False,
    output_dir: str = "artifacts/by_stock",
    # ▼ 품질/타임아웃/실행기 — 기본 완화/비활성 ▼
    per_code_timeout_sec: int | None = 150,
    skip_nan_heavy: bool = False,      # 기본 False (스킵 안 함)
    nan_ratio_limit: float = 0.85,     # 완화
    min_non_null: int = 3,             # 완화
    prefer_process: bool = False,
    # 캐시 옵션
    cache_dir: str | Path | None = None,
    cache_ttl: float | int | None = None,
    force_refresh: bool = False,
) -> pd.DataFrame:
    """
    복수 종목 재무지표 수집
    """
    if not codes:
        return pd.DataFrame(columns=DEFAULT_COLS)

    init_dart(api_key)
    output_dir_path = _resolve_output_dir_safely(output_dir)

    frames: list[pd.DataFrame] = []
    failed: list[tuple[str, str | None, str]] = []
    skipped: list[tuple[str, str | None, str]] = []

    cfg = WorkerConfig(
        bgn_de=bgn_de, report_tp=report_tp, separate=separate,
        latest_only=latest_only, percent_format=percent_format,
        api_key=api_key, retries=3, throttle_sec=1.2,
    )

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

    cache_root = _resolve_cache_dir(cache_dir)
    ttl_seconds = float(cache_ttl) if cache_ttl is not None else None

    submit_targets: list[LookupTarget] = []

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

    frames_ordered: list[pd.DataFrame | None] = [None] * len(submit_targets)
    cache_keys: dict[int, str] = {}
    targets_to_fetch: list[tuple[int, LookupTarget]] = []

    if cache_root is not None:
        for idx, target in enumerate(submit_targets):
            ck = _build_cache_key(
                code=target.stock_code,
                bgn_de=bgn_de, report_tp=report_tp, separate=separate,
                latest_only=latest_only, percent_format=percent_format,
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
                        if skip_nan_heavy and not _quality_ok(df, nan_ratio_limit, min_non_null):
                            filled = df.notna().sum(axis=1).max()
                            cols_with_vals = [c for c in df.columns if pd.to_numeric(df[c], errors="coerce").notna().any()]
                            tqdm.write(f"⏭️  [{target.label}] NaN 과다로 스킵 (filled_max={filled}, have={len(cols_with_vals)} cols: {cols_with_vals[:8]}...)")
                            skipped.append((target.identifier, target.stock_code, "nan_heavy"))
                        else:
                            frames_ordered[idx] = df
                            if cache_root is not None:
                                ck = cache_keys.get(idx)
                                if ck:
                                    _store_cached_frame(cache_root, ck, df)
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

    from_cache = [f for f in frames_ordered if f is not None]
    frames.extend(from_cache)

    if not frames:
        print("❗ 유효한 데이터가 없습니다.")
        return pd.DataFrame(columns=DEFAULT_COLS)

    result = pd.concat(frames)
    print(f"\n✅ 완료! 총 {len(result)}개 데이터 수집 성공.")
    return result