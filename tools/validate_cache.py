#!/usr/bin/env python3
"""Cache validation utility for get_metrics_for_codes."""
from __future__ import annotations

import argparse
import logging
import random
import shutil
from pathlib import Path
from typing import Sequence

import numpy as np
try:
    import pandas as pd
except Exception as e:
    raise SystemExit("pandas가 필요합니다. `pip install pandas` 후 다시 실행하세요.") from e

from kiwoom_finance import batch as metrics_batch
from kiwoom_finance.dart_client import get_corp_list, init_dart

LOGGER = logging.getLogger("validate_cache")

DEFAULT_SAMPLE_SIZE = 10
DEFAULT_RANDOM_SEED = 2024
DEFAULT_CACHE_ROOT = Path(".cache_validation")
DEFAULT_MAX_DIFFS = 20

METRICS_PARAMS = {
    "bgn_de": "20170101",
    "report_tp": "annual",
    "separate": False,
    "latest_only": True,
    "percent_format": False,  # ML 파이프라인 호환을 위해 숫자형 유지
}


def configure_logging(verbose: bool) -> None:
    level = logging.DEBUG if verbose else logging.INFO
    logging.basicConfig(level=level, format="%(asctime)s [%(levelname)s] %(message)s")


def load_all_stock_codes() -> list[str]:
    corps = get_corp_list()
    codes: set[str] = set()
    for corp in corps:
        stock_code = getattr(corp, "stock_code", None)
        if not stock_code:
            continue
        stock_code = str(stock_code).strip()
        if len(stock_code) == 6 and stock_code.isdigit():
            codes.add(stock_code)
    if not codes:
        raise RuntimeError("No stock codes available from DART corp list")
    sorted_codes = sorted(codes)
    LOGGER.info("Loaded %d stock codes from DART", len(sorted_codes))
    return sorted_codes


def resolve_codes(
    explicit_codes: Sequence[str] | None,
    sample_size: int,
    seed: int,
) -> list[str]:
    if explicit_codes:
        unique_codes = []
        seen: set[str] = set()
        for code in explicit_codes:
            code = code.strip()
            if not code:
                continue
            if code not in seen:
                unique_codes.append(code)
                seen.add(code)
        if not unique_codes:
            raise ValueError("No valid stock codes provided")
        return unique_codes

    all_codes = load_all_stock_codes()
    if sample_size > len(all_codes):
        raise ValueError(
            f"Sample size {sample_size} exceeds available codes {len(all_codes)}"
        )
    rng = random.Random(seed)
    sample = rng.sample(all_codes, sample_size)
    LOGGER.info(
        "Sampled %d codes (first 5: %s)",
        sample_size,
        ", ".join(sample[:5]) if sample else "",
    )
    return sample


def prepare_cache_dir(cache_dir: Path, reset: bool) -> Path:
    cache_dir = cache_dir.expanduser()
    if reset and cache_dir.exists():
        shutil.rmtree(cache_dir)
    cache_dir.mkdir(parents=True, exist_ok=True)
    return cache_dir


def align_frames(cold: pd.DataFrame, warm: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame]:
    index = cold.index.union(warm.index)
    columns = cold.columns.union(warm.columns)
    cold_aligned = cold.reindex(index=index, columns=columns)
    warm_aligned = warm.reindex(index=index, columns=columns)
    # 일관된 정렬
    cold_aligned = cold_aligned.sort_index().sort_index(axis=1)
    warm_aligned = warm_aligned.sort_index().sort_index(axis=1)
    return cold_aligned, warm_aligned


def column_differences(cold: pd.DataFrame, warm: pd.DataFrame) -> dict[str, list[str]]:
    cold_cols = set(cold.columns)
    warm_cols = set(warm.columns)
    return {
        "only_in_cold": sorted(cold_cols - warm_cols),
        "only_in_warm": sorted(warm_cols - cold_cols),
    }


def dtype_mismatches(cold: pd.DataFrame, warm: pd.DataFrame) -> list[tuple[str, str, str]]:
    mismatches: list[tuple[str, str, str]] = []
    shared = cold.columns.intersection(warm.columns)
    for column in shared:
        dtype_cold = str(cold[column].dtype)
        dtype_warm = str(warm[column].dtype)
        if dtype_cold != dtype_warm:
            mismatches.append((column, dtype_cold, dtype_warm))
    return mismatches


def value_differences(
    cold: pd.DataFrame,
    warm: pd.DataFrame,
    rtol: float,
    atol: float,
    max_records: int,
) -> list[dict[str, object]]:
    diffs: list[dict[str, object]] = []
    shared_cols = cold.columns.intersection(warm.columns)

    for column in shared_cols:
        cold_series = cold[column]
        warm_series = warm[column]

        # 숫자형 비교: isclose + NaN 동일 취급
        if pd.api.types.is_numeric_dtype(cold_series) and pd.api.types.is_numeric_dtype(warm_series):
            cold_values = cold_series.to_numpy(dtype=float, na_value=np.nan)
            warm_values = warm_series.to_numpy(dtype=float, na_value=np.nan)

            # 무한대 존재 여부 체크(위생)
            if np.isinf(cold_values).any() or np.isinf(warm_values).any():
                mask = np.isinf(cold_values) | np.isinf(warm_values)
            else:
                mask = ~np.isclose(cold_values, warm_values, rtol=rtol, atol=atol, equal_nan=True)
        else:
            # 비숫자형은 엄격 동등성 + 동시 NaN 허용
            mask = ~(cold_series.eq(warm_series) | (cold_series.isna() & warm_series.isna()))

        if not mask.any():
            continue

        mismatch_indices = cold_series.index[mask]
        for idx in mismatch_indices:
            diffs.append(
                {
                    "index": idx,
                    "column": column,
                    "cold": cold_series.at[idx],
                    "warm": warm_series.at[idx],
                }
            )
            if len(diffs) >= max_records:
                return diffs
    return diffs


