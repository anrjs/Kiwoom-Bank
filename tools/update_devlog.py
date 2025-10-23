#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
update_devlog.py
- Git 커밋/벤치마크/검증 결과를 모아 DEVLOG.md에 노션-호환 형식으로 추가합니다.

기능
1) 기간별 git 로그 요약 (기본: 최근 1일)
2) tools/bench_metrics.py 결과(benchmark.csv) 요약 (선택)
3) validate_cache 결과 요약(로그 파일 또는 표준입력) (선택)
4) 위 내용을 섹션으로 구성해 DEVLOG.md 최상단에 prepend

사용 예)
  python tools/update_devlog.py \
    --title "캐시 파이프라인 도입 & 벤치마크" \
    --date-from 2025-10-20 --date-to 2025-10-22 \
    --bench-csv benchmark.csv \
    --validate-log .cache_validation/validate.log \
    --next-steps "레이트리밋 감지, CI 통합"

필수 아님 옵션:
  --repo-root: Git 루트 지정(기본: 현재 스크립트 상위의 repo 루트 탐색)
  --devlog: DEVLOG.md 경로(기본: repo 루트/DEVLOG.md)
  --note: 자유서술 메모(멀티라인 OK)
"""
from __future__ import annotations

import argparse
import csv
import os
import sys
from datetime import datetime, timedelta
from pathlib import Path
from typing import List, Optional, Tuple
import subprocess
import textwrap

# ---------- 유틸 ----------

def run(cmd: List[str], cwd: Optional[Path] = None, check: bool = True) -> subprocess.CompletedProcess:
    return subprocess.run(cmd, cwd=str(cwd) if cwd else None, check=check, capture_output=True, text=True)

def find_repo_root(start: Path) -> Path:
    cur = start.resolve()
    for _ in range(10):
        if (cur / ".git").exists():
            return cur
        if cur.parent == cur:
            break
        cur = cur.parent
    return start.resolve()

def read_git_log(repo_root: Path, date_from: str, date_to: str) -> List[Tuple[str, str, str]]:
    """
    반환: [(hash7, date_iso, subject), ...]
    """
    # 날짜 포맷 정규화
    df = datetime.fromisoformat(date_from)
    dt = datetime.fromisoformat(date_to)
    # git log --since/--until 는 당일 23:59:59까지 포함하려면 다음날 00:00 직전으로 처리
    until = (dt + timedelta(days=1) - timedelta(seconds=1)).isoformat(sep=" ")
    res = run(
        ["git", "log", f"--since={df.isoformat(sep=' ')}", f"--until={until}", "--pretty=%h|%ad|%s", "--date=short"],
        cwd=repo_root,
        check=False,
    )
    lines = [ln.strip() for ln in res.stdout.splitlines() if ln.strip()]
    out = []
    for ln in lines:
        parts = ln.split("|", 2)
        if len(parts) == 3:
            out.append((parts[0], parts[1], parts[2]))
    return out

def format_git_log_md(entries: List[Tuple[str,str,str]]) -> str:
    if not entries:
        return "- (해당 기간 커밋 없음)"
    return "\n".join([f"- `{h}` {d} — {s}" for (h,d,s) in entries])

def read_benchmark_csv(csv_path: Path) -> Optional[str]:
    if not csv_path.exists():
        return None
    rows = []
    with csv_path.open("r", encoding="utf-8-sig", newline="") as f:
        reader = csv.DictReader(f)
        for r in reader:
            rows.append(r)
    if not rows:
        return None

    # 표시용 테이블(노션 호환): sample_size, run_label, total_seconds, p50, p90, hit_rate
    header = ["sample_size", "run_label", "total_seconds", "per_stock_p50_seconds", "per_stock_p90_seconds", "cache_hit_rate_pct", "success_count", "failure_count"]
    # 정렬: sample_size, run_label(cold→warm)
    def key(r):
        run_order = 0 if r.get("run_label","") == "cold" else 1
        try:
            ss = int(r.get("sample_size","0"))
        except:
            ss = 0
        return (ss, run_order)
    rows.sort(key=key)

    lines = []
    lines.append("| " + " | ".join(header) + " |")
    lines.append("|" + "|".join(["---"]*len(header)) + "|")
    for r in rows:
        def fmt(k, default=""):
            v = r.get(k, default)
            return f"{float(v):.2f}" if k in ("total_seconds","per_stock_p50_seconds","per_stock_p90_seconds") and v not in (None,"","NaN") else (v or "")
        line = [
            r.get("sample_size",""),
            r.get("run_label",""),
            fmt("total_seconds"),
            fmt("per_stock_p50_seconds"),
            fmt("per_stock_p90_seconds"),
            (lambda x: f"{float(x):.1f}%" if x not in (None,"","NaN") else "")(r.get("cache_hit_rate_pct","")),
            r.get("success_count",""),
            r.get("failure_count",""),
        ]
        lines.append("| " + " | ".join(line) + " |")
    return "\n".join(lines)

def read_validate_log(log_path: Path) -> Optional[str]:
    if not log_path.exists():
        return None
    text = log_path.read_text(encoding="utf-8", errors="ignore")
    # 간단한 패턴: PASS 포함 여부, 혹은 Column/Dtype/Value 섹션 일부 추출
    if "Cache validation: PASS" in text or "Cache validation succeeded" in text:
        return "**결과:** ✅ PASS (warm 결과가 cold 계산과 동일)"
    # 일부 핵심 라인만 발췌
    lines = []
    for ln in text.splitlines():
        if any(k in ln for k in ("Column differences", "Dtype mismatches", "Value discrepancies", "Only in cold", "Only in warm")):
            lines.append(ln.strip())
    if not lines:
        # 전체 길면 너무 기니 앞부분만
        snippet = "\n".join(text.splitlines()[:50])
        return f"**결과:** ⚠️ 차이 발견 (상세 로그 일부)\n```\n{snippet}\n```"
    return "**결과:** ⚠️ 차이 발견\n```\n" + "\n".join(lines) + "\n```"

def prepend_devlog(devlog_path: Path, new_block: str) -> None:
    existing = devlog_path.read_text(encoding="utf-8") if devlog_path.exists() else ""
    content = new_block.rstrip() + "\n\n" + existing
    devlog_path.write_text(content, encoding="utf-8")

def build_md_block(
    title: str,
    date_from: str,
    date_to: str,
    note: Optional[str],
    git_md: str,
    bench_md: Optional[str],
    validate_md: Optional[str],
    next_steps: Optional[str],
) -> str:
    period = f"{date_from} ~ {date_to}"
    now = datetime.now().strftime("%Y-%m-%d %H:%M")
    note_block = f"\n{note.strip()}\n" if note else ""
    bench_block = f"\n**벤치마크 요약**\n\n{bench_md}\n" if bench_md else "\n*벤치마크 결과 없음*\n"
    validate_block = f"\n**캐시 검증 요약**\n\n{validate_md}\n" if validate_md else "\n*캐시 검증 로그 없음*\n"
    next_block = f"\n**Next Steps**\n- " + "\n- ".join([ln.strip("- ").strip() for ln in next_steps.splitlines() if ln.strip()]) + "\n" if next_steps else ""

    # 노션-호환 마크다운 블럭
    return textwrap.dedent(f"""\
    # 🧭 개발 로그 — {title}
    **기간:** {period}  
    **작성:** {now}

    --- 

    ## ✍️ 개요
    {note_block if note_block.strip() else "이번 기간의 핵심 작업/변경 사항을 정리합니다."}

    ## 🔧 변경 사항 (Git)
    {git_md}

    ## 🚀 성능 벤치마크
    {bench_block}

    ## 🔍 캐시 일관성 검증
    {validate_block}
    {next_block}
    ---
    """)

# ---------- 메인 ----------

def main():
    parser = argparse.ArgumentParser(description="DEVLOG.md 업데이트(노션 호환)")
    parser.add_argument("--title", required=True, help="노션 섹션 제목")
    parser.add_argument("--date-from", default=datetime.now().date().isoformat(), help="YYYY-MM-DD")
    parser.add_argument("--date-to", default=datetime.now().date().isoformat(), help="YYYY-MM-DD")
    parser.add_argument("--repo-root", type=Path, default=None, help="Git 루트 (기본: 자동 탐색)")
    parser.add_argument("--devlog", type=Path, default=None, help="DEVLOG.md 경로 (기본: 루트/DEVLOG.md)")
    parser.add_argument("--bench-csv", type=Path, default=None, help="bench_metrics 결과 CSV 경로(선택)")
    parser.add_argument("--validate-log", type=Path, default=None, help="validate_cache 로그 파일 경로(선택)")
    parser.add_argument("--note", type=str, default=None, help="자유 메모(멀티라인 가능)")
    parser.add_argument("--next-steps", type=str, default=None, help="다음 액션 항목(줄바꿈으로 여러개)")
    args = parser.parse_args()

    # repo 루트 해석
    repo_root = args.repo_root or find_repo_root(Path.cwd())
    devlog_path = args.devlog or (repo_root / "DEVLOG.md")

    # git 로그 수집
    git_entries = read_git_log(repo_root, args.date_from, args.date_to)
    git_md = format_git_log_md(git_entries)

    # 벤치마크/검증 요약
    bench_md = read_benchmark_csv(args.bench_csv) if args.bench_csv else None
    validate_md = read_validate_log(args.validate_log) if args.validate_log else None

    block = build_md_block(
        title=args.title,
        date_from=args.date_from,
        date_to=args.date_to,
        note=args.note,
        git_md=git_md,
        bench_md=bench_md,
        validate_md=validate_md,
        next_steps=args.next_steps,
    )

    devlog_path.parent.mkdir(parents=True, exist_ok=True)
    prepend_devlog(devlog_path, block)
    print(f"✅ DEVLOG 갱신 완료 → {devlog_path}")

if __name__ == "__main__":
    main()
