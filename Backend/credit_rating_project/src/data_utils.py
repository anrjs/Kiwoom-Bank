# -*- coding: utf-8 -*-
import os
import re
import json
import numpy as np
import pandas as pd
from typing import Dict, List, Tuple

from .config import (
    FEATURE_COLS, TARGET_COL, ID_COL,
    NUMERIC_PERCENT_COLS, ARTIFACTS_DIR, RATING_ORDER
)

# ──────────────────────────────────────────────
# 퍼센트 처리
# ──────────────────────────────────────────────
def _to_float_from_percent(s):
    if pd.isna(s): return None
    if isinstance(s, (int, float)): return float(s)
    s = str(s).strip()
    return float(s.replace("%", "")) / 100.0 if "%" in s else float(s)

def clean_percent_columns(df: pd.DataFrame) -> pd.DataFrame:
    for col in NUMERIC_PERCENT_COLS:
        if col in df.columns:
            df[col] = df[col].map(_to_float_from_percent)
    return df

# ──────────────────────────────────────────────
# 등급 정규화 (텍스트 기반)
# ──────────────────────────────────────────────
_KR_SYNONYM_MAP = {
    "AA0": "AA", "A0":"A", "BBB0":"BBB", "BB0":"BB", "B0":"B", "CCC0":"CCC",
    "CC0":"CC", "C0":"C",
}
_INVALID_LABELS = {"NR", "N/A", "NA", "WD", "WR", "SD", "RD", "-", "", "NONE"}

def _normalize_minus_plus(s: str) -> str:
    s = s.replace("–", "-").replace("−", "-")
    s = s.replace("＋", "+").replace(" + ", "+").replace(" - ", "-")
    return s

def normalize_rating(raw: str) -> str:
    if raw is None:
        return None
    s = str(raw).strip().upper()
    s = _normalize_minus_plus(s)
    s = re.sub(r"\s+", "", s)
    s = _KR_SYNONYM_MAP.get(s, s)
    s = s.split("/")[0] if "/" in s else s
    s = re.sub(r"[^ABCD\+\-]", "", s)
    if s in _INVALID_LABELS:
        return None
    return s if s else None

# ──────────────────────────────────────────────
# 데이터셋 로드 및 전처리
# ──────────────────────────────────────────────
def load_dataframe(path_or_dir: str) -> pd.DataFrame:
    # 파일 1개 또는 폴더 처리
    if os.path.isdir(path_or_dir):
        files = [os.path.join(path_or_dir, f) for f in os.listdir(path_or_dir) if f.lower().endswith(".xlsx")]
        df_list = [pd.read_excel(f) for f in files]
        df = pd.concat(df_list, ignore_index=True)
    else:
        df = pd.read_excel(path_or_dir)

    # 퍼센트 변환
    df = clean_percent_columns(df)

    # 필수 컬럼 확인
    missing = set([ID_COL, TARGET_COL] + FEATURE_COLS) - set(df.columns)
    if missing:
        raise ValueError(f"필수 컬럼 누락: {missing}")

    return df

# ──────────────────────────────────────────────
# X, y 분리 및 매핑 저장
# ──────────────────────────────────────────────
def split_X_y(df: pd.DataFrame) -> Tuple[pd.DataFrame, pd.Series, Dict[str, int], Dict[int, str]]:
    X = df[FEATURE_COLS].copy()
    raw_y = df[TARGET_COL].map(normalize_rating)

    # 유효한 등급만 남기기
    rating_set = set(raw_y.dropna().unique())
    class_order = [r for r in RATING_ORDER if r in rating_set]

    label2id = {label: i for i, label in enumerate(class_order)}
    id2label = {i: label for label, i in label2id.items()}
    y = raw_y.map(label2id)

    # 저장
    os.makedirs(ARTIFACTS_DIR, exist_ok=True)
    with open(os.path.join(ARTIFACTS_DIR, "label_mapping.json"), "w", encoding="utf-8") as f:
        json.dump({"label2id": label2id, "id2label": id2label}, f, ensure_ascii=False, indent=2)
    with open(os.path.join(ARTIFACTS_DIR, "feature_columns.json"), "w", encoding="utf-8") as f:
        json.dump(FEATURE_COLS, f, ensure_ascii=False, indent=2)

    return X, y, label2id, id2label