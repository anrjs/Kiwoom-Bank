# -*- coding: utf-8 -*-
# """
# NICE 신용평가 - 검색 결과가 '목록(표)'로 뜨는 경우까지 처리
# - 검색 후 바로 상세(companyGradeInfo)로 이동하면 기존과 동일하게 처리
# - 검색 결과가 /search/search.do (기업 목록 표)로 뜨면,
#   표의 '채권' 칼럼에 값이 있는 기업들만 순서대로 cmpCd를 수집한 뒤 상세 페이지에서 등급 파싱
# - 회사명은 상세 페이지에서 확정 추출(div.tbl_type99 > table) → 정확도 보장
# """

import os
import re
import time
import unicodedata
from datetime import datetime
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


# -------------------- 기본 설정 --------------------
BASE = "https://www.nicerating.com"
HOME = f"{BASE}/"
SEARCH_TIMEOUT = 20
REQUEST_TIMEOUT = 15
HEADLESS = True  # 디버깅 시 False

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/118.0.0.0 Safari/537.36"
    )
}

# -------------------- 이름/등급 파서 (상세 페이지) --------------------
def _extract_name_from_tbl_type99(soup: BeautifulSoup) -> str | None:
    tbl = soup.select_one("div.tbl_type99 table")
    if not tbl:
        return None
    tbody = tbl.find("tbody")
    first_td = (tbody.find("td") if tbody else tbl.find("td"))
    return first_td.get_text(" ", strip=True) if first_td else None

def _extract_grade_primary_tbl1(soup: BeautifulSoup) -> str | None:
    table = soup.find("table", {"id": "tbl1"})
    if not table:
        return None
    tds = table.find_all("td", class_="cell_txt01")
    if not tds:
        return None
    return tds[0].get_text(strip=True) or None

LONGTERM_GRADE_RE = re.compile(
    r"^(AAA|AA\+|AA|AA\-|A\+|A|A\-|BBB\+|BBB|BBB\-|BB\+|BB|BB\-|B\+|B|B\-|CCC|CC|C|D)$"
)
OUTLOOK_RE = re.compile(r"(안정적|긍정적|부정적|유동적|Stable|Positive|Negative|Developing)", re.I)

def _extract_grade_from_major_table(soup: BeautifulSoup) -> str | None:
    """상세 페이지 '주요 등급내역'의 '회사채' 행에서 현재 등급/전망 보강 추출."""
    for tr in soup.find_all("tr"):
        text = tr.get_text(" ", strip=True)
        if "회사채" in text:
            toks = text.replace("/", " ").split()
            grades = [x for x in toks if LONGTERM_GRADE_RE.match(x)]
            outs   = [x for x in toks if OUTLOOK_RE.search(x)]
            if grades:
                g = grades[-1]
                return f"{g} {outs[-1]}" if outs else g
    return None

def fetch_company_and_grade_by_cmpcd(cmpCd: str, session: requests.Session) -> tuple[str, str]:
    """상세 페이지에서 회사명/채권 등급 파싱(원래 하던 방식)."""
    url = f"{BASE}/disclosure/companyGradeInfo.do?cmpCd={cmpCd}&deviceType=N&isPaidMember=false"
    resp = session.get(url, headers=HEADERS, timeout=REQUEST_TIMEOUT)
    resp.raise_for_status()
    soup = BeautifulSoup(resp.text, "html.parser")

    # 회사명
    name = _extract_name_from_tbl_type99(soup)
    if not name:
        for sel in ["div.cont_title h3", "h3.tit", ".company_name", ".cmp_name", "div.title_area h3"]:
            el = soup.select_one(sel)
            if el:
                name = el.get_text(strip=True)
                break
    if not name:
        title_text = soup.title.get_text(strip=True) if soup.title else ""
        name = title_text.split("|")[0].split("-")[0].strip() or cmpCd

    # 등급
    grade = _extract_grade_primary_tbl1(soup) or _extract_grade_from_major_table(soup) or ""
    return name, grade


