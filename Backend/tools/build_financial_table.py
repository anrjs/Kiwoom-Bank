"""Utility script to fetch financial statements for multiple companies.

This module demonstrates how to combine the :mod:`kiwoom_finance.dart_client`
helpers (``init_dart``, ``find_corp``, ``extract_fs``) with preprocessing and
metric calculation helpers to build a tabular view of the latest financial
metrics for several companies.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable, List, Optional

import pandas as pd

from kiwoom_finance.dart_client import init_dart, find_corp, extract_fs
from kiwoom_finance.preprocess import preprocess_all
from kiwoom_finance.metrics import compute_metrics_df_flat_kor, TARGET_FEATURES


@dataclass
class CompanyResult:
    """Container for a single company's extraction result."""

    corp_name: str
    stock_code: Optional[str]
    corp_code: Optional[str]
    status: str
    metrics: Optional[pd.Series]
    error: Optional[str] = None

    def to_dict(self) -> dict:
        base = {
            "corp_name": self.corp_name,
            "stock_code": self.stock_code,
            "corp_code": self.corp_code,
            "status": self.status,
        }
        if isinstance(self.metrics, pd.Series):
            base.update(self.metrics.to_dict())
        if self.error:
            base["error"] = self.error
        return base


def _latest_metrics_series(metrics_df: pd.DataFrame) -> Optional[pd.Series]:
    """Return the most recent metrics row (latest closing date)."""

    if not isinstance(metrics_df, pd.DataFrame) or metrics_df.empty:
        return None

    # 인덱스는 문자열 형태의 YYYYMMDD 이므로 정수형으로 정렬하여 최신 연도를 선택한다.
    try:
        idx = metrics_df.index.astype(int)
    except ValueError:
        # Index가 정수로 캐스팅되지 않는다면 기본 정렬을 사용한다.
        idx = pd.Index(range(len(metrics_df)))

    latest_pos = idx.argmax()
    latest_key = metrics_df.index[latest_pos]
    return metrics_df.loc[latest_key]


def build_financial_table(
    company_names: Iterable[str],
    *,
    api_key: Optional[str] = None,
    bgn_de: str = "20200101",
    report_tp: str = "annual",
    separate: bool = False,
    metrics: Optional[List[str]] = None,
) -> pd.DataFrame:
    """Fetch financial statements for each company and return a DataFrame."""

    init_dart(api_key)
    metrics_cols = metrics or TARGET_FEATURES

    results: List[CompanyResult] = []
    for name in company_names:
        corp = find_corp(name, by="name")
        if corp is None:
            results.append(
                CompanyResult(
                    corp_name=name,
                    stock_code=None,
                    corp_code=None,
                    status="NOT_FOUND",
                    metrics=None,
                )
            )
            continue

        try:
            fs = extract_fs(corp, bgn_de=bgn_de, report_tp=report_tp, separate=separate)
            bs_df, is_df, cis_df, cf_df = preprocess_all(fs)
            metrics_df = compute_metrics_df_flat_kor(bs_df, is_df, cis_df, cf_df)
            latest_metrics = _latest_metrics_series(metrics_df)
            if isinstance(latest_metrics, pd.Series):
                latest_metrics = latest_metrics.reindex(metrics_cols)
            status = "OK" if isinstance(latest_metrics, pd.Series) else "EMPTY"
            results.append(
                CompanyResult(
                    corp_name=getattr(corp, "corp_name", name),
                    stock_code=getattr(corp, "stock_code", None),
                    corp_code=getattr(corp, "corp_code", None),
                    status=status,
                    metrics=latest_metrics,
                )
            )
        except Exception as exc:  # pylint: disable=broad-except
            results.append(
                CompanyResult(
                    corp_name=getattr(corp, "corp_name", name),
                    stock_code=getattr(corp, "stock_code", None),
                    corp_code=getattr(corp, "corp_code", None),
                    status="ERROR",
                    metrics=None,
                    error=str(exc),
                )
            )

    data = [res.to_dict() for res in results]
    df = pd.DataFrame(data)
    if metrics_cols:
        # Ensure columns exist even when data is missing.
        for col in metrics_cols:
            if col not in df.columns:
                df[col] = pd.NA
    ordered_cols = [col for col in [
        "corp_name",
        "stock_code",
        "corp_code",
        "status",
        "error",
    ] if col in df.columns] + [col for col in metrics_cols]
    return df[ordered_cols]


if __name__ == "__main__":
    SAMPLE_COMPANIES = ["삼성전자", "LG화학", "현대자동차"]
    table = build_financial_table(SAMPLE_COMPANIES, bgn_de="20200101", report_tp="annual")
    pd.set_option("display.max_columns", None)
    pd.set_option("display.width", 120)
    print(table)

pd.to_csv("table.csv")