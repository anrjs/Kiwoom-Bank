# -*- coding: utf-8 -*-
"""
NICE 신용평가 - 병렬 검색 크롤러(캐시 + 리트라이 강화)
- 디스크 캐시: data/output/*.csv 를 모아 인덱스 구축 → 캐시 히트 시 즉시 반환(크롤링 생략)
- 런타임 캐시: 한 번 수집한 결과는 같은 실행 중 재사용
- 1라운드: 병렬(스레드) 크롤링
- 2라운드(최종 리트라이): 1라운드 '검색 실패/결과 없음'만 직렬 재검색(대기시간 상향, 표에서 채권값 없어도 cmpCd만 있으면 상세 재파싱)
- 상세 페이지 요청은 500/502/503/504/429 등 일시 오류 시 재시도
- 워커 세션 깨지면 드라이버 재생성 후 1회 재시도
"""
# 필요 패키지
# pip install selenium webdriver-manager beautifulsoup4 requests pandas

import os
import re
import time
import math
import unicodedata
import threading
import argparse
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

# 등급 문자열 정리
def _clean_grade(g: str | None) -> str:
    if not g:
        return ""
    g = str(g).strip()
    # 등급 뒤에 붙은 불필요한 쉼표/공백 제거 (예: "A," -> "A")
    g = re.sub(r"[\s,;]+$", "", g)
    return g

def build_two_column_df(companies: list[str], rows_all: list[dict]) -> pd.DataFrame:
    """
    companies.txt 순서를 보존하여
    [회사명(요청검색어), 등급] 2열 DataFrame을 만든다.
    - 동일 검색어에서 다수 기업이 발견되면 등급있음/이름일치/포함/유사도 기준으로 1건 선택
    """
    # 수집 결과가 없으면 빈 등급으로 반환
    if not rows_all:
        return pd.DataFrame({"회사명": companies, "등급": [""] * len(companies)})

    df_rows = pd.DataFrame(rows_all)
    # 필요한 컬럼 보정
    for c in ["요청검색어", "회사명", "등급"]:
        if c not in df_rows.columns:
            df_rows[c] = ""
    # 등급 정리
    df_rows["등급"] = df_rows["등급"].map(_clean_grade)

    results = []
    for q in companies:
        cand = df_rows[df_rows["요청검색어"] == q]
        if cand.empty:
            results.append({"회사명": q, "등급": ""})
            continue

        q_norm = normalize_text(aliasize(q))

        # 스코어 계산: 등급 유무>정확일치>부분포함>유사도
        def _score(row) -> float:
            comp = str(row.get("회사명", ""))
            grade = _clean_grade(row.get("등급", ""))
            comp_norm = normalize_text(aliasize(comp))
            sim = name_similarity(comp_norm, q_norm)
            s = 0.0
            if grade: s += 2.0                # 등급 있는 항목 가중치
            if comp_norm == q_norm: s += 1.5  # 정확 일치
            if (q_norm and comp_norm) and (q_norm in comp_norm or comp_norm in q_norm):
                s += 1.0                      # 부분 포함
            s += 0.5 * sim                    # 유사도 보정
            return s

        # 최상 스코어 1건 선택
        best = cand.copy()
        best["__score"] = best.apply(_score, axis=1)
        best = best.sort_values("__score", ascending=False).iloc[0]
        results.append({"회사명": q, "등급": _clean_grade(best.get("등급", ""))})

    return pd.DataFrame(results)


# -------------------- 기본 설정 --------------------
BASE = "https://www.nicerating.com"
HOME = f"{BASE}/"

SEARCH_TIMEOUT = 20            # 1라운드 기본 wait(초)
REQUEST_TIMEOUT = 15
HEADLESS = True                # 디버깅 시 False
MAX_WORKERS = 4                # 3~6 권장
BATCH_SIZE_AUTO = True         # True면 회사 수/워커 수로 자동 분할

