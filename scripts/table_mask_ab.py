#!/usr/bin/env python
"""A/B the table molecule-masking switch on real patents.

Runs only the pages that carry table evidence (from the library's SQL rows), so
the comparison covers exactly the affected surface:

    off → current behaviour (structures read as cell text)
    on  → structures blanked for cell OCR, ``[MOL:n]`` token in their cell

Reports per document: tables, table rows, cells, chemistry-looking cells,
masked tables/molecules. Nothing is written to the library.

Usage::

    .venv/Scripts/python scripts/table_mask_ab.py \\
        --db .tmp/e2e/library/library.db --pdf-dir .tmp/e2e/pdfs
    .venv/Scripts/python scripts/table_mask_ab.py --db <db> --pdf <one.pdf> --doc-id <id>
"""

from __future__ import annotations

import argparse
import json
import re
import sqlite3
import time
from pathlib import Path

from mbforge.db.sqlite.repositories import create_repositories
from mbforge.server.runtime_provider import create_runtime_provider
from mbforge.service.pipeline.layout.parse import parse_page_image, render_page_rgb
from mbforge.service.ports import (
    configure_repository_factory,
    configure_runtime_provider,
    get_runtime,
)

CHEM = re.compile(
    r"(?:^|\s|\()(?:CH3|CH2|NH2|NH|OH|CO2H|COOH|CF3|H3C|CO|CN|NO2|SO2|Cl|Br|"
    r"Me|Et|Ac|Ph|Boc|Fmoc)(?=$|\s|\)|,|\.|;|:)"
)
SEPARATOR = set("-: ")
COUNT_KEYS = (
    "tables",
    "rows",
    "cells",
    "chem_cells",
    "masked_tables",
    "masked_molecules",
)


def table_pages(db: Path, doc_id: str) -> list[int]:
    """Pages that holding table evidence, in page order."""
    connection = sqlite3.connect(f"file:{db}?mode=ro", uri=True)
    try:
        rows = connection.execute(
            "select distinct page from source_evidence "
            "where doc_id=? and kind in ('tab','seq') order by page",
            (doc_id,),
        ).fetchall()
    finally:
        connection.close()
    return [int(row[0]) for row in rows]


def analyze(page) -> dict:
    """Count chemistry-looking cells in one parsed page's tables."""
    tables = [region for region in page.regions if str(region.get("type")) == "table"]
    cells = chem = rows = 0
    for table in tables:
        for line in str(table.get("text") or "").splitlines():
            stripped = line.strip()
            if not stripped.startswith("|"):
                continue
            parts = [part.strip() for part in stripped.strip("|").split("|")]
            if all(set(part) <= SEPARATOR for part in parts if part):
                continue
            rows += 1
            for part in parts:
                if not part:
                    continue
                cells += 1
                if CHEM.search(part):
                    chem += 1
    return {
        "tables": len(tables),
        "rows": rows,
        "cells": cells,
        "chem_cells": chem,
        "masked_tables": sum(1 for t in tables if t.get("molecule_cells")),
        "masked_molecules": sum(len(t.get("molecule_cells") or []) for t in tables),
    }


def run(pdf: Path, doc_id: str, pages: list[int], flag: bool, detector) -> dict:
    """Parse *pages* twice-safe: no output is persisted, models are reused."""
    import pymupdf

    totals = dict.fromkeys(COUNT_KEYS, 0)
    start = time.perf_counter()
    document = pymupdf.open(str(pdf))
    try:
        for page_num in pages:
            image = render_page_rgb(document.load_page(page_num - 1))
            parsed = parse_page_image(
                image,
                doc_id=doc_id,
                page_num=page_num,
                detector=detector,
                mask_table_molecules=flag,
            )
            counted = analyze(parsed)
            for key in COUNT_KEYS:
                totals[key] += counted[key]
    finally:
        document.close()
    totals["seconds"] = round(time.perf_counter() - start, 1)
    totals["pages"] = len(pages)
    return totals


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--db", required=True)
    parser.add_argument("--pdf-dir")
    parser.add_argument("--pdf")
    parser.add_argument("--doc-id")
    args = parser.parse_args()

    configure_repository_factory(create_repositories)
    configure_runtime_provider(create_runtime_provider())

    db = Path(args.db)
    connection = sqlite3.connect(f"file:{db}?mode=ro", uri=True)
    connection.row_factory = sqlite3.Row
    if args.pdf:
        docs = [{"doc_id": args.doc_id, "file_name": Path(args.pdf).name}]
        pdfs = {Path(args.pdf).name: Path(args.pdf)}
    else:
        docs = [
            dict(row)
            for row in connection.execute("select doc_id, file_name from documents")
        ]
        pdfs = (
            {path.name: path for path in Path(args.pdf_dir).glob("*.pdf")}
            if args.pdf_dir
            else {}
        )
        storage = db.parent
        for doc in docs:
            stored = storage / "storage" / doc["doc_id"] / doc["file_name"]
            if doc["file_name"] not in pdfs and stored.is_file():
                pdfs[doc["file_name"]] = stored
    connection.close()

    detector = get_runtime().hiro_layout.get_hiro()
    summary: list[dict] = []
    for doc in docs:
        pdf = pdfs.get(doc["file_name"])
        pages = table_pages(db, doc["doc_id"])
        if pdf is None or not pages:
            print(
                f"skip {doc['file_name']} (pdf={pdf is not None}, pages={len(pages)})",
                flush=True,
            )
            continue
        baseline = run(pdf, doc["doc_id"], pages, False, detector)
        masked = run(pdf, doc["doc_id"], pages, True, detector)
        print(f"{doc['file_name']}: off={json.dumps(baseline)}", flush=True)
        print(f"{doc['file_name']}: on ={json.dumps(masked)}", flush=True)
        summary.append(
            {
                "file": doc["file_name"],
                "pages": len(pages),
                "tables": baseline["tables"],
                "chem_off": baseline["chem_cells"],
                "chem_on": masked["chem_cells"],
                "masked_molecules": masked["masked_molecules"],
                "rows_off": baseline["rows"],
                "rows_on": masked["rows"],
                "cells_off": baseline["cells"],
                "cells_on": masked["cells"],
            }
        )
    print("\nSUMMARY", flush=True)
    print(json.dumps(summary, indent=2), flush=True)


if __name__ == "__main__":
    main()
