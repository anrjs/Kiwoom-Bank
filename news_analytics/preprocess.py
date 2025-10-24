# news_analytics/preprocess.py
from __future__ import annotations
import re
from typing import List

_punct_re = re.compile(r"[\[\]\(\)\{\}<>\"'“”‘’]")

def clean_titles(titles: List[str]) -> List[str]:
    """
    간단한 전처리: 괄호/따옴표 제거, 다중 공백 정리
    뉴스 토큰화/불용어 제거가 필요하면 여기서 확장
    """
    out: List[str] = []
    for t in titles:
        s = (t or "").strip()
        s = _punct_re.sub(" ", s)
        s = re.sub(r"\s+", " ", s).strip()
        out.append(s)
    return out
