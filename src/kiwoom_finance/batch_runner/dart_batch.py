from __future__ import annotations

import argparse
import os
import signal
import threading
import time
import warnings
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Iterable, List, Sequence

import pandas as pd

from kiwoom_finance.batch import get_metrics_for_codes

DEFAULT_CODES = ["SK하이닉스"]


@dataclass(slots=True)
class DartBatchPaths:
    """Filesystem layout used by the batch runner."""

    output_dir: Path
    cache_dir: Path
    result_csv: Path
    failed_csv: Path
    skipped_csv: Path
    snapshot_dir: Path
    integrity_csv: Path

    @classmethod
    def from_base_dir(cls, base_dir: str | Path | None = None) -> "DartBatchPaths":
        base = Path(base_dir) if base_dir is not None else Path.cwd()
        artifacts = base / "artifacts"
        return cls(
            output_dir=artifacts / "by_stock",
            cache_dir=artifacts / ".pklcache",
            result_csv=base / "metrics_result.csv",
            failed_csv=artifacts / "failed_codes.csv",
            skipped_csv=artifacts / "skipped_codes.csv",
            snapshot_dir=artifacts / "snapshots",
            integrity_csv=artifacts / "metrics_integrity_report.csv",
        )

    def ensure(self) -> "DartBatchPaths":
        self.output_dir.mkdir(parents=True, exist_ok=True)
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        self.snapshot_dir.mkdir(parents=True, exist_ok=True)
        for csv_path in (self.result_csv, self.failed_csv, self.skipped_csv, self.integrity_csv):
            csv_path.parent.mkdir(parents=True, exist_ok=True)
        return self


@dataclass(slots=True)
class DartBatchSettings:
    """Runtime options forwarded to :func:`get_metrics_for_codes`."""

    bgn_de: str = "20210101"
    report_tp: str = "annual"
    separate: bool = True
    latest_only: bool = False
    percent_format: bool = False
    api_key: str | None = None
    max_workers: int = 4
    prefer_process: bool = True
    per_code_timeout_sec: int = 90
    skip_nan_heavy: bool = True
    nan_ratio_limit: float = 0.60
    min_non_null: int = 5
    cache_ttl: int = 24 * 3600
    force_refresh: bool = False
    save_each: bool = True


def normalize_codes(codes: Iterable[str]) -> List[str]:
    digits = [str(code) for code in codes]
    digits = [code for code in digits if code.isdigit() and len(code) <= 6]
    digits = [code.zfill(6) for code in digits]
    # remove duplicates while preserving order
    return list(dict.fromkeys(digits))


def list_done_codes_from_csv_cache(out_dir: Path) -> set[str]:
    done: set[str] = set()
    for csv_path in out_dir.glob("*.csv"):
        code = csv_path.stem
        if code.isdigit():
            done.add(code.zfill(6))
    return done


def compute_todo_codes(all_codes: Sequence[str], out_dir: Path) -> List[str]:
    done = list_done_codes_from_csv_cache(out_dir)
    return [code for code in all_codes if code not in done]


def merge_by_stock_cache(out_dir: Path) -> pd.DataFrame:
    files = list(out_dir.glob("*.csv"))
    if not files:
        return pd.DataFrame()

    frames: list[pd.DataFrame] = []
    for csv_path in files:
        try:
            df = pd.read_csv(csv_path, encoding="utf-8-sig")
        except Exception as exc:  # pragma: no cover - defensive logging
            print(f"⚠️ 캐시 파일 읽기 실패: {csv_path.name} ({exc})")
            continue

        if "stock_code" not in df.columns:
            df["stock_code"] = csv_path.stem.zfill(6)
        else:
            df["stock_code"] = df["stock_code"].astype(str).str[:6].str.zfill(6)
        frames.append(df)

    if not frames:
        return pd.DataFrame()

    merged = pd.concat(frames, ignore_index=True)
    merged["_score"] = merged.apply(lambda row: row.notna().sum(), axis=1)
    merged.sort_values(["stock_code", "_score"], ascending=[True, False], inplace=True)
    merged = merged.drop_duplicates(subset=["stock_code"], keep="first")
    merged.drop(columns=["_score"], inplace=True, errors="ignore")
    merged.set_index("stock_code", inplace=True)
    return merged


