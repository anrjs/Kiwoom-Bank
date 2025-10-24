# -*- coding: utf-8 -*-
"""
NICE 신용평가 - 병렬 검색 크롤러(견고화 버전)
- 검색을 직접 URL(/search/search.do)로 열어 상세/목록 모두 처리
- 목록(표)면 '채권' 칼럼 값이 있는 행만 순서대로 상세 재파싱
- 상세 페이지 요청은 500/502/503/504/429 등 일시 오류 시 재시도
- 워커(WebDriver) 세션 깨질 경우 자동 재생성 + 1회 재시도
"""

import os
import re
import time
import math
import unicodedata
from datetime import datetime
from difflib import SequenceMatcher
from urllib.parse import urlparse, parse_qs, quote_plus
from concurrent.futures import ThreadPoolExecutor, as_completed

import requests
import pandas as pd
from bs4 import BeautifulSoup

# Selenium
from selenium import webdriver
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.common.by import By
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.common.exceptions import WebDriverException
from webdriver_manager.chrome import ChromeDriverManager

# -------------------- 기본 설정 --------------------
BASE = "https://www.nicerating.com"
HOME = f"{BASE}/"
SEARCH_TIMEOUT = 20
REQUEST_TIMEOUT = 15
HEADLESS = True          # 디버깅 시 False
MAX_WORKERS = 4          # 동시에 띄울 크롬 수(3~6 권장)
BATCH_SIZE_AUTO = True   # True면 회사 수/워커 수로 자동 분할

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/118.0.0.0 Safari/537.36"
    ),
}

TRANSIENT_STATUS = {500, 502, 503, 504, 429}

# -------------------- 상세 페이지 파서(기존 로직) --------------------
def _extract_name_from_tbl_type99(soup: BeautifulSoup) -> str | None:
    tbl = soup.select_one("div.tbl_type99 table")
    if not tbl:
        return None
    tbody = tbl.find("tbody")
    first_td = (tbody.find("td") if tbody else tbl.find("td"))
    return first_td.get_text(" ", strip=True) if first_td else None  # 

def _extract_grade_primary_tbl1(soup: BeautifulSoup) -> str | None:
    table = soup.find("table", {"id": "tbl1"})
    if not table:
        return None
    tds = table.find_all("td", class_="cell_txt01")
    if not tds:
        return None
    return tds[0].get_text(strip=True) or None  # 

LONGTERM_GRADE_RE = re.compile(
    r"^(AAA|AA\+|AA|AA\-|A\+|A|A\-|BBB\+|BBB|BBB\-|BB\+|BB|BB\-|B\+|B|B\-|CCC|CC|C|D)$"
)
OUTLOOK_RE = re.compile(r"(안정적|긍정적|부정적|유동적|Stable|Positive|Negative|Developing)", re.I)

def _extract_grade_from_major_table(soup: BeautifulSoup) -> str | None:
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

# -------------------- Requests 재시도 유틸 --------------------
def _retry_get(session: requests.Session, url: str, max_retries=2, backoff=2) -> requests.Response:
    """
    500/502/503/504/429 등 일시 오류 시 재시도.
    """
    last_exc = None
    for attempt in range(1, max_retries + 1):
        try:
            resp = session.get(url, headers={**HEADERS, "Referer": HOME}, timeout=REQUEST_TIMEOUT)
            # 상태코드 체크
            if resp.status_code in TRANSIENT_STATUS:
                raise requests.HTTPError(f"Transient {resp.status_code}", response=resp)
            resp.raise_for_status()
            return resp
        except requests.RequestException as e:
            last_exc = e
            # 일시 오류면 백오프 후 재시도
            st = getattr(e, "response", None).status_code if hasattr(e, "response") and e.response else None
            if st in TRANSIENT_STATUS and attempt < max_retries:
                print(f"⚠️ HTTP {st} 재시도 {attempt}/{max_retries} → {url}")
                time.sleep(backoff)
                continue
            break
    raise last_exc or RuntimeError("GET failed")

