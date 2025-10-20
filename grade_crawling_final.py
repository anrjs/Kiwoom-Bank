# ...existing code...
import requests
from bs4 import BeautifulSoup
import pandas as pd
from time import sleep

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/118.0.0.0 Safari/537.36"
}

def _extract_name_from_tbl_type99(soup: BeautifulSoup) -> str | None:
    # div.tbl_type99 > table 내 첫 번째 td가 기업명
    tbl = soup.select_one("div.tbl_type99 table")
    if not tbl:
        return None
    tbody = tbl.find("tbody")
    first_td = (tbody.find("td") if tbody else tbl.find("td"))
    if first_td:
        return first_td.get_text(" ", strip=True)
    return None

def fetch_company_and_grade(cmpCd: str) -> tuple[str, str]:
    url = f"https://www.nicerating.com/disclosure/companyGradeInfo.do?cmpCd={cmpCd}"
    resp = requests.get(url, headers=HEADERS, timeout=15)
    resp.raise_for_status()
    soup = BeautifulSoup(resp.text, "html.parser")

    # 등급 추출
    grade = ""
    table = soup.find("table", {"id": "tbl1"})
    if table:
        tds = table.find_all("td", class_="cell_txt01")
        if tds:
            grade = tds[0].get_text(strip=True)

    # 1) tbl_type99 표에서 기업명 추출
    name = _extract_name_from_tbl_type99(soup)

    # 2) 실패 시 기존 셀렉터 폴백
    if not name:
        for sel in [
            "div.cont_title h3",
            "h3.tit",
            ".company_name",
            ".cmp_name",
            "div.title_area h3",
        ]:
            el = soup.select_one(sel)
            if el:
                name = el.get_text(strip=True)
                break

    # 3) 그래도 없으면 title 또는 cmpCd
    if not name:
        title_text = (soup.title.get_text(strip=True) if soup.title else "") or ""
        name = title_text.split("|")[0].split("-")[0].strip() or cmpCd

    return name, grade

# 수집 대상 cmpCd 5개
targets = [
    "5207805",  # 에코프로
    "1709744", # 한화
    "1509922", # 한화오션
    "1407283", # 현대자동차
    "1855106", # 한솔테크닉스
    "1463144", # 대한항공
    "5110558", # 두산퓨얼셀
    "1267319", # 대한방직
    "5110566", # 디에이치오토리드
    "5103009", # 핸즈코퍼레이션
    "1903621", # 롯데쇼핑
    "2170795", # 엘아이지넥스원
    "5010736", # 대유에이텍
]

rows = []
for code in targets:
    try:
        name, grade = fetch_company_and_grade(code)
    except Exception:
        name, grade = code, ""
    rows.append({"회사명": name, "등급": grade})
    sleep(0.4)  # 서버 부하 방지

df = pd.DataFrame(rows).set_index("회사명")
print(df)
# df.to_csv("등급결과.csv", encoding="utf-8-sig")
# print("✅ 등급결과.csv 저장 완료")
# # ...existing code...