def save_snapshot(df: pd.DataFrame, paths: DartBatchPaths, tag: str) -> Path | None:
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    snapshot_path = paths.snapshot_dir / f"metrics_result_{tag}_{ts}.csv"
    try:
        df.to_csv(snapshot_path, encoding="utf-8-sig")
        print(f"💾 스냅샷 저장: {snapshot_path}")
        return snapshot_path
    except Exception as exc:  # pragma: no cover - defensive logging
        print(f"⚠️ 스냅샷 저장 실패: {exc}")
        return None


def _to_num_strict(value):
    if isinstance(value, str):
        text = value.strip().replace(",", "")
        if text.endswith("%"):
            try:
                return float(text[:-1]) / 100.0
            except Exception:
                return pd.NA
        try:
            return float(text)
        except Exception:
            return pd.NA
    return pd.to_numeric(value, errors="coerce")


def produce_integrity_report(df: pd.DataFrame, paths: DartBatchPaths) -> pd.DataFrame:
    if df.empty:
        return df

    res = df.copy()
    for col in ("debt_ratio", "equity_ratio"):
        if col in res.columns:
            res[col] = res[col].map(_to_num_strict)

    if "debt_ratio" in res.columns:
        debt_ratio = res["debt_ratio"]
        res["equity_implied_from_debt"] = (1.0 / (1.0 + debt_ratio)).where(debt_ratio.notna())
    else:
        res["equity_implied_from_debt"] = pd.NA

    if "equity_ratio" in res.columns:
        equity_ratio = res["equity_ratio"].copy()
    else:
        equity_ratio = pd.Series(pd.NA, index=res.index, dtype="float64")

    res["equity_ratio_filled"] = equity_ratio.where(equity_ratio.notna(), res["equity_implied_from_debt"])
    res["Δ_equity_ratio"] = (res["equity_ratio_filled"] - res["equity_implied_from_debt"]).astype("float64")

    na_summary = res.isna().sum().sort_values(ascending=False)
    print("\n=== 결측치 요약(상위 15개) ===")
    print(na_summary.head(15))

    cols_show = [
        col
        for col in (
            "equity_ratio",
            "equity_ratio_filled",
            "debt_ratio",
            "equity_implied_from_debt",
            "Δ_equity_ratio",
        )
        if col in res.columns
    ]
    print("\n=== 무결성 체크 샘플(상위 10행) ===")
    print(res[cols_show].head(10))

    try:
        res.to_csv(paths.integrity_csv, encoding="utf-8-sig", index=True)
        print(f"🧾 무결성 리포트 저장: {paths.integrity_csv}")
    except Exception as exc:  # pragma: no cover - defensive logging
        print(f"⚠️ 무결성 리포트 저장 실패: {exc}")

    return res


def run_batch_for(
    codes: Sequence[str],
    settings: DartBatchSettings,
    paths: DartBatchPaths,
) -> pd.DataFrame:
    if not codes:
        return pd.DataFrame()

    print(f"🚀 배치 시작: {len(codes)}개 종목 (예시: {list(codes)[:5]})")
    df = get_metrics_for_codes(
        list(codes),
        bgn_de=settings.bgn_de,
        report_tp=settings.report_tp,
        separate=settings.separate,
        latest_only=settings.latest_only,
        percent_format=settings.percent_format,
        api_key=settings.api_key,
        save_each=settings.save_each,
        output_dir=str(paths.output_dir),
        max_workers=settings.max_workers,
        prefer_process=settings.prefer_process,
        per_code_timeout_sec=settings.per_code_timeout_sec,
        skip_nan_heavy=settings.skip_nan_heavy,
        nan_ratio_limit=settings.nan_ratio_limit,
        min_non_null=settings.min_non_null,
        cache_dir=str(paths.cache_dir),
        cache_ttl=settings.cache_ttl,
        force_refresh=settings.force_refresh,
    )
    return df


