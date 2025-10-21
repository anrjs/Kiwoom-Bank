def credit_signal(score: dict) -> float:
    """간단 지표 예시: (pos - neg) * 100. 필요 시 가중/비선형 변환.
    score 예: {"POSITIVE":0.42,"NEGATIVE":0.31,"NEUTRAL":0.27}
    """
    return round(100.0 * (score.get("POSITIVE",0.0) - score.get("NEGATIVE",0.0)), 2)