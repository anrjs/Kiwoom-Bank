# -*- coding: utf-8 -*-
"""
Non-financial scoring package (DART-based).
Exposes:
- extract_non_financial_core
- evaluate_company, classify_industry
"""
from .non_financial_extractor import extract_non_financial_core
from .industry_credit_model import evaluate_company, classify_industry
