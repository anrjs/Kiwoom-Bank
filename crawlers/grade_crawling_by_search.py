# -*- coding: utf-8 -*-
"""
NICE 신용평가 - 검색 후 URL에서 cmpCd 추출 → 등급 수집
- 검색 → (가장 유사한 결과) 클릭 → URL의 cmpCd 파싱
- companyGradeInfo.do?cmpCd=... 상세 페이지로 진입해 채권등급 파싱
"""

import re
import time
import unicodedata
from pathlib import Path
from difflib import SequenceMatcher
from urllib.parse import urlparse, parse_qs

import requests
import pandas as pd
from bs4 import BeautifulSoup

# Selenium
from selenium import webdriver
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.common.by import By
from selenium.webdriver.common.keys import Keys
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from webdriver_manager.chrome import ChromeDriverManager


# ---------------- Basic config ----------------
BASE = "https://www.nicerating.com"
HOME = f"{BASE}/"
SEARCH_TIMEOUT = 20
REQUEST_TIMEOUT = 15
HEADLESS = True  # 디버깅시 False

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/118.0.0.0 Safari/537.36"
    )
}


# ---------------- Name normalization / similarity ----------------
ALIASES = [
    (re.compile(r"\b에스케이", re.I), "SK"),
    (re.compile(r"\b엘지", re.I), "LG"),
    (re.compile(r"\b씨제이", re.I), "CJ"),
    (re.compile(r"\b케이티\b", re.I), "KT"),
    (re.compile(r"\b케이비\b", re.I), "KB"),
    (re.compile(r"\b엔에이치\b", re.I), "NH"),
    (re.compile(r"\b에이치디", re.I), "HD"),
    (re.compile(r"\b에이케이\b", re.I), "AK"),
]
def aliasize(s: str) -> str:
    for pat, rep in ALIASES:
        s = pat.sub(rep, s)
    return re.sub(r"\s*\(주\)|㈜", "", s).strip()

def normalize_text(s: str) -> str:
    if not s: return ""
    s = unicodedata.normalize("NFKC", s).strip().lower()
    s = re.sub(r"(주식회사|㈜|\(주\)|유한회사|홀딩스)", " ", s)
    s = re.sub(r"[\(\)\[\]\{\}]", " ", s)
    return re.sub(r"\s+", " ", s)

def name_similarity(a: str, b: str) -> float:
    return SequenceMatcher(None, normalize_text(a), normalize_text(b)).ratio()


# ---------------- Detail page parser (당신의 원본 로직 유지) ----------------
def _extract_name_from_tbl_type99(soup: BeautifulSoup) -> str | None:
    tbl = soup.select_one("div.tbl_type99 table")
    if not tbl: return None
    tbody = tbl.find("tbody")
    first_td = (tbody.find("td") if tbody else tbl.find("td"))
    return first_td.get_text(" ", strip=True) if first_td else None

def _extract_grade_primary_tbl1(soup: BeautifulSoup) -> str | None:
    table = soup.find("table", {"id": "tbl1"})
    if not table: return None
    tds = table.find_all("td", class_="cell_txt01")
    if not tds: return None
    return tds[0].get_text(strip=True) or None

# 보강: '회사채' 행에서 현재 등급/전망
LONGTERM_GRADE_RE = re.compile(
    r"^(AAA|AA\+|AA|AA\-|A\+|A|A\-|BBB\+|BBB|BBB\-|BB\+|BB|BB\-|B\+|B|B\-|CCC|CC|C|D)$"
)
OUTLOOK_RE = re.compile(r"(안정적|긍정적|부정적|유동적|Stable|Positive|Negative|Developing)", re.I)

def _extract_grade_from_major_table(soup: BeautifulSoup) -> str | None:
    for tr in soup.find_all("tr"):
        t = tr.get_text(" ", strip=True)
        if "회사채" in t:
            toks = t.replace("/", " ").split()
            grades = [x for x in toks if LONGTERM_GRADE_RE.match(x)]
            outs   = [x for x in toks if OUTLOOK_RE.search(x)]
            if grades:
                g = grades[-1]
                return f"{g} {outs[-1]}" if outs else g
    return None