# 최종 리트라이(직렬) 설정
FINAL_RETRY = True
FINAL_RETRY_TIMEOUT = 35       # 리트라이 wait(초) - 더 길게
FINAL_RETRY_SLEEP = 1.2        # 목록표 재파싱 대기(초)
REQUIRE_BOND_IN_TABLE_FIRST = True   # 1라운드: 표에서 '채권' 칼럼 있는 행만
REQUIRE_BOND_IN_TABLE_RETRY = False  # 2라운드: 표에서 채권 칼럼 없어도 cmpCd만 있으면 상세 재파싱

# 캐시 설정
USE_CACHE_FIRST = True         # ✅ 캐시 우선 사용
CACHE_MATCH_EXACT_ONLY = True  # True: 정규화한 이름/요청검색어 '정확' 일치만 매칭(권장)
# False로 바꾸면 퍼지 매칭(유사도)도 시도하도록 확장할 수 있음(아래 함수 내 주석 참고)

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/118.0.0.0 Safari/537.36"
    ),
}
TRANSIENT_STATUS = {500, 502, 503, 504, 429}

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
    if not s:
        return ""
    s = unicodedata.normalize("NFKC", s).strip().lower()
    s = re.sub(r"(주식회사|㈜|\(주\)|유한회사|홀딩스)", " ", s)
    s = re.sub(r"[\(\)\[\]\{\}]", " ", s)
    return re.sub(r"\s+", " ", s)

def name_similarity(a: str, b: str) -> float:
    return SequenceMatcher(None, normalize_text(a), normalize_text(b)).ratio()


# -------------------- 상세 페이지 파서(기존 로직 유지) --------------------
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

def _retry_get(session: requests.Session, url: str, max_retries=2, backoff=2) -> requests.Response:
    """500/502/503/504/429 등 일시 오류 시 재시도."""
    last_exc = None
    for attempt in range(1, max_retries + 1):
        try:
            resp = session.get(url, headers={**HEADERS, "Referer": HOME}, timeout=REQUEST_TIMEOUT)
            if resp.status_code in TRANSIENT_STATUS:
                raise requests.HTTPError(f"Transient {resp.status_code}", response=resp)
            resp.raise_for_status()
            return resp
        except requests.RequestException as e:
            last_exc = e
            st = getattr(e, "response", None).status_code if hasattr(e, "response") and e.response else None
            if st in TRANSIENT_STATUS and attempt < max_retries:
                print(f"⚠️ HTTP {st} 재시도 {attempt}/{max_retries} → {url}")
                time.sleep(backoff)
                continue
            break
    raise last_exc or RuntimeError("GET failed")

def fetch_company_and_grade_by_cmpcd(cmpCd: str, session: requests.Session) -> tuple[str, str]:
    """상세 페이지(회사명/채권등급) 파싱."""
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


# -------------------- 캐시(디스크 & 런타임) --------------------
DISK_CACHE = {"by_name": {}, "by_req": {}}
RUNTIME_CACHE_BY_NAME = {}   # { name_norm: {"회사명":..., "cmpCd":..., "등급":...} }
CACHE_LOCK = threading.Lock()

def _output_dir() -> str:
    base_dir = os.path.dirname(__file__)
    return os.path.join(base_dir, "..", "data", "output")

