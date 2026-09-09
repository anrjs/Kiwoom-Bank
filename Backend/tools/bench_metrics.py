#!/usr/bin/env python3
"""Benchmark helper for kiwoom_finance.metrics caching pipeline.

This script measures cold and warm cache performance for randomly sampled
stock-code batches and writes the summary to ``benchmark.csv`` while emitting
structured logs to stdout.
"""
from __future__ import annotations

import argparse
import logging
import random
import shutil
import time
from datetime import datetime
from pathlib import Path
from typing import Iterable, Sequence

import os, sys
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

try:
    import pandas as pd
except Exception as e:  # 친절한 의존성 가드
    raise SystemExit("pandas가 필요합니다. `pip install pandas` 후 다시 실행하세요.") from e

from kiwoom_finance import batch as metrics_batch
from kiwoom_finance.dart_client import get_corp_list, init_dart

LOGGER = logging.getLogger("bench_metrics")

DEFAULT_SAMPLE_SIZES = (50, 200)
DEFAULT_CACHE_ROOT = Path(".bench_cache")
DEFAULT_OUTPUT_PATH = Path("benchmark.csv")
DEFAULT_RANDOM_SEED = 4242

METRICS_PARAMS = {
    "bgn_de": "20170101",
    "report_tp": "annual",
    "separate": False,
    "latest_only": True,
    "percent_format": True,  # 벤치마크용 표현 유지. ML 파이프라인은 False 권장
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


def sample_stock_codes(all_codes: Sequence[str], sample_size: int, rng: random.Random) -> list[str]:
    if sample_size > len(all_codes):
        raise ValueError(
            f"Requested sample size {sample_size} exceeds available codes {len(all_codes)}"
        )
    sample = rng.sample(list(all_codes), sample_size)
    LOGGER.info(
        "Sampled %d codes (first 5: %s)", sample_size, ", ".join(sample[:5]) if sample else ""
    )
    return sample


def prepare_cache_dir(base_cache_root: Path, sample_size: int) -> Path:
    cache_root = (base_cache_root / f"sample_{sample_size}").expanduser()
    if cache_root.exists():
        shutil.rmtree(cache_root)
    cache_root.mkdir(parents=True, exist_ok=True)
    LOGGER.info("Prepared cache directory: %s", cache_root)
    return cache_root


def cache_path_for(code: str, cache_root: Path) -> Path:
    cache_key = metrics_batch.build_cache_key_public(
        code=code,
        bgn_de=METRICS_PARAMS["bgn_de"],
        report_tp=METRICS_PARAMS["report_tp"],
        separate=METRICS_PARAMS["separate"],
        latest_only=METRICS_PARAMS["latest_only"],
        percent_format=METRICS_PARAMS["percent_format"],
    )
    return cache_root / f"{cache_key}.pkl"


def run_single_pass(
    codes: Sequence[str],
    cache_root: Path,
    api_key: str | None,
    run_label: str,
    expect_cache: bool,
) -> dict:
    total_codes = len(codes)
    run_start_wall = datetime.now()
    run_start_perf = time.perf_counter()

    per_code_records = []

    LOGGER.info(
        "Starting %s run for %d codes (cache=%s)",
        run_label,
        total_codes,
        "expected" if expect_cache else "cold",
    )

    for idx, code in enumerate(codes, start=1):
        cache_hit_expected = False
        cache_label = "cold"
        if expect_cache:
            cache_hit_expected = cache_path_for(code, cache_root).exists()
            cache_label = "hit" if cache_hit_expected else "miss"
        LOGGER.info("[%3d/%3d] %s start (cache=%s)", idx, total_codes, code, cache_label)

        code_start = time.perf_counter()
        success = True
        error_msg = ""
        try:
            metrics_batch.get_metrics_for_codes(
                [code],
                api_key=api_key,
                cache_dir=cache_root,
                cache_ttl=None,
                force_refresh=False,
                **METRICS_PARAMS,
            )
        except Exception as exc:  # pragma: no cover - benchmark utility
            success = False
            error_msg = str(exc)
            LOGGER.error("[%3d/%3d] %s failed: %s", idx, total_codes, code, exc)
        duration = time.perf_counter() - code_start

        if success:
            LOGGER.info(
                "[%3d/%3d] %s done in %.2fs (cache=%s)",
                idx,
                total_codes,
                code,
                duration,
                cache_label,
            )
        else:
            LOGGER.info(
                "[%3d/%3d] %s finished with error in %.2fs (cache=%s)",
                idx,
                total_codes,
                code,
                duration,
                cache_label,
            )

        per_code_records.append(
            {
                "code": code,
                "seconds": duration,
                "success": success,
                "cache_hit": bool(cache_hit_expected and success),
                "cache_checked": expect_cache,
                "error": error_msg,
            }
        )

    total_seconds = time.perf_counter() - run_start_perf
    run_end_wall = datetime.now()

    successes = [record for record in per_code_records if record["success"]]
    success_durations = [record["seconds"] for record in successes]
    p50 = float(pd.Series(success_durations).quantile(0.5)) if success_durations else None
    p90 = float(pd.Series(success_durations).quantile(0.9)) if success_durations else None

    failure_records = [record for record in per_code_records if not record["success"]]
    failure_codes = [record["code"] for record in failure_records]

    cache_hits = sum(1 for record in per_code_records if record["cache_hit"])
    cache_miss_codes: list[str] = []
    if expect_cache:
        cache_miss_codes = [record["code"] for record in per_code_records if not record["cache_hit"]]

    cache_hit_rate = (
        cache_hits / total_codes if expect_cache and total_codes > 0 else None
    )

    LOGGER.info(
        "%s run finished in %.2fs (success=%d, failure=%d)",
        run_label,
        total_seconds,
        len(successes),
        len(failure_records),
    )
    if expect_cache:
        LOGGER.info(
            "%s run cache stats: hit=%d miss=%d", run_label, cache_hits, len(cache_miss_codes)
        )

    return {
        "sample_size": total_codes,
        "run_label": run_label,
        "total_codes": total_codes,
        "total_seconds": total_seconds,
        "per_stock_p50_seconds": p50,
        "per_stock_p90_seconds": p90,
        "success_count": len(successes),
        "failure_count": len(failure_records),
        "failure_codes": " ".join(failure_codes),
        "cache_hit_count": cache_hits,
        "cache_hit_rate": cache_hit_rate,
        "cache_hit_rate_pct": (cache_hit_rate * 100.0) if cache_hit_rate is not None else None,
        "cache_miss_codes": " ".join(cache_miss_codes),
        "cache_dir": str(cache_root),
        "start_time": run_start_wall.isoformat(timespec="seconds"),
        "end_time": run_end_wall.isoformat(timespec="seconds"),
        "bgn_de": METRICS_PARAMS["bgn_de"],
        "report_tp": METRICS_PARAMS["report_tp"],
        "separate": METRICS_PARAMS["separate"],
        "latest_only": METRICS_PARAMS["latest_only"],
        "percent_format": METRICS_PARAMS["percent_format"],
    }


def build_argument_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Benchmark metrics caching performance")
    parser.add_argument(
        "--sizes",
        type=int,
        nargs="+",
        default=list(DEFAULT_SAMPLE_SIZES),
        help="List of sample sizes to benchmark (default: 50 200)",
    )
    parser.add_argument(
        "--seed",
        type=int,
        default=DEFAULT_RANDOM_SEED,
        help="Random seed for sampling stock codes",
    )
    parser.add_argument(
        "--cache-root",
        type=Path,
        default=DEFAULT_CACHE_ROOT,
        help="Base directory to store benchmark caches",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=DEFAULT_OUTPUT_PATH,
        help="CSV file to write benchmark summary",
    )
    parser.add_argument(
        "--api-key",
        type=str,
        default=None,
        help="DART API key override (defaults to environment/.env)",
    )
    parser.add_argument(
        "--verbose",
        action="store_true",
        help="Enable verbose logging",
    )
    return parser


def format_optional_seconds(value: float | None) -> str:
    if value is None or pd.isna(value):
        return ""
    return f"{value:.2f}"


def main(argv: Iterable[str] | None = None) -> None:
    parser = build_argument_parser()
    args = parser.parse_args(list(argv) if argv is not None else None)

    configure_logging(args.verbose)

    LOGGER.info(
        "Benchmark fixed parameters: bgn_de=%s report_tp=%s separate=%s latest_only=%s",
        METRICS_PARAMS["bgn_de"],
        METRICS_PARAMS["report_tp"],
        METRICS_PARAMS["separate"],
        METRICS_PARAMS["latest_only"],
    )

    cache_root = args.cache_root.expanduser()
    cache_root.mkdir(parents=True, exist_ok=True)

    rng = random.Random(args.seed)

    init_dart(api_key=args.api_key)
    all_codes = load_all_stock_codes()

    all_results = []

    for sample_size in args.sizes:
        LOGGER.info("=== Benchmarking sample size %d ===", sample_size)
        codes = sample_stock_codes(all_codes, sample_size, rng)
        sample_cache_dir = prepare_cache_dir(cache_root, sample_size)

        cold_result = run_single_pass(
            codes=codes,
            cache_root=sample_cache_dir,
            api_key=args.api_key,
            run_label="cold",
            expect_cache=False,
        )
        warm_result = run_single_pass(
            codes=codes,
            cache_root=sample_cache_dir,
            api_key=args.api_key,
            run_label="warm",
            expect_cache=True,
        )
        all_results.extend([cold_result, warm_result])

    results_df = pd.DataFrame(all_results)
    if not results_df.empty:
        column_order = [
            "sample_size",
            "run_label",
            "total_codes",
            "total_seconds",
            "per_stock_p50_seconds",
            "per_stock_p90_seconds",
            "success_count",
            "failure_count",
            "cache_hit_count",
            "cache_hit_rate",
            "cache_hit_rate_pct",
            "cache_miss_codes",
            "failure_codes",
            "start_time",
            "end_time",
            "cache_dir",
            "bgn_de",
            "report_tp",
            "separate",
            "latest_only",
            "percent_format",
        ]
        results_df = results_df[column_order]
        results_df.to_csv(args.output, index=False)
        LOGGER.info("Benchmark summary written to %s", args.output)

        display_df = results_df[
            [
                "sample_size",
                "run_label",
                "total_seconds",
                "per_stock_p50_seconds",
                "per_stock_p90_seconds",
                "success_count",
                "failure_count",
                "cache_hit_rate_pct",
                "cache_miss_codes",
            ]
        ].copy()
        display_df["total_seconds"] = display_df["total_seconds"].map(format_optional_seconds)
        display_df["per_stock_p50_seconds"] = display_df["per_stock_p50_seconds"].map(
            format_optional_seconds
        )
        display_df["per_stock_p90_seconds"] = display_df["per_stock_p90_seconds"].map(
            format_optional_seconds
        )
        display_df["cache_hit_rate_pct"] = display_df["cache_hit_rate_pct"].map(
            lambda v: f"{v:.1f}%" if v is not None and not pd.isna(v) else ""
        )
        print("\n=== Benchmark Summary ===")
        print(display_df.to_string(index=False))
    else:
        LOGGER.warning("No benchmark results were produced")


if __name__ == "__main__":  # pragma: no cover - script entry point
    main()
