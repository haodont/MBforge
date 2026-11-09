#!/usr/bin/env python
"""Extract table-region crops from a folder of patent PDFs (parallel).

Only the local layout detector runs (Hiro-Layout): each page is rendered once,
its ``table`` regions are cropped with a small padding, and saved as PNG. No OCR,
no molecule recognition — this is the quickest way to build a table sample
library.

Parallelism is per PDF (a document is processed sequentially by one worker), so
each worker loads the layout model once and then spends its time rendering and
cropping. A finished document writes a ``.done`` marker, so an interrupted run
resumes where it stopped.

Output::

    <out>/<pdf-relative-stem>/p0001_t01.png
    <out>/manifest.jsonl      one row per crop (source, page, bbox, size)
    <out>/manifest.csv        the same rows for spreadsheets
    <out>/index.html          thumbnail contact sheet for browsing
    <out>/<pdf>.done          resume marker (a finished PDF is skipped)

Usage::

    .venv/Scripts/python scripts/extract_table_crops.py \\
        --pdf-dir "C:/Users/.../03-patent/file" \\
        --out-dir "C:/Users/.../03-patent/table-crops" \\
        --workers 4
"""

from __future__ import annotations

import argparse
import csv
import json
import os
import time
from concurrent.futures import ProcessPoolExecutor, as_completed
from multiprocessing import get_context
from pathlib import Path

from PIL import Image

from mbforge.server.runtime_provider import create_runtime_provider
from mbforge.service.pipeline.layout.parse import render_page_rgb
from mbforge.service.pipeline.layout.regions import build_regions
from mbforge.service.ports import configure_runtime_provider, get_runtime

COLUMNS = (
    "source",
    "page",
    "table",
    "file",
    "dpi",
    "x0",
    "y0",
    "x1",
    "y1",
    "width_px",
    "height_px",
    "score",
)

_WORKER_DETECTOR = None


def _worker_init() -> None:
    """Load the layout model once per worker process."""
    global _WORKER_DETECTOR
    configure_runtime_provider(create_runtime_provider())
    _WORKER_DETECTOR = get_runtime().hiro_layout.get_hiro()


def iter_pdfs(root: Path) -> list[Path]:
    return sorted(path for path in root.rglob("*.pdf") if path.is_file())


def stem_of(pdf: Path, root: Path) -> str:
    relative = pdf.relative_to(root).with_suffix("")
    return "__".join(relative.parts)


def crop_table(
    image,
    bbox_px: list[float],
    *,
    dpi: float,
    padding_pt: float,
) -> Image.Image:
    """Crop one table region, padded in PDF points and clipped to the page."""
    pad = padding_pt * dpi / 72.0
    height, width = image.shape[:2]
    x0 = max(0, int(round(float(bbox_px[0]) - pad)))
    y0 = max(0, int(round(float(bbox_px[1]) - pad)))
    x1 = min(width, int(round(float(bbox_px[2]) + pad)))
    y1 = min(height, int(round(float(bbox_px[3]) + pad)))
    if x1 <= x0 or y1 <= y0:
        raise ValueError("empty table crop")
    return Image.fromarray(image[y0:y1, x0:x1])


