"""Backwards compatible launcher for the DART batch runner."""

from __future__ import annotations

import sys
from pathlib import Path


def _ensure_src_on_path() -> None:
    base_dir = Path(__file__).resolve().parent
    src_dir = base_dir / "src"
    if str(src_dir) not in sys.path:
        sys.path.insert(0, str(src_dir))


def main() -> int:
    _ensure_src_on_path()
    from kiwoom_finance.batch_runner.dart_batch import main as _runner_main

    return _runner_main()


if __name__ == "__main__":  # pragma: no cover - CLI entry point
    raise SystemExit(main())
    