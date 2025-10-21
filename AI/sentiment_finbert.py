# sentiment_finbert.py
import os
import time
from typing import List, Dict
import numpy as np
from transformers import pipeline
from openai import OpenAI

from config import FINBERT_MODEL, OPENAI_TRANSLATE_MODEL, OPENAI_TRANSLATE_TEMPERATURE, OPENAI_TRANSLATE_BATCH

# --- OpenAI 클라이언트 초기화 ---
_oai = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))

# --- OpenAI 번역 함수 ---
def translate_ko_en_openai(texts: List[str]) -> List[str]:
    """
    한국어 문장 리스트 -> 영어 번역 리스트 (OpenAI Responses API)
    - 온도 0, 포맷: 번역문만
    - 배치/재시도 포함
    """
    if not texts:
        return []

    out: List[str] = []
    B = int(OPENAI_TRANSLATE_BATCH or 20)

    # 프롬프트(번역 가이드라인): 용어 보존, 숫자/기호 원형 유지 등
    system_prompt = (
        "You are a professional financial news translator. "
        "Translate Korean to natural, newsroom-style English. "
        "Preserve entities, figures, and tickers precisely. "
        "Return ONLY the translated sentence without any extra words or quotes."
    )

    for i in range(0, len(texts), B):
        batch = texts[i:i+B]
        # 개별 호출(안전) – 실패시 재시도
        for t in batch:
            retries = 3
            backoff = 1.5
            while True:
                try:
                    resp = _oai.responses.create(
                        model=OPENAI_TRANSLATE_MODEL,
                        temperature=OPENAI_TRANSLATE_TEMPERATURE,
                        # 단순 텍스트 입력
                        input=[
                            {"role": "system", "content": system_prompt},
                            {"role": "user", "content": f"KR: {t}\nEN:"}
                        ],
                    )
                    translated = resp.output_text.strip()
                    out.append(translated)
                    break
                except Exception as e:
                    retries -= 1
                    if retries <= 0:
                        # 실패한 건은 원문을 그대로 넣어두면 다운스트림에서라도 처리 가능
                        out.append(t)
                        print(f"[WARN] OpenAI translate failed. Fallback original. err={e}")
                        break
                    time.sleep(backoff)
                    backoff *= 2

    return out

# --- FinBERT 분류기 (PyTorch 2.6+ CPU 설치 필수; .bin 로드 정책 때문) ---
finbert = pipeline("text-classification", model=FINBERT_MODEL, top_k=None)

LABEL_MAP = {"positive": "POSITIVE", "negative": "NEGATIVE", "neutral": "NEUTRAL"}

def analyze_texts_ko(texts: List[str]) -> List[Dict[str, float]]:
    if not texts:
        return []
    # ★ 번역 단계: OpenAI 사용
    en_texts = translate_ko_en_openai(texts)

    outputs = finbert(en_texts)  # 각 문장마다 [ {label, score} x3 ]
    results = []
    for scores in outputs:
        d = {"POSITIVE": 0.0, "NEGATIVE": 0.0, "NEUTRAL": 0.0}
        for s in scores:
            lab = LABEL_MAP.get(s["label"].lower())
            if lab:
                d[lab] = float(s["score"])
        results.append(d)
    return results

def weighted_aggregate(results: List[Dict[str, float]], weights: List[float]) -> Dict[str, float]:
    if not results:
        return {"POSITIVE": 0.0, "NEGATIVE": 0.0, "NEUTRAL": 0.0}
    w = np.array(weights if weights else [1.0]*len(results), dtype=float)
    w = np.clip(w, 1e-6, None)
    pos = np.average([r["POSITIVE"] for r in results], weights=w)
    neg = np.average([r["NEGATIVE"] for r in results], weights=w)
    neu = np.average([r["NEUTRAL"] for r in results], weights=w)
    return {"POSITIVE": round(pos,4), "NEGATIVE": round(neg,4), "NEUTRAL": round(neu,4)}
