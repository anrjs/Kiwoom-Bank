"""Utilities to run the credit rating model on stored feature CSVs."""
from __future__ import annotations

import json
import math
from functools import lru_cache
from pathlib import Path
from typing import Any, Dict, List, Optional

import joblib
import numpy as np
import pandas as pd

# NOTE: ``api`` is a namespace package, so this works without __init__.py.
from api.features import SAVE_DIR as FEATURES_DIR  # type: ignore

_CREDIT_ROOT = Path(__file__).resolve().parents[1] / "credit_rating_project"
_CONFIG_PATH = _CREDIT_ROOT / "src" / "config.py"

if not _CONFIG_PATH.exists():
    raise RuntimeError(f"Credit rating config not found: {_CONFIG_PATH}")


@lru_cache(maxsize=1)
def _load_config_module():
    """Dynamically load the credit rating config module."""
    import importlib.util

    spec = importlib.util.spec_from_file_location("credit_config", _CONFIG_PATH)
    if spec is None or spec.loader is None:
        raise ImportError(f"Unable to load credit rating config from {_CONFIG_PATH}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)  # type: ignore[misc]
    return module


def _get_config_attr(name: str):
    module = _load_config_module()
    if not hasattr(module, name):
        raise AttributeError(f"credit_config missing attribute '{name}'")
    return getattr(module, name)


FEATURE_COLS: List[str] = list(_get_config_attr("FEATURE_COLS"))
NUMERIC_PERCENT_COLS: List[str] = list(_get_config_attr("NUMERIC_PERCENT_COLS"))
_ARTIFACTS_DIR = (_CREDIT_ROOT / _get_config_attr("ARTIFACTS_DIR")).resolve()
_MODEL_BUNDLE_PATH = _ARTIFACTS_DIR / "model.joblib"
_LABEL_MAPPING_PATH = _ARTIFACTS_DIR / "label_mapping.json"


class CreditModelNotReady(RuntimeError):
    """Raised when the credit model artifacts are missing."""


def _to_float_from_percent(value: Any) -> Optional[float]:
    """Convert value that may contain percent strings into float."""
    if value is None:
        return None
    if isinstance(value, str):
        text = value.strip()
        if not text:
            return None
        if text.endswith("%"):
            text = text[:-1]
            try:
                return float(text) / 100.0
            except ValueError as exc:  # pragma: no cover - safety guard
                raise ValueError(f"Cannot parse percent value: {value!r}") from exc
        try:
            return float(text)
        except ValueError as exc:  # pragma: no cover - safety guard
            raise ValueError(f"Cannot parse numeric value: {value!r}") from exc
    if isinstance(value, (int, float, np.floating)):
        if isinstance(value, float) and (math.isnan(value) or math.isinf(value)):
            return None
        return float(value)
    return float(value)


def _prepare_feature_frame(df: pd.DataFrame) -> pd.DataFrame:
    working = df.copy()
    for col in NUMERIC_PERCENT_COLS:
        if col in working.columns:
            working[col] = working[col].map(_to_float_from_percent)
    missing = [col for col in FEATURE_COLS if col not in working.columns]
    if missing:
        raise ValueError(f"Missing required feature columns: {missing}")
    return working[FEATURE_COLS].copy()


@lru_cache(maxsize=1)
def _load_model_bundle():
    if not _MODEL_BUNDLE_PATH.exists():
        raise CreditModelNotReady(f"Model bundle missing: {_MODEL_BUNDLE_PATH}")
    if not _LABEL_MAPPING_PATH.exists():
        raise CreditModelNotReady(f"Label mapping missing: {_LABEL_MAPPING_PATH}")

    bundle = joblib.load(_MODEL_BUNDLE_PATH)
    if not isinstance(bundle, dict) or "preprocessor" not in bundle or "model" not in bundle:
        raise RuntimeError("Invalid model bundle format")

    with open(_LABEL_MAPPING_PATH, "r", encoding="utf-8") as f:
        mapping = json.load(f)
    id2label = {int(k): v for k, v in mapping.get("id2label", {}).items()}
    if not id2label:
        raise RuntimeError("Label mapping is empty")

    return bundle["preprocessor"], bundle["model"], id2label


def _sanitize_company_name(company: str) -> str:
    return company.replace("/", "_").replace("\\", "_")


def find_latest_feature_file(company: str) -> Optional[Path]:
    safe = _sanitize_company_name(company)
    candidates = sorted(FEATURES_DIR.glob(f"{safe}_*.csv"))
    if not candidates:
        return None
    return max(candidates, key=lambda p: p.stat().st_mtime)


def load_feature_rows(path: Path) -> pd.DataFrame:
    if not path.exists():
        raise FileNotFoundError(path)
    df = pd.read_csv(path, index_col=0, encoding="utf-8-sig")
    df.index.name = df.index.name or "company"
    df = df.reset_index().rename(columns={"index": "company"})
    return df


def predict_from_dataframe(df: pd.DataFrame) -> List[Dict[str, Any]]:
    if df.empty:
        return []

    preprocessor, model, id2label = _load_model_bundle()
    X = _prepare_feature_frame(df)
    X_transformed = preprocessor.transform(X)
    y_pred_reg = model.predict(X_transformed)
    y_pred_notch = np.clip(np.round(y_pred_reg), 0, len(id2label) - 1).astype(int)
    results: List[Dict[str, Any]] = []

    company_series: Optional[pd.Series] = None
    if "company" in df.columns:
        company_series = df["company"]
    elif "회사명" in df.columns:
        company_series = df["회사명"]

    label_series = df["public_credit_rating"] if "public_credit_rating" in df.columns else None

    for idx in range(len(df)):
        company_name: Optional[str] = None
        if company_series is not None:
            raw_name = company_series.iloc[idx]
            if not pd.isna(raw_name):
                company_name = str(raw_name)
        features_dict: Dict[str, Optional[float]] = {}
        for col in FEATURE_COLS:
            value = X.iloc[idx][col]
            if pd.isna(value):
                features_dict[col] = None
            else:
                features_dict[col] = float(value)
        actual_label: Optional[str] = None
        if label_series is not None:
            value = label_series.iloc[idx]
            if not pd.isna(value):
                actual_label = str(value)
        results.append(
            {
                "company": company_name,
                "predicted_grade": id2label.get(int(y_pred_notch[idx])),
                "predicted_notch": int(y_pred_notch[idx]),
                "raw_score": float(y_pred_reg[idx]),
                "features": features_dict,
                "public_credit_rating": actual_label,
            }
        )
    return results


def predict_for_company(company: str) -> Dict[str, Any]:
    feature_file = find_latest_feature_file(company)
    if feature_file is None:
        raise FileNotFoundError(f"No feature CSV found for '{company}' in {FEATURES_DIR}")

    df = load_feature_rows(feature_file)
    if "company" in df.columns:
        mask = df["company"].astype(str).str.lower() == company.lower()
        if mask.any():
            df = df.loc[mask].copy()
    predictions = predict_from_dataframe(df)
    if not predictions:
        raise RuntimeError(f"No predictions generated for '{company}'")
    prediction = predictions[0]
    prediction.setdefault("company", company)
    prediction["source_file"] = str(feature_file)
    prediction["artifacts_dir"] = str(_ARTIFACTS_DIR)
    return prediction