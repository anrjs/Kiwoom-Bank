# train_xgb_credit.py
import os
import re
import json
import argparse
import joblib
import numpy as np
import pandas as pd
from typing import List, Dict
from sklearn.model_selection import train_test_split
from sklearn.metrics import classification_report, confusion_matrix
from xgboost import XGBClassifier

# -----------------------------
# 1) 유틸: 컬럼 정리/변환
# -----------------------------
PERCENT_LIKE_COLS_DEFAULT = [
    "debt_ratio","equity_ratio","debt_dependency_ratio",
    "current_ratio","quick_ratio","operating_margin","roa","roe","net_profit_margin",
    "sales_growth_rate","operating_income_growth_rate","total_asset_growth_rate",
]

TIMES_LIKE_COLS_DEFAULT = [
    "interest_coverage_ratio","ebitda_to_total_debt","cfo_to_total_debt",
    "total_asset_turnover","accounts_receivable_turnover","inventory_turnover",
]

def to_float(s):
    """'182.52%' -> 1.8252, 'N/A' -> np.nan, '1,234' -> 1234.0"""
    if pd.isna(s):
        return np.nan
    if isinstance(s, (int, float, np.number)):
        return float(s)
    s = str(s).strip()
    if s.upper() in {"N/A", "NA", "NONE", ""}:
        return np.nan
    s = s.replace(",", "")
    if s.endswith("%"):
        try:
            return float(s[:-1]) / 100.0
        except Exception:
            return np.nan
    try:
        return float(s)
    except Exception:
        return np.nan

def normalize_numeric_columns(df: pd.DataFrame,
                            percent_cols: List[str],
                            times_cols: List[str]) -> pd.DataFrame:
    out = df.copy()
    for c in percent_cols:
        if c in out.columns:
            out[c] = out[c].apply(to_float)
    for c in times_cols:
        if c in out.columns:
            out[c] = out[c].apply(to_float)
    # free_cash_flow는 정수/부호 있는 현금흐름
    if "free_cash_flow" in out.columns:
        out["free_cash_flow"] = out["free_cash_flow"].apply(to_float)
    return out

# -----------------------------
# 2) 한국식 신용등급 정규화/순서 매핑
# -----------------------------
# 한국 표기 관행: A+, A0, A-, BBB+, BBB0, ... (0는 '플랫')
# 등급이 낮을수록 리스크 ↑. 여기선 높은 등급을 큰 값으로 매핑하도록 설계(가독성 상관 없음)
RATING_ORDER = [
    "AAA", "AA+", "AA0", "AA-", "A+", "A0", "A-",
    "BBB+", "BBB0", "BBB-",
    "BB+", "BB0", "BB-",
    "B+", "B0", "B-",
    "CCC+", "CCC0", "CCC-",
    "CC", "C", "D"
]

def normalize_rating_text(s: str) -> str:
    """
    입력 예: ' A A + ', 'AA+', 'AA- ', 'A0', 'BBB0', 'BBB-', 'bbb+', 'Ccc'
    → 표준 포맷으로 정규화 (대문자, 공백/구두점 제거, 0/+, -, 등 유지)
    """
    if s is None:
        return ""
    s = str(s).upper().strip()
    s = re.sub(r"\s+", "", s)
    # 흔한 변형 정리
    s = s.replace("AAO", "AA0").replace("AO", "A0").replace("BBO", "BB0").replace("BBBO", "BBB0")
    s = s.replace("＋", "+").replace("－", "-")
    # KIS/KR/MS 채용 포맷에 흔한 변형들 허용
    return s

RATING_TO_ID: Dict[str, int] = {r: i for i, r in enumerate(RATING_ORDER)}
ID_TO_RATING: Dict[int, str] = {i: r for r, i in RATING_TO_ID.items()}

def encode_ratings(y_raw: pd.Series) -> pd.Series:
    y_norm = y_raw.astype(str).map(normalize_rating_text)
    # 미지정/이상치 필터링: 정해진 체계 밖 등급은 NaN 처리
    y_id = y_norm.map(lambda s: RATING_TO_ID.get(s, np.nan))
    return y_id

