# wrapper API around the implementation module
from typing import Tuple, List
import importlib
import nice_rating.crawler_impl as crawler_impl


# import crawler_impl dynamically so user can replace it without editing wrapper
from .crawler_impl import (
    build_two_column_df,
    search_and_collect_resilient,
    _load_disk_cache,
    _lookup_cache,
    _update_runtime_cache,
    worker_process,
    retry_failed_serial,
)

def crawl_companies(companies: List[str]):
    """
    실행용 호출 인터페이스.
    companies: list of company name strings.
    반환: (df_final, skipped_all)  -- pandas.DataFrame, list[tuple[str,str]]
    """
    # Expect crawler_impl to implement crawl_companies(companies) that returns (df, skipped)
    if hasattr(crawler_impl, "crawl_companies"):
        return crawler_impl.crawl_companies(companies)
    else:
        # If the implementation doesn't provide crawl_companies, try to call main-like flow
        # Fallback: call crawler_impl.main() but that expects companies.txt or cli args — so raise informative error.
        raise RuntimeError("crawler_impl.py does not expose 'crawl_companies'. Please ensure you pasted the original monolith into crawler_impl.py and it contains crawl_companies() or adapt the wrapper.")
