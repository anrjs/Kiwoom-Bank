from __future__ import annotations

import asyncio
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, Iterable, List, Sequence, Tuple

import numpy as np
import pandas as pd

from ..batch import get_metrics_for_codes
from ..dart_client import IdentifierType, find_corp

try:  # pragma: no cover - optional dependency (selenium stack)
    import crawling_cash_final as _credit_module  # type: ignore
except Exception:  # pragma: no cover - module not available in all envs
    _credit_module = None  # type: ignore


SUMMARY_METRIC_COLUMNS: Tuple[str, ...] = (
    "debt_ratio",
    "roa",
    "total_asset_growth_rate",
    "cfo_to_total_debt",
    "current_ratio",
    "quick_ratio",
)

DEFAULT_METRIC_CACHE_DIR = Path("artifacts/by_stock")


@dataclass(slots=True)
class CompanyTarget:
    """Resolved corp information for downstream lookups."""

    query: str
    stock_code: str
    corp_name: str | None = None


def _normalize_stock_code(raw: Any) -> str | None:
    if raw is None:
        return None
    code = str(raw).strip()
    if not code:
        return None
    if code.isdigit() and len(code) < 6:
        code = code.zfill(6)
    return code


def resolve_targets(
    identifiers: Sequence[str],
    *,
    identifier_type: IdentifierType = "auto",
) -> Tuple[List[CompanyTarget], List[Dict[str, Any]]]:
    """Resolve identifiers to stock codes using the cached DART corp list."""

    targets: List[CompanyTarget] = []
    errors: List[Dict[str, Any]] = []

    for raw in identifiers:
        token = (str(raw).strip() if raw is not None else "")
        if not token:
            errors.append({"query": raw, "reason": "empty"})
            continue

        try:
            corp = find_corp(token, by=identifier_type)
        except Exception as exc:  # pragma: no cover - defensive
            errors.append({"query": token, "reason": "lookup_error", "detail": str(exc)})
            continue

        if corp is None:
            errors.append({"query": token, "reason": "not_found"})
            continue

        stock_code = _normalize_stock_code(getattr(corp, "stock_code", None))
        corp_name = getattr(corp, "corp_name", None)
        if corp_name is not None:
            corp_name = str(corp_name).strip() or None

        if not stock_code:
            errors.append({"query": token, "reason": "no_stock_code", "corp_name": corp_name})
            continue

        targets.append(CompanyTarget(query=token, stock_code=stock_code, corp_name=corp_name))

    return targets, errors


def _series_to_serializable(row: pd.Series) -> Dict[str, float | None]:
    out: Dict[str, float | None] = {}
    for key, value in row.items():
        if pd.isna(value):
            out[key] = None
        elif isinstance(value, (np.floating, float, int, np.integer)):
            out[key] = float(value)
        else:
            try:
                out[key] = float(value)
            except Exception:
                out[key] = None
    return out


def _collect_metrics(
    targets: Sequence[CompanyTarget],
    metric_columns: Sequence[str],
    output_dir: Path | str,
) -> Tuple[Dict[str, Dict[str, float | None]], Dict[str, Any]]:
    codes_ordered = [t.stock_code for t in targets]
    unique_codes = list(dict.fromkeys(codes_ordered))

    meta: Dict[str, Any] = {
        "requested": len(unique_codes),
        "columns": list(metric_columns),
        "output_dir": str(output_dir),
    }

    if not unique_codes:
        meta["available"] = 0
        meta["available_columns"] = []
        return {}, meta

    df = get_metrics_for_codes(
        unique_codes,
        latest_only=True,
        percent_format=False,
        identifier_type="code",
        save_each=True,
        output_dir=str(output_dir),
    )

    if df is None or df.empty:
        meta["available"] = 0
        meta["available_columns"] = []
        return {}, meta

    df = df.copy()
    available_cols = [col for col in metric_columns if col in df.columns]
    if available_cols:
        df = df[available_cols]
    meta["available_columns"] = available_cols

    metrics: Dict[str, Dict[str, float | None]] = {}
    for idx, row in df.iterrows():
        stock_code = _normalize_stock_code(idx) or str(idx)
        metrics[stock_code] = _series_to_serializable(row)

    meta["available"] = len(metrics)
    return metrics, meta


def _ts_to_datetime(value: Any) -> datetime | None:
    if isinstance(value, pd.Timestamp):
        return value.to_pydatetime()
    if isinstance(value, datetime):
        return value
    return None


