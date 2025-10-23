# test_metrics.py (repo 루트에서 실행)
from __future__ import annotations

import os
import sys
import signal
import time
from datetime import datetime
from pathlib import Path
from typing import Iterable, List, Set, Optional

import pandas as pd
import warnings

# ── 경로 설정 ─────────────────────────────────────────────────────────────
BASE_DIR = Path(__file__).resolve().parent
SRC_DIR = BASE_DIR / "src"
if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))

# ── .env 로드(있으면) ────────────────────────────────────────────────────
def _load_dotenv_if_possible():
    try:
        from dotenv import load_dotenv, find_dotenv
        path = find_dotenv(usecwd=True)
        if path:
            load_dotenv(path)
            print(f"🧩 .env 로드: {path}")
    except Exception:
        pass

_load_dotenv_if_possible()

# ── 내부 import ───────────────────────────────────────────────────────────
from kiwoom_finance.batch import get_metrics_for_codes

# ── 경고 억제(선택) ──────────────────────────────────────────────────────
warnings.filterwarnings("ignore", category=UserWarning, module="dart_fss")
warnings.filterwarnings("ignore", category=RuntimeWarning, module="dart_fss")

# ── 타깃 종목(원본) ──────────────────────────────────────────────────────
CODES = ["005930"]

# ── 유틸: 코드 정제 ─────────────────────────────────────────────────────
def normalize_codes(codes: Iterable[str]) -> List[str]:
    codes = [str(c) for c in codes]
    codes = [c for c in codes if c.isdigit() and len(c) <= 6]
    codes = [c.zfill(6) for c in codes]
    return list(dict.fromkeys(codes))  # 중복 제거(순서 보존)

# ── 캐시/출력 경로 ──────────────────────────────────────────────────────
OUTPUT_DIR = BASE_DIR / "artifacts" / "by_stock"  # per-stock CSV 캐시 폴더
OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

PKL_CACHE_DIR = BASE_DIR / "artifacts" / ".pklcache"
PKL_CACHE_DIR.mkdir(parents=True, exist_ok=True)

RESULT_CSV = BASE_DIR / "metrics_result.csv"
FAILED_CSV = BASE_DIR / "artifacts" / "failed_codes.csv"
SKIPPED_CSV = BASE_DIR / "artifacts" / "skipped_codes.csv"
SNAP_DIR = BASE_DIR / "artifacts" / "snapshots"
SNAP_DIR.mkdir(parents=True, exist_ok=True)

INTEGRITY_CSV = BASE_DIR / "artifacts" / "metrics_integrity_report.csv"

# ── DART 키: .env 우선, 없으면 백업 키 ───────────────────────────────────
API_KEY = os.getenv("DART_API_KEY", "").strip() or "YOUR_BACKUP_KEY"

# ── 진행 중 강제 종료 대비: SIGINT/SIGTERM 핸들러 ────────────────────────
_stop_requested = False
def _handle_stop(signum, frame):
    global _stop_requested
    _stop_requested = True
    print("\n🛑 중지 요청 감지. 현재 배치가 끝나면 안전하게 저장하고 종료합니다...")

for _sig in ("SIGINT", "SIGTERM"):
    if hasattr(signal, _sig):
        signal.signal(getattr(signal, _sig), _handle_stop)

# ── 파일 기반: 완료/미완료 판단 ─────────────────────────────────────────
def list_done_codes_from_csv_cache(out_dir: Path) -> Set[str]:
    """artifacts/by_stock/*.csv 파일명 기준 완료 종목 세트"""
    done = set()
    for p in out_dir.glob("*.csv"):
        code = p.stem
        if code.isdigit():
            done.add(code.zfill(6))
    return done

def compute_todo_codes(all_codes: List[str], out_dir: Path) -> List[str]:
    done = list_done_codes_from_csv_cache(out_dir)
    return [c for c in all_codes if c not in done]