def _load_disk_cache() -> dict:
    """data/output/*.csv 파일들을 모아 캐시 인덱스 생성."""
    out_dir = _output_dir()
    if not os.path.isdir(out_dir):
        return {"by_name": {}, "by_req": {}}

    csv_files = [f for f in os.listdir(out_dir) if f.lower().endswith(".csv")]
    if not csv_files:
        return {"by_name": {}, "by_req": {}}

    frames = []
    for fn in csv_files:
        path = os.path.join(out_dir, fn)
        try:
            df = pd.read_csv(path, encoding="utf-8-sig")
        except Exception:
            try:
                df = pd.read_csv(path, encoding="utf-8-sig", index_col=0).reset_index()
                if "index" in df.columns and "회사명" not in df.columns:
                    df = df.rename(columns={"index": "회사명"})
            except Exception:
                continue

        # 필요한 컬럼 보정
        for col in ["회사명", "cmpCd", "등급", "요청검색어"]:
            if col not in df.columns:
                df[col] = None

        # 파일명에서 타임스탬프 파싱(예: ..._YYYYMMDD_HHMM.csv)
        ts = pd.Timestamp(1970, 1, 1)
        m = re.search(r"_(\d{8})[_-](\d{4})", fn)
        if m:
            try:
                ts = pd.to_datetime(m.group(1) + m.group(2), format="%Y%m%d%H%M")
            except Exception:
                pass
        df["source_ts"] = ts
        frames.append(df[["회사명", "cmpCd", "등급", "요청검색어", "source_ts"]])

    if not frames:
        return {"by_name": {}, "by_req": {}}

    cache_df = pd.concat(frames, ignore_index=True)
    cache_df["회사명"] = cache_df["회사명"].astype(str)
    cache_df["cmpCd"] = cache_df["cmpCd"].astype(str)
    cache_df.loc[cache_df["cmpCd"].isin(["", "nan", "None", "NaN"]), "cmpCd"] = None

    cache_df["name_norm"] = cache_df["회사명"].map(lambda s: normalize_text(aliasize(s)))
    if "요청검색어" in cache_df.columns:
        cache_df["req_norm"] = cache_df["요청검색어"].astype(str).map(lambda s: normalize_text(aliasize(s)))
    else:
        cache_df["req_norm"] = ""

    # 최신 항목이 남도록 정렬
    cache_df = cache_df.sort_values("source_ts")

    by_name, by_req = {}, {}
    for _, row in cache_df.iterrows():
        rec = {
            "회사명": row["회사명"],
            "cmpCd": row["cmpCd"],
            "등급": row["등급"],
            "source_ts": row["source_ts"],
        }
        if row["name_norm"]:
            by_name[row["name_norm"]] = rec
        if row["req_norm"]:
            by_req[row["req_norm"]] = rec

    return {"by_name": by_name, "by_req": by_req}

def _lookup_cache(query: str) -> dict | None:
    """쿼리를 캐시에서 조회. 런타임 캐시 → 디스크 캐시 순."""
    variants = [
        query,
        aliasize(query),
        query.replace(" ", ""),
        aliasize(query).replace(" ", ""),
    ]
    # 1) 런타임 캐시(정확 일치)
    with CACHE_LOCK:
        for v in variants:
            key = normalize_text(v)
            if key in RUNTIME_CACHE_BY_NAME:
                return RUNTIME_CACHE_BY_NAME[key]

    # 2) 디스크 캐시: 요청검색어 기준(정확 일치)
    for v in variants:
        key = normalize_text(v)
        if key in DISK_CACHE["by_req"]:
            return DISK_CACHE["by_req"][key]

    # 3) 디스크 캐시: 회사명 기준(정확 일치)
    for v in variants:
        key = normalize_text(v)
        if key in DISK_CACHE["by_name"]:
            return DISK_CACHE["by_name"][key]

    # (선택) 퍼지 매칭을 허용하려면 아래 주석 해제 + 임계치 조정
    # if not CACHE_MATCH_EXACT_ONLY:
    #     # by_name에서 유사도 최고 항목 선택(0.93 이상 가정)
    #     best_key, best_score, best_rec = None, 0.0, None
    #     for k, rec in DISK_CACHE["by_name"].items():
    #         s = name_similarity(k, normalize_text(query))
    #         if s > best_score:
    #             best_key, best_score, best_rec = k, s, rec
    #     if best_rec and best_score >= 0.93:
    #         return best_rec

    return None

