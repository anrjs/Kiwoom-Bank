import argparse
from naver_news import collect_news
from preprocess import dedup_by_title_host, build_inputs
from sentiment_finbert import analyze_texts_ko, weighted_aggregate
from utils_scoring import credit_signal

from news_analytics import config

from .config import MAX_PAGES, NEWS_PER_PAGE




def run(company: str):
    query = f'"{company}"'
    items = collect_news(query, max_pages=MAX_PAGES, per_page=NEWS_PER_PAGE)
    items = dedup_by_title_host(items)


    texts, weights = build_inputs(items)
    if not texts:
        print("No news fetched.")
        return


    results = analyze_texts_ko(texts)
    agg = weighted_aggregate(results, weights)
    signal = credit_signal(agg)


    print(f"\n[ {company} ] 총 {len(texts)}건 분석")
    print("가중 평균 스코어:", agg)
    print("뉴스 기반 신용 신호 :", signal)




if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("company", type=str, help="회사명 (예: 삼성전자)")
    args = parser.parse_args()
    run(args.company)