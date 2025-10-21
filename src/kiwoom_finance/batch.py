# src/kiwoom_finance/batch.py
from typing import List
import pandas as pd
from .dart_client import init_dart, find_corp, extract_fs
from .preprocess import preprocess_all

DEFAULT_COLS = [
    "debt_ratio","equity_ratio","debt_dependency_ratio",
    "current_ratio","quick_ratio","interest_coverage_ratio",
    "ebitda_to_total_debt","cfo_to_total_debt","free_cash_flow",
    "operating_margin","roa","roe","net_profit_margin",
    "total_asset_turnover","accounts_receivable_turnover","inventory_turnover",
    "sales_growth_rate","operating_income_growth_rate","total_asset_growth_rate",
]

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

    frames = []
    for code in codes:
        corp = find_corp(code)
        fs = extract_fs(corp, bgn_de=bgn_de, report_tp=report_tp, separate=separate)
        bs_flat, is_flat, cis_flat, cf_flat = preprocess_all(fs)

        metrics_df = compute_metrics_df_flat_kor(
            bs_flat_df=bs_flat,
            is_flat_df=is_flat,
            cis_flat_df=cis_flat,
            cf_flat_df=cf_flat,
            key_cols=None,
        )
        df = metrics_df.loc[:, [c for c in DEFAULT_COLS if c in metrics_df.columns]].copy()

        if latest_only:
            df_sorted = df.sort_index(ascending=False)

            # ✅ “유효 최신행” 선정 기준 강화
            priority_cols = [
                # 유동성/레버리지
                "current_ratio","quick_ratio","debt_ratio","equity_ratio",
                # 수익성 — 이 중 하나라도 있으면 우선 채택
                "operating_margin","roa","roe","net_profit_margin"
            ]
            use_cols = [c for c in priority_cols if c in df_sorted.columns]
            if use_cols:
                mask = df_sorted[use_cols].notna().any(axis=1)
            else:
                mask = df_sorted.notna().any(axis=1)

            latest_valid = df_sorted[mask].head(1)
            if latest_valid.empty:
                latest_valid = df_sorted.head(1)
            df = latest_valid.copy()

        # 인덱스를 종목코드로
        df.index = [corp.stock_code] if latest_only else [f"{corp.stock_code}_{i}" for i in range(len(df))]
        df.index.name = "stock_code"

        if percent_format:
            pct_cols = [
                "debt_ratio","equity_ratio","debt_dependency_ratio",
                "current_ratio","quick_ratio",
                "operating_margin","roa","roe","net_profit_margin",
                "sales_growth_rate","operating_income_growth_rate","total_asset_growth_rate",
            ]
            times_cols = [
                "interest_coverage_ratio","ebitda_to_total_debt","cfo_to_total_debt",
                "total_asset_turnover","accounts_receivable_turnover","inventory_turnover",
            ]
            for c in pct_cols:
                if c in df.columns:
                    s = pd.to_numeric(df[c], errors="coerce") * 100
                    # dtype 충돌 방지
                    df.loc[:, c] = s.round(2).astype(object).astype(str) + "%"
                    df.loc[:, c] = df[c].str.replace("nan%", "N/A", regex=False)
            for c in times_cols:
                if c in df.columns:
                    df.loc[:, c] = pd.to_numeric(df[c], errors="coerce").round(2)
            if "free_cash_flow" in df.columns:
                df.loc[:, "free_cash_flow"] = (
                    pd.to_numeric(df["free_cash_flow"], errors="coerce")
                    .round(0)
                    .astype("Int64")
                )

        frames.append(df)

    if not frames:
        return pd.DataFrame(columns=DEFAULT_COLS)
    return pd.concat(frames, axis=0)