# -----------------------------
# 3) 데이터 로드 & 학습
# -----------------------------
def main(args):
    # 엑셀 로드
    df = pd.read_excel(args.excel_path)

    # 타깃 컬럼명
    target_col = args.target_col

    # 숫자 전처리 (퍼센트/배수/N/A 처리)
    df = normalize_numeric_columns(
        df,
        percent_cols=PERCENT_LIKE_COLS_DEFAULT,
        times_cols=TIMES_LIKE_COLS_DEFAULT,
    )

    # 타깃 인코딩
    if target_col not in df.columns:
        raise ValueError(f"[ERROR] target_col '{target_col}' not found in columns: {df.columns.tolist()}")
    y = encode_ratings(df[target_col])

    # 학습용 피처 선택(숫자)
    # - stock_code, 회사명, 날짜/키 등 비수치/식별 컬럼 제외
    drop_like = {target_col, "stock_code", "code", "corp_name", "name", "date", "period", "latest_key"}
    feature_cols = [c for c in df.columns if c not in drop_like]
    # 가능한 것만 숫자로 강제
    X = df[feature_cols].apply(pd.to_numeric, errors="coerce")

    # 피처/타깃 결측 제거(또는 일부만 제거하고 impute 가능)
    data = pd.concat([X, y.rename("__y__")], axis=1)
    # 최소한 타깃은 결측 제거
    data = data.loc[data["__y__"].notna()].copy()
    # 너무 결측이 많은 행 제거(옵션): 여기선 전체 피처 중 70% 이상 NaN이면 제거
    thresh = int(0.3 * (X.shape[1]))  # 남아 있어야 하는 최소 유효피처 수
    data = data.loc[data.drop(columns="__y__").notna().sum(axis=1) >= thresh]

    # 최종 X, y
    y_final = data["__y__"].astype(int)
    X_final = data.drop(columns="__y__")

    # train/valid split (stratified)
    X_tr, X_va, y_tr, y_va = train_test_split(
        X_final, y_final, test_size=args.valid_ratio, random_state=42, stratify=y_final
    )

    # XGBoost 설정
    num_class = len(RATING_ORDER)
    clf = XGBClassifier(
        n_estimators=args.n_estimators,
        max_depth=args.max_depth,
        learning_rate=args.learning_rate,
        subsample=0.9,
        colsample_bytree=0.9,
        reg_lambda=1.0,
        objective="multi:softprob",
        num_class=num_class,
        eval_metric="mlogloss",
        n_jobs=-1,
        random_state=42,
        tree_method="hist",      # GPU 있으면 'gpu_hist'
    )

    # early stopping
    clf.fit(
        X_tr, y_tr,
        eval_set=[(X_va, y_va)],
        verbose=True,
        early_stopping_rounds=args.early_stopping_rounds,
    )

    # 평가
    y_pred = clf.predict(X_va)
    print("\n[Classification Report]")
    print(classification_report(y_va, y_pred, target_names=[ID_TO_RATING[i] for i in sorted(ID_TO_RATING)]))

    print("\n[Confusion Matrix] (rows=true, cols=pred)")
    print(confusion_matrix(y_va, y_pred))

    # 중요도 상위 출력
    importances = pd.Series(clf.feature_importances_, index=X_final.columns).sort_values(ascending=False)
    print("\n[Top 20 Feature Importances]")
    print(importances.head(20))

    # 아티팩트 저장
    os.makedirs(args.out_dir, exist_ok=True)
    model_path = os.path.join(args.out_dir, "xgb_credit_rating.model")
    joblib.dump(clf, model_path)

    mapping_path = os.path.join(args.out_dir, "label_mapping.json")
    with open(mapping_path, "w", encoding="utf-8") as f:
        json.dump({"RATING_ORDER": RATING_ORDER, "RATING_TO_ID": RATING_TO_ID, "ID_TO_RATING": ID_TO_RATING}, f, ensure_ascii=False, indent=2)

    used_cols_path = os.path.join(args.out_dir, "used_feature_columns.txt")
    with open(used_cols_path, "w", encoding="utf-8") as f:
        f.write("\n".join(X_final.columns))

    print(f"\n✅ Saved model to: {model_path}")
    print(f"✅ Saved label mapping to: {mapping_path}")
    print(f"✅ Saved feature columns to: {used_cols_path}")

if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--excel_path", type=str, required=True, help="지표+공개신용등급이 포함된 엑셀 파일 경로")
    parser.add_argument("--target_col", type=str, default="공개신용등급", help="레이블 컬럼명")
    parser.add_argument("--out_dir", type=str, default="./model_out", help="모델/매핑 저장 폴더")
    parser.add_argument("--valid_ratio", type=float, default=0.2)
    parser.add_argument("--n_estimators", type=int, default=1000)
    parser.add_argument("--max_depth", type=int, default=6)
    parser.add_argument("--learning_rate", type=float, default=0.05)
    parser.add_argument("--early_stopping_rounds", type=int, default=50)
    args = parser.parse_args()
    main(args)
