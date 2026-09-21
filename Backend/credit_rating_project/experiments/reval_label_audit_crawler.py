# -*- coding: utf-8 -*-
"""
experiments/reval_label_audit_crawler.py — ACI 재검증 [1. 라벨 감사]

Backend/nice_rating/crawler_impl.py의 검색·요청 로직을 "복사"해서(원본은 수정하지 않음),
NICE 기업신용등급 페이지에서 단일 현재등급이 아니라 **등급 이력(등급+평가일자)**을
긁어오도록 확장한 독립 스크립트입니다.

⚠️ 매우 중요한 주의사항 (반드시 읽어주세요)
  이 스크립트를 만든 세션(클라우드 컨테이너)은 네트워크 정책상 nicerating.com에
  전혀 접속할 수 없어서(403 policy denial), 실제 NICE 페이지의 "등급 이력" 테이블
  마크업을 직접 열어보고 확인할 방법이 없었습니다.
  아래 파서는 companyGradeInfo.do 페이지의 모든 <table>을 훑어서
  "날짜처럼 생긴 문자열 + 등급처럼 생긴 문자열"이 같은 행(<tr>)에 같이 있으면
  그걸 하나의 (평가일자, 등급) 이력 항목으로 간주하는 범용(generic) 방식입니다.
  실제 페이지에 등급 변동 이력 테이블이 없거나 다른 구조라면 이 방식으로는
  못 찾을 수 있습니다.

  ▶ 반드시 로컬에서 실행하기 전에:
    1) --debug 옵션으로 1~2개 회사(예: HMM)만 먼저 돌려서, 찾아낸 이력이
       실제 NICE 사이트에서 눈으로 본 등급 이력과 맞는지 확인하세요.
    2) 안 맞으면 아래 `_extract_rating_history_from_html()` 함수의 테이블
       선택 로직을 실제 페이지 구조에 맞게 수정해야 합니다 (이 함수만 고치면 됨).
    3) 확인 완료 후 전체 69개 기업으로 돌리세요.

사용법 (로컬 PC, Chrome 설치되어 있는 환경에서):
  pip install selenium webdriver-manager beautifulsoup4 requests pandas openpyxl

  # 먼저 1~2개 회사로 파서 검증
  python experiments/reval_label_audit_crawler.py --data real_dataset.xlsx \
      --companies "HMM" --debug

  # 검증 후 전체 실행
  python experiments/reval_label_audit_crawler.py --data real_dataset.xlsx \
      --cutoff_date 2025-10-13 --out_dir experiments_out
"""
import argparse
import os
import re
import sys
import time
from datetime import datetime
from urllib.parse import quote_plus

import pandas as pd
import requests
from bs4 import BeautifulSoup

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from experiments.common import load_valid_data  # noqa: E402  (표본 목록 로드용, src/* 미수정)

# ──────────────────────────────────────────────
# nice_rating/crawler_impl.py에서 "복사"해온 기본 설정 (원본 파일은 건드리지 않음)
# ──────────────────────────────────────────────
BASE = "https://www.nicerating.com"
HOME = f"{BASE}/"
SEARCH_TIMEOUT = 20
REQUEST_TIMEOUT = 15
HEADLESS_DEFAULT = True
HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/118.0.0.0 Safari/537.36"
    ),
}
TRANSIENT_STATUS = {500, 502, 503, 504, 429}

CMP_RE = re.compile(r"cmpCd=(\d+)")
JS_CMP_RE = re.compile(r"fn_cmpGradeInfo\('(\d+)'\)")

#  \b는 '+'/'-'로 끝나는 등급(A+, AA- 등) 뒤에서 단어경계로 인식되지 않아
#  깨지므로, 영숫자 전후 경계를 직접 검사하는 lookaround로 대체.
GRADE_TOKEN_RE = re.compile(
    r"(?<![A-Za-z0-9])(AAA|AA\+|AA0|AA-|AA|A\+|A0|A-|A|BBB\+|BBB0|BBB-|BBB|BB\+|BB0|BB-|BB|"
    r"B\+|B0|B-|B|CCC\+|CCC0|CCC-|CCC|CC|C|D)(?![A-Za-z0-9])"
)
DATE_TOKEN_RE = re.compile(
    r"(20\d{2})[.\-/년]\s?(\d{1,2})[.\-/월]\s?(\d{1,2})"
)


def _normalize_grade_token(tok: str) -> str:
    return tok.replace("0", "").strip() if tok not in ("D",) else tok


def _retry_get(session: requests.Session, url: str, max_retries=2, backoff=2) -> requests.Response:
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
                time.sleep(backoff)
                continue
            break
    raise last_exc or RuntimeError("GET failed")


def _build_search_url(query: str) -> str:
    return f"{BASE}/search/search.do?mainSType=CMP&mainSText={quote_plus(query)}"