def run_batch_loop(
    codes: Iterable[str],
    *,
    settings: DartBatchSettings | None = None,
    paths: DartBatchPaths | None = None,
    stop_event: threading.Event | None = None,
    max_passes: int = 5,
) -> pd.DataFrame:
    settings = settings or DartBatchSettings()
    paths = (paths or DartBatchPaths.from_base_dir()).ensure()

    normalized = normalize_codes(codes)
    print(f"✅ 타깃 종목 수: {len(normalized)} (예시 5개: {normalized[:5]})")
    print(f"📁 CSV 캐시 폴더: {paths.output_dir.resolve()}")

    merged_initial = merge_by_stock_cache(paths.output_dir)
    if not merged_initial.empty:
        merged_initial.to_csv(paths.result_csv, encoding="utf-8-sig")
        print(f"📄 초기 병합본 저장: {paths.result_csv} (rows={len(merged_initial)})")

    passes = 0
    while passes < max_passes:
        if stop_event and stop_event.is_set():
            print("🛑 중지 요청으로 루프 종료")
            break

        todo = compute_todo_codes(normalized, paths.output_dir)
        if not todo:
            print("🎉 처리할 남은 종목이 없습니다.")
            break

        passes += 1
        print(f"\n🔁 패스 {passes}/{max_passes} — 남은 종목: {len(todo)}")
        try:
            _ = run_batch_for(todo, settings, paths)
        except Exception as exc:  # pragma: no cover - defensive logging
            print(f"❌ 배치 호출 오류: {exc}")
            time.sleep(5)
            continue

        merged = merge_by_stock_cache(paths.output_dir)
        if not merged.empty:
            merged.to_csv(paths.result_csv, encoding="utf-8-sig")
            print(f"✅ 병합/저장 완료: {paths.result_csv} (rows={len(merged)})")
            save_snapshot(merged, paths, tag=f"pass{passes}")
        else:
            print("⚠️ 병합 결과가 비어 있습니다. 캐시/로그를 확인하세요.")

        if paths.failed_csv.exists():
            try:
                failed = pd.read_csv(paths.failed_csv, dtype=str)
                if not failed.empty:
                    example = failed.head(10).to_dict(orient="list")
                    print(f"⚠️ 실패 종목 {len(failed)}개 (예시 10개): {example}")
            except Exception:
                pass
        if paths.skipped_csv.exists():
            try:
                skipped = pd.read_csv(paths.skipped_csv, dtype=str)
                if not skipped.empty:
                    example = skipped.head(10).to_dict(orient="list")
                    print(f"ℹ️ 스킵 종목 {len(skipped)}개 (예시 10개): {example}")
            except Exception:
                pass

    final_df = merge_by_stock_cache(paths.output_dir)
    if not final_df.empty:
        final_df.to_csv(paths.result_csv, encoding="utf-8-sig")
        print(f"\n🏁 최종 저장 완료: {paths.result_csv} (rows={len(final_df)})")
    else:
        print("\n❗ 최종 병합본이 비었습니다. 실행 로그/캐시를 확인하세요.")

    if not final_df.empty:
        try:
            _ = produce_integrity_report(final_df, paths)
        except Exception as exc:  # pragma: no cover - defensive logging
            print(f"⚠️ 무결성 체크 중 오류: {exc}")

    return final_df


def load_dotenv_if_possible() -> None:
    try:
        from dotenv import find_dotenv, load_dotenv

        path = find_dotenv(usecwd=True)
        if path:
            load_dotenv(path)
            print(f"🧩 .env 로드: {path}")
    except Exception:
        pass


