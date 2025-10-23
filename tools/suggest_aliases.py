# tools/suggest_aliases.py
from __future__ import annotations

import argparse
import time
from collections import Counter, defaultdict
from pathlib import Path
from typing import Iterable, Dict, List

import numpy as np
import pandas as pd
from tqdm import tqdm

from kiwoom_finance.dart_client import init_dart, find_corp, extract_fs
from kiwoom_finance.preprocess import preprocess_all
from kiwoom_finance.aliases import _normalize_name, KOR_KEY_ALIASES

# ----------------------------
# 유틸: 안전한 문자열 변환
# ----------------------------
def _safe_str(x) -> str:
    """컬럼명이 float/NaN/None이어도 안전하게 문자열로 변환."""
    if x is None:
        return ""
    # pandas의 NaN / numpy.nan 처리
    if isinstance(x, float) and (np.isnan(x) or str(x) == "nan"):
        return ""
    s = str(x)
    if s.strip().lower() in {"nan", "none"}:
        return ""
    return s.strip()

# ----------------------------
# 연결→별도 자동 폴백
# ----------------------------
def _extract_with_fallback(corp, bgn_de: str, report_tp: str, separate: bool):
    """
    1) separate 설정대로 시도
    2) NotFoundConsolidated 이면 반대 separate로 재시도
    """
    try:
        return extract_fs(corp, bgn_de=bgn_de, report_tp=report_tp, separate=separate)
    except Exception as e:
        # dart_fss가 없을 수도 있으니 문자열 방식도 병행
        is_nfc = "NotFoundConsolidated" in f"{type(e)} {e}"
        if not is_nfc:
            try:
                from dart_fss.errors.errors import NotFoundConsolidated  # type: ignore
                if isinstance(e, NotFoundConsolidated):
                    is_nfc = True
            except Exception:
                pass
        if is_nfc:
            alt = not separate
            tqdm.write(
                f"🔁 [{getattr(corp, 'stock_code', '???')}] 연결/별도 미발견 → "
                f"{'별도' if alt else '연결'}로 재시도"
            )
            return extract_fs(corp, bgn_de=bgn_de, report_tp=report_tp, separate=alt)
        raise

# ----------------------------
# 저장 함수 (안전 문자열화)
# ----------------------------
def _save_candidates(counter: Counter, sample_map: Dict[str, List[str]], out_path: Path):
    rows = []
    for norm, cnt in counter.most_common():
        samples = sample_map.get(norm, [])[:5]
        # 모두 문자열화 + 공백/NaN 제거 + 중복 제거
        clean_samples = []
        for s in samples:
            ss = _safe_str(s)
            if ss and ss not in clean_samples:
                clean_samples.append(ss)
        examples_str = " | ".join(clean_samples)
        rows.append((norm, cnt, examples_str))

    df = pd.DataFrame(rows, columns=["normalized_name", "count", "examples"])
    out_path.parent.mkdir(parents=True, exist_ok=True)
    df.to_csv(out_path.as_posix(), index=False, encoding="utf-8-sig")
    return df

