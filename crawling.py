from selenium import webdriver
from selenium.webdriver.chrome.service import Service as ChromeService
from webdriver_manager.chrome import ChromeDriverManager
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from bs4 import BeautifulSoup
import pandas as pd
import time
from selenium.webdriver.support import expected_conditions as EC

# --- 설정값 ---
URL = "https://www.kisrating.com/ratingsSearch/corp_overview.do?kiscd=350893"
# TODO: 다운로드한 ChromeDriver의 경로를 지정하세요.
# CHROMEDRIVER_PATH = 'C:/workspace/kiwoombank/project1/chromedriver.exe'
HEADERS = {
    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36'
}

# --- 함수 정의 ---
def fetch_dynamic_ratings_data(url):
    # Service를 ChromeDriverManager로 자동 설정 (경로 문제 완전 해결)
    service = ChromeService(ChromeDriverManager().install())

    options = webdriver.ChromeOptions()
    # 🚨 중요: 봇 감지 회피 옵션 추가 
    # 이 옵션은 Selenium을 "자동화된 소프트웨어"가 아닌 "사용자"처럼 보이게 합니다.
    options.add_experimental_option("excludeSwitches", ["enable-automation"])
    options.add_argument("user-agent=Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/141.0.0.0 Safari/537.36")

    # Headless는 주석 처리 유지 (창 띄워서 확인)
    # options.add_argument('headless') 

    driver = webdriver.Chrome(service=service, options=options)
    
    try:
        driver.get(url)

        # 1. 데이터가 로딩될 때까지 명시적으로 대기 (강화된 조건)
        # ID 'tb1' 테이블 내부에 데이터 행(<tr>)이 나타날 때까지 최대 10초 대기
        WebDriverWait(driver, 10).until(
            EC.presence_of_element_located((By.CSS_SELECTOR, "#tb1 > tbody > tr")) 
        )
        time.sleep(1)  # 1초의 여유 시간 추가 (데이터가 완전히 화면에 그려질 시간 확보)

        # 2. 로딩이 완료된 최종 HTML 가져오기
        page_source = driver.page_source
        
        # 3. BeautifulSoup으로 HTML 파싱
        soup = BeautifulSoup(page_source, 'html.parser')
        # ID가 'tb1'인 테이블 찾기 (확실하게 tb1 사용)
        table = soup.find('table', {'id': 'tb1'}) 

        if not table:
            return "테이블(tb1)을 찾을 수 없습니다. (대기 후에도 실패)"

        # ... (이후 헤더 및 데이터 추출 과정은 동일) ...
        # (주의: table.find('tbody').find_all('tr') 이 부분에서 데이터를 제대로 추출해야 합니다.)
        headers = [th.text.strip() for th in table.find('thead').find_all('th')]
        
        rows = table.find('tbody').find_all('tr')
        data = []
        for row in rows:
            cols = row.find_all('td')
            # ... (데이터 추출 및 정리) ...
            cols = [ele.text.strip() for ele in cols]
            data.append([ele for ele in cols if ele])

        return headers, data

    except Exception as e:
        return f"크롤링 중 오류 발생: {e}"
    
    finally:
        driver.quit()


# --- 실행 ---
print("Selenium을 이용한 동적 데이터 로딩 및 추출 시작...")
result = fetch_dynamic_ratings_data(URL)

if isinstance(result, tuple):
    headers, data = result
    
    # 데이터프레임 생성
    df = pd.DataFrame(data, columns=headers)
    
    print("\n--- 추출된 회사채 등급 데이터프레임 ---")
    print(df)
    
else:
    print(f"\n데이터 추출 실패: {result}")