def configure_warnings() -> None:
    warnings.filterwarnings("ignore", category=UserWarning, module="dart_fss")
    warnings.filterwarnings("ignore", category=RuntimeWarning, module="dart_fss")


def install_signal_handlers(stop_event: threading.Event) -> None:
    def _handle(signum, frame):  # pragma: no cover - signal handler
        stop_event.set()
        print("\n🛑 중지 요청 감지. 현재 배치가 끝나면 안전하게 저장하고 종료합니다...")

    for name in ("SIGINT", "SIGTERM"):
        if hasattr(signal, name):
            signal.signal(getattr(signal, name), _handle)


def _build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Run DART metrics batch runner.")
    parser.add_argument("codes", nargs="*", help="Target stock codes (default: 005930).")
    parser.add_argument("--base-dir", type=Path, default=None, help="프로젝트 루트 또는 출력 루트 경로")
    parser.add_argument("--passes", type=int, default=5, help="최대 반복 패스 수")
    parser.add_argument("--api-key", type=str, default=None, help="DART API Key")
    parser.add_argument("--bgn-de", dest="bgn_de", default="20210101")
    parser.add_argument("--report-tp", dest="report_tp", default="annual")
    parser.add_argument("--latest-only", action="store_true", default=False)
    parser.add_argument("--percent-format", action="store_true", default=False)
    parser.add_argument("--consolidated", dest="separate", action="store_false", help="연결 재무제표 사용")
    parser.set_defaults(separate=True)
    parser.add_argument("--max-workers", type=int, default=4)
    parser.add_argument("--per-code-timeout", type=int, default=90)
    parser.add_argument("--no-skip-nan-heavy", dest="skip_nan_heavy", action="store_false")
    parser.set_defaults(skip_nan_heavy=True)
    parser.add_argument("--min-non-null", type=int, default=5)
    parser.add_argument("--nan-ratio-limit", type=float, default=0.60)
    parser.add_argument("--cache-ttl", type=int, default=24 * 3600)
    parser.add_argument("--force-refresh", action="store_true", default=False)
    parser.add_argument("--thread-pool", dest="prefer_process", action="store_false", help="스레드 풀 사용")
    parser.set_defaults(prefer_process=True)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    load_dotenv_if_possible()
    configure_warnings()

    parser = _build_arg_parser()
    args = parser.parse_args(argv)

    codes = args.codes or DEFAULT_CODES
    paths = DartBatchPaths.from_base_dir(args.base_dir).ensure()
    api_key = args.api_key or os.getenv("DART_API_KEY", "").strip() or None

    settings = DartBatchSettings(
        bgn_de=args.bgn_de,
        report_tp=args.report_tp,
        separate=args.separate,
        latest_only=args.latest_only,
        percent_format=args.percent_format,
        api_key=api_key,
        max_workers=args.max_workers,
        prefer_process=args.prefer_process,
        per_code_timeout_sec=args.per_code_timeout,
        skip_nan_heavy=args.skip_nan_heavy,
        nan_ratio_limit=args.nan_ratio_limit,
        min_non_null=args.min_non_null,
        cache_ttl=args.cache_ttl,
        force_refresh=args.force_refresh,
    )

    stop_event = threading.Event()
    install_signal_handlers(stop_event)

    try:
        run_batch_loop(codes, settings=settings, paths=paths, stop_event=stop_event, max_passes=args.passes)
    except KeyboardInterrupt:
        print("\n🛑 사용자 중단. 마지막 병합을 시도합니다...")
        final_df = merge_by_stock_cache(paths.output_dir)
        if not final_df.empty:
            final_df.to_csv(paths.result_csv, encoding="utf-8-sig")
            print(f"💾 중단 전 저장: {paths.result_csv} (rows={len(final_df)})")
        return 1

    return 0


if __name__ == "__main__":  # pragma: no cover - CLI entry point
    raise SystemExit(main())