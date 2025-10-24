# news_analytics/config.py
from __future__ import annotations
import os
from dataclasses import dataclass

@dataclass(frozen=True)
class Settings:
    # NAVER Open API
    NAVER_CLIENT_ID: str | None = os.getenv("NAVER_CLIENT_ID")
    NAVER_CLIENT_SECRET: str | None = os.getenv("NAVER_CLIENT_SECRET")

    # 요청/제한 기본값
    REQUEST_TIMEOUT: int = int(os.getenv("NEWS_REQUEST_TIMEOUT", "15"))
    SLEEP_BETWEEN_CALLS: float = float(os.getenv("NEWS_SLEEP_BETWEEN_CALLS", "0.2"))
    NEWS_PER_PAGE: int = int(os.getenv("NEWS_PER_PAGE", "20"))

    # 감성분석 모델/번역
    FINBERT_MODEL: str = os.getenv("FINBERT_MODEL", "yiyanghkust/finbert-tone")
    OPENAI_API_KEY: str | None = os.getenv("OPENAI_API_KEY")
    OPENAI_TRANSLATE_MODEL: str = os.getenv("OPENAI_TRANSLATE_MODEL", "gpt-4o-mini")
    OPENAI_TRANSLATE_TEMPERATURE: float = float(os.getenv("OPENAI_TRANSLATE_TEMPERATURE", "0.0"))
    OPENAI_TRANSLATE_BATCH: int = int(os.getenv("OPENAI_TRANSLATE_BATCH", "20"))

    # 가중치/스코어링(필요 시 조정)
    RECENCY_HALF_LIFE_HOURS: float = float(os.getenv("RECENCY_HALF_LIFE_HOURS", "36"))
    POS_WEIGHT: float = float(os.getenv("POS_WEIGHT", "1.0"))
    NEG_WEIGHT: float = float(os.getenv("NEG_WEIGHT", "1.0"))

settings = Settings()

# 단순 import 호환을 위해 개별 이름도 노출
NAVER_CLIENT_ID = settings.NAVER_CLIENT_ID
NAVER_CLIENT_SECRET = settings.NAVER_CLIENT_SECRET
REQUEST_TIMEOUT = settings.REQUEST_TIMEOUT
SLEEP_BETWEEN_CALLS = settings.SLEEP_BETWEEN_CALLS
NEWS_PER_PAGE = settings.NEWS_PER_PAGE
FINBERT_MODEL = settings.FINBERT_MODEL
OPENAI_API_KEY = settings.OPENAI_API_KEY
OPENAI_TRANSLATE_MODEL = settings.OPENAI_TRANSLATE_MODEL
OPENAI_TRANSLATE_TEMPERATURE = settings.OPENAI_TRANSLATE_TEMPERATURE
OPENAI_TRANSLATE_BATCH = settings.OPENAI_TRANSLATE_BATCH
RECENCY_HALF_LIFE_HOURS = settings.RECENCY_HALF_LIFE_HOURS
POS_WEIGHT = settings.POS_WEIGHT
NEG_WEIGHT = settings.NEG_WEIGHT
