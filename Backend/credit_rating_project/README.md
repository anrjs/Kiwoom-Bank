# Credit Rating Modeling Pipeline (Tabular + News Sentiment)

기업의 재무지표와 뉴스 감성, 비정형 텍스트 점수를 기반으로  
공개 신용등급(AAA~D)을 예측하는 머신러닝 파이프라인입니다.

---

## 📂 데이터 구성 예시 (`real_dataset.xlsx`)

| 열 이름 | 설명 |
|---------|------|
| `회사명` | 기업 이름 |
| `debt_ratio` | 부채비율 |
| `roa` | 총자산이익률 |
| `total_asset_growth_rate` | 자산성장률 |
| `cfo_to_total_debt` | 총부채 대비 영업현금흐름 |
| `current_ratio` | 유동비율 |
| `quick_ratio` | 당좌비율 |
| `news_sentiment_score` | 뉴스 감성 점수 |
| `news_count` | 뉴스 기사 수 |
| `sentiment_volatility` | 뉴스 감성 변동성 |
| `positive_ratio` | 긍정 뉴스 비중 |
| `negative_ratio` | 부정 뉴스 비중 |
| `recency_weight_mean` | 최신성 가중 평균 |
| `business_report_text_score` | 사업보고서 기반 비정형 점수 |
| `public_credit_rating` | 실제 등급 라벨 (예: AAA, AA+, ..., D)

---

## 🚀 실행 방법

### ▶️ Conda 가상환경 기준

```bash
# Conda 환경 생성
conda create -n credit_env python=3.10 -y

# 가상환경 활성화
conda activate credit_env

# 종속성 설치
pip install -r requirements.txt
```

### ▶️ 모델 학습

```bash
# 모델 학습 (real_dataset.xlsx 기준)
python -m src.train --input data/real_dataset.xlsx --output_dir artifacts_signal
```

### ▶️ 예측 실행

```bash
# test_dataset.xlsx 파일에 대해 예측 실행
python predict_single.py
```

- 입력: `data/test_dataset.xlsx`
- 출력: `artifacts_signal/test_predictions.xlsx`
- 주요 피처 및 예측 등급이 CLI에 출력되며, 엑셀로 저장됩니다.

---

## 🧠 모델 개요

- **모델**: CatBoostRegressor 기반 순서형 등급 회귀
- **입력 피처**: 6개 재무지표 + 7개 뉴스 및 비정형 지표
- **출력**: 실수 → 반올림된 노치 → 등급 문자열 복원
- **클래스 불균형 보정**: 등급 빈도 기반 sample weight 사용

---

## 📊 평가 지표

- Quadratic Weighted Kappa (QWK)
- Mean Absolute Error (MAE)
- Macro / Weighted F1-score
- Balanced Accuracy

---

## ⚠️ 데이터 전처리 정책

- `NR`, `NA`, `WD`, `WR` 등 무효 등급 자동 제거
- 등급 표기 정규화: `AA0` → `AA`, `BBB0` → `BBB`
- 수치형 피처 처리:
  - 퍼센트 문자열 변환
  - log1p, winsorization (1%, 99%)
  - RobustScaler 적용
- 일부 피처 간 상호작용 자동 생성
  - 예: `roa × news_sentiment_score`

---

## 📁 학습 결과물 (output_dir 기준)

| 파일명 | 설명 |
|--------|------|
| `model.joblib` | 전처리기 + CatBoost 모델 |
| `label_mapping.json` | 등급 ↔ 노치 매핑 정보 |
| `metrics.json` | QWK, F1, MAE 등 성능 지표 |
| `confusion_matrix.png` | 혼동 행렬 이미지 |
| `feature_columns.json` | 사용된 피처 목록 |
| `test_predictions.xlsx` | 예측 결과 저장 파일

---

## 🔁 재현성

- `--seed` 옵션으로 난수 시드 고정 가능 (기본값: 42)

---

## 📬 유지보수 계획

- 등급 병합 정책 실험  
- FastAPI 서버 연동  
- 프론트엔드 통합 (기업 입력 → 등급 추정)