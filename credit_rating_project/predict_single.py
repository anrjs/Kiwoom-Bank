# -*- coding: utf-8 -*-
import os
import json
import joblib
import numpy as np
import pandas as pd
from src.data_utils import _to_float_from_percent
from src.config import NUMERIC_PERCENT_COLS, FEATURE_COLS, ARTIFACTS_DIR

def prepare_input(df: pd.DataFrame) -> pd.DataFrame:
    """ 퍼센트 → 수치 변환 후, feature column만 추출 """
    for col in NUMERIC_PERCENT_COLS:
        if col in df.columns:
            df[col] = df[col].map(_to_float_from_percent)
    return df[FEATURE_COLS].copy()

def load_label_mapping(path: str) -> dict:
    with open(path, "r", encoding="utf-8") as f:
        mp = json.load(f)
    return {int(k): v for k, v in mp["id2label"].items()}

def predict(input_path: str, output_path: str):
    # 입력 데이터 로드 (확장자에 따라 처리)
    if input_path.endswith(".csv"):
        df = pd.read_csv(input_path)
    else:
        df = pd.read_excel(input_path)

    X = prepare_input(df)

    # 모델 및 전처리기 로드
    bundle = joblib.load(os.path.join(ARTIFACTS_DIR, "model.joblib"))
    preprocessor = bundle["preprocessor"]
    model = bundle["model"]

    # 라벨 매핑 로드
    id2label = load_label_mapping(os.path.join(ARTIFACTS_DIR, "label_mapping.json"))

    # 예측
    X_transformed = preprocessor.transform(X)
    y_pred_reg = model.predict(X_transformed)
    y_pred_notch = np.clip(np.round(y_pred_reg), 0, len(id2label)-1).astype(int)
    y_pred_label = [id2label[n] for n in y_pred_notch]

    # 결과 출력
    df_result = df.copy()
    df_result["predicted_notch"] = y_pred_notch
    df_result["predicted_label"] = y_pred_label

    # CLI 출력 요약
    print("\n📊 예측 결과 (상위 피처 포함):")
    show_col = "stock_code" if "stock_code" in df.columns else df.columns[0]
    for i in range(len(df)):
        features = ", ".join([f"{col}={df[col].iloc[i]:.3f}" for col in FEATURE_COLS if col in df.columns])
        print(f"{df_result[show_col].iloc[i]} → 예측 등급: {y_pred_label[i]} | 주요 피처: {features}")

    # 저장
    os.makedirs(os.path.dirname(output_path), exist_ok=True)
    df_result.to_excel(output_path, index=False)
    print(f"\n✅ 예측 결과 저장됨: {output_path}")

def main():
    # comp_features 폴더는 상위 디렉토리 위치
    comp_features_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "comp_features"))
    
    csv_files = [f for f in os.listdir(comp_features_dir) if f.endswith(".csv")]
    
    if not csv_files:
        print("❌ 'comp_features' 폴더에 CSV 파일이 없습니다.")
        return

    first_csv_path = os.path.join(comp_features_dir, csv_files[0])
    output_path = os.path.join(ARTIFACTS_DIR, "first_csv_predictions.xlsx")

    print(f"📂 입력 파일: {first_csv_path}")
    predict(first_csv_path, output_path)

if __name__ == "__main__":
    main()
