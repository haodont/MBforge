#!/usr/bin/env python
"""Detect whether each extracted table crop contains molecular structures.

Three independent signals are combined:
  1. MolDet molecule boxes inside the table bbox (primary; same detector the
     Extract stage and the table masking use);
  2. PDF vector drawings inside the table bbox (structure drawings are vector
     paths in most patents; a text-only table has almost none);
  3. the table header naming a structure column (``Structure``/``结构``), taken
     from the classifier output when available.

Output: one JSON row per table with the molecule boxes (PDF points) and the
signals, so the row parser can bind structures to table rows instead of guessing.

Usage::

    .venv/Scripts/python scripts/detect_table_structures.py \\
        --crops-dir .../table-crops --pdf-dir .../file \\
        --out-dir   .../table-structures \\
        --classes   .../activity-classes/all_classes.jsonl \\
        --workers 3
"""

from __future__ import annotations

import argparse
import json
import time
from collections import defaultdict
from concurrent.futures import ProcessPoolExecutor, as_completed
from multiprocessing import get_context
from pathlib import Path

from PIL import Image

from mbforge.server.runtime_provider import create_runtime_provider
from mbforge.service.pipeline.layout.parse import render_page_rgb
from mbforge.service.ports import configure_runtime_provider, get_runtime

_WORKER_READY = False
#: MolDet is trained at 200 DPI; the same resolution the molecule pass uses.
DETECT_DPI = 200.0
#: A table "has a structure" when enough vector drawing items fall inside it.
VECTOR_ITEM_MIN = 10


def _worker_init() -> None:
    global _WORKER_READY
    configure_runtime_provider(create_runtime_provider())
    _WORKER_READY = True


def load_manifest(crops_dir: Path) -> dict[tuple[str, int, int], dict]:
    rows = {}
    for line in (crops_dir / "manifest.jsonl").read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        row = json.loads(line)
        rows[(row["source"], int(row["page"]), int(row["table"]))] = row
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


def boxes_overlap(a: list[float], b: list[float]) -> float:
    """Fraction of box *a* covered by box *b*."""
    area = max(0.0, a[2] - a[0]) * max(0.0, a[3] - a[1])
    if area <= 0:
        return 0.0
    ix0, iy0 = max(a[0], b[0]), max(a[1], b[1])
    ix1, iy1 = min(a[2], b[2]), min(a[3], b[3])
    return max(0.0, ix1 - ix0) * max(0.0, iy1 - iy0) / area


def inside(box: list[float], table: list[float]) -> bool:
    """A molecule belongs to the table when its centre or most of it is inside."""
    cx = (box[0] + box[2]) / 2
    cy = (box[1] + box[3]) / 2
    if table[0] <= cx <= table[2] and table[1] <= cy <= table[3]:
        return True
    return boxes_overlap(box, table) > 0.5


