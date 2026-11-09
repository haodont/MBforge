#!/usr/bin/env python
"""Group extracted table crops into logical tables and classify them.

Reads the crop manifest, attaches page dimensions from the source PDFs (no
rendering), joins the fragment-level classifier output, groups fragments
(cross-page continuation / column break) and assigns one class per logical
table. A fragment without a header inherits its logical table's class; a table
whose header was never read is surfaced as ``activity?`` only when it prints
value-shaped content, never silently dropped.

Usage::

    .venv/Scripts/python scripts/group_table_fragments.py \\
        --crops-dir .../table-crops --pdf-dir .../file \\
        --classes   .../activity-tables/all_classes.jsonl \\
        --out-dir   .../logical-tables
"""

from __future__ import annotations

import argparse
import json
import re
from collections import defaultdict
from pathlib import Path

from mbforge.service.pipeline.activity.logical_tables import (
    FragmentClass,
    TableFragment,
    classify_logical_table,
    group_fragments,
)


def load_manifest(crops_dir: Path) -> list[dict]:
    rows = []
    for line in (crops_dir / "manifest.jsonl").read_text(encoding="utf-8").splitlines():
        if line.strip():
            rows.append(json.loads(line))
    return rows


def load_classes(path: Path | None) -> dict[tuple[str, int, int], dict]:
    if path is None or not path.is_file():
        return {}
    rows = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        row = json.loads(line)
        rows[(row["source"], int(row["page"]), int(row["table"]))] = row
    return rows


_DESIGNATION_HEAD_RE = re.compile(
    r"^(?:\d{1,4}[A-Za-z]?(?:\s*[-–]\s*\d+)*|化合物\s*\d+[A-Za-z]?|实施例\s*\d+|"
    r"[A-Za-z]{1,4}\d{2,}[A-Za-z\-\d]*|\d+\s*组分\s*\d+)$"
)
_VALUE_CELL_RE = re.compile(
    r"^(?:<|>|~|=|≤|≥)?\s*[-+]?\d*[.,]?\d+(?:\s*±\s*\d*[.,]?\d+)?$|"
    r"^(?:\+{1,4}|十{1,4}|[A-Da-d]|ND|NA|NT)$"
)


def header_is_data(markdown: str) -> bool:
    """Whether the first Markdown row is a data row promoted to a header.

    A continuation fragment prints no header, so the recognizer turns its first
    data row into one: ``| 化合物23A | B |`` looks exactly like a header row.
    Such a row starts with a designation and carries at least one value cell.
    """
    lines = [line for line in str(markdown or "").splitlines() if line.strip()]
    if not lines:
        return False
    cells = [cell.strip() for cell in lines[0].strip().strip("|").split("|")]
    if not cells or not _DESIGNATION_HEAD_RE.match(cells[0]):
        return False
    return any(_VALUE_CELL_RE.match(cell) for cell in cells[1:] if cell)


def fragment_class(meta: dict | None) -> FragmentClass:
    if not meta:
        return FragmentClass()
    signals = meta.get("signals") or {}
    return FragmentClass(
        name=str(meta.get("class") or "other"),
        numeric_density=float(signals.get("numeric_density") or 0.0),
        qualitative_values=int(signals.get("qualitative_values") or 0),
        unit_values=int(signals.get("unit_values") or 0),
    )


def structure_count(meta: dict | None) -> int:
    if not meta:
        return 0
    return int(meta.get("structure_count") or 0)


def header_signals(meta: dict | None) -> tuple[bool | None, int | None, str]:
    if not meta:
        return None, None, ""
    signals = meta.get("signals") or {}
    has_header = bool(
        signals.get("activity_metrics")
        or signals.get("pk_metrics")
        or signals.get("analytical")
        or signals.get("glossary")
        or signals.get("structure")
        or signals.get("synthesis")
    )
    columns = signals.get("columns")
    markdown = str(meta.get("markdown") or "")
    first_line = markdown.splitlines()[0].strip() if markdown else ""
    return has_header, columns, first_line[:120]