# ── 병합 유틸: 캐시 CSV → 하나의 테이블 ─────────────────────────────────
def merge_by_stock_cache(out_dir: Path) -> pd.DataFrame:
    files = list(out_dir.glob("*.csv"))
    if not files:
        return pd.DataFrame()

    dfs = []
    for fp in files:
        try:
            df = pd.read_csv(fp, encoding="utf-8-sig")
            # 보조: stock_code 없으면 파일명으로 부여
            if "stock_code" not in df.columns:
                df["stock_code"] = fp.stem.zfill(6)
            else:
                # 문자열로 정규화
                df["stock_code"] = df["stock_code"].astype(str).str[:6].str.zfill(6)
            dfs.append(df)
        except Exception as e:
            print(f"⚠️ 캐시 파일 읽기 실패: {fp.name} ({e})")

    if not dfs:
        return pd.DataFrame()

    merged = pd.concat(dfs, ignore_index=True)

    # 같은 stock_code 여러 행 → non-NaN 비중 높은 행 우선
    def _non_na_score(row: pd.Series) -> int:
        return row.notna().sum()

    merged["_score"] = merged.apply(_non_na_score, axis=1)
    merged.sort_values(["stock_code", "_score"], ascending=[True, False], inplace=True)
    merged = merged.drop_duplicates(subset=["stock_code"], keep="first")
    merged = merged.drop(columns=["_score"], errors="ignore")
    merged.set_index("stock_code", inplace=True)
    return merged

def save_snapshot(df: pd.DataFrame, tag: str) -> None:
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    path = SNAP_DIR / f"metrics_result_{tag}_{ts}.csv"
    try:
        df.to_csv(path, encoding="utf-8-sig")
        print(f"💾 스냅샷 저장: {path}")
    except Exception as e:
        print(f"⚠️ 스냅샷 저장 실패: {e}")

# ── 숫자 변환(퍼센트/콤마/공백) ──────────────────────────────────────────
def to_num_strict(x):
    if isinstance(x, str):
        s = x.strip().replace(",", "")
        if s.endswith("%"):
            try:
                return float(s[:-1]) / 100.0
            except Exception:
                return pd.NA
        try:
            return float(s)
        except Exception:
            return pd.NA
    return pd.to_numeric(x, errors="coerce")

# ── 한 번의 배치 호출(wrap) ─────────────────────────────────────────────
def run_batch_for(codes: List[str]) -> pd.DataFrame:
    """get_metrics_for_codes 래퍼: 강한 타임아웃/프로세스풀/피클캐시 사용"""
    if not codes:
        return pd.DataFrame()

    print(f"🚀 배치 시작: {len(codes)}개 종목 (예시: {codes[:5]})")
    df = get_metrics_for_codes(
        codes,
        bgn_de="20210101",
        report_tp="annual",
        separate=True,
        latest_only=False,
        percent_format=False,
        api_key=API_KEY,

        # 파일/캐시
        save_each=True,
        output_dir=str(OUTPUT_DIR),

        # 안정성/성능 설정(중요)
        max_workers=4,                 # 연결/서버 안정성 위해 동시성 낮춤
        prefer_process=True,           # 프로세스풀(+ 하드 타임아웃 유효)
        per_code_timeout_sec=90,       # 종목별 최대 90초
        skip_nan_heavy=True,           # NaN 과다는 스킵
        nan_ratio_limit=0.60,
        min_non_null=5,

        # 피클 캐시: 재시작 가속
        cache_dir=str(PKL_CACHE_DIR),
        cache_ttl=24 * 3600,
        force_refresh=False,
    )
    return df

# ── 무결성/결측치 보고서 생성 ───────────────────────────────────────────
def produce_integrity_report(df: pd.DataFrame) -> pd.DataFrame:
    if df.empty:
        return df

    res = df.copy()

    # 강제 숫자 변환
    for col in ("debt_ratio", "equity_ratio"):
        if col in res.columns:
            res[col] = res[col].map(to_num_strict)

    # implied equity from debt
    if "debt_ratio" in res.columns:
        dr = res["debt_ratio"]
        res["equity_implied_from_debt"] = (1.0 / (1.0 + dr)).where(dr.notna())
    else:
        res["equity_implied_from_debt"] = pd.NA

    # filled equity ratio: 보고치가 있으면 그대로, 없으면 implied로 보충
    if "equity_ratio" in res.columns:
        er = res["equity_ratio"].copy()
    else:
        er = pd.Series(pd.NA, index=res.index, dtype="float64")

    res["equity_ratio_filled"] = er.where(er.notna(), res["equity_implied_from_debt"])

    # Δ = (보고치 또는 보충치) - implied
    res["Δ_equity_ratio"] = (res["equity_ratio_filled"] - res["equity_implied_from_debt"]).astype("float64")

    # 결측치 요약
    na_summary = res.isna().sum().sort_values(ascending=False)
    print("\n=== 결측치 요약(상위 15개) ===")
    print(na_summary.head(15))

    # 샘플 출력
    cols_show = [c for c in ["equity_ratio", "equity_ratio_filled", "debt_ratio", "equity_implied_from_debt", "Δ_equity_ratio"] if c in res.columns]
    print("\n=== 무결성 체크 샘플(상위 10행) ===")
    print(res[cols_show].head(10))

    # 파일로 저장
    try:
        res.to_csv(INTEGRITY_CSV, encoding="utf-8-sig", index=True)
        print(f"🧾 무결성 리포트 저장: {INTEGRITY_CSV}")
    except Exception as e:
        print(f"⚠️ 무결성 리포트 저장 실패: {e}")

    return res

