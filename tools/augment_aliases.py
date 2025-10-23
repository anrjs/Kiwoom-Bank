# tools/augment_aliases.py
from __future__ import annotations
import argparse, time, json
from pathlib import Path
from collections import Counter, defaultdict

import pandas as pd
from tqdm import tqdm

from kiwoom_finance.dart_client import init_dart, find_corp, extract_fs
from kiwoom_finance.preprocess import preprocess_all
from kiwoom_finance.aliases import _normalize_name, KOR_KEY_ALIASES, CF_KEY_ALIASES

# ---------- 1) 안전/위험 키 규칙 ----------
AUTO_ALLOW_SAFE_KEYS = {
    # BS 보조
    "현금및현금성자산","기타유동자산","기타비유동자산","기타유동부채","기타비유동부채",
    "리스부채","유형자산","무형자산",
    # CF 보조
    "투자활동현금흐름","재무활동현금흐름","유형자산의취득","유형자산의처분","무형자산의취득","무형자산의처분",
    "기초현금및현금성자산","기말현금및현금성자산","이자의지급",
}

REVIEW_ONLY_KEYS = {
    # IS 핵심
    "매출액","수익","영업수익","영업이익","당기순이익",
    # 자본 핵심
    "자본금","이익잉여금",
}

# ---------- 2) 연결→별도 자동 폴백 ----------
def get_fs_with_fallback(corp, bgn_de, report_tp, separate=True):
    try:
        return extract_fs(corp, bgn_de=bgn_de, report_tp=report_tp, separate=separate)
    except Exception as e:
        from dart_fss.errors.errors import NotFoundConsolidated
        is_nfc = isinstance(e, NotFoundConsolidated) or "NotFoundConsolidated" in f"{type(e)} {e}"
        if is_nfc:
            alt = not separate
            tqdm.write(f"🔁 [{getattr(corp,'stock_code','?')}] 연결/별도 미발견 → {'별도' if alt else '연결'} 재시도")
            return extract_fs(corp, bgn_de=bgn_de, report_tp=report_tp, separate=alt)
        raise

# ---------- 3) 수집 ----------
def scan_codes_for_aliases(codes, bgn_de, report_tp, separate, throttle, limit=None):
    counter = Counter()
    examples = defaultdict(list)

    it = codes[:limit] if limit else codes
    pbar = tqdm(total=len(it), ncols=100, desc="🔎 스캔", dynamic_ncols=False)
    for code in it:
        try:
            time.sleep(throttle)
            corp = find_corp(code)
            fs = get_fs_with_fallback(corp, bgn_de=bgn_de, report_tp=report_tp, separate=separate)
            bs, is_, cis, cf = preprocess_all(fs)
            for df in (bs, is_, cis, cf):
                if df is None or df.empty:
                    continue
                for c in df.columns:
                    norm = _normalize_name(c)
                    counter[norm] += 1
                    if len(examples[norm]) < 5 and c not in examples[norm]:
                        examples[norm].append(c)
            pbar.set_postfix(ok=code)
        except Exception as e:
            pbar.set_postfix(err=f"{code}:{type(e).__name__}")
        finally:
            pbar.update(1)
    pbar.close()
    return counter, examples

# ---------- 4) 안전 자동추가 & 검토 큐 ----------
def split_safe_and_review(counter, examples):
    known = set()
    for v in KOR_KEY_ALIASES.values():
        known.update(v)
    known_norm = {_normalize_name(x) for x in known if x}

    safe_rows, review_rows = [], []

    for norm, cnt in counter.most_common():
        # 이미 등록됨 → 스킵
        if norm in known_norm:
            continue
        # 원형 예시
        sample = examples.get(norm, [])
        original = sample[0] if sample else norm

        # 원형(공백/기호 제외)이 자동 허용 리스트 중 하나인가?
        # NOTE: 원형을 그대로 비교할 때도 normalize 없이 판단이 필요한 항목이라 original도 함께 체크
        # (예: "기타 유동부채" vs "기타유동부채")
        base = original.replace(" ", "").replace("·","").replace(",","").replace("(","").replace(")","").replace("/","").replace("-","")

        if base in AUTO_ALLOW_SAFE_KEYS and base not in REVIEW_ONLY_KEYS:
            safe_rows.append((norm, cnt, " | ".join(sample[:5])))
        else:
            review_rows.append((norm, cnt, " | ".join(sample[:5])))

    safe_df = pd.DataFrame(safe_rows, columns=["normalized_name","count","examples"])
    review_df = pd.DataFrame(review_rows, columns=["normalized_name","count","examples"])
    return safe_df, review_df