def page_sizes(pdf_path: Path, pages: set[int]) -> dict[int, tuple[float, float]]:
    import pymupdf

    document = pymupdf.open(str(pdf_path))
    try:
        sizes = {}
        for page in pages:
            if page < 1 or page > document.page_count:
                continue
            rect = document.load_page(page - 1).rect
            sizes[page] = (float(rect.width), float(rect.height))
        return sizes
    finally:
        document.close()


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--crops-dir", required=True)
    parser.add_argument("--pdf-dir", required=True)
    parser.add_argument("--out-dir", required=True)
    parser.add_argument("--classes", default=None)
    parser.add_argument("--sources", default=None)
    parser.add_argument("--x-tolerance", type=float, default=5.0)
    parser.add_argument("--bottom-margin", type=float, default=0.12)
    parser.add_argument("--top-margin", type=float, default=0.88)
    args = parser.parse_args()

    crops_dir = Path(args.crops_dir).resolve()
    out_dir = Path(args.out_dir).resolve()
    out_dir.mkdir(parents=True, exist_ok=True)
    allowed = (
        {name.strip() for name in args.sources.split(",") if name.strip()}
        if args.sources
        else None
    )
    manifest = [
        row
        for row in load_manifest(crops_dir)
        if allowed is None or row["source"] in allowed
    ]
    classes = load_classes(Path(args.classes) if args.classes else None)

    by_source: dict[str, list[dict]] = defaultdict(list)
    for row in manifest:
        by_source[row["source"]].append(row)

    fragments: list[TableFragment] = []
    for source, rows in sorted(by_source.items()):
        sizes = page_sizes(
            Path(args.pdf_dir) / source, {int(row["page"]) for row in rows}
        )
        for row in rows:
            width, height = sizes.get(int(row["page"]), (0.0, 0.0))
            has_header, columns, caption = header_signals(
                classes.get((row["source"], int(row["page"]), int(row["table"])))
            )
            fragments.append(
                TableFragment(
                    source=row["source"],
                    page=int(row["page"]),
                    table=int(row["table"]),
                    bbox=(
                        float(row["x0"]),
                        float(row["y0"]),
                        float(row["x1"]),
                        float(row["y1"]),
                    ),
                    page_width=width,
                    page_height=height,
                    has_header=has_header,
                    column_count=columns,
                    caption=caption,
                    header_is_data=header_is_data(
                        str(
                            (
                                classes.get(
                                    (row["source"], int(row["page"]), int(row["table"]))
                                )
                                or {}
                            ).get("markdown")
                            or ""
                        )
                    ),
                )
            )

    groups = group_fragments(
        fragments,
        x_tolerance=args.x_tolerance,
        bottom_margin=args.bottom_margin,
        top_margin=args.top_margin,
    )
    fragment_classes = {key: fragment_class(meta) for key, meta in classes.items()}

    class_counts: dict[str, int] = {}
    lines = []
    activity_tables = []
    for group in groups:
        name, source = classify_logical_table(group, fragment_classes)
        class_counts[name] = class_counts.get(name, 0) + 1
        structure_total = sum(
            structure_count(
                classes.get((group.first.source, fragment.page, fragment.table))
            )
            for fragment in group.fragments
        )
        record = {
            "logical_id": group.logical_id,
            "source": group.first.source,
            "class": name,
            "class_source": source,
            "structure_count": structure_total,
            "fragments": [
                {
                    "page": fragment.page,
                    "table": fragment.table,
                    "bbox": [round(value, 2) for value in fragment.bbox],
                    "has_header": fragment.has_header,
                    "columns": fragment.column_count,
                    "class": fragment_classes.get(
                        (group.first.source, fragment.page, fragment.table),
                        FragmentClass(),
                    ).name,
                    "structure_count": structure_count(
                        classes.get((group.first.source, fragment.page, fragment.table))
                    ),
                }
                for fragment in group.fragments
            ],
        }
        lines.append(json.dumps(record, ensure_ascii=False))
        if name in {"activity", "pk", "activity?"}:
            activity_tables.append(record)

    (out_dir / "logical_tables.jsonl").write_text(
        "\n".join(lines) + "\n", encoding="utf-8"
    )
    (out_dir / "activity_logical_tables.jsonl").write_text(
        "\n".join(json.dumps(row, ensure_ascii=False) for row in activity_tables)
        + "\n",
        encoding="utf-8",
    )
    (out_dir / "logical_table_classes.json").write_text(
        json.dumps(class_counts, indent=2, ensure_ascii=False), encoding="utf-8"
    )

    multi = [group for group in groups if len(group.fragments) > 1]
    summary = {
        "fragments": len(fragments),
        "logical_tables": len(groups),
        "multi_fragment_groups": len(multi),
        "largest_group": max((len(group.fragments) for group in groups), default=0),
        "classes": class_counts,
        "activity_tables": len(activity_tables),
        "activity_with_structures": sum(
            1 for row in activity_tables if row["structure_count"] > 0
        ),
    }
    (out_dir / "logical_tables_summary.json").write_text(
        json.dumps(summary, indent=2, ensure_ascii=False), encoding="utf-8"
    )
    print(json.dumps(summary, indent=2, ensure_ascii=False))
    for group in multi:
        pages = ", ".join(f"p{f.page}t{f.table}" for f in group.fragments)
        print(f"  {group.logical_id}: {pages}")


if __name__ == "__main__":
    main()
