# =========================
# server.py
# FastAPI + train_with_news + FinBERT 기반 실시간 분석 서버
# =========================
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
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

from openai import OpenAI
from transformers import pipeline
import joblib
import torch

# ---------- 설정 ----------
COMPANY_COL = "company_name"
FINBERT_MODEL = "yiyanghkust/finbert-tone"
OPENAI_MODEL = "gpt-4o-mini"
NEWS_PER_PAGE = 30
MAX_PAGES = 1
REQUEST_TIMEOUT = 10
SLEEP_BETWEEN_CALLS = 0.2
RECENCY_HALF_LIFE_DAYS = 15
SOURCE_WEIGHT = {
    "www.hankyung.com": 1.2,
    "www.yonhapnews.co.kr": 1.2,
    "www.mk.co.kr": 1.1,
}

# ---------- FastAPI ----------
app = FastAPI(title="AI Credit Risk API")
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # React 3000 포트 허용
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ---------- 환경 로드 ----------
load_dotenv()
openai_key = os.getenv("OPENAI_API_KEY")
if not openai_key:
    raise RuntimeError("❌ OPENAI_API_KEY 환경변수가 필요합니다 (.env 확인).")
client = OpenAI(api_key=openai_key)

# ---------- FinBERT 초기화 ----------
device = 0 if torch.cuda.is_available() else -1
print(f"[INFO] FinBERT Device: {'GPU' if device == 0 else 'CPU'}")
finbert = pipeline("text-classification", model=FINBERT_MODEL, top_k=None, device=device)

# ---------- XGBoost 모델 로드 ----------
try:
    xgb_model = joblib.load("xgb_credit_model.pkl")
    label_encoder = joblib.load("label_encoder.pkl")
    eature_cols = joblib.load("xgb_feature_columns.pkl")
    print("[INFO] ✅ XGBoost 모델 및 라벨 인코더 로드 완료")
except Exception as e:
    print(f"[WARN] ⚠️ 모델 파일을 찾을 수 없습니다: {e}")
    xgb_model, label_encoder, feature_cols = None, None, None

# ---------- 유틸 ----------
def clean_text(t: str):
    if not t:
        return ""
    return html.unescape(t.replace("<b>", "").replace("</b>", "").strip())

def parse_pubdate(pubdate_str: str) -> datetime:
    try:
        return datetime.strptime(pubdate_str, "%a, %d %b %Y %H:%M:%S %z")
    except Exception:
        return datetime.now(timezone.utc)

def recency_weight(pub_dt, now):
    delta_days = max(0.0, (now - pub_dt).total_seconds() / 86400.0)
    return 0.5 ** (delta_days / float(RECENCY_HALF_LIFE_DAYS))

def source_weight(host):
    return SOURCE_WEIGHT.get(host, 1.0)

def build_inputs(items: List[Dict]) -> Tuple[List[str], List[float]]:
    now = datetime.now(timezone.utc)
    texts, weights = [], []
    for it in items:
        title = clean_text(it.get("title", ""))
        desc = clean_text(it.get("description", ""))
        text = (title + " " + desc).strip()
        if not text:
            continue
        pub = parse_pubdate(it.get("pubDate", ""))
        w = recency_weight(pub, now) * source_weight(urlparse(it.get("link", "")).netloc)
        texts.append(text)
        weights.append(w)
    return texts, weights

def weighted_aggregate(results, weights):
    if not results:
        return {"POSITIVE": 0.0, "NEGATIVE": 0.0, "NEUTRAL": 0.0}
    w = np.clip(np.array(weights if weights else [1.0]*len(results)), 1e-6, None)
    pos = np.average([r["POSITIVE"] for r in results], weights=w)
    neg = np.average([r["NEGATIVE"] for r in results], weights=w)
    neu = np.average([r["NEUTRAL"] for r in results], weights=w)
    return {"POSITIVE": round(pos, 4), "NEGATIVE": round(neg, 4), "NEUTRAL": round(neu, 4)}

def credit_signal(score):
    return round(100.0 * (score.get("POSITIVE", 0.0) - score.get("NEGATIVE", 0.0)), 2)

# ---------- 외부 API ----------
def get_naver_news(query: str, display=NEWS_PER_PAGE, start=1) -> List[Dict]:
    headers = {
        "X-Naver-Client-Id": os.getenv("NAVER_CLIENT_ID", ""),
        "X-Naver-Client-Secret": os.getenv("NAVER_CLIENT_SECRET", ""),
    }
    params = {"query": query, "display": display, "start": start, "sort": "sim"}
    r = requests.get("https://openapi.naver.com/v1/search/news.json",
                     headers=headers, params=params, timeout=REQUEST_TIMEOUT)
    r.raise_for_status()
    return r.json().get("items", [])