def detect_group(task: tuple) -> list[dict]:
    """Run MolDet / vector analysis once for a page and score its tables."""
    source, page_number, tables, pdf_path = task
    import pymupdf

    document = pymupdf.open(pdf_path)
    try:
        page = document.load_page(int(page_number) - 1)
        width, height = float(page.rect.width), float(page.rect.height)
        image = render_page_rgb(page, DETECT_DPI / 72.0)
        result = get_runtime().moldet.detect_molecules(Image.fromarray(image))
        molecule_boxes = []
        for detection in result.bboxes:
            x0, y0, x1, y1 = (float(value) for value in detection.bbox)
            molecule_boxes.append(
                [
                    round(x0 * width, 2),
                    round((1 - y1) * height, 2),
                    round(x1 * width, 2),
                    round((1 - y0) * height, 2),
                ]
            )
        drawings = page.get_drawings()
        rows = []
        for table in tables:
            table_box = [table["x0"], table["y0"], table["x1"], table["y1"]]
            mols = [box for box in molecule_boxes if inside(box, table_box)]
            drawing_objects = 0
            drawing_items = 0
            for drawing in drawings:
                rect = drawing.get("rect")
                if rect is None:
                    continue
                box = [rect.x0, rect.y0, rect.x1, rect.y1]
                if boxes_overlap(box, table_box) < 0.5:
                    continue
                drawing_objects += 1
                drawing_items += len(drawing.get("items") or [])
            rows.append(
                {
                    **table,
                    "molecule_count": len(mols),
                    "molecule_boxes": mols,
                    "drawing_objects": drawing_objects,
                    "drawing_items": drawing_items,
                    "has_structure": bool(mols or drawing_items >= VECTOR_ITEM_MIN),
                }
            )
        return rows
    finally:
        document.close()


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--crops-dir", required=True)
    parser.add_argument("--pdf-dir", required=True)
    parser.add_argument("--out-dir", required=True)
    parser.add_argument("--classes", default=None)
    parser.add_argument("--sources", default=None, help="comma-separated PDF names")
    parser.add_argument("--only-activity", action="store_true")
    parser.add_argument("--workers", type=int, default=1)
    parser.add_argument("--limit", type=int, default=None)
    args = parser.parse_args()

    crops_dir = Path(args.crops_dir).resolve()
    pdf_dir = Path(args.pdf_dir).resolve()
    out_dir = Path(args.out_dir).resolve()
    out_dir.mkdir(parents=True, exist_ok=True)

    manifest = load_manifest(crops_dir)
    classes = load_classes(Path(args.classes) if args.classes else None)
    sources = (
        {name.strip() for name in args.sources.split(",") if name.strip()}
        if args.sources
        else None
    )

    candidates: list[dict] = []
    for key, row in manifest.items():
        if sources is not None and row["source"] not in sources:
            continue
        meta = classes.get(key)
        if args.only_activity and (
            not meta or meta["class"] not in {"activity", "activity?", "pk"}
        ):
            continue
        candidates.append({**row, "class": (meta or {}).get("class", "")})
    candidates.sort(key=lambda row: (row["source"], row["page"], row["table"]))
    if args.limit is not None:
        candidates = candidates[: args.limit]
    print(f"{len(candidates)} table(s) to inspect", flush=True)

    groups: dict[tuple[str, int], list[dict]] = defaultdict(list)
    for row in candidates:
        groups[(row["source"], int(row["page"]))].append(row)

    tasks = [
        (source, page, tables, str(pdf_dir / source))
        for (source, page), tables in sorted(groups.items())
    ]
    started = time.perf_counter()
    results: list[dict] = []
    if args.workers > 1:
        with ProcessPoolExecutor(
            max_workers=args.workers,
            mp_context=get_context("spawn"),
            initializer=_worker_init,
        ) as executor:
            futures = [executor.submit(detect_group, task) for task in tasks]
            for future in as_completed(futures):
                results.extend(future.result())
    else:
        _worker_init()
        for task in tasks:
            results.extend(detect_group(task))

    results = [
        {
            "source": row["source"],
            "page": row["page"],
            "table": row["table"],
            "class": row.get("class", ""),
            "has_structure": row["has_structure"],
            "molecule_count": row["molecule_count"],
            "molecule_boxes": row["molecule_boxes"],
            "drawing_objects": row["drawing_objects"],
            "drawing_items": row["drawing_items"],
            "bbox": [row["x0"], row["y0"], row["x1"], row["y1"]],
        }
        for row in results
    ]
    results.sort(key=lambda row: (row["source"], row["page"], row["table"]))
    (out_dir / "structure_presence.jsonl").write_text(
        "\n".join(json.dumps(row, ensure_ascii=False) for row in results) + "\n",
        encoding="utf-8",
    )
    summary = {
        "tables": len(results),
        "with_structure": sum(1 for row in results if row["has_structure"]),
        "with_molecules": sum(1 for row in results if row["molecule_count"]),
        "with_drawings": sum(1 for row in results if row["drawing_items"]),
        "seconds": round(time.perf_counter() - started, 1),
    }
    (out_dir / "structure_summary.json").write_text(
        json.dumps(summary, indent=2), encoding="utf-8"
    )
    print(json.dumps(summary, indent=2), flush=True)


if __name__ == "__main__":
    main()
