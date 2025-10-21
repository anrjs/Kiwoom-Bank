# # test_metrics.py (루트에 위치)
from kiwoom_finance.batch import get_metrics_for_codes
import warnings
warnings.filterwarnings("ignore", category=UserWarning, module="dart_fss")
warnings.filterwarnings("ignore", category=RuntimeWarning, module="dart_fss")
df = get_metrics_for_codes(
    ['005380', '079550', '023530', '003490', '086520', '004710', '042660', '336260', '001070', '143210', '290120'],
    latest_only=True,
    percent_format=True,
    api_key="66ce66618f4850247aa36d3d0bea34737980af17"   # ← 직접 전달
)
print(df)



# --- sanity check: equity_ratio ≈ 1 / (1 + debt_ratio) 이어야 함 ---
import pandas as pd
res = df.copy()
er = pd.to_numeric(res["equity_ratio"].str.rstrip("%"), errors="coerce")/100
dr = pd.to_numeric(res["debt_ratio"].str.rstrip("%"), errors="coerce")/100
res["equity_implied_from_debt"] = (1/(1+dr)).round(4)
res["equity_ratio_numeric"] = er.round(4)
res["Δ_equity_ratio"] = (res["equity_ratio_numeric"] - res["equity_implied_from_debt"]).round(4)
print(res[["equity_ratio","debt_ratio","equity_implied_from_debt","Δ_equity_ratio"]])

df.to_csv("metrics_result.csv", encoding="utf-8-sig", index=True)