# -------------------- 문자열 보정/유사도 --------------------
ALIASES = [
    (re.compile(r"\b에스케이", re.I), "SK"),
    (re.compile(r"\b엘지", re.I), "LG"),
    (re.compile(r"\b씨제이", re.I), "CJ"),
    (re.compile(r"\b케이티\b", re.I), "KT"),
    (re.compile(r"\b케이비\b", re.I), "KB"),
    (re.compile(r"\b엔에이치\b", re.I), "NH"),
    (re.compile(r"\b에이치디", re.I), "HD"),
    (re.compile(r"\b에이케이\b", re.I), "AK"),
    (re.compile(r"\b포스코", re.I), "POSCO"),
    (re.compile(r"\b씨제이", re.I), "CJ"),
    (re.compile(r"\b케이비", re.I), "KB"),
    (re.compile(r"\b지에스", re.I), "GS"),
    (re.compile(r"\b아이비", re.I), "IB"),
    (re.compile(r"\b비엑스", re.I), "BX"),
    (re.compile(r"\b에이아이", re.I), "AI"),

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


# -------------------- 검색/페이지 전환 유틸 --------------------
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
            if el.is_displayed():
                return el
        except Exception:
            pass
    raise RuntimeError("검색 입력창을 찾지 못했습니다.")

def _close_overlays(driver):
    for sel in ["button.close", ".btn_close", "a.close", "button[aria-label='닫기']"]:
        try:
            for el in driver.find_elements(By.CSS_SELECTOR, sel):
                if el.is_displayed():
                    el.click()
        except Exception:
            pass

def _parse_cmpcd_from_url(url: str) -> str | None:
    try:
        q = parse_qs(urlparse(url).query)
        if "cmpCd" in q and q["cmpCd"]:
            return q["cmpCd"][0]
    except Exception:
        pass
    m = re.search(r"cmpCd=(\d+)", url)
    return m.group(1) if m else None


# -------------------- 검색 결과 '목록(표)' 파서 --------------------
# cmpCd 패턴(링크/onclick/속성 모두)
CMP_RE = re.compile(r"cmpCd=(\d+)")
JS_CMP_RE = re.compile(r"fn_cmpGradeInfo\('(\d+)'\)")
ANY_CODE_RE = re.compile(r"(\d{7,8})")  # 안전 장치: 7~8자리 숫자

# 채권 칼럼 텍스트 인지(장기등급/전망; A1같은 CP는 배제)
GRADE_CELL_RE = re.compile(
    r"(AAA|AA\+|AA|AA-|A\+|A|A-|BBB\+|BBB|BBB-|BB\+|BB|BB-|B\+|B|B-|CCC|CC|C|D)"
    r"(?:\s*/\s*(Stable|Positive|Negative|Developing|안정적|긍정적|부정적|유동적))?",
    re.I
)

def _extract_candidates_from_search_table(html: str) -> list[dict]:
    """
    /search/search.do 결과 테이블에서
    - cmpCd
    - name_hint(행 내 텍스트)
    - list_grade(채권 칼럼 추정 값)
    을 뽑는다. (표의 순서 보존)
    """
    soup = BeautifulSoup(html, "html.parser")

    # 표(클래스가 바뀌어도 첫 번째 테이블을 기본으로 시도)
    table = soup.select_one("div.tbl_type01 table") or soup.find("table")
    if not table:
        return []

    out: list[dict] = []
    tbody = table.find("tbody") or table

    for tr in tbody.find_all("tr", recursive=False):
        tds = tr.find_all("td")
        if not tds:
            continue

        # 1) cmpCd 추출 (행 내부의 href/onclick/속성 전체 스캔)
        cmpcd = None
        # a[href]
        for a in tr.select('a[href]'):
            href = a.get("href") or ""
            m = CMP_RE.search(href) or JS_CMP_RE.search(href)
            if m:
                cmpcd = m.group(1); break
        if not cmpcd:
            # onclick들
            for el in tr.find_all(onclick=True):
                oc = el.get("onclick") or ""
                m = JS_CMP_RE.search(oc) or CMP_RE.search(oc) or ANY_CODE_RE.search(oc)
                if m:
                    code = m.group(1)
                    if len(code) >= 7:
                        cmpcd = code; break
        if not cmpcd:
            # 모든 속성에서 검색 (희귀)
            for el in tr.find_all(True):
                for k, v in el.attrs.items():
                    if isinstance(v, str):
                        m = JS_CMP_RE.search(v) or CMP_RE.search(v) or ANY_CODE_RE.search(v)
                        if m:
                            code = m.group(1)
                            if len(code) >= 7:
                                cmpcd = code; break
                if cmpcd:
                    break

        # 2) name_hint (기업명 추정 - 상세에서 확정하지만, 로깅용)
        name_hint = ""
        a_name = tr.select_one('a[href*="companyGradeInfo.do"], a[href^="javascript:fn_cmpGradeInfo"]')
        if a_name:
            name_hint = a_name.get_text(" ", strip=True)
        if not name_hint:
            # 첫 번째 비어있지 않은 td 텍스트
            for td in tds:
                txt = td.get_text(" ", strip=True)
                if txt:
                    name_hint = txt; break

        # 3) '채권' 칼럼 값 추정
        list_grade = None
        for td in tds:
            text = td.get_text(" ", strip=True)
            # A1 같은 CP 등급은 배제(장기등급 패턴만 허용)
            m = GRADE_CELL_RE.search(text)
            if m:
                g = m.group(1)
                o = m.group(2)
                list_grade = f"{g} {o}" if o else g
                break

        # 필터: '채권' 값이 있는 행만 사용
        if cmpcd and list_grade:
            out.append({"cmpCd": cmpcd, "name_hint": name_hint, "list_grade": list_grade})

    return out


# -------------------- 검색 실행 → 상세/목록 분기 --------------------
def search_and_collect(driver: webdriver.Chrome, query: str, session: requests.Session) -> list[dict]:
    """
    하나의 검색어(query)에 대해
    - 바로 상세페이지로 이동: cmpCd 파싱 → 상세 파싱
    - 목록(표) 페이지로 이동: 표에서 cmpCd+채권값 있는 행만 수집 → 각 상세 파싱
    """
    results: list[dict] = []

    # 원문/별칭 2회 시도
    for attempt, q in enumerate([query, aliasize(query)], 1):
        driver.get(HOME)
        time.sleep(1.0)
        _close_overlays(driver)

        box = _find_search_box(driver)
        box.clear(); box.send_keys(q); box.send_keys(Keys.ENTER)

        # 결과 대기
        try:
            WebDriverWait(driver, SEARCH_TIMEOUT).until(
                EC.any_of(
                    EC.url_contains("companyGradeInfo.do"),
                    EC.url_contains("/search/search.do"),
                    EC.presence_of_element_located((By.CSS_SELECTOR, 'a[href*="companyGradeInfo.do"]')),
                    EC.presence_of_element_located((By.CSS_SELECTOR, '[onclick*="fn_cmpGradeInfo("]'))
                )
            )
        except Exception:
            pass

        curr_url = driver.current_url

        # 1) 상세로 바로 이동한 경우
        cmpcd = _parse_cmpcd_from_url(curr_url)
        if cmpcd:
            name, grade = fetch_company_and_grade_by_cmpcd(cmpcd, session)
            if grade:
                results.append({
                    "요청검색어": query,
                    "회사명": name,
                    "cmpCd": cmpcd,
                    "등급": grade
                })
            return results  # 바로 상세로 들어갔으면 종료

        # 2) 목록(표) 페이지인 경우: 표 파싱
        if "/search/search.do" in curr_url:
            html = driver.page_source
            candidates = _extract_candidates_from_search_table(html)
            if not candidates:
                continue  # 별칭 시도
            # 표의 순서대로 상세 파싱
            for cand in candidates:
                code = cand["cmpCd"]
                name, grade = fetch_company_and_grade_by_cmpcd(code, session)
                if not grade:
                    continue
                results.append({
                    "요청검색어": query,
                    "회사명": name,
                    "cmpCd": code,
                    "등급": grade
                })
            return results

        # 3) 그 밖의 화면: DOM에서 직접 후보를 찾아 상세로(예전 로직 폴백)
        html = driver.page_source
        # onclick/href에서 cmpCd 수색
        soup = BeautifulSoup(html, "html.parser")
        code = None
        for a in soup.select('a[href*="companyGradeInfo.do"]'):
            m = re.search(r"cmpCd=(\d+)", a.get("href", ""))
            if m: code = m.group(1); break
        if not code:
            for el in soup.find_all(onclick=True):
                m = JS_CMP_RE.search(el.get("onclick",""))
                if m: code = m.group(1); break

        if code:
            name, grade = fetch_company_and_grade_by_cmpcd(code, session)
            if grade:
                results.append({
                    "요청검색어": query,
                    "회사명": name,
                    "cmpCd": code,
                    "등급": grade
                })
            return results

        # alias 시도로 재도전
    return results


# -------------------- I/O & 메인 파이프라인 --------------------
def load_companies_from_txt() -> list[str]:
    base_dir = os.path.dirname(__file__)
    path = os.path.join(base_dir, "..", "data", "input", "companies.txt")
    if not os.path.exists(path):
        return []
    with open(path, "r", encoding="utf-8-sig") as f:
        names = [ln.strip() for ln in f if ln.strip()]
    return names

def main():
    companies = load_companies_from_txt()
    print(f"📋 대상 검색어 수: {len(companies)}")

    options = _stealth_options()
    driver = webdriver.Chrome(service=Service(ChromeDriverManager().install()), options=options)
    _post_launch_stealth(driver)

    session = requests.Session()
    session.headers.update(HEADERS)

    rows, skipped = [], []
    try:
        for i, q in enumerate(companies, 1):
            try:
                found = search_and_collect(driver, q, session)
            except Exception as e:
                print(f"❗ 검색 실패: {q} -> {e}")
                skipped.append((q, "검색 실패")); continue

            if not found:
                print(f"🔎 결과 없음: {q}")
                skipped.append((q, "결과 없음")); continue

            rows.extend(found)
            if i % 5 == 0:
                print(f"  진행률: {i}/{len(companies)}")
            time.sleep(0.3)
    finally:
        driver.quit()

    if not rows:
        print("⚠ 수집된 결과가 없습니다.")
        return

    df = pd.DataFrame(rows).drop_duplicates(subset=["cmpCd"]).set_index("회사명").sort_index()
    print(df.head(10))

    # 저장: Kiwoom-Bank/data/output/
    base_dir = os.path.dirname(__file__)
    out_dir = os.path.join(base_dir, "..", "data", "output")
    os.makedirs(out_dir, exist_ok=True)
    out_path = os.path.join(out_dir, f"나이스_회사채등급_by_search_{datetime.now():%Y%m%d_%H%M}.csv")
    df.to_csv(out_path, encoding="utf-8-sig")
    print(f"\n✅ 저장 완료: {out_path}")

    if skipped:
        print("\n— 건너뛴 검색어(사유) —")
        for name, why in skipped:
            print(f"  • {name}: {why}")

if __name__ == "__main__":
    main()