def fetch_company_and_grade_by_cmpcd(cmpCd: str, session: requests.Session) -> tuple[str, str]:
    """
    상세 페이지에서 회사명/채권 등급 파싱(원래 하던 방식).
    - 일시 오류 시 재시도
    """
    url = f"{BASE}/disclosure/companyGradeInfo.do?cmpCd={cmpCd}&deviceType=N&isPaidMember=false"
    resp = _retry_get(session, url, max_retries=2, backoff=2)
    soup = BeautifulSoup(resp.text, "html.parser")

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

# -------------------- Selenium 유틸 --------------------
def _stealth_options() -> Options:
    opts = Options()
    if HEADLESS: opts.add_argument("--headless=new")
    opts.add_argument("--no-sandbox")
    opts.add_argument("--disable-dev-shm-usage")
    opts.add_argument("--disable-gpu")
    opts.add_argument("--lang=ko-KR")
    opts.add_argument("--window-size=1280,2000")
    opts.add_argument(f"user-agent={HEADERS['User-Agent']}")
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

def _parse_cmpcd_from_url(url: str) -> str | None:
    try:
        q = parse_qs(urlparse(url).query)
        if "cmpCd" in q and q["cmpCd"]:
            return q["cmpCd"][0]
    except Exception:
        pass
    m = re.search(r"cmpCd=(\d+)", url)
    return m.group(1) if m else None

# -------------------- 목록(표) 파서 --------------------
CMP_RE = re.compile(r"cmpCd=(\d+)")
JS_CMP_RE = re.compile(r"fn_cmpGradeInfo\('(\d+)'\)")
ANY_CODE_RE = re.compile(r"(\d{7,8})")
GRADE_CELL_RE = re.compile(
    r"(AAA|AA\+|AA|AA-|A\+|A|A-|BBB\+|BBB|BBB-|BB\+|BB|BB-|B\+|B|B-|CCC|CC|C|D)"
    r"(?:\s*/\s*(Stable|Positive|Negative|Developing|안정적|긍정적|부정적|유동적))?",
    re.I
)

def _extract_candidates_from_search_table(html: str) -> list[dict]:
    """
    /search/search.do 결과 테이블에서
    - cmpCd
    - name_hint
    - list_grade(채권 칼럼 추정 값)
    을 추출. 표의 순서를 보존.
    """
    soup = BeautifulSoup(html, "html.parser")
    table = soup.select_one("div.tbl_type01 table") or soup.find("table")
    if not table:
        return []

    out, tbody = [], (table.find("tbody") or table)
    for tr in tbody.find_all("tr", recursive=False):
        tds = tr.find_all("td")
        if not tds:
            continue

        cmpcd = None
        for a in tr.select('a[href]'):
            href = a.get("href") or ""
            m = CMP_RE.search(href) or JS_CMP_RE.search(href)
            if m:
                cmpcd = m.group(1); break
        if not cmpcd:
            for el in tr.find_all(onclick=True):
                oc = el.get("onclick") or ""
                m = JS_CMP_RE.search(oc) or CMP_RE.search(oc) or ANY_CODE_RE.search(oc)
                if m and len(m.group(1)) >= 7:
                    cmpcd = m.group(1); break
        if not cmpcd:
            for el in tr.find_all(True):
                for _, v in el.attrs.items():
                    if isinstance(v, str):
                        m = JS_CMP_RE.search(v) or CMP_RE.search(v) or ANY_CODE_RE.search(v)
                        if m and len(m.group(1)) >= 7:
                            cmpcd = m.group(1); break
                if cmpcd: break

        name_hint = ""
        a_name = tr.select_one('a[href*="companyGradeInfo.do"], a[href^="javascript:fn_cmpGradeInfo"]')
        if a_name: name_hint = a_name.get_text(" ", strip=True)
        if not name_hint:
            for td in tds:
                txt = td.get_text(" ", strip=True)
                if txt: name_hint = txt; break

        list_grade = None
        for td in tds:
            text = td.get_text(" ", strip=True)
            m = GRADE_CELL_RE.search(text)
            if m:
                g, o = m.group(1), m.group(2)
                list_grade = f"{g} {o}" if o else g
                break

        if cmpcd and list_grade:
            out.append({"cmpCd": cmpcd, "name_hint": name_hint, "list_grade": list_grade})
    return out