# ---------- 5) 반영 로직(메모리 상) ----------
def apply_safe_to_aliases(safe_df):
    # 여기서는 대표적으로 BS/CF에서 많이 쓰는 곳에 추가
    # 필요시 더 촘촘히 매핑 규칙 추가
    adds = defaultdict(list)

    for _, row in safe_df.iterrows():
        name = row["normalized_name"]
        # 대표 키군에 귀속
        if name in {"현금및현금성자산"}:
            adds["current_assets"].append("현금및현금성자산")
        elif name in {"기타유동자산"}:
            adds["current_assets"].append("기타유동자산")
        elif name in {"기타비유동자산","유형자산","무형자산"}:
            # 총자산 직접합산은 위험할 수 있어 “참조용”으로만 추가하고 실제 계산엔 안 씀
            pass
        elif name in {"기타유동부채"}:
            adds["current_liabilities"].append("기타유동부채")
        elif name in {"기타비유동부채","리스부채"}:
            # 차입/부채 집계에 도움
            pass
        # CF 계정
        elif name in {"투자활동현금흐름","재무활동현금흐름"}:
            # 총현금흐름 집계에는 직접 안 쓰니 참고만
            pass
        elif name in {"유형자산의취득","무형자산의취득"}:
            CF_KEY_ALIASES.setdefault("capex", [])
            if "유형자산의 취득" not in CF_KEY_ALIASES["capex"]:
                CF_KEY_ALIASES["capex"].extend(["유형자산의 취득","유형자산의취득"])
            if "무형자산의 취득" not in CF_KEY_ALIASES["capex"]:
                CF_KEY_ALIASES["capex"].extend(["무형자산의 취득","무형자산의취득"])
        elif name in {"유형자산의처분","무형자산의처분","이자의지급","기초현금및현금성자산","기말현금및현금성자산"}:
            # 보고/검증용 참조에 활용
            pass

    # KOR_KEY_ALIASES에 반영
    for key, vals in adds.items():
        cur = KOR_KEY_ALIASES.get(key, [])
        merged = list(dict.fromkeys(cur + vals))
        KOR_KEY_ALIASES[key] = merged

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--api-key", default=None)
    ap.add_argument("--bgn-de", default="20210101")
    ap.add_argument("--report-tp", choices=["annual","quarter"], default="annual")
    ap.add_argument("--separate", action="store_true", help="연결 대신 별도 우선")
    ap.add_argument("--limit", type=int, default=None)
    ap.add_argument("--throttle", type=float, default=0.6)
    ap.add_argument("--autosave-every", type=int, default=100)
    ap.add_argument("--codes", nargs="*", default=[])
    args = ap.parse_args()

    init_dart(args.api_key)

    # 기본 샘플 없으면 상위에서 내려온 코드 목록 또는 일부 대형주 샘플
    SAMPLE = args.codes or ["005930","000660","035420","051910","207940","000270","068270","035720","034220","000720"]

    t0 = time.time()
    counter, examples = scan_codes_for_aliases(
        SAMPLE, bgn_de=args.bgn_de, report_tp=args.report_tp, separate=args.separate,
        throttle=args.throttle, limit=args.limit
    )

    safe_df, review_df = split_safe_and_review(counter, examples)
    apply_safe_to_aliases(safe_df)  # 메모리 상 반영

    # 저장
    project_root = Path(__file__).resolve().parents[1]
    out_dir = project_root / "artifacts"
    out_dir.mkdir(parents=True, exist_ok=True)

    safe_path   = out_dir / "aliases_auto_added_preview.json"
    review_path = out_dir / "aliases_review_queue.csv"

    # 현재 메모리상의 보강된 KOR_KEY_ALIASES/CF_KEY_ALIASES 미리보기 저장(적용은 수동 반영)
    preview = {
        "KOR_KEY_ALIASES_preview": KOR_KEY_ALIASES,
        "CF_KEY_ALIASES_preview": CF_KEY_ALIASES,
        "auto_added_candidates": safe_df.to_dict(orient="records"),
    }
    safe_path.write_text(json.dumps(preview, ensure_ascii=False, indent=2), encoding="utf-8")
    review_df.to_csv(review_path.as_posix(), index=False, encoding="utf-8-sig")

    elapsed = time.time() - t0
    print(f"\n📝 자동추가 프리뷰: {safe_path}")
    print(f"📝 검토 대기열 CSV: {review_path}")
    print(f"⏱️ 경과시간: {elapsed:.1f}s | 수집 distinct 후보: {len(counter)}개 | 안전 자동추가: {len(safe_df)}개 | 검토대상: {len(review_df)}개")

if __name__ == "__main__":
    main()
