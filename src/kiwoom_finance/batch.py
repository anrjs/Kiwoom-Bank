# src/kiwoom_finance/batch.py
from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Callable, List

import pandas as pd

from .dart_client import extract_fs, find_corp, init_dart
from .preprocess import preprocess_all

DEFAULT_COLS = [
    "debt_ratio","equity_ratio","debt_dependency_ratio",
    "current_ratio","quick_ratio","interest_coverage_ratio",
    "ebitda_to_total_debt","cfo_to_total_debt","free_cash_flow",
    "operating_margin","roa","roe","net_profit_margin",
    "total_asset_turnover","accounts_receivable_turnover","inventory_turnover",
    "sales_growth_rate","operating_income_growth_rate","total_asset_growth_rate",
]

LATEST_PRIORITY_COLS = (
    "current_ratio","quick_ratio","debt_ratio","equity_ratio",
    "operating_margin","roa","roe","net_profit_margin",
)

PERCENT_COLS = (
    "debt_ratio","equity_ratio","debt_dependency_ratio",
    "current_ratio","quick_ratio",
    "operating_margin","roa","roe","net_profit_margin",
    "sales_growth_rate","operating_income_growth_rate","total_asset_growth_rate",
)

TIMES_COLS = (
    "interest_coverage_ratio","ebitda_to_total_debt","cfo_to_total_debt",
    "total_asset_turnover","accounts_receivable_turnover","inventory_turnover",
)

DEFAULT_MAX_WORKERS = 4


def _select_latest_row(df: pd.DataFrame) -> pd.DataFrame:
    if df.empty:
        return df

    sorted_df = df.sort_index(ascending=False)
    use_cols = [c for c in LATEST_PRIORITY_COLS if c in sorted_df.columns]
    if use_cols:
        mask = sorted_df[use_cols].notna().any(axis=1)
    else:
        mask = sorted_df.notna().any(axis=1)

    valid_indices = mask[mask].index
    if len(valid_indices):
        first_valid = valid_indices[0]
        return sorted_df.loc[[first_valid]]
    return sorted_df.iloc[[0]]


def _format_metrics_frame(df: pd.DataFrame) -> pd.DataFrame:
    if df.empty:
        return df

    out = df.copy()

    pct_cols = [c for c in PERCENT_COLS if c in out.columns]
    if pct_cols:
        pct_values = (
            out.loc[:, pct_cols]
            .apply(pd.to_numeric, errors="coerce")
            .mul(100)
            .round(2)
        )
        pct_formatted = (pct_values.astype("string") + "%").where(
            pct_values.notna(), other="N/A"
        )
        out.loc[:, pct_cols] = pct_formatted

    times_cols = [c for c in TIMES_COLS if c in out.columns]
    if times_cols:
        out.loc[:, times_cols] = (
            out.loc[:, times_cols]
            .apply(pd.to_numeric, errors="coerce")
            .round(2)
        )

    if "free_cash_flow" in out.columns:
        out.loc[:, "free_cash_flow"] = (
            pd.to_numeric(out["free_cash_flow"], errors="coerce")
            .round(0)
            .astype("Int64")
        )

    return out


def _with_index(df: pd.DataFrame, stock_code: str, latest_only: bool) -> pd.DataFrame:
    df = df.copy()
    if df.empty:
        df.index = pd.Index([], name="stock_code")
        return df

    if latest_only:
        new_index = [stock_code]
    else:
        new_index = [f"{stock_code}_{i}" for i in range(len(df))]
    df.index = new_index
    df.index.name = "stock_code"
    return df


def _run_worker(
    code: str,
    bgn_de: str,
    report_tp: str,
    separate: bool,
    latest_only: bool,
    percent_format: bool,
    compute_metrics: Callable[..., pd.DataFrame],
) -> pd.DataFrame:
    corp = find_corp(code)
    fs = extract_fs(corp, bgn_de=bgn_de, report_tp=report_tp, separate=separate)
    bs_flat, is_flat, cis_flat, cf_flat = preprocess_all(fs)

    metrics_df = compute_metrics(
        bs_flat_df=bs_flat,
        is_flat_df=is_flat,
        cis_flat_df=cis_flat,
        cf_flat_df=cf_flat,
        key_cols=None,
    )
    df = metrics_df.loc[:, [c for c in DEFAULT_COLS if c in metrics_df.columns]].copy()

    if latest_only:
        df = _select_latest_row(df)

    df = _with_index(df, corp.stock_code, latest_only)

    if percent_format:
        df = _format_metrics_frame(df)

    return df


def get_metrics_for_codes(
    codes: List[str],
    bgn_de: str = "20170101",
    report_tp: str = "annual",
    separate: bool = False,
    latest_only: bool = True,
    percent_format: bool = True,
    api_key: str | None = None,
) -> pd.DataFrame:
    from .metrics import compute_metrics_df_flat_kor

    init_dart(api_key=api_key)

    if not codes:
        return pd.DataFrame(columns=DEFAULT_COLS)

    compute = compute_metrics_df_flat_kor

    if len(codes) == 1:
        frames = [
            _run_worker(
                codes[0],
                bgn_de,
                report_tp,
                separate,
                latest_only,
                percent_format,
                compute,
            )
        ]
    else:
        frames_ordered: list[pd.DataFrame | None] = [None] * len(codes)
        max_workers = min(DEFAULT_MAX_WORKERS, len(codes)) or 1

        with ThreadPoolExecutor(max_workers=max_workers) as executor:
            future_to_idx = {
                executor.submit(
                    _run_worker,
                    code,
                    bgn_de,
                    report_tp,
                    separate,
                    latest_only,
                    percent_format,
                    compute,
                ): idx
                for idx, code in enumerate(codes)
            }

            for future in as_completed(future_to_idx):
                idx = future_to_idx[future]
                frames_ordered[idx] = future.result()

        frames = [frame for frame in frames_ordered if frame is not None]

    if not frames:
        return pd.DataFrame(columns=DEFAULT_COLS)
    return pd.concat(frames, axis=0)