def extract_pdf(
    pdf: Path,
    root: Path,
    out_dir: Path,
    *,
    detector,
    dpi: float,
    conf: float,
    padding_pt: float,
    max_pages: int | None,
    shard: Path,
) -> list[dict]:
    """Extract one PDF's tables; append its manifest rows to the worker shard."""
    import pymupdf

    stem = stem_of(pdf, root)
    target = out_dir / stem
    target.mkdir(parents=True, exist_ok=True)
    zoom = dpi / 72.0
    rows: list[dict] = []
    started = time.perf_counter()
    document = pymupdf.open(str(pdf))
    try:
        total = document.page_count
        if max_pages is not None:
            total = min(total, max_pages)
        for index in range(total):
            page = document.load_page(index)
            image = render_page_rgb(page, zoom)
            boxes = get_runtime().hiro_layout.detect_regions(
                image, detector, threshold=conf
            )
            regions, _frame = build_regions(
                boxes,
                doc_id=stem,
                page=index + 1,
                page_size_px=(float(image.shape[1]), float(image.shape[0])),
                dpi=dpi,
            )
            tables = [region for region in regions if str(region["type"]) == "table"]
            for table_index, region in enumerate(tables, start=1):
                crop = crop_table(
                    image, region["bbox_px"], dpi=dpi, padding_pt=padding_pt
                )
                name = f"p{index + 1:04d}_t{table_index:02d}.png"
                relative = Path(stem) / name
                crop.save(target / name, format="PNG")
                rows.append(
                    {
                        "source": str(pdf.relative_to(root)),
                        "page": index + 1,
                        "table": table_index,
                        "file": relative.as_posix(),
                        "dpi": dpi,
                        "x0": round(float(region["bbox_pdf"][0]), 2),
                        "y0": round(float(region["bbox_pdf"][1]), 2),
                        "x1": round(float(region["bbox_pdf"][2]), 2),
                        "y1": round(float(region["bbox_pdf"][3]), 2),
                        "width_px": crop.width,
                        "height_px": crop.height,
                        "score": round(float(region["score"]), 4),
                    }
                )
    finally:
        document.close()
    elapsed = time.perf_counter() - started
    # Commit the rows only after the document finished: an interrupted document
    # leaves no manifest rows and is simply redone on resume.
    with shard.open("a", encoding="utf-8") as handle:
        for row in rows:
            handle.write(json.dumps(row, ensure_ascii=False) + "\n")
    (out_dir / f"{stem}.done").write_text(
        json.dumps({"pages": total, "tables": len(rows), "seconds": round(elapsed, 1)}),
        encoding="utf-8",
    )
    return rows


def _worker_task(task: tuple) -> dict:
    pdf, root, out_dir, dpi, conf, padding_pt, max_pages = task
    if _WORKER_DETECTOR is None:
        _worker_init()
    started = time.perf_counter()
    try:
        rows = extract_pdf(
            Path(pdf),
            Path(root),
            Path(out_dir),
            detector=_WORKER_DETECTOR,
            dpi=dpi,
            conf=conf,
            padding_pt=padding_pt,
            max_pages=max_pages,
            shard=Path(out_dir) / f"manifest.shard-{os.getpid()}.jsonl",
        )
        return {
            "pdf": Path(pdf).name,
            "tables": len(rows),
            "error": None,
            "seconds": round(time.perf_counter() - started, 1),
        }
    except Exception as exc:  # noqa: BLE001 — one broken PDF must not stop the run
        return {
            "pdf": Path(pdf).name,
            "tables": 0,
            "error": str(exc),
            "seconds": round(time.perf_counter() - started, 1),
        }


def write_index(out_dir: Path, rows: list[dict]) -> None:
    by_doc: dict[str, list[dict]] = {}
    for row in rows:
        by_doc.setdefault(row["source"], []).append(row)
    cards: list[str] = []
    for source in sorted(by_doc):
        cards.append(
            f'<h2>{source} <small>({len(by_doc[source])})</small></h2><div class="grid">'
        )
        for row in by_doc[source]:
            name = Path(row["file"]).name
            cards.append(
                f'<figure><a href="{row["file"]}"><img loading="lazy" '
                f'src="{row["file"]}" alt="{name}"></a>'
                f"<figcaption>p{row['page']} · t{row['table']} · "
                f"{row['width_px']}×{row['height_px']}</figcaption></figure>"
            )
        cards.append("</div>")
    html = (
        "<!doctype html><meta charset='utf-8'><title>table crops</title>"
        "<style>body{font:14px system-ui;margin:24px;background:#fafafa}"
        "h2{margin-top:28px} .grid{display:grid;gap:14px;"
        "grid-template-columns:repeat(auto-fill,minmax(260px,1fr))}"
        "figure{margin:0;background:#fff;border:1px solid #ddd;border-radius:8px;padding:8px}"
        "img{max-width:100%;height:auto;border:1px solid #eee}"
        "figcaption{color:#666;font-size:12px;margin-top:6px}</style>"
        f"<h1>Table crops — {len(rows)} items / {len(by_doc)} documents</h1>"
        + "".join(cards)
    )
    (out_dir / "index.html").write_text(html, encoding="utf-8")