# ----------------------------
# 메인 수집 로직
# ----------------------------
def collect_unmatched_aliases(
    codes: Iterable[str],
    api_key: str | None = None,
    bgn_de: str = "20210101",
    report_tp: str = "annual",
    separate: bool = True,
    limit: int | None = None,
    throttle: float = 0.6,
    autosave_every: int = 100,
    quiet: bool = False,
):
    """
    각 종목의 재무제표를 스캔하면서 aliases.py에 정의되지 않은 미매칭 컬럼명 후보를 수집.
    - 연결→별도 자동 폴백
    - 진행률/ETA 표시
    - 주기적 자동저장
    """
    init_dart(api_key)

    # 이미 등록된 alias 정규화 집합
    all_known = set(sum(KOR_KEY_ALIASES.values(), []))
    all_known_norm = {_normalize_name(x) for x in all_known if x}

    counter: Counter = Counter()
    sample_map: Dict[str, List[str]] = defaultdict(list)

    # 출력 경로
    project_root = Path(__file__).resolve().parents[1]
    out_dir = project_root / "artifacts"
    out_dir.mkdir(parents=True, exist_ok=True)
    out_path = out_dir / "missing_aliases_candidates.csv"

    # 진행률 바
    iter_codes = list(codes[:limit] if limit else codes)
    pbar = tqdm(total=len(iter_codes), ncols=110, dynamic_ncols=False, desc="🔎 Scanning aliases")

    ok = 0
    fail = 0
    t0 = time.time()
    last_start = t0

    for i, code in enumerate(iter_codes, start=1):
        start = time.time()
        try:
            time.sleep(throttle)
            corp = find_corp(code)
            fs = _extract_with_fallback(corp, bgn_de=bgn_de, report_tp=report_tp, separate=separate)
            bs, is_, cis, cf = preprocess_all(fs)

            for name, df in [("BS", bs), ("IS", is_), ("CIS", cis), ("CF", cf)]:
                if df is None or df.empty:
                    continue
                for c in df.columns:
                    # 안전 문자열화
                    raw = _safe_str(c)
                    if not raw:
                        continue
                    norm = _normalize_name(raw)
                    if norm in all_known_norm:
                        continue
                    counter[norm] += 1
                    lst = sample_map[norm]
                    if raw not in lst and len(lst) < 8:
                        lst.append(raw)
            ok += 1
        except Exception as e:
            fail += 1
            if not quiet:
                tqdm.write(f"⚠️ {code}: {e}")
        finally:
            # 진행률 상태 업데이트
            now = time.time()
            last = now - start
            found = len(counter)
            pbar.set_postfix(
                last=f"{last:.2f}s", found=f"{found:,}", ok=ok, fail=fail
            )
            pbar.update(1)

            # 주기적 자동저장
            if autosave_every and (i % autosave_every == 0):
                try:
                    _save_candidates(counter, sample_map, out_path)
                    if not quiet:
                        tqdm.write(f"📝 Autosaved → {out_path}")
                except Exception as se:
                    tqdm.write(f"❗ Autosave failed: {type(se).__name__}: {se}")

    pbar.close()

    # 최종 저장
    df = _save_candidates(counter, sample_map, out_path)
    elapsed = time.time() - t0
    print(
        f"\n📝 저장 완료: {out_path}\n"
        f"   • distinct 후보: {len(counter):,}\n"
        f"   • 처리 종목: {ok} 성공 / {fail} 실패\n"
        f"   • 총 경과: {elapsed:.1f}s (평균 {elapsed/max(1,len(iter_codes)):.2f}s/종목)"
    )
    return df

# ----------------------------
# CLI
# ----------------------------
def _default_codes() -> List[str]:
    # 대형주 위주 샘플(필요 시 교체)
    return [
        "086820","065170","456010","121890","122350",
        "069540","002420","241770","019170","005360",
        "032790","240810","013810","062040","005850",
        "266470","216050","361670","048870","189350",
        "018260","222080","102460","100590","217910",
    ]

if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--api-key", default=None)
    ap.add_argument("--bgn-de", default="20210101")
    ap.add_argument("--report-tp", choices=["annual", "quarter"], default="annual")
    ap.add_argument("--separate", action="store_true", help="연결 대신 별도 우선")
    ap.add_argument("--limit", type=int, default=None)
    ap.add_argument("--throttle", type=float, default=0.6, help="요청 간 대기(초). 너무 낮추면 차단 위험")
    ap.add_argument("--autosave-every", type=int, default=100, help="N개 처리마다 중간 저장")
    ap.add_argument("--quiet", action="store_true", help="예외 로그 최소화")
    ap.add_argument("--codes", nargs="*", default=[])
    args = ap.parse_args()

    codes = args.codes or _default_codes()
    collect_unmatched_aliases(
        codes=codes,
        api_key=args.api_key,
        bgn_de=args.bgn_de,
        report_tp=args.report_tp,
        separate=args.separate,
        limit=args.limit,
        throttle=args.throttle,
        autosave_every=args.autosave_every,
        quiet=args.quiet,
    )