def fetch_company_and_grade_by_cmpcd(cmpCd: str, session: requests.Session) -> tuple[str, str]:
    # 삼성전자 수동 접속 시 보이던 파라미터 포함 (굳이 없어도 됨)
    url = f"{BASE}/disclosure/companyGradeInfo.do?cmpCd={cmpCd}&deviceType=N&isPaidMember=false"
    resp = session.get(url, headers=HEADERS, timeout=REQUEST_TIMEOUT)
    resp.raise_for_status()
    soup = BeautifulSoup(resp.text, "html.parser")

    name = _extract_name_from_tbl_type99(soup)
    if not name:
        for sel in ["div.cont_title h3", "h3.tit", ".company_name", ".cmp_name", "div.title_area h3"]:
            el = soup.select_one(sel)
            if el: name = el.get_text(strip=True); break
    if not name:
        title_text = soup.title.get_text(strip=True) if soup.title else ""
        name = title_text.split("|")[0].split("-")[0].strip() or cmpCd

    grade = _extract_grade_primary_tbl1(soup) or _extract_grade_from_major_table(soup) or ""
    return name, grade


# ---------------- Selenium helpers ----------------
def _stealth_options() -> Options:
    opts = Options()
    if HEADLESS: opts.add_argument("--headless=new")
    opts.add_argument("--no-sandbox")
    opts.add_argument("--disable-dev-shm-usage")
    opts.add_argument("--disable-gpu")
    opts.add_argument("--lang=ko-KR")
    opts.add_argument("--window-size=1280,2000")
    opts.add_argument(f"user-agent={HEADERS['User-Agent']}")
    # 봇 특성 제거
    opts.add_experimental_option("excludeSwitches", ["enable-automation"])
    opts.add_experimental_option("useAutomationExtension", False)
    return opts

def _post_launch_stealth(driver):
    try:
        driver.execute_cdp_cmd(
            "Page.addScriptToEvaluateOnNewDocument",
            {"source": 'Object.defineProperty(navigator, "webdriver", {get: () => undefined});'}
        )
    except Exception:
        pass

def _find_search_box(driver: webdriver.Chrome):
    sels = [
        "input#searchKeyword", "input#keyword",
        "input[name='searchKeyword']", "input[name='keyword']",
        "header input[type='text']", "form input[type='text']",
        "input[type='search']",
    ]
    for sel in sels:
        try:
            el = WebDriverWait(driver, 6).until(EC.presence_of_element_located((By.CSS_SELECTOR, sel)))
            if el.is_displayed(): return el
        except Exception:
            pass
    raise RuntimeError("검색 입력창을 찾지 못했습니다.")

def _close_overlays(driver):
    for sel in ["button.close", ".btn_close", "a.close", "button[aria-label='닫기']"]:
        try:
            for el in driver.find_elements(By.CSS_SELECTOR, sel):
                if el.is_displayed(): el.click()
        except Exception:
            pass

def _switch_to_new_tab_if_opened(driver, prev_handles):
    # 새 탭이 열렸으면 전환
    new_handles = driver.window_handles
    if len(new_handles) > len(prev_handles):
        for h in new_handles:
            if h not in prev_handles:
                driver.switch_to.window(h)
                return True
    return False

def _parse_cmpcd_from_url(url: str) -> str | None:
    # ?cmpCd=1326874&... 에서 cmpCd만 추출
    try:
        q = parse_qs(urlparse(url).query)
        if "cmpCd" in q and q["cmpCd"]:
            return q["cmpCd"][0]
    except Exception:
        pass
    m = re.search(r"cmpCd=(\d+)", url)
    return m.group(1) if m else None


