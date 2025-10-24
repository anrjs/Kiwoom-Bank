# Credit Rating Modeling Pipeline (Tabular + News Sentiment)

본 프로젝트는 다음과 같은 데이터를 가정합니다.

- **A열**: 기업코드 (issuer id / 기업 식별자)
- **B~T열**: 재무지표 (수치형)
- **U열**: 뉴스 감성 점수 `news_sentiment` (수치형, -1 ~ 1 또는 0 ~ 1 등 임의 스케일)
- **V열**: 공개 신용등급(문자열, 예: AAA, AA+, AA0, AA-, ... , D)

> 실제 열 이름이 다를 수 있으므로 스크립트가 **자동으로 열을 탐지**합니다.  
> 탐지 규칙: (1) 기업코드: 이름에 '기업코드', 'corp', 'company', 'issuer' 포함 or 첫 번째 열  
> (2) 신용등급: 이름에 '등급' 또는 'rating' 포함 or 마지막 열  
> (3) 뉴스 스코어: 이름에 'news' 또는 'sentiment' 포함 or 등급 직전 열

## 실행 방법

```bash
# 1) 가상환경(선택)
python -m venv .venv
source .venv/bin/activate  # Windows: .venv\Scripts\activate

# 2) 의존성 설치
pip install -r requirements.txt

# 3) 학습 실행
python -m src.train --input /mnt/data/stock.xlsx --output_dir artifacts --fast
# 또는
python -m src.train --input data/stock.xlsx --output_dir artifacts
```

- `--fast` 옵션은 permutation importance 등 시간이 오래 걸리는 단계를 생략/축소합니다.
- 학습 결과는 `artifacts/` 아래에 저장됩니다.
  - `model.joblib`: 학습된 파이프라인(전처리+모델)
  - `label_mapping.json`: 등급 ↔ 노치 매핑 정보
  - `metrics.json`: 평가 지표(QWK, MAE(노치), Macro/Weighted F1 등)
  - `confusion_matrix.png`: 혼동행렬 이미지
  - `feature_importance.csv`: permutation importance 결과(상위 n개)
  - `feature_columns.json`: 사용된 컬럼 목록(원본/파생)

## 모델 개요

- **문제정의**: 순서형(Ordinal) 레이블(신용등급)을 **노치(정수)** 로 매핑하여
  **HistGradientBoostingRegressor(absolute_error)** 로 학습 → 예측값을 반올림해 등급 복원.
  이렇게 하면 **한 노치 오차 < 여러 노치 오차** 를 자연스럽게 최소화합니다.
- **클래스 불균형 보정**: 훈련 데이터에서 등급 분포로 **class weight**를 계산하여 **sample_weight** 로 사용.
- **피처 엔지니어링**:
  - 결측치 **중앙값 대치**, **Winsorization(1%/99%)**, **RobustScaler**
  - `news_sentiment`와 상위 상관 피처 간 **상호작용(term)** 자동 생성
  - (양수인 열에 한해) **log1p 변환**
- **평가 지표**: Quadratic Weighted Kappa(QWK), 노치 MAE, Macro/Weighted F1, Balanced Accuracy 등.

## 데이터 주의

- `NR`/`NA`/`WD` 등 **유효하지 않은 등급**은 제외됩니다.
- 등급 문자열은 `AA0` → `AA` 처럼 **정규화** 됩니다. (국내 표기 지원)
- 기업별 중복/시계열 데이터가 있을 경우 **그룹-스트라타 파티션**으로 홀드아웃을 구성합니다.

## 재현성

- `--seed`로 난수 시드를 제어할 수 있습니다(기본 42).
