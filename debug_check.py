# debug_check.py (또는 노트북 셀)
from kiwoom_finance.dart_client import init_dart, find_corp, extract_fs
from kiwoom_finance.preprocess import preprocess_all
from kiwoom_finance.metrics import compute_metrics_df_flat_kor

init_dart()  # .env의 DART_API_KEY 사용

corp = find_corp("005380")  # 원하는 종목코드
fs = extract_fs(corp, bgn_de="20240101", report_tp="annual", separate=False)
bs_flat, is_flat, cis_flat, cf_flat = preprocess_all(fs)

df, dbg = compute_metrics_df_flat_kor(
    bs_flat_df=bs_flat,
    is_flat_df=is_flat,
    cis_flat_df=cis_flat,
    cf_flat_df=cf_flat,
    return_debug=True,   # ← 여기!
)

print("== 선택된 컬럼명 ==", dbg["chosen_cols"])
print("== 최신키 ==", dbg["latest_key"])
print("== 최신 원시값 ==", dbg["latest_raw_values"])
print("== 최신 비율(숫자) ==", dbg["latest_ratios_numeric"])
print(df.tail(1))  # 최신 행 확인
