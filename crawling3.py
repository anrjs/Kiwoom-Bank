import requests
from bs4 import BeautifulSoup

url = "https://www.nicerating.com/disclosure/companyGradeInfo.do?cmpCd=1709744&searchText=%ED%95%9C%ED%99%94"

headers = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/118.0.0.0 Safari/537.36"
}

resp = requests.get(url, headers=headers)
resp.raise_for_status()

soup = BeautifulSoup(resp.text, "html.parser")  # html.parser면 추가 설치 불필요

# 등급 표 찾기
table = soup.find("table", {"id": "tbl1"})

# 표 안의 모든 <td class="cell_txt01"> 추출
td_list = table.find_all("td", class_="cell_txt01")

# 첫 번째 값이 등급 (예: "A+")
if td_list:
    grade = td_list[0].get_text(strip=True)
    print("첫 번째 등급 데이터:", grade)
else:
    print("등급 데이터를 찾지 못했습니다.")