def _find_cmpcd_candidates_from_search_html(html: str) -> list[str]:
    soup = BeautifulSoup(html, "html.parser")
    codes = []
    for a in soup.select("a[href]"):
        href = a.get("href") or ""
        m = CMP_RE.search(href) or JS_CMP_RE.search(href)
        if m and m.group(1) not in codes:
            codes.append(m.group(1))
    for el in soup.find_all(onclick=True):
        oc = el.get("onclick") or ""
        m = JS_CMP_RE.search(oc) or CMP_RE.search(oc)
        if m and m.group(1) not in codes:
            codes.append(m.group(1))
    return codes


def search_cmpcd(driver, company: str, wait_timeout: int = SEARCH_TIMEOUT) -> list[str]:
    from selenium.webdriver.support.ui import WebDriverWait
    from selenium.webdriver.support import expected_conditions as EC
    from selenium.webdriver.common.by import By
    from urllib.parse import urlparse, parse_qs

    driver.get(_build_search_url(company))
    try:
        WebDriverWait(driver, wait_timeout).until(
            EC.any_of(
                EC.url_contains("companyGradeInfo.do"),
                EC.presence_of_element_located((By.CSS_SELECTOR, "table")),
            )
        )
    except Exception:
        pass

    q = parse_qs(urlparse(driver.current_url).query)
    if "cmpCd" in q and q["cmpCd"]:
        return [q["cmpCd"][0]]

    return _find_cmpcd_candidates_from_search_html(driver.page_source)


# ──────────────────────────────────────────────
# ⚠️ 실제 페이지에서 검증이 필요한 핵심 파싱 함수
# ──────────────────────────────────────────────
def _extract_rating_history_from_html(html: str, debug: bool = False) -> list[dict]:
    """
    companyGradeInfo.do 페이지의 모든 테이블을 훑어서
    (평가일자, 등급) 쌍이 같이 들어있는 행을 이력 항목으로 수집.
    실제 사이트 구조와 다를 수 있으니 --debug로 반드시 확인할 것.
    """
    soup = BeautifulSoup(html, "html.parser")
    history = []
    for table in soup.find_all("table"):
        rows = table.find_all("tr")
        for tr in rows:
            text = tr.get_text(" ", strip=True)
            date_m = DATE_TOKEN_RE.search(text)
            grade_m = GRADE_TOKEN_RE.search(text)
            if date_m and grade_m:
                y, m, d = date_m.groups()
                try:
                    dt = datetime(int(y), int(m), int(d))
                except ValueError:
                    continue
                history.append({
                    "date": dt,
                    "grade": _normalize_grade_token(grade_m.group(1)),
                    "raw_row_text": text,
                })
                if debug:
                    print(f"    [DEBUG row] {text}")
    return history


def _extract_single_current_grade(html: str) -> str | None:
    """이력 테이블을 못 찾았을 때의 폴백: nice_rating/crawler_impl.py와 동일한
    '회사채' 키워드가 있는 행에서 최초 발견 등급 하나만 추출."""
    soup = BeautifulSoup(html, "html.parser")
    for tr in soup.find_all("tr"):
        text = tr.get_text(" ", strip=True)
        if "회사채" in text:
            m = GRADE_TOKEN_RE.search(text)
            if m:
                return _normalize_grade_token(m.group(1))
    return None


def fetch_rating_history(cmpCd: str, session: requests.Session, debug: bool = False) -> list[dict]:
    url = f"{BASE}/disclosure/companyGradeInfo.do?cmpCd={cmpCd}&deviceType=N&isPaidMember=false"
    resp = _retry_get(session, url)
    if debug:
        print(f"    [DEBUG] fetched {url} (len={len(resp.text)})")
    history = _extract_rating_history_from_html(resp.text, debug=debug)
    return history


def pick_label_as_of(history: list[dict], cutoff: datetime) -> dict | None:
    """cutoff 이전(포함) 항목 중 가장 최근 것을 선택."""
    eligible = [h for h in history if h["date"] <= cutoff]
    if not eligible:
        return None
    return max(eligible, key=lambda h: h["date"])


# ──────────────────────────────────────────────
# 메인
# ──────────────────────────────────────────────
def _new_driver(headless: bool):
    from selenium import webdriver
    from selenium.webdriver.chrome.options import Options
    from selenium.webdriver.chrome.service import Service
    from webdriver_manager.chrome import ChromeDriverManager

    opts = Options()
    if headless:
        opts.add_argument("--headless=new")
    opts.add_argument("--no-sandbox")
    opts.add_argument("--disable-dev-shm-usage")
    opts.add_argument("--disable-gpu")
    opts.add_argument("--lang=ko-KR")
    opts.add_argument("--window-size=1280,2000")
    opts.add_argument(f"user-agent={HEADERS['User-Agent']}")
    driver_path = ChromeDriverManager().install()
    driver = webdriver.Chrome(service=Service(driver_path), options=opts)
    return driver


