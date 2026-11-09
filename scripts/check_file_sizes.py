"""Fail when a backend source file grows past the size budget.

Existing oversized files are recorded in ``scripts/size_baseline.json``; they
may shrink but never grow. New files must stay at or below ``MAX_LINES``.

Usage:
    uv run python scripts/check_file_sizes.py
    uv run python scripts/check_file_sizes.py --write-baseline
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

MAX_LINES = 500
ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "src" / "mbforge"
BASELINE = ROOT / "scripts" / "size_baseline.json"


def line_count(path: Path) -> int:
    return sum(1 for _ in path.open(encoding="utf-8"))


def current_sizes() -> dict[str, int]:
    sizes = {
        path.relative_to(ROOT).as_posix(): line_count(path)
        for path in SOURCE.rglob("*.py")
    }
    return dict(sorted(sizes.items()))


def load_baseline() -> dict[str, int]:
    if not BASELINE.exists():
        return {}
    return json.loads(BASELINE.read_text(encoding="utf-8"))


def write_baseline() -> None:
    baseline = {
        path: size for path, size in current_sizes().items() if size > MAX_LINES
    }
    BASELINE.write_text(json.dumps(baseline, indent=2) + "\n", encoding="utf-8")
    print(f"wrote {len(baseline)} oversized files to {BASELINE.relative_to(ROOT)}")


def check() -> int:
    baseline = load_baseline()
    failures: list[str] = []
    for path, size in current_sizes().items():
        allowed = baseline.get(path, MAX_LINES)
        if size > allowed:
            failures.append(f"{path}: {size} lines > {allowed} allowed")
    if failures:
        print("File size budget exceeded:", file=sys.stderr)
        for failure in failures:
            print(f"  {failure}", file=sys.stderr)
        print(
            "Split the file by responsibility; do not raise the budget.",
            file=sys.stderr,
        )
        return 1
    print(f"File size budget OK ({len(baseline)} baseline exemptions).")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--write-baseline", action="store_true")
    args = parser.parse_args()
    if args.write_baseline:
        write_baseline()
        return 0
    return check()


if __name__ == "__main__":
    raise SystemExit(main())