def merge_manifests(out_dir: Path) -> list[dict]:
    """Merge the canonical manifest with every worker shard, then write outputs."""
    rows: dict[str, dict] = {}
    sources = [
        out_dir / "manifest.jsonl",
        *sorted(out_dir.glob("manifest.shard-*.jsonl")),
    ]
    for path in sources:
        if not path.is_file():
            continue
        for line in path.read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            try:
                row = json.loads(line)
            except json.JSONDecodeError:
                continue
            rows[row["file"]] = row
    ordered = sorted(
        rows.values(), key=lambda row: (row["source"], row["page"], row["table"])
    )
    (out_dir / "manifest.jsonl").write_text(
        "\n".join(json.dumps(row, ensure_ascii=False) for row in ordered) + "\n",
        encoding="utf-8",
    )
    with (out_dir / "manifest.csv").open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=COLUMNS)
        writer.writeheader()
        writer.writerows({key: row[key] for key in COLUMNS} for row in ordered)
    write_index(out_dir, ordered)
    for path in out_dir.glob("manifest.shard-*.jsonl"):
        path.unlink()
    return ordered


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--pdf-dir", required=True)
    parser.add_argument("--out-dir", required=True)
    parser.add_argument("--workers", type=int, default=1)
    parser.add_argument("--dpi", type=float, default=200.0)
    parser.add_argument("--conf", type=float, default=0.4)
    parser.add_argument("--padding-pt", type=float, default=2.0)
    parser.add_argument("--max-pages", type=int, default=None)
    parser.add_argument("--limit", type=int, default=None)
    parser.add_argument("--force", action="store_true", help="redo finished PDFs")
    args = parser.parse_args()

    root = Path(args.pdf_dir).resolve()
    out_dir = Path(args.out_dir).resolve()
    if not root.is_dir():
        raise SystemExit(f"not a directory: {root}")
    out_dir.mkdir(parents=True, exist_ok=True)

    pdfs = iter_pdfs(root)
    if args.limit is not None:
        pdfs = pdfs[: args.limit]
    pending = [
        pdf
        for pdf in pdfs
        if args.force or not (out_dir / f"{stem_of(pdf, root)}.done").is_file()
    ]
    print(f"{len(pdfs)} PDF(s), {len(pending)} pending", flush=True)
    if not pending:
        merge_manifests(out_dir)
        return

    tasks = [
        (
            str(pdf),
            str(root),
            str(out_dir),
            args.dpi,
            args.conf,
            args.padding_pt,
            args.max_pages,
        )
        for pdf in pending
    ]
    started = time.perf_counter()
    if args.workers > 1:
        executor = ProcessPoolExecutor(
            max_workers=args.workers,
            mp_context=get_context("spawn"),
            initializer=_worker_init,
        )
        with executor:
            futures = [executor.submit(_worker_task, task) for task in tasks]
            for position, future in enumerate(as_completed(futures), start=1):
                result = future.result()
                status = (
                    f"ERROR {result['error']}"
                    if result["error"]
                    else f"{result['tables']} tables"
                )
                print(
                    f"[{position}/{len(tasks)}] {result['pdf']}: {status} "
                    f"({result['seconds']}s)",
                    flush=True,
                )
    else:
        for position, task in enumerate(tasks, start=1):
            result = _worker_task(task)
            status = (
                f"ERROR {result['error']}"
                if result["error"]
                else f"{result['tables']} tables"
            )
            print(
                f"[{position}/{len(tasks)}] {result['pdf']}: {status} "
                f"({result['seconds']}s)",
                flush=True,
            )

    rows = merge_manifests(out_dir)
    print(
        f"done: {len(rows)} table crops from {len({row['source'] for row in rows})} "
        f"document(s) in {time.perf_counter() - started:.1f}s -> {out_dir}",
        flush=True,
    )


if __name__ == "__main__":
    main()
