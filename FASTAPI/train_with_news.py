# ================================
# train_with_news.py (자동 학습 + 모델 저장)
# ================================
import os
import time
import html
import requests
import pandas as pd
import numpy as np
from datetime import datetime, timezone
from urllib.parse import urlparse
from typing import List, Dict, Tuple
from dotenv import load_dotenv

from sklearn.model_selection import train_test_split
from sklearn.preprocessing import LabelEncoder
from sklearn.metrics import accuracy_score, classification_report
import xgboost as xgb
import joblib

# ----------- 설정 -----------
COMPANY_COL = "company_name"
TARGET_COL = "credit_ratings"

# ----------- 유틸 함수 -----------
def clean_text(t):
    if not t:
        return ""
    return html.unescape(t.replace("<b>", "").replace("</b>", "").strip())

def parse_pubdate(pubdate_str):
    try:
        return datetime.strptime(pubdate_str, "%a, %d %b %Y %H:%M:%S %z")
    except Exception:
        return datetime.now(timezone.utc)

def recency_weight(pub_dt, now):
    delta_days = max(0.0, (now - pub_dt).total_seconds() / 86400.0)
    return 0.5 ** (delta_days / 15.0)

def source_weight(host):
    return 1.0

def weighted_aggregate(results, weights):
    if not results: 
        return {"POSITIVE":0,"NEGATIVE":0,"NEUTRAL":0}
    w = np.clip(np.array(weights), 1e-6, None)
    pos = np.average([r["POSITIVE"] for r in results], weights=w)
    neg = np.average([r["NEGATIVE"] for r in results], weights=w)
    neu = np.average([r["NEUTRAL"] for r in results], weights=w)
    return {"POSITIVE": round(pos,4), "NEGATIVE": round(neg,4), "NEUTRAL": round(neu,4)}

def credit_signal(score):
    return round(100.0 * (score.get("POSITIVE",0) - score.get("NEGATIVE",0)), 2)


# ----------- 머신러닝 파이프라인 -----------
def train_and_eval(train_df: pd.DataFrame, target_col: str = TARGET_COL):
    """
    뉴스 기반 피처로 XGBoost 신용등급 예측 모델 학습
    """
    # 🔹 학습에 사용할 피처 목록 (뉴스 기반)
    features = [
        "news_sentiment_score",
        "news_count",
        "positive_ratio",
        "negative_ratio",
        "sentiment_volatility",
        "recency_weight_mean"
    ]

    # 데이터 유효성 검증
    for f in features:
        if f not in train_df.columns:
            raise ValueError(f"필요한 피처 '{f}'가 데이터에 없습니다. stock_augmented.xlsx를 확인하세요.")

    if target_col not in train_df.columns:
        raise ValueError(f"타깃 열 '{target_col}'이 데이터에 없습니다.")

    y = train_df[target_col]
    X = train_df[features]
    feature_cols = X.columns  # 🔹 학습에 사용된 컬럼명 저장

    # 타깃 인코딩
    le = LabelEncoder()
    y_enc = le.fit_transform(y)

    # 학습/테스트 분리 (라벨이 1개인 경우 예외처리)
    try:
        X_train, X_test, y_train, y_test = train_test_split(
            X, y_enc, test_size=0.2, random_state=42, stratify=y_enc
        )
    except ValueError as e:
        print(f"[WARN] stratify 불가: {e}")
        X_train, X_test, y_train, y_test = train_test_split(
            X, y_enc, test_size=0.2, random_state=42
        )

    # XGBoost 모델 정의
    model = xgb.XGBClassifier(
        objective="multi:softmax",
        num_class=len(le.classes_),
        eval_metric="mlogloss",
        use_label_encoder=False,
        random_state=42
    )

    # 모델 학습
    print("\n--- XGBoost 모델 학습 중 ---")
    model.fit(X_train, y_train)
    print("--- 학습 완료 ---")

    # 평가
    y_pred = model.predict(X_test)
    acc = accuracy_score(y_test, y_pred)
    print(f"\n✅ 모델 정확도: {acc * 100:.2f}%")
    print("\n--- 상세 평가 리포트 ---")
    print(classification_report(y_test, y_pred, target_names=le.classes_))

    return model, le, feature_cols


def main(train_path="stock_augmented.xlsx"):
    load_dotenv()

    # 경로 확인
    if not os.path.exists(train_path):
        raise FileNotFoundError(f"{train_path} 파일을 찾을 수 없습니다.")

    # 데이터 로드
    if train_path.endswith(".xlsx"):
        df = pd.read_excel(train_path)
    else:
        df = pd.read_csv(train_path)

    print(f"📊 데이터 로드 완료: {df.shape[0]}개 샘플, {df.shape[1]}개 컬럼")

    # 모델 학습
    model, le, feature_cols = train_and_eval(df)

    # 모델 저장
    joblib.dump(model, "xgb_credit_model.pkl")
    joblib.dump(le, "label_encoder.pkl")
    joblib.dump(feature_cols, "xgb_feature_columns.pkl")

    print("\n✅ 모델 및 feature 컬럼 저장 완료:")
    print(" - xgb_credit_model.pkl")
    print(" - label_encoder.pkl")
    print(" - xgb_feature_columns.pkl")


if __name__ == "__main__":
    main()
