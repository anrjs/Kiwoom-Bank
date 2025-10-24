# -*- coding: utf-8 -*-
import argparse
import pandas as pd
import numpy as np
import joblib
import json
import os
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

def main(args):
    # 입력 데이터 로드
    df = pd.read_excel(args.input)
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
    print("\n📊 예측 결과:")
    show_col = "stock_code" if "stock_code" in df.columns else df.columns[0]
    for i in range(len(df)):
        print(f"{df_result[show_col].iloc[i]} → 예측 등급: {y_pred_label[i]}")

    # 저장
    os.makedirs(os.path.dirname(args.output), exist_ok=True)
    df_result.to_excel(args.output, index=False)
    print(f"\n✅ 예측 결과 저장됨: {args.output}")

if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--input", type=str, default="data/sample_dataset.xlsx", help="예측할 엑셀 파일 경로")
    parser.add_argument("--output", type=str, default=os.path.join(ARTIFACTS_DIR, "predictions.xlsx"), help="결과 저장 경로")
    args = parser.parse_args()
    main(args)