# -------------------- 검색 실행(견고) --------------------
def _build_search_url(query: str) -> str:
    return f"{BASE}/search/search.do?mainSType=CMP&mainSText={quote_plus(query)}"

def search_and_collect_resilient(driver: webdriver.Chrome, query: str, session: requests.Session) -> list[dict]:
    """
    - 검색 URL로 직접 진입
    - 상세로 바로 리다이렉트되면 cmpCd 추출
    - 목록(표)면 테이블 파싱 → '채권' 칼럼 있는 행들만 상세 재파싱
    - 원문/별칭/공백제거 변형으로 최대 4회 시도
    - DOM 늦게 뜰 때를 대비해 wait → 재파싱 1회 더
    """
    results: list[dict] = []

    candidates_query = [
        query,
        aliasize(query),
        aliasize(query).replace(" ", ""),
        query.replace(" ", "")
    ]
    seen_codes = set()

    for q in candidates_query:
        # 1) 검색 URL로 직접 진입
        driver.get(_build_search_url(q))

        # 2) 상세로 리다이렉트되거나, 목록 테이블이 나타날 때까지 대기
        try:
            WebDriverWait(driver, SEARCH_TIMEOUT).until(
                EC.any_of(
                    EC.url_contains("companyGradeInfo.do"),
                    EC.presence_of_element_located((By.CSS_SELECTOR, "div.tbl_type01 table")),
                    EC.presence_of_element_located((By.CSS_SELECTOR, "table"))
                )
            )
        except Exception:
            pass

        # 3) 상세로 바로 간 경우
        cmpcd = _parse_cmpcd_from_url(driver.current_url)
        if cmpcd:
            if cmpcd not in seen_codes:
                name, grade = fetch_company_and_grade_by_cmpcd(cmpcd, session)
                if grade:
                    seen_codes.add(cmpcd)
                    results.append({"요청검색어": query, "회사명": name, "cmpCd": cmpcd, "등급": grade})
            return results  # 상세면 한 건으로 종료

        # 4) 목록(표) 파싱 (첫 시도)
        html = driver.page_source
        cands = _extract_candidates_from_search_table(html)
        if not cands:
            # 0.8초 더 기다렸다가 다시 파싱(로딩 지연 대비)
            time.sleep(0.8)
            html = driver.page_source
            cands = _extract_candidates_from_search_table(html)

        if cands:
            # 표의 순서대로 상세 재파싱
            for cand in cands:
                code = cand["cmpCd"]
                if code in seen_codes:
                    continue
                name, grade = fetch_company_and_grade_by_cmpcd(code, session)
                if not grade:
                    continue
                seen_codes.add(code)
                results.append({"요청검색어": query, "회사명": name, "cmpCd": code, "등급": grade})
            return results

        # 이 변형으로도 실패하면 다음 변형으로 계속
    return results

# -------------------- 병렬 워커 --------------------
def _new_driver(driver_path: str) -> webdriver.Chrome:
    options = _stealth_options()
    driver = webdriver.Chrome(service=Service(driver_path), options=options)
    _post_launch_stealth(driver)
    return driver