def collect_news_for_company(name: str):
    all_items = []
    start = 1
    for _ in range(MAX_PAGES):
        items = get_naver_news(f"\"{name}\"", display=NEWS_PER_PAGE, start=start)
        if not items:
            break
        all_items.extend(items)
        start += NEWS_PER_PAGE
        time.sleep(SLEEP_BETWEEN_CALLS)
    seen, unique = set(), []
    for it in all_items:
        title = clean_text(it["title"])
        host = urlparse(it.get("link", "")).netloc
        if (title, host) in seen:
            continue
        seen.add((title, host))
        unique.append(it)
    return unique

# ---------- 번역 ----------
def translate_openai(texts: List[str], client: OpenAI):
    out = []
    for t in texts:
        try:
            resp = client.responses.create(
                model=OPENAI_MODEL,
                temperature=0.0,
                input=[
                    {"role": "system", "content": "Translate Korean financial news into English clearly."},
                    {"role": "user", "content": t},
                ],
            )
            out.append(resp.output_text.strip())
        except Exception as e:
            print(f"[WARN] translation failed: {e}")
            out.append(t)
    return out

# ---------- FinBERT 감성 분석 ----------
def finbert_scores(texts, finbert):
    outputs = finbert(texts)
    LABEL_MAP = {"positive": "POSITIVE", "negative": "NEGATIVE", "neutral": "NEUTRAL"}
    results = []
    for scores in outputs:
        d = {"POSITIVE": 0.0, "NEGATIVE": 0.0, "NEUTRAL": 0.0}
        for s in scores:
            lab = LABEL_MAP.get(s["label"].lower())
            if lab:
                d[lab] = float(s["score"])
        results.append(d)
    return results

# ---------- 요청 모델 ----------
class CompanyRequest(BaseModel):
    company_name: str

# ---------- API 엔드포인트 ----------
@app.post("/analyze")
def analyze_company_api(req: CompanyRequest):
    """React에서 기업명을 받아 FinBERT + XGBoost 모델로 등급 예측"""
    name = req.company_name
    print(f"[INFO] Analyzing {name}...")

    # 1️⃣ 뉴스 수집
    items = collect_news_for_company(name)
    texts, weights = build_inputs(items)
    if not texts:
        return {"company": name, "predicted_grade": "데이터 부족"}

    # 2️⃣ 번역 + 감성 분석
    en_texts = translate_openai(texts, client)
    results = finbert_scores(en_texts, finbert)

    # 3️⃣ 감성 지표 계산
    agg = weighted_aggregate(results, weights)
    signal = credit_signal(agg)

    # 4️⃣ 피처 구성
    features = {
        "news_sentiment_score": signal,
        "news_count": len(texts),
        "positive_ratio": np.mean([r["POSITIVE"] for r in results]),
        "negative_ratio": np.mean([r["NEGATIVE"] for r in results]),
        "sentiment_volatility": np.std([r["POSITIVE"] - r["NEGATIVE"] for r in results]),
        "recency_weight_mean": np.mean(weights) if weights else 0
    }
    df_features = pd.DataFrame([features])

# 5️⃣ XGBoost 예측
    if xgb_model and label_encoder:
        try:
            # ✅ feature_cols 로드되어 있다면 (학습 당시 컬럼 구조)
            if "feature_cols" in globals() and feature_cols is not None:
                # feature_cols 순서에 맞게 정렬, 누락된 컬럼은 0으로 채움
                df_features = df_features.reindex(columns=feature_cols, fill_value=0)

            # ✅ 예측 수행
            pred = xgb_model.predict(df_features)[0]
            grade = label_encoder.inverse_transform([pred])[0]
        except Exception as e:
            print(f"[WARN] 모델 예측 실패: {e}")
            grade = "예측 오류"
    else:
        grade = "모델 없음"

    # 6️⃣ 결과 반환
    return {
        "company": name,
        "news_sentiment_score": signal,
        "news_count": len(texts),
        "agg": agg,
        "predicted_grade": grade,
    }

# ---------- Root ----------
@app.get("/")
def root():
    return {"message": "✅ AI Credit Risk API is running"}

