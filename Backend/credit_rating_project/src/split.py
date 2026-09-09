# -*- coding: utf-8 -*-
from typing import Tuple
import numpy as np
import pandas as pd
from sklearn.model_selection import train_test_split, StratifiedKFold
from .config import CV_FOLDS, RANDOM_SEED

def group_stratified_split(groups, y, test_size=0.2, random_state=42):
    """그룹별 다중 라벨이 존재할 때: 그룹별 대표 라벨로 stratified split"""
    groups = np.asarray(groups)
    y = np.asarray(y)
    df = pd.DataFrame({"group": groups, "y": y})
    df = df.dropna(subset=["group", "y"])
    maj = df.groupby("group")["y"].agg(lambda s: s.value_counts().index[0])
    uniq_groups = maj.index.values
    grp_labels = maj.values
    g_train, g_test = train_test_split(uniq_groups, test_size=test_size,
                                       random_state=random_state, stratify=grp_labels)
    mask_train = np.isin(groups, g_train)
    mask_test = np.isin(groups, g_test)
    idx_train = np.where(mask_train)[0]
    idx_test = np.where(mask_test)[0]
    return idx_train, idx_test

def make_cv():
    """기본 stratified k-fold cross validation"""
    return StratifiedKFold(n_splits=CV_FOLDS, shuffle=True, random_state=RANDOM_SEED)