def _to_float_frame(df: pd.DataFrame) -> pd.DataFrame:
    """
    가능한 컬럼은 float로 강제 캐스팅(학습 호환).
    실패하는 컬럼은 원형 유지.
    """
    out = df.copy()
    for c in out.columns:
        if pd.api.types.is_numeric_dtype(out[c]):
            try:
                out[c] = pd.to_numeric(out[c], errors="coerce")
            except Exception:
                pass
    return out


def validate_cache(
    codes: Sequence[str],
    api_key: str | None,
    cache_dir: Path,
    rtol: float,
    atol: float,
    max_diffs: int,
) -> dict[str, object]:
    LOGGER.info("Running cold pass for %d codes", len(codes))
    cold_df = metrics_batch.get_metrics_for_codes(
        list(codes),
        api_key=api_key,
        cache_dir=cache_dir,
        cache_ttl=None,
        force_refresh=True,
        **METRICS_PARAMS,
    )

    LOGGER.info("Running warm pass (cache readback)")
    warm_df = metrics_batch.get_metrics_for_codes(
        list(codes),
        api_key=api_key,
        cache_dir=cache_dir,
        cache_ttl=None,
        force_refresh=False,
        **METRICS_PARAMS,
    )

    # 위생: float 캐스팅
    cold_df = _to_float_frame(cold_df)
    warm_df = _to_float_frame(warm_df)

    cold_aligned, warm_aligned = align_frames(cold_df, warm_df)

    column_diff = column_differences(cold_aligned, warm_aligned)
    dtype_diff = dtype_mismatches(cold_aligned, warm_aligned)
    value_diff = value_differences(cold_aligned, warm_aligned, rtol, atol, max_diffs)

    identical = not column_diff["only_in_cold"] and not column_diff["only_in_warm"]
    identical = identical and not dtype_diff and not value_diff

    return {
        "cold": cold_df,
        "warm": warm_df,
        "column_diff": column_diff,
        "dtype_diff": dtype_diff,
        "value_diff": value_diff,
        "identical": identical,
    }


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Validate that cached get_metrics_for_codes results match freshly "
            "computed DataFrames"
        )
    )
    parser.add_argument("--codes", nargs="*", help="Explicit stock codes to validate")
    parser.add_argument(
        "--sample-size",
        type=int,
        default=DEFAULT_SAMPLE_SIZE,
        help="Number of random stock codes to sample when --codes is omitted",
    )
    parser.add_argument(
        "--seed",
        type=int,
        default=DEFAULT_RANDOM_SEED,
        help="Random seed for sampling stock codes",
    )
    parser.add_argument("--api-key", help="DART API key", default=None)
    parser.add_argument(
        "--cache-dir",
        type=Path,
        default=DEFAULT_CACHE_ROOT,
        help="Directory to store cache files for validation",
    )
    parser.add_argument(
        "--no-reset-cache",
        action="store_true",
        help="Do not delete the cache directory before running",
    )
    parser.add_argument(
        "--rtol",
        type=float,
        default=1e-9,
        help="Relative tolerance for numeric comparisons",
    )
    parser.add_argument(
        "--atol",
        type=float,
        default=0.0,
        help="Absolute tolerance for numeric comparisons",
    )
    parser.add_argument(
        "--max-diffs",
        type=int,
        default=DEFAULT_MAX_DIFFS,
        help="Maximum number of differing cells to report",
    )
    parser.add_argument(
        "--verbose",
        action="store_true",
        help="Enable verbose logging",
    )
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)

    configure_logging(args.verbose)

    init_dart(api_key=args.api_key)

    try:
        codes = resolve_codes(args.codes, args.sample_size, args.seed)
    except Exception as exc:
        LOGGER.error("Failed to resolve stock codes: %s", exc)
        return 2

    cache_dir = prepare_cache_dir(Path(args.cache_dir), reset=not args.no_reset_cache)

    result = validate_cache(
        codes=codes,
        api_key=args.api_key,
        cache_dir=cache_dir,
        rtol=args.rtol,
        atol=args.atol,
        max_diffs=args.max_diffs,
    )

    if result["identical"]:
        LOGGER.info("Cache validation succeeded: warm results match cold computation")
        print("Cache validation: PASS")
        return 0

    LOGGER.error("Cache validation found discrepancies")
    column_diff = result["column_diff"]
    if column_diff["only_in_cold"] or column_diff["only_in_warm"]:
        print("Column differences:")
        if column_diff["only_in_cold"]:
            print("  Only in cold :", ", ".join(column_diff["only_in_cold"]))
        if column_diff["only_in_warm"]:
            print("  Only in warm :", ", ".join(column_diff["only_in_warm"]))

    dtype_diff = result["dtype_diff"]
    if dtype_diff:
        print("Dtype mismatches:")
        for column, cold_dtype, warm_dtype in dtype_diff:
            print(f"  {column}: cold={cold_dtype} warm={warm_dtype}")

    value_diff = result["value_diff"]
    if value_diff:
        print("Value discrepancies (showing up to %d):" % args.max_diffs)
        for record in value_diff:
            print(
                f"  index={record['index']} column={record['column']} "
                f"cold={record['cold']} warm={record['warm']}"
            )

    return 1


if __name__ == "__main__":
    raise SystemExit(main())