def search_company_then_get_cmpcd_from_url(driver: webdriver.Chrome, company_name: str) -> str | None:
    """
    1) HOME에서 검색 → 결과 중 가장 유사한 항목 클릭
    2) 클릭 후 로드된 페이지(or 새 탭)의 URL에서 cmpCd 파싱
    """
    # 원문 → 별칭(에스케이→SK 등) 두 번 시도
    for attempt, query in enumerate([company_name, aliasize(company_name)], 1):
        driver.get(HOME)
        time.sleep(1.0)
        _close_overlays(driver)

        # 검색 입력
        box = _find_search_box(driver)
        box.clear(); box.send_keys(query); time.sleep(0.2)
        prev_handles = driver.window_handles[:]
        box.send_keys(Keys.ENTER)

        # 결과 표시 대기 (링크/onclick/iframe 등)
        try:
            WebDriverWait(driver, SEARCH_TIMEOUT).until(
                EC.any_of(
                    EC.presence_of_element_located((By.CSS_SELECTOR, '[onclick*="fn_cmpGradeInfo("]')),
                    EC.presence_of_element_located((By.CSS_SELECTOR, 'a[href*="companyGradeInfo.do"]')),
                    EC.presence_of_element_located((By.CSS_SELECTOR, "iframe")),
                    EC.url_contains("companyGradeInfo.do")
                )
            )
        except Exception:
            pass

        # 만약 직접 상세 페이지로 이동했다면 바로 URL 파싱
        cmpcd = _parse_cmpcd_from_url(driver.current_url)
        if cmpcd: return cmpcd

        # 자동완성/검색 버튼 클릭 시도
        if not cmpcd:
            try:
                box.send_keys(Keys.ARROW_DOWN); box.send_keys(Keys.ENTER)
                WebDriverWait(driver, 4).until(EC.url_contains("companyGradeInfo.do"))
                cmpcd = _parse_cmpcd_from_url(driver.current_url)
                if cmpcd: return cmpcd
            except Exception:
                pass

        # 수동으로 결과 항목 클릭 (유사도 기준으로 가장 가까운 것)
        candidates = []
        # a[href*=companyGradeInfo]
        for a in driver.find_elements(By.CSS_SELECTOR, 'a[href*="companyGradeInfo.do"]'):
            try:
                txt = (a.text or a.get_attribute("title") or "").strip()
                sc = name_similarity(company_name, txt)
                candidates.append((sc, a))
            except Exception:
                pass
        # onclick=fn_cmpGradeInfo(...)
        for el in driver.find_elements(By.CSS_SELECTOR, '[onclick*="fn_cmpGradeInfo("]'):
            try:
                txt = (el.text or el.get_attribute("title") or "").strip()
                sc = name_similarity(company_name, txt)
                candidates.append((sc, el))
            except Exception:
                pass

        # 유사도 높은 순으로 클릭 시도
        candidates.sort(key=lambda x: x[0], reverse=True)
        for sc, el in candidates[:5]:
            try:
                if sc < (0.35 if attempt == 2 else 0.5):
                    continue
                prev = driver.window_handles[:]
                el.click()
                time.sleep(1.0)
                _switch_to_new_tab_if_opened(driver, prev)
                WebDriverWait(driver, 6).until(EC.url_contains("companyGradeInfo.do"))
                cmpcd = _parse_cmpcd_from_url(driver.current_url)
                if cmpcd: return cmpcd
            except Exception:
                # 다른 후보로 계속 시도
                continue

        # 여기까지 실패면 alias 시도로 넘어감
    return None


# ---------------- I/O & pipeline ----------------
def load_companies_from_txt(path="../data/input/companies.txt") -> list[str]:
    p = Path(path)
    if not p.exists(): return []
    return [ln.strip() for ln in p.read_text(encoding="utf-8-sig").splitlines() if ln.strip()]

def main():
    companies = load_companies_from_txt("../data/input/companies.txt")
    print(f"📋 대상 기업 수: {len(companies)}")

    options = _stealth_options()
    driver = webdriver.Chrome(service=Service(ChromeDriverManager().install()), options=options)
    _post_launch_stealth(driver)

    session = requests.Session()
    session.headers.update(HEADERS)

    rows, skipped = [], []

    try:
        for i, corp in enumerate(companies, 1):
            try:
                cmpcd = search_company_then_get_cmpcd_from_url(driver, corp)
            except Exception as e:
                print(f"❗ 검색 실패: {corp} -> {e}")
                skipped.append((corp, "검색 실패")); continue

            if not cmpcd:
                print(f"🔎 검색결과/URL에 cmpCd 없음: {corp}")
                skipped.append((corp, "cmpCd 없음")); continue

            # 동일 세션 유지(필요 시)
            for c in driver.get_cookies():
                session.cookies.set(c["name"], c["value"], domain=c.get("domain") or "www.nicerating.com")

            try:
                name, grade = fetch_company_and_grade_by_cmpcd(cmpcd, session)
            except Exception as e:
                print(f"❗ 상세 조회 실패: {corp} (cmpCd={cmpcd}) -> {e}")
                skipped.append((corp, "상세 조회 실패")); continue

            if not grade:
                print(f"⏭ 등급 없음: {name} (요청: {corp}, cmpCd={cmpcd})")
                skipped.append((corp, "등급 없음")); continue

            rows.append({"요청기업명": corp, "회사명": name, "cmpCd": cmpcd, "등급": grade})

            if i % 10 == 0:
                print(f"  진행률: {i}/{len(companies)}")
            time.sleep(0.3)
    finally:
        driver.quit()

    if not rows:
        print("⚠ 등급을 추출한 기업이 없습니다.")
        return

    df = pd.DataFrame(rows).set_index("회사명").sort_index()
    ts = pd.Timestamp.now().strftime("%Y%m%d_%H%M")
    out = f"나이스_회사채등급_by_url_{ts}.csv"
    df.to_csv(out, encoding="utf-8-sig")
    print(f"\n✅ 저장 완료: {out}")
    print(df.head(10))

    if skipped:
        print("\n— 건너뛴 기업(사유) —")
        for corp, why in skipped:
            print(f"  • {corp}: {why}")

if __name__ == "__main__":
    main()