MANUAL_CHECK = {
    "HMM": "A+", "브이티": "BB+", "아주스틸": "BB+",
    "형지I&C": "B+", "형지엘리트": "B+",
    "코스모신소재": None, "제이스코홀딩스": None,
}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--data", required=True, help="real_dataset.xlsx (69개 기업 목록 + 원래 라벨)")
    parser.add_argument("--companies", type=str, default=None,
                         help="쉼표구분 회사명만 대상 (검증용, 예: 'HMM,브이티')")
    parser.add_argument("--cutoff_date", type=str, default="2025-10-13")
    parser.add_argument("--headless", action="store_true", default=HEADLESS_DEFAULT)
    parser.add_argument("--debug", action="store_true")
    parser.add_argument("--out_dir", type=str, default="experiments_out")
    parser.add_argument("--sleep", type=float, default=0.5)
    args = parser.parse_args()
    os.makedirs(args.out_dir, exist_ok=True)

    cutoff = datetime.strptime(args.cutoff_date, "%Y-%m-%d")

    # 69개 전체(유효필터 이전) 목록 + 원래 라벨을 얻기 위해 원본 엑셀을 직접 읽음
    df_raw = pd.read_excel(args.data)
    if args.companies:
        wanted = set(c.strip() for c in args.companies.split(","))
        df_raw = df_raw[df_raw["회사명"].isin(wanted)]
    companies = df_raw[["회사명", "public_credit_rating"]].drop_duplicates("회사명")

    print(f"대상 기업 수: {len(companies)}, 기준일: {cutoff.date()}")

    driver = _new_driver(args.headless)
    session = requests.Session()
    session.headers.update(HEADERS)

    rows = []
    try:
        for i, r in enumerate(companies.itertuples(index=False), 1):
            name, orig_label = r[0], r[1]
            print(f"[{i}/{len(companies)}] {name} ...")
            try:
                cmpcds = search_cmpcd(driver, name)
            except Exception as e:
                print(f"    검색 실패: {e}")
                cmpcds = []

            history, note = [], ""
            for cmpcd in cmpcds:
                try:
                    h = fetch_rating_history(cmpcd, session, debug=args.debug)
                    history.extend(h)
                except Exception as e:
                    note = f"상세조회실패({e})"

            picked = pick_label_as_of(history, cutoff)
            if picked:
                corrected_label = picked["grade"]
                as_of_date = picked["date"].strftime("%Y-%m-%d")
            else:
                # 이력 테이블을 못 찾았으면 '현재 등급' 단건이라도 폴백 시도
                corrected_label, as_of_date = None, None
                for cmpcd in cmpcds:
                    try:
                        resp = _retry_get(session,
                                           f"{BASE}/disclosure/companyGradeInfo.do?cmpCd={cmpcd}&deviceType=N&isPaidMember=false")
                        single = _extract_single_current_grade(resp.text)
                        if single:
                            corrected_label = single
                            as_of_date = None
                            note = (note + " " if note else "") + "날짜불명(현재등급 폴백)"
                            break
                    except Exception:
                        pass
                if corrected_label is None:
                    note = (note + " " if note else "") + "등급없음"

            manual = MANUAL_CHECK.get(name)
            manual_match = None
            if name in MANUAL_CHECK:
                manual_match = (corrected_label == manual) if manual is not None else (corrected_label is None)

            rows.append({
                "회사명": name,
                "원래라벨": orig_label,
                "교정라벨": corrected_label,
                "교정라벨_평가일자": as_of_date,
                "cmpCd_후보": ";".join(cmpcds) if cmpcds else "",
                "이력_수집건수": len(history),
                "비고": note,
                "수동확인값": manual,
                "수동확인_일치": manual_match,
            })
            time.sleep(args.sleep)
    finally:
        try:
            driver.quit()
        except Exception:
            pass

    df = pd.DataFrame(rows)
    df["원래라벨_교정라벨_일치"] = df.apply(
        lambda r: (r["원래라벨"] == r["교정라벨"]) if pd.notna(r["교정라벨"]) else None, axis=1
    )

    out_path = os.path.join(args.out_dir, "stage1_corrected_labels.csv")
    df.to_csv(out_path, index=False, encoding="utf-8-sig")

    print("\n" + "=" * 60)
    print("결과")
    print("=" * 60)
    print(df.to_string(index=False))

    n_total = len(df)
    n_no_grade = df["교정라벨"].isna().sum()
    n_compared = n_total - n_no_grade
    n_mismatch = (df["원래라벨_교정라벨_일치"] == False).sum()  # noqa: E712
    print(f"\n전체 {n_total}건 / 등급없음 {n_no_grade}건 / 비교가능 {n_compared}건 중 불일치 {n_mismatch}건")

    if MANUAL_CHECK:
        checked = df[df["회사명"].isin(MANUAL_CHECK.keys())]
        if len(checked):
            print("\n수동확인 7건 대조:")
            print(checked[["회사명", "교정라벨", "수동확인값", "수동확인_일치"]].to_string(index=False))
            n_ok = checked["수동확인_일치"].sum()
            print(f"→ {n_ok}/{len(checked)}건 일치")

    print(f"\n저장: {out_path}")


if __name__ == "__main__":
    main()
