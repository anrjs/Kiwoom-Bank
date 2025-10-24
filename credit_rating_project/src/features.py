# -*- coding: utf-8 -*-
from typing import List, Optional, Tuple
import numpy as np
import pandas as pd
from sklearn.base import BaseEstimator, TransformerMixin
from sklearn.impute import SimpleImputer
from sklearn.preprocessing import RobustScaler

from .config import WINSOR_LO, WINSOR_HI, TOPK_INTERACT, FEATURE_COLS

# ─────────────────────────────────────────────
# 커스텀 전처리 컴포넌트
# ─────────────────────────────────────────────
class Winsorizer(BaseEstimator, TransformerMixin):
    def __init__(self, lower=WINSOR_LO, upper=WINSOR_HI):
        self.lower = lower
        self.upper = upper
        self.quantiles_ = None

    def fit(self, X, y=None):
        X = np.asarray(X, dtype=float)
        lo = np.nanquantile(X, self.lower, axis=0)
        hi = np.nanquantile(X, self.upper, axis=0)
        self.quantiles_ = (lo, hi)
        return self

    def transform(self, X):
        X = np.asarray(X, dtype=float)
        lo, hi = self.quantiles_
        return np.clip(X, lo, hi)

class SelectiveLog1p(BaseEstimator, TransformerMixin):
    def __init__(self):
        self.apply_mask_ = None

    def fit(self, X, y=None):
        X = np.asarray(X, dtype=float)
        mins = np.nanmin(X, axis=0)
        self.apply_mask_ = mins > 0
        return self

    def transform(self, X):
        X = np.asarray(X, dtype=float)
        Z = X.copy()
        mask = self.apply_mask_
        Z[:, mask] = np.log1p(Z[:, mask])
        return Z

class InteractionWithSentiment(BaseEstimator, TransformerMixin):
    def __init__(self, news_index: int, topk: int = TOPK_INTERACT):
        self.news_index = news_index
        self.topk = topk
        self.topk_idx_ = None
        self.n_features_in_ = None

    def fit(self, X, y=None):
        X = np.asarray(X, dtype=float)
        self.n_features_in_ = X.shape[1]
        if y is None:
            self.topk_idx_ = []
            return self

        from scipy.stats import spearmanr
        corrs = []
        for j in range(X.shape[1]):
            if j == self.news_index:
                corrs.append(0.0); continue
            xj = X[:, j]
            mask = ~np.isnan(xj) & ~np.isnan(y)
            if mask.sum() < 10:
                corrs.append(0.0)
            else:
                try:
                    c, _ = spearmanr(xj[mask], y[mask])
                except Exception:
                    c = 0.0
                corrs.append(abs(0.0 if c is None else c))
        order = np.argsort(corrs)[::-1]
        self.topk_idx_ = [int(i) for i in order[:self.topk] if int(i) != self.news_index]
        return self

    def transform(self, X):
        X = np.asarray(X, dtype=float)
        news = X[:, self.news_index].reshape(-1, 1)
        if not self.topk_idx_:
            return X
        inters = [ (X[:, i] * news.ravel()).reshape(-1, 1) for i in self.topk_idx_ ]
        Z = np.hstack([X] + inters)
        return Z

# ─────────────────────────────────────────────
# 전체 파이프라인 통합 클래스
# ─────────────────────────────────────────────
class TabularPreprocessor(BaseEstimator, TransformerMixin):
    """Impute → Winsorize → Log1p → Scale → Interaction"""
    def __init__(self, news_index: Optional[int] = None, topk: int = TOPK_INTERACT):
        self.imputer = SimpleImputer(strategy="median")
        self.winsor = Winsorizer()
        self.log1p = SelectiveLog1p()
        self.scaler = RobustScaler()
        self.news_index = news_index
        self.interact = None
        self.n_features_out_ = None
        self.topk_idx_ = None
        self.topk = topk

    def fit(self, X, y=None):
        X = self.imputer.fit_transform(X)
        X = self.winsor.fit_transform(X)
        X = self.log1p.fit_transform(X)
        X = self.scaler.fit_transform(X)

        self.interact = InteractionWithSentiment(
            news_index=self.news_index if self.news_index is not None else 0,
            topk=self.topk
        )
        self.interact.fit(X, y=y)
        self.topk_idx_ = self.interact.topk_idx_

        X2 = self.interact.transform(X)
        self.n_features_out_ = X2.shape[1]
        return self

    def transform(self, X):
        X = self.imputer.transform(X)
        X = self.winsor.transform(X)
        X = self.log1p.transform(X)
        X = self.scaler.transform(X)
        X = self.interact.transform(X)
        return X

# ─────────────────────────────────────────────
# 사용 편의 함수
# ─────────────────────────────────────────────
def build_feature_pipeline() -> TabularPreprocessor:
    # config.FEATURE_COLS에서 뉴스 감성 점수 위치 자동 추출
    try:
        news_col_candidates = [c for c in FEATURE_COLS if "sentiment" in c.lower()]
        news_col = news_col_candidates[0]
        news_index = FEATURE_COLS.index(news_col)
    except IndexError:
        print("[WARN] 뉴스 감성 컬럼을 찾을 수 없습니다. 기본 인덱스 0 사용.")
        news_index = 0

    return TabularPreprocessor(news_index=news_index, topk=TOPK_INTERACT)