def worker_process(batch: list[str], worker_id: int, driver_path: str) -> dict:
    """
    스레드 1개가 배치(기업 리스트)를 처리.
    - 세션 깨지면 드라이버 재생성 + 1회 재시도
    """
    rows, skipped = [], []
    driver = _new_driver(driver_path)

    session = requests.Session()
    session.headers.update(HEADERS)

    try:
        for i, q in enumerate(batch, 1):
            retry_once = False
            while True:
                try:
                    found = search_and_collect_resilient(driver, q, session)
                    if not found:
                        print(f"[W{worker_id}] 🔎 결과 없음: {q}")
                        skipped.append((q, "결과 없음"))
                    else:
                        rows.extend(found)
                    break  # 정상 처리 or 결과 없음 → 다음 회사로
                except WebDriverException as e:
                    msg = str(e).lower()
                    if not retry_once and ("invalid session id" in msg or "disconnected" in msg or "chrome not reachable" in msg):
                        print(f"[W{worker_id}] ♻️ 드라이버 재생성 후 재시도: {q}")
                        try:
                            driver.quit()
                        except Exception:
                            pass
                        driver = _new_driver(driver_path)
                        retry_once = True
                        continue  # 같은 회사 한 번 더 시도
                    else:
                        print(f"[W{worker_id}] ❗ 검색 실패: {q} -> {e}")
                        skipped.append((q, "검색 실패"))
                        break
                except Exception as e:
                    print(f"[W{worker_id}] ❗ 검색 실패: {q} -> {e}")
                    skipped.append((q, "검색 실패"))
                    break

            if i % 10 == 0:
                print(f"[W{worker_id}] 진행률: {i}/{len(batch)}")
            time.sleep(0.25)  # 서버 예의, 너무 줄이지 마세요
    finally:
        try:
            driver.quit()
        except Exception:
            pass

    return {"rows": rows, "skipped": skipped}

# -------------------- 입/출력 & 메인 --------------------
def load_companies_from_txt() -> list[str]:
    base_dir = os.path.dirname(__file__)
    path = os.path.join(base_dir, "..", "data", "input", "companies.txt")
    if not os.path.exists(path):
        return []
    with open(path, "r", encoding="utf-8-sig") as f:
        return [ln.strip() for ln in f if ln.strip()]

def save_dataframe(df: pd.DataFrame) -> str:
    base_dir = os.path.dirname(__file__)
    out_dir = os.path.join(base_dir, "..", "data", "output")
    os.makedirs(out_dir, exist_ok=True)
    out_path = os.path.join(out_dir, f"나이스_회사채등급_by_search_parallel_{datetime.now():%Y%m%d_%H%M}.csv")
    df.to_csv(out_path, encoding="utf-8-sig")
    return out_path

def chunk_by_size(lst: list, size: int) -> list[list]:
    return [lst[i:i+size] for i in range(0, len(lst), size)]

def main():
    companies = load_companies_from_txt()
    if not companies:
        print("⚠ companies.txt가 비어있거나 경로가 잘못되었습니다.")
        return
    print(f"📋 대상 검색어 수: {len(companies)}")

    # 크롬 드라이버는 메인에서 한 번만 설치하여 경로 공유(스레드들 재활용)
    driver_path = ChromeDriverManager().install()

    # 배치 분할
    if BATCH_SIZE_AUTO:
        size = max(1, math.ceil(len(companies) / MAX_WORKERS))
    else:
        size = 40  # 원하는 고정 배치 크기
    batches = chunk_by_size(companies, size)
    print(f"🧵 워커 수: {MAX_WORKERS}, 배치 {len(batches)}개, 배치 크기 ≈ {size}")

    rows_all, skipped_all = [], []

    with ThreadPoolExecutor(max_workers=MAX_WORKERS) as ex:
        futs = {ex.submit(worker_process, batch, idx+1, driver_path): idx+1
                for idx, batch in enumerate(batches)}
        for fut in as_completed(futs):
            wid = futs[fut]
            try:
                res = fut.result()
                rows_all.extend(res["rows"])
                skipped_all.extend(res["skipped"])
                print(f"[W{wid}] ✅ 완료: rows={len(res['rows'])}, skipped={len(res['skipped'])}")
            except Exception as e:
                print(f"[W{wid}] ❗ 워커 예외: {e}")

    if not rows_all:
        print("⚠ 수집된 결과가 없습니다.")
        return

    df = (pd.DataFrame(rows_all)
            .drop_duplicates(subset=["cmpCd"])
            .set_index("회사명")
            .sort_index())
    print(df.head(10))

    out_path = save_dataframe(df)
    print(f"\n✅ 저장 완료: {out_path}")

    if skipped_all:
        print("\n— 건너뛴 검색어(사유) —")
        for name, why in skipped_all[:80]:
            print(f"  • {name}: {why}")
        if len(skipped_all) > 80:
            print(f"  …외 {len(skipped_all)-80}건")

if __name__ == "__main__":
    main()
