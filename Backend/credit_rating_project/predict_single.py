# -*- coding: utf-8 -*-
import os
import json
import argparse
import joblib
import numpy as np
import pandas as pd

from src.data_utils import _to_float_from_percent
from src.config import NUMERIC_PERCENT_COLS, FEATURE_COLS, ARTIFACTS_DIR

def _safe_read_csv(path: str) -> pd.DataFrame:
    """
    comp_features에서 저장된 CSV는 보통 회사명이 인덱스로 들어가므로
    index_col=0로 먼저 시도. 실패 시 일반 read_csv로 재시도.
    """
    try:
        df = pd.read_csv(path, index_col=0, encoding="utf-8-sig")
        # 인덱스가 회사명이라면 열로 올려주기
        if df.index.name is None:
            df.index.name = "company"
        df = df.reset_index().rename(columns={"index": "company"})
        return df
    except Exception:
        # fallback
        return pd.read_csv(path, encoding="utf-8-sig")

def prepare_input(df: pd.DataFrame) -> pd.DataFrame:
    """퍼센트 → 수치 변환 후, FEATURE_COLS를 모두 갖춘 프레임 생성(누락은 NaN)"""
    working = df.copy()
    for col in NUMERIC_PERCENT_COLS:
        if col in working.columns:
            working[col] = working[col].map(_to_float_from_percent)

    # 누락 컬럼은 NaN으로 채워서 파이프라인(SimpleImputer 등)이 처리하게 함
    for col in FEATURE_COLS:
        if col not in working.columns:
            working[col] = np.nan

    # 컬럼 순서 고정
    return working.reindex(columns=FEATURE_COLS)

def load_label_mapping(path: str) -> dict:
    with open(path, "r", encoding="utf-8") as f:
        mp = json.load(f)
    return {int(k): v for k, v in mp["id2label"].items()}

def predict(input_path: str, output_path: str):
    # 입력 데이터 로드
    if input_path.lower().endswith(".csv"):
        df = _safe_read_csv(input_path)
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
    y_pred_notch = np.clip(np.round(y_pred_reg), 0, len(id2label) - 1).astype(int)
    y_pred_label = [id2label[n] for n in y_pred_notch]

    # 결과 합치기
    df_result = df.copy()
    df_result["predicted_notch"] = y_pred_notch
    df_result["predicted_label"] = y_pred_label

    # CLI 요약 출력
    print("\n📊 예측 결과:")
    show_col = "company" if "company" in df_result.columns else (df_result.columns[0] if len(df_result.columns) else "row")
    for i in range(len(df_result)):
        name = df_result.iloc[i][show_col] if show_col in df_result.columns else f"row_{i}"
        print(f"- {name} → 예측 등급: {y_pred_label[i]} (notch={int(y_pred_notch[i])}, score={float(y_pred_reg[i]):.3f})")

    # 저장
    os.makedirs(os.path.dirname(output_path), exist_ok=True)
    df_result.to_excel(output_path, index=False)
    print(f"\n✅ 예측 결과 저장됨: {output_path}")

def _sanitize_company_name(company: str) -> str:
    return company.replace("/", "_").replace("\\", "_")

def _find_latest_csv(comp_features_dir: str, company: str | None) -> str:
    """
    - company가 주어지면 '{safe}_*.csv' 중 수정시간(mtime) 최신 파일 선택
    - 아니면 디렉토리 내 전체 CSV 중 mtime 최신 선택
    """
    all_csv = [f for f in os.listdir(comp_features_dir) if f.lower().endswith(".csv")]
    if not all_csv:
        raise FileNotFoundError("❌ 'comp_features' 폴더에 CSV 파일이 없습니다.")

    if company:
        safe = _sanitize_company_name(company)
        cand = [f for f in all_csv if f.startswith(f"{safe}_")]
        if not cand:
            raise FileNotFoundError(f"❌ company='{company}'(safe='{safe}') 에 해당하는 CSV가 없습니다.")
        latest = max(cand, key=lambda f: os.path.getmtime(os.path.join(comp_features_dir, f)))
    else:
        latest = max(all_csv, key=lambda f: os.path.getmtime(os.path.join(comp_features_dir, f)))

    return os.path.join(comp_features_dir, latest)

def main():
    parser = argparse.ArgumentParser(description="Predict credit label from latest comp_features CSV.")
    parser.add_argument("--company", "-c", type=str, default=None, help="특정 회사명만 대상으로 최신 CSV 선택 (예: 삼성전자)")
    args = parser.parse_args()

    # comp_features 폴더는 상위 디렉토리(프로젝트 루트) 위치
    comp_features_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "comp_features"))

    latest_csv_path = _find_latest_csv(comp_features_dir, args.company)
    output_path = os.path.join(ARTIFACTS_DIR, "latest_csv_predictions.xlsx")

    print(f"📂 선택된 CSV 파일: {latest_csv_path}")
    predict(latest_csv_path, output_path)

if __name__ == "__main__":
    main()