def _update_runtime_cache(records: list[dict]) -> None:
    """동일 실행 중 수집한 결과를 런타임 캐시에 반영."""
    with CACHE_LOCK:
        for r in records:
            nm = normalize_text(aliasize(r["회사명"]))
            RUNTIME_CACHE_BY_NAME[nm] = {"회사명": r["회사명"], "cmpCd": r["cmpCd"], "등급": r["등급"]}


# -------------------- 목록(표) 파서 --------------------
CMP_RE = re.compile(r"cmpCd=(\d+)")
JS_CMP_RE = re.compile(r"fn_cmpGradeInfo\('(\d+)'\)")
ANY_CODE_RE = re.compile(r"(\d{7,8})")
GRADE_CELL_RE = re.compile(
    r"(AAA|AA\+|AA|AA-|A\+|A|A-|BBB\+|BBB|BBB-|BB\+|BB|BB-|B\+|B|B-|CCC|CC|C|D)"
    r"(?:\s*/\s*(Stable|Positive|Negative|Developing|안정적|긍정적|부정적|유동적))?",
    re.I
)

def _extract_candidates_from_search_table(html: str, require_bond=True) -> list[dict]:
    """
    /search/search.do 결과 테이블에서
    - cmpCd
    - name_hint
    - list_grade(채권 칼럼 값, 있으면)
    추출. require_bond=False면 '채권' 값 없어도 cmpCd만 있으면 후보 포함.
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

        # cmpCd
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
        if not cmpcd:
            continue

        # 이름 힌트
        name_hint = ""
        a_name = tr.select_one('a[href*="companyGradeInfo.do"], a[href^="javascript:fn_cmpGradeInfo"]')
        if a_name:
            name_hint = a_name.get_text(" ", strip=True)
        if not name_hint:
            for td in tds:
                txt = td.get_text(" ", strip=True)
                if txt:
                    name_hint = txt; break

        # '채권' 칼럼 값(있으면)
        list_grade = None
        for td in tds:
            text = td.get_text(" ", strip=True)
            m = GRADE_CELL_RE.search(text)
            if m:
                g, o = m.group(1), m.group(2)
                list_grade = f"{g} {o}" if o else g
                break

        if require_bond and not list_grade:
            continue

        out.append({"cmpCd": cmpcd, "name_hint": name_hint, "list_grade": list_grade})

    return out


# -------------------- 검색 실행(견고) --------------------
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

def _build_search_url(query: str) -> str:
    return f"{BASE}/search/search.do?mainSType=CMP&mainSText={quote_plus(query)}"

def search_and_collect_resilient(
    driver: webdriver.Chrome,
    query: str,
    session: requests.Session,
    wait_timeout: int,
    table_wait_extra: float,
    require_bond_in_table: bool
) -> list[dict]:
    """
    - 검색 URL로 직접 진입
    - 상세로 바로 리다이렉트되면 cmpCd 추출 후 상세 파싱
    - 목록(표)면 테이블 파싱 → (옵션) '채권' 칼럼 값 있는 행만 상세 재파싱
    - DOM 늦게 뜰 수 있어 재파싱 1회 더 시도
    """
    results: list[dict] = []
    candidates_query = [
        query,
        aliasize(query),
        aliasize(query).replace(" ", ""),
        query.replace(" ", ""),
    ]
    seen_codes = set()

    for q in candidates_query:
        driver.get(_build_search_url(q))
        try:
            WebDriverWait(driver, wait_timeout).until(
                EC.any_of(
                    EC.url_contains("companyGradeInfo.do"),
                    EC.presence_of_element_located((By.CSS_SELECTOR, "div.tbl_type01 table")),
                    EC.presence_of_element_located((By.CSS_SELECTOR, "table"))
                )
            )
        except Exception:
            pass

        # 상세로 바로 이동
        cmpcd = _parse_cmpcd_from_url(driver.current_url)
        if cmpcd:
            if cmpcd not in seen_codes:
                name, grade = fetch_company_and_grade_by_cmpcd(cmpcd, session)
                if grade:
                    seen_codes.add(cmpcd)
                    results.append({"요청검색어": query, "회사명": name, "cmpCd": cmpcd, "등급": grade})
                    _update_runtime_cache(results)  # 런타임 캐시 반영
            return results  # 상세면 1건으로 종료

        # 목록(표) 파싱
        html = driver.page_source
        cands = _extract_candidates_from_search_table(html, require_bond=require_bond_in_table)
        if not cands:
            time.sleep(table_wait_extra)
            html = driver.page_source
            cands = _extract_candidates_from_search_table(html, require_bond=require_bond_in_table)

        if cands:
            for cand in cands:
                code = cand["cmpCd"]
                if code in seen_codes:
                    continue
                name, grade = fetch_company_and_grade_by_cmpcd(code, session)
                if not grade:
                    continue
                seen_codes.add(code)
                item = {"요청검색어": query, "회사명": name, "cmpCd": code, "등급": grade}
                results.append(item)
            if results:
                _update_runtime_cache(results)  # 런타임 캐시 반영
            return results

        # 다음 변형으로 계속
    return results


# -------------------- 드라이버 관리 --------------------
def _new_driver(driver_path: str) -> webdriver.Chrome:
    options = _stealth_options()
    driver = webdriver.Chrome(service=Service(driver_path), options=options)
    _post_launch_stealth(driver)
    return driver


# -------------------- 병렬 워커 --------------------
def worker_process(batch: list[str], worker_id: int, driver_path: str) -> dict:
    """
    스레드 1개가 배치(기업 리스트) 처리.
    - 캐시 우선 조회
    - 세션 깨지면 드라이버 재생성 + 1회 재시도
    """
    rows, skipped = [], []
    driver = _new_driver(driver_path)
    session = requests.Session()
    session.headers.update(HEADERS)

    try:
        for i, q in enumerate(batch, 1):
            # 0) 캐시 히트 시 즉시 반환(크롤링 생략)
            if USE_CACHE_FIRST:
                cached = _lookup_cache(q)
                if cached and cached.get("등급"):
                    rows.append({
                        "요청검색어": q,
                        "회사명": cached["회사명"],
                        "cmpCd": cached.get("cmpCd"),
                        "등급": cached["등급"],
                        "source": "cache"
                    })
                    # 런타임 캐시도 최신화
                    _update_runtime_cache([{"회사명": cached["회사명"], "cmpCd": cached.get("cmpCd"), "등급": cached["등급"]}])
                    if i % 10 == 0:
                        print(f"[W{worker_id}] 진행률(캐시): {i}/{len(batch)}")
                    continue  # 다음 회사로

            # 1) 크롤링
            retry_once = False
            while True:
                try:
                    found = search_and_collect_resilient(
                        driver, q, session,
                        wait_timeout=SEARCH_TIMEOUT,
                        table_wait_extra=0.8,
                        require_bond_in_table=REQUIRE_BOND_IN_TABLE_FIRST
                    )
                    if not found:
                        print(f"[W{worker_id}] 🔎 결과 없음: {q}")
                        skipped.append((q, "결과 없음"))
                    else:
                        rows.extend(found)
                    break  # 정상 처리 or 결과 없음 → 다음 회사
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
                        continue
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
            time.sleep(0.25)  # 서버 예의
    finally:
        try:
            driver.quit()
        except Exception:
            pass

    return {"rows": rows, "skipped": skipped}


# -------------------- 최종 리트라이(직렬) --------------------
def retry_failed_serial(failed_names: list[str], driver_path: str) -> tuple[list[dict], list[tuple[str, str]]]:
    """
    1라운드에서 '검색 실패/결과 없음'이었던 기업:
    - 캐시 먼저 확인
    - 단일 드라이버로 직렬 재검색(대기 늘림)
    - 표에서 채권값 없어도 cmpCd만 있으면 상세 재파싱
    """
    rows, skipped = [], []
    if not failed_names:
        return rows, skipped

    print(f"\n🔁 최종 리트라이 대상 수: {len(failed_names)}")
    driver = _new_driver(driver_path)
    session = requests.Session()
    session.headers.update(HEADERS)

    try:
        for idx, q in enumerate(failed_names, 1):
            # 0) 캐시 재확인(1라운드 중 다른 워커가 수집했을 수도 있음)
            cached = _lookup_cache(q)
            if cached and cached.get("등급"):
                rows.append({
                    "요청검색어": q,
                    "회사명": cached["회사명"],
                    "cmpCd": cached.get("cmpCd"),
                    "등급": cached["등급"],
                    "source": "cache(retry)"
                })
                _update_runtime_cache([{"회사명": cached["회사명"], "cmpCd": cached.get("cmpCd"), "등급": cached["등급"]}])
                continue

            try:
                found = search_and_collect_resilient(
                    driver, q, session,
                    wait_timeout=FINAL_RETRY_TIMEOUT,
                    table_wait_extra=FINAL_RETRY_SLEEP,
                    require_bond_in_table=REQUIRE_BOND_IN_TABLE_RETRY
                )
                if not found:
                    print(f"[RETRY] 여전히 결과 없음: {q}")
                    skipped.append((q, "최종 결과 없음"))
                else:
                    rows.extend(found)
                    _update_runtime_cache(found)
            except Exception as e:
                print(f"[RETRY] ❗ 실패: {q} -> {e}")
                skipped.append((q, "최종 검색 실패"))

            if idx % 20 == 0:
                print(f"[RETRY] 진행률: {idx}/{len(failed_names)}")
            time.sleep(0.35)
    finally:
        try:
            driver.quit()
        except Exception:
            pass

    return rows, skipped


# -------------------- 입/출력 & 메인 --------------------
def load_companies_from_txt() -> list[str]:
    base_dir = os.path.dirname(__file__)
    path = os.path.join(base_dir, "..", "data", "input", "companies.txt")
    if not os.path.exists(path):
        return []
    with open(path, "r", encoding="utf-8-sig") as f:
        return [ln.strip() for ln in f if ln.strip()]

def save_dataframe(df: pd.DataFrame, suffix="parallel_cache") -> str:
    base_dir = os.path.dirname(__file__)
    out_dir = os.path.join(base_dir, "..", "data", "output")
    os.makedirs(out_dir, exist_ok=True)
    out_path = os.path.join(out_dir, f"나이스_회사채등급_by_search_{suffix}_{datetime.now():%Y%m%d_%H%M}.csv")
    df.to_csv(out_path, encoding="utf-8-sig")
    return out_path

def chunk_by_size(lst: list, size: int) -> list[list]:
    return [lst[i:i+size] for i in range(0, len(lst), size)]

# 추가: 프로그래밍 호출용 함수 (리스트 입력받아 실행하고 결과 반환)
def crawl_companies(companies: list[str]) -> tuple[pd.DataFrame, list[tuple[str, str]]]:
    """
    companies: list of company names (strings)
    returns: (df_final, skipped_all)
    """
    # 0) 디스크 캐시 로드 (한 번만)
    global DISK_CACHE
    DISK_CACHE = _load_disk_cache()
    print(f"💾 디스크 캐시 로드 완료: by_name={len(DISK_CACHE['by_name'])}, by_req={len(DISK_CACHE['by_req'])}")

    if not companies:
        raise ValueError("입력된 회사 리스트가 비어있습니다.")

    print(f"📋 대상 검색어 수: {len(companies)}")

    driver_path = ChromeDriverManager().install()

    # ---- 1라운드: 병렬 처리 ----
    if BATCH_SIZE_AUTO:
        size = max(1, math.ceil(len(companies) / MAX_WORKERS))
    else:
        size = 40
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

    # ---- 2라운드: 최종 리트라이(선택) ----
    if FINAL_RETRY:
        failed_names = [name for name, why in skipped_all if why in ("검색 실패", "결과 없음")]
        failed_names = list(dict.fromkeys(failed_names))  # 중복 제거, 순서 보존
        if failed_names:
            rows_retry, skipped_retry = retry_failed_serial(failed_names, driver_path)
            rows_all.extend(rows_retry)
            # 최종 스킵 갱신
            skipped_all = [(n, w) for (n, w) in skipped_all if n not in failed_names] + skipped_retry

    # rows_all: 앞 단계에서 수집한 원시 결과 (list[dict])
    df_final = build_two_column_df(companies, rows_all)
    return df_final, skipped_all

def main():
    # argparse로 터미널 입력 수신; 입력 없으면 기존 companies.txt 사용(기존 동작 유지)
    parser = argparse.ArgumentParser(description="NICE 회사채등급 크롤러 - 회사명을 인자로 넘기거나, 입력 없으면 companies.txt 사용")
    parser.add_argument("companies", nargs="*", help="회사명들 공백으로 구분하여 입력 (예: 삼성전자 SK하이닉스)")
    args = parser.parse_args()
    companies = args.companies if args.companies else load_companies_from_txt()

    # 0) 디스크 캐시 로드 (한 번만)
    global DISK_CACHE
    DISK_CACHE = _load_disk_cache()
    print(f"💾 디스크 캐시 로드 완료: by_name={len(DISK_CACHE['by_name'])}, by_req={len(DISK_CACHE['by_req'])}")

    if not companies:
        print("⚠ companies.txt가 비어있거나 경로가 잘못되었으며, 터미널 입력도 제공되지 않았습니다.")
        return
    print(f"📋 대상 검색어 수: {len(companies)}")

    driver_path = ChromeDriverManager().install()

    # ---- 1라운드: 병렬 처리 ----
    if BATCH_SIZE_AUTO:
        size = max(1, math.ceil(len(companies) / MAX_WORKERS))
    else:
        size = 40
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

    # ---- 2라운드: 최종 리트라이(선택) ----
    if FINAL_RETRY:
        failed_names = [name for name, why in skipped_all if why in ("검색 실패", "결과 없음")]
        failed_names = list(dict.fromkeys(failed_names))  # 중복 제거, 순서 보존
        if failed_names:
            rows_retry, skipped_retry = retry_failed_serial(failed_names, driver_path)
            rows_all.extend(rows_retry)
            # 최종 스킵 갱신
            skipped_all = [(n, w) for (n, w) in skipped_all if n not in failed_names] + skipped_retry

    # rows_all: 앞 단계에서 수집한 원시 결과 (list[dict])
    df_final = build_two_column_df(companies, rows_all)

    # 저장 경로
    base_dir = os.path.dirname(__file__)
    out_dir = os.path.join(base_dir, "..", "data", "output")
    os.makedirs(out_dir, exist_ok=True)
    out_path = os.path.join(out_dir, f"회사채등급_요청명_2col_{datetime.now():%Y%m%d_%H%M}.csv")

    # 두 컬럼만 저장
    df_final[["회사명", "등급"]].to_csv(out_path, index=False, encoding="utf-8-sig")

    print("\n[미리보기] 요청명-등급 2열")
    print(df_final.head(10))
    print(f"\n✅ 저장 완료: {out_path}")

    # (선택) 스킵 로그
    if skipped_all:
        print("\n— 건너뛴 검색어(사유) —")
        for name, why in skipped_all[:80]:
            print(f"  • {name}: {why}")
        if len(skipped_all) > 80:
            print(f"  …외 {len(skipped_all)-80}건")


if __name__ == "__main__":
    main()
