import pandas as pd

def preprocess_all(fs):
    cis_flat = fs['cis']
    is_flat  = fs['is']
    bs_flat  = fs['bs']
    cf_flat  = fs['cf']

    # ====== 전처리 (사용자 제공 원본 그대로) ======
    if isinstance(is_flat, pd.DataFrame) and not is_flat.empty:
        is_flat = is_flat.T
        is_flat.columns = is_flat.columns.get_level_values(-1)
        is_flat.columns = is_flat.iloc[1]
        is_flat = is_flat.reset_index(level=1, drop=True)
        is_flat.index = is_flat.index.str.split('-').str[-1]
        cond3 = is_flat.index.to_series().astype(str).str.isdigit()
        is_flat = is_flat.loc[cond3]
        is_flat.index = is_flat.index.astype(str).astype(int)

    bs_flat = bs_flat.T
    bs_flat.columns = bs_flat.columns.get_level_values(-1)
    bs_flat.columns = bs_flat.iloc[1]
    bs_flat = bs_flat.reset_index(level=1, drop=True)
    cond = bs_flat.index.to_series().astype(str).str.isdigit()
    bs_flat = bs_flat.loc[cond]
    bs_flat.index = bs_flat.index.astype(str).astype(int)

    cis_flat = cis_flat.T
    cis_flat.columns = cis_flat.columns.get_level_values(-1)
    cis_flat.columns = cis_flat.iloc[1]
    cis_flat = cis_flat.drop(cis_flat.index[0:7])
    cis_flat = cis_flat.reset_index(level=1, drop=True)
    cis_flat.index = cis_flat.index.str.split('-').str[-1]

    cf_flat = cf_flat.T
    cf_flat.columns = cf_flat.columns.get_level_values(-1)
    cf_flat.columns = cf_flat.iloc[1]
    cf_flat = cf_flat.reset_index(level=1, drop=True)
    cf_flat.index = cf_flat.index.str.split('-').str[-1]
    cond2 = cf_flat.index.to_series().astype(str).str.isdigit()
    cf_flat = cf_flat.loc[cond2]
    cf_flat.index = cf_flat.index.astype(str).astype(int)
    # =============================================

    return bs_flat, is_flat, cis_flat, cf_flat
