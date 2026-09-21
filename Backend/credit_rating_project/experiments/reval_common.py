# -*- coding: utf-8 -*-
"""
experiments/reval_common.py — ACI 재검증 공용 유틸리티 (교정 라벨 데이터 로딩)

기존 experiments/common.py는 "원래 라벨"만 다루므로 수정하지 않고,
"교정 라벨(NICE 이력 대조 결과)"을 반영한 데이터셋을 만드는 로직만 여기 새로 둡니다.
"""
import os
import sys
from collections import Counter

import numpy as np
import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from src.config import FEATURE_COLS, ID_COL, RATING_ORDER  # noqa: E402
from src.data_utils import load_dataframe, normalize_rating  # noqa: E402


def load_corrected_data(data_path: str, labels_csv_path: str):
    """
    data_path   : real_dataset.xlsx (69개 기업 원본 피처 + 원래 라벨)
    labels_csv_path : reval_label_audit_crawler.py가 만든 stage1_corrected_labels.csv
                       (회사명, 교정라벨 컬럼 필요. 교정라벨이 비어있으면 해당 기업 제외)

    반환: X, y_all(교정라벨 기준 notch id), ids, label2id, id2label
          (기존 src.data_utils.split_X_y와 동일한 필터링 규칙: 클래스당 표본 2건 미만 제외)
    """
    df_raw = load_dataframe(data_path)
    labels_df = pd.read_csv(labels_csv_path)

    if "교정라벨" not in labels_df.columns:
        raise ValueError(f"{labels_csv_path}에 '교정라벨' 컬럼이 없습니다.")

    merged = df_raw.merge(labels_df[["회사명", "교정라벨"]], on="회사명", how="left")

    n_before = len(merged)
    merged = merged[merged["교정라벨"].notna()].reset_index(drop=True)
    n_no_label = n_before - len(merged)
    print(f"[reval_common] 교정라벨 없음으로 제외된 기업: {n_no_label}건 "
          f"(전체 {n_before}건 중 {len(merged)}건 사용)")

    merged["교정라벨_정규화"] = merged["교정라벨"].map(normalize_rating)
    unresolved = merged["교정라벨_정규화"].isna().sum()
    if unresolved:
        print(f"[reval_common] ⚠ 교정라벨 정규화 실패(형식 이상) {unresolved}건도 제외합니다.")
        merged = merged[merged["교정라벨_정규화"].notna()].reset_index(drop=True)

    rating_set = set(merged["교정라벨_정규화"].unique())
    class_order = [r for r in RATING_ORDER if r in rating_set]
    label2id = {label: i for i, label in enumerate(class_order)}
    id2label = {i: label for label, i in label2id.items()}

    y_all_full = merged["교정라벨_정규화"].map(label2id).values.astype(int)
    X_full = merged[FEATURE_COLS].copy()
    ids_full = merged[ID_COL] if ID_COL in merged.columns else pd.Series(
        [f"row_{i}" for i in range(len(merged))]
    )

    # 클래스당 표본 2건 미만이면 제외 (기존 파이프라인과 동일 규칙)
    counts = Counter(y_all_full)
    valid_classes = {k for k, v in counts.items() if v >= 2} or set(np.unique(y_all_full))
    mask = np.isin(y_all_full, list(valid_classes))

    X = X_full.loc[mask].reset_index(drop=True)
    y_all = y_all_full[mask]
    ids = ids_full.loc[mask].reset_index(drop=True)

    n_dropped_singleton = (~mask).sum()
    if n_dropped_singleton:
        print(f"[reval_common] 클래스당 표본 2건 미만이라 추가 제외: {n_dropped_singleton}건")

    print(f"[reval_common] 최종 사용 표본 수: {len(y_all)}건, 클래스 수: {len(np.unique(y_all))}")

    return X, y_all, ids, label2id, id2label