def _iter_credit_candidates(target: CompanyTarget) -> Iterable[str]:
    seen: set[str] = set()
    for candidate in (target.corp_name, target.query):
        if not candidate:
            continue
        norm = candidate.strip()
        if not norm or norm in seen:
            continue
        seen.add(norm)
        yield norm


def _ensure_credit_cache() -> bool:
    if _credit_module is None:
        return False
    try:
        cache_ready = bool(getattr(_credit_module, "_CACHE_READY", False))
        if not cache_ready:
            cache = _credit_module._load_disk_cache()  # type: ignore[attr-defined]
            _credit_module.DISK_CACHE = cache  # type: ignore[attr-defined]
            setattr(_credit_module, "_CACHE_READY", True)
        return True
    except Exception:
        return False


def _collect_credit(
    targets: Sequence[CompanyTarget],
    *,
    cache_only: bool = True,
) -> Tuple[Dict[str, Dict[str, Any]], Dict[str, Any]]:
    meta: Dict[str, Any] = {
        "available": _credit_module is not None,
        "cache_only": cache_only,
        "hits": 0,
    }

    if _credit_module is None:
        meta["reason"] = "module_not_imported"
        return {}, meta

    cache_ready = _ensure_credit_cache()
    meta["cache_loaded"] = cache_ready
    if not cache_ready:
        meta["reason"] = "cache_load_failed"
        return {}, meta

    results: Dict[str, Dict[str, Any]] = {}
    clean_grade = getattr(_credit_module, "_clean_grade", None)
    lookup_cache = getattr(_credit_module, "_lookup_cache", None)

    for target in targets:
        record = None
        for candidate in _iter_credit_candidates(target):
            try:
                record = lookup_cache(candidate) if lookup_cache else None  # type: ignore[misc]
            except Exception:
                record = None
            if record:
                break

        if not record:
            continue

        rating_raw = record.get("등급") if isinstance(record, dict) else None
        rating = clean_grade(rating_raw) if callable(clean_grade) else rating_raw

        ts = record.get("source_ts") if isinstance(record, dict) else None
        timestamp = _ts_to_datetime(ts)

        results[target.stock_code] = {
            "company_name": record.get("회사명") if isinstance(record, dict) else target.corp_name,
            "rating": rating or None,
            "cmp_cd": record.get("cmpCd") if isinstance(record, dict) else None,
            "cache_timestamp": timestamp,
            "cache_hit": True,
            "source": "nicerating_cache",
        }

    meta["hits"] = len(results)
    return results, meta


async def get_company_summaries(
    identifiers: Sequence[str],
    *,
    identifier_type: IdentifierType = "auto",
    metric_columns: Sequence[str] = SUMMARY_METRIC_COLUMNS,
    metrics_output_dir: Path | str = DEFAULT_METRIC_CACHE_DIR,
    enable_credit_lookup: bool = True,
    credit_cache_only: bool = True,
) -> Dict[str, Any]:
    """Resolve companies and gather metrics/credit data concurrently."""

    targets, errors = await asyncio.to_thread(
        resolve_targets,
        identifiers,
        identifier_type=identifier_type,
    )

    meta: Dict[str, Any] = {
        "requested": len(identifiers),
        "resolved": len(targets),
    }

    metrics_task = asyncio.create_task(
        asyncio.to_thread(_collect_metrics, targets, metric_columns, metrics_output_dir)
    )

    if enable_credit_lookup:
        credit_task = asyncio.create_task(
            asyncio.to_thread(_collect_credit, targets, cache_only=credit_cache_only)
        )
    else:
        credit_task = None

    metrics_map, metrics_meta = await metrics_task
    credit_map: Dict[str, Dict[str, Any]]
    credit_meta: Dict[str, Any]

    if credit_task is not None:
        credit_map, credit_meta = await credit_task
    else:
        credit_map, credit_meta = {}, {"available": False, "cache_only": credit_cache_only, "hits": 0}

    meta["metrics"] = metrics_meta
    meta["credit_rating"] = credit_meta

    results: List[Dict[str, Any]] = []
    for target in targets:
        stock_code = target.stock_code
        metrics_payload = metrics_map.get(stock_code)
        credit_payload = credit_map.get(stock_code) if enable_credit_lookup else None

        notes: List[str] = []
        if metrics_payload is None:
            notes.append("metrics_not_available")
        if enable_credit_lookup and credit_payload is None:
            notes.append("credit_not_available")

        results.append(
            {
                "query": target.query,
                "stock_code": stock_code,
                "corp_name": target.corp_name or target.query,
                "metrics": metrics_payload,
                "credit_rating": credit_payload,
                "notes": notes,
            }
        )

    return {"results": results, "errors": errors, "meta": meta}