# ── 메인 로직: 남은 종목만 반복 처리 + 중간 스냅샷 ──────────────────────
def main():
    all_codes = normalize_codes(CODES)
    print(f"✅ 타깃 종목 수: {len(all_codes)} (예시 5개: {all_codes[:5]})")
    print(f"📁 CSV 캐시 폴더: {OUTPUT_DIR.resolve()}")

    # 1) 먼저 현재 캐시로 스냅샷/리절트 생성 (실행 중에도 최신 상태 확인 가능)
    merged0 = merge_by_stock_cache(OUTPUT_DIR)
    if not merged0.empty:
        merged0.to_csv(RESULT_CSV, encoding="utf-8-sig")
        print(f"📄 초기 병합본 저장: {RESULT_CSV} (rows={len(merged0)})")

    # 2) 남은 종목만 수행
    passes = 0
    max_passes = 5  # 방어적 상한
    while passes < max_passes:
        if _stop_requested:
            print("🛑 중지 요청으로 루프 종료")
            break

        todo = compute_todo_codes(all_codes, OUTPUT_DIR)
        if not todo:
            print("🎉 처리할 남은 종목이 없습니다.")
            break

        passes += 1
        print(f"\n🔁 패스 {passes}/{max_passes} — 남은 종목: {len(todo)}")

        try:
            _ = run_batch_for(todo)
        except Exception as e:
            print(f"❌ 배치 호출 오류: {e}")
            time.sleep(5)
            continue

        # 패스 직후 병합/스냅샷
        merged = merge_by_stock_cache(OUTPUT_DIR)
        if not merged.empty:
            merged.to_csv(RESULT_CSV, encoding="utf-8-sig")
            print(f"✅ 병합/저장 완료: {RESULT_CSV} (rows={len(merged)})")
            save_snapshot(merged, tag=f"pass{passes}")
        else:
            print("⚠️ 병합 결과가 비어 있습니다. 캐시/로그를 확인하세요.")

        # 실패/스킵 현황 안내
        if FAILED_CSV.exists():
            try:
                failed = pd.read_csv(FAILED_CSV, dtype=str)
                if not failed.empty:
                    ex = failed.head(10).to_dict(orient="list")
                    print(f"⚠️ 실패 종목 {len(failed)}개 (예시 10개): {ex}")
            except Exception:
                pass
        if SKIPPED_CSV.exists():
            try:
                skipped = pd.read_csv(SKIPPED_CSV, dtype=str)
                if not skipped.empty:
                    ex = skipped.head(10).to_dict(orient="list")
                    print(f"ℹ️ 스킵 종목 {len(skipped)}개 (예시 10개): {ex}")
            except Exception:
                pass

    # 3) 종료 직전 최종 병합/저장 (안전)
    final_df = merge_by_stock_cache(OUTPUT_DIR)
    if not final_df.empty:
        final_df.to_csv(RESULT_CSV, encoding="utf-8-sig")
        print(f"\n🏁 최종 저장 완료: {RESULT_CSV} (rows={len(final_df)})")
    else:
        print("\n❗ 최종 병합본이 비었습니다. 실행 로그/캐시를 확인하세요.")

    # 4) 무결성/결측치 리포트
    if not final_df.empty:
        try:
            _ = produce_integrity_report(final_df)
        except Exception as e:
            print(f"⚠️ 무결성 체크 중 오류: {e}")

if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("\n🛑 사용자 중단. 마지막 병합을 시도합니다...")
        try:
            final_df = merge_by_stock_cache(OUTPUT_DIR)
            if not final_df.empty:
                final_df.to_csv(RESULT_CSV, encoding="utf-8-sig")
                print(f"💾 중단 전 저장: {RESULT_CSV} (rows={len(final_df)})")
        except Exception as e:
            print(f"⚠️ 중단 전 저장 실패: {e}")
        sys.exit(1)
