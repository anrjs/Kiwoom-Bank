import os
from dotenv import load_dotenv


load_dotenv()


NAVER_CLIENT_ID = os.getenv("NAVER_CLIENT_ID")
NAVER_CLIENT_SECRET = os.getenv("NAVER_CLIENT_SECRET")


# 모델 이름
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
OPENAI_TRANSLATE_MODEL = "gpt-4o-mini"   # 또는 "gpt-4o" / "gpt-5" 등
OPENAI_TRANSLATE_TEMPERATURE = 0.0       # 번역은 결정적 출력이 좋아요
OPENAI_TRANSLATE_BATCH = 20              # 한번에 보낼 문장 수(안전한 기본)
FINBERT_MODEL = "yiyanghkust/finbert-tone" # 3-class: positive/negative/neutral


# 분석 기본 설정
REQUEST_TIMEOUT = 10
NEWS_PER_PAGE = 50
MAX_PAGES = 2
SLEEP_BETWEEN_CALLS = 0.2
NEUTRAL_FLOOR = 0.0 # 필요시 최소 중립 비율 바닥치
RECENCY_HALF_LIFE_DAYS = 15 # 최근성 가중치 반감기(일)
SOURCE_WEIGHT = {
# 도메인별 가중치 (예시). 기본 1.0, 신뢰도 높은 매체를 1.1~1.3 정도로 가중
"www.hankyung.com": 1.2,
"www.yonhapnews.co.kr": 1.2,
"www.mk.co.kr": 1.1,
}