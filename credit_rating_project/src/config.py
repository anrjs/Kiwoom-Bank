# -*- coding: utf-8 -*-

# 📌 실제 데이터 경로 설정 (파일 or 폴더)
DATA_PATH = "data/real_dataset.xlsx"

# 📌 결과물 저장 폴더
ARTIFACTS_DIR = "artifacts_signal"

# 📌 컬럼 정의
ID_COL = "회사명"  # real_dataset의 첫 번째 열 이름
TARGET_COL = "public_credit_rating"  # ✅ 실제 신용등급 컬럼명으로 수정

# 퍼센트 문자열로 된 컬럼
NUMERIC_PERCENT_COLS = [
    "debt_ratio",
    "current_ratio",
    "quick_ratio",
    "roa",
    "total_asset_growth_rate"
]

# 수치형 컬럼 (이미 숫자 타입)
NUMERIC_COLS = [
    "cfo_to_total_debt",
    "news_sentiment_score",
    "news_count",
    "sentiment_volatility",
    "positive_ratio",
    "negative_ratio",
    "recency_weight_mean",
    "business_report_text_score"  # ✅ 새로 추가된 비정형 점수
]

# 전체 피처 컬럼
FEATURE_COLS = NUMERIC_PERCENT_COLS + NUMERIC_COLS

# 신용등급 정렬(국제/국내 혼용 표기를 최대한 커버)
# 'AA0' 같은 국내 표기는 'AA'로 정규화됩니다.
RATING_ORDER = [
    "AAA","AA+","AA","AA-",
    "A+","A","A-",
    "BBB+","BBB","BBB-",
    "BB+","BB","BB-",
    "B+","B","B-",
    "CCC+","CCC","CCC-",
    "CC","C","D"
]

# winsorization 백분위수
WINSOR_LO = 0.01
WINSOR_HI = 0.99

# 상호작용을 만들 상위 상관 피처 개수 (news_sentiment 기준)
TOPK_INTERACT = 5

# permutation importance에서 계산할 상위 피처 수
TOPN_IMPORTANCE = 40

# 평가에 사용할 최소 클래스 개수 미만이면 경고
MIN_CLASSES_FOR_QWK = 3

# 교차검증 fold 수
CV_FOLDS = 5

# 재현성을 위한 랜덤시드
RANDOM_SEED = 42

# 클래스 불균형 시 사용
USE_CLASS_WEIGHTS = True

# ============================================
# 데이터 증폭 관련 설정 (Augmentation Settings)
# ============================================
AUG_ENABLED = True
AUG_TARGET_PER_CLASS = 30
AUG_MAX_SYNTHETIC_RATIO = 1.5
AUG_MIXUP_ALPHA = 0.4
AUG_MIXUP_RATIO = 0.6
AUG_JITTER_SCALE = 0.10
AUG_LO = 0.005
AUG_HI = 0.995
AUG_SEED = 42

# ============================================
# CatBoost 단조 제약 (Monotonic Constraints)
# ============================================
MONOTONE_SIGNS = {
    "debt_ratio": +1,
    "current_ratio": -1,
    "quick_ratio": -1,
    "cfo_to_total_debt": -1,
    "roa": -1,
    "total_asset_growth_rate": 0,
    "news_sentiment_score": -1,
    "news_count": 0,
    "sentiment_volatility": +1,
    "positive_ratio": -1,
    "negative_ratio": +1,
    "recency_weight_mean": -1,
    "business_report_text_score": -1  # ✅ 새로 추가
}