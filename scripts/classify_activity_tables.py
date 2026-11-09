#!/usr/bin/env python
"""Classify extracted table crops into activity / PK / analytical / glossary / other.

The classifier is deterministic and explainable: each crop is turned into text
with the local table recognizer (SLANet-1M structure + RapidOCR cell text), then
scored from header metrics, value shapes and explicit negative markers
(NMR/LC/MS/analytical, reagent/glossary, yield/synthesis). No LLM, no training.

Output::

    <out>/all_classes.jsonl     one row per crop: class, confidence, signals
    <out>/activity_manifest.csv the activity subset (plus its markdown)
    <out>/activity/<source>/... hard-linked copies of the activity crops
    <out>/activity_index.html   contact sheet with the reason each table matched

Usage::

    .venv/Scripts/python scripts/classify_activity_tables.py \\
        --crops-dir "C:/Users/.../03-patent/table-crops" \\
        --out-dir   "C:/Users/.../03-patent/activity-tables" \\
        --workers 3
"""

from __future__ import annotations

import argparse
import csv
import json
import os
import re
import time
import unicodedata
from concurrent.futures import ProcessPoolExecutor, as_completed
from multiprocessing import get_context
from pathlib import Path

import numpy as np
from PIL import Image

from mbforge.foundation.inference.ocr import page_text
from mbforge.foundation.inference.table_slanet import predict_table
from mbforge.server.runtime_provider import create_runtime_provider
from mbforge.service.pipeline.activity.normalization import find_activity_metrics
from mbforge.service.pipeline.layout.table_html import html_table_to_markdown
from mbforge.service.ports import configure_runtime_provider, get_runtime

_WORKER_READY = False
#: OCR is quadratic-ish in pixels; page-sized table crops are downscaled before
#: recognition (headers/values stay legible, throughput improves ~10-25x).
MAX_SIDE = 1400
ENGINE = "masked"

# --- vocabulary --------------------------------------------------------------

ACTIVITY_HEADER_RE = re.compile(
    r"(?<![A-Za-z])(?:p\s*(?:ic|ec|ed|gi|ac|cc)\s*[50O]{2}|"
    r"(?:ic|ec|ed|gi|ac|cc)\s*[50O]{2}|p\s*k[di]|k[di])"
    r"(?![A-Za-z])|抑制率|抑制活性|激动活性|拮抗活性|结合活性|抑制|激动|拮抗|活性|"
    r"(?<![A-Za-z])(?:inhibition|activation|potency|activity|response)(?![A-Za-z])",
    re.IGNORECASE,
)
#: Case-sensitive on purpose: ``Cl`` is chlorine, ``CL`` is clearance. Only the
#: header band is searched, so a structure drawing cannot contribute a token.
PK_HEADER_RE = re.compile(
    r"(?<![A-Za-z])(?:AUC[0-9A-Za-z\-]*|Cmax|Tmax|MRT|Vss|Vd|CL)(?![A-Za-z])|"
    r"clearance|bioavailability|half[\s-]?life|t\s*1/2|t½|"
    r"半衰期|清除率|生物利用度|表观分布容积|达峰|药代"
)
ANALYTICAL_RE = re.compile(
    r"NMR|LC\s*/?\s*MS|LCMS|HPLC|HRMS|ESI|m/z|\[M\s*[+\-]|"
    r"Analytical|分析数据|表征|核磁|质谱|保留时间|retention|"
    r"spectrum|spectra|spectroscop|ppm|δ\s*\d|J\s*=|^\s*1H|\b13C\b",
    re.IGNORECASE,
)
GLOSSARY_RE = re.compile(
    r"缩写|术语|简称|全称|释义|abbreviation|definition|glossary",
    re.IGNORECASE,
)
STRUCTURE_HEADER_RE = re.compile(r"structure|结构|化学结构|骨架|formula", re.IGNORECASE)
SYNTH_RE = re.compile(
    r"收率|产率|yield|reagent|试剂|condition|条件|合成", re.IGNORECASE
)
VALUE_UNIT_RE = re.compile(
    r"(?:<|>|~|=|≤|≥)?\s*\d+(?:\.\d+)?\s*"
    r"(?:nM|μM|uM|mM|pM|%|fold|ng\s*/\s*mL|mL\s*/\s*min\s*/\s*kg)|"
    r"\d+(?:\.\d+)?\s+h\b",
    re.IGNORECASE,
)
NUMERIC_RE = re.compile(r"^\s*(?:<|>|~|=|≤|≥)?\s*[-+]?\d*\.?\d+(?:\s*±\s*\d*\.?\d+)?")
QUALITATIVE_CELL_RE = re.compile(r"^(?:[+\-—–]{1,4}|[A-Da-d]|ND|NA|NT|十{1,4})$")
SEPARATOR_RE = re.compile(r"^\s*\|?\s*:?-{3,}")


def _norm(text: str) -> str:
    return unicodedata.normalize("NFKC", str(text or ""))


def split_row(line: str) -> list[str]:
    stripped = line.strip()
    if not (stripped.startswith("|") and stripped.endswith("|")):
        return []
    return [cell.strip().replace(r"\|", "|") for cell in stripped[1:-1].split("|")]


def table_rows(markdown: str) -> list[list[str]]:
    rows = [split_row(line) for line in markdown.splitlines() if line.strip()]
    return [row for row in rows if row]


def header_band(markdown: str) -> str:
    """Header rows only: before the separator, plus unit rows (no data rows).

    Data rows are excluded on purpose: structure glyphs in the first data row
    (``Cl``, ``N``) otherwise leak into the PK/analytical vocabulary.
    """
    lines = [line for line in markdown.splitlines() if line.strip()]
    rows = [split_row(line) for line in lines]
    separator = next(
        (
            index
            for index, row in enumerate(rows)
            if SEPARATOR_RE.match("|" + "|".join(row) + "|")
        ),
        None,
    )
    if separator is None or separator == 0:
        return "\n".join(lines[:3])
    header = lines[:separator]
    for band, line in enumerate(lines[separator + 1 :], start=1):
        cells = split_row(line)
        if not cells:
            break
        if any(NUMERIC_RE.match(_norm(cell)) for cell in cells if cell.strip()):
            break
        header.append(line)
        if band >= 2:
            break
    return "\n".join(header)


def numeric_density(rows: list[list[str]]) -> float:
    cells = [cell for row in rows for cell in row if cell.strip()]
    if not cells:
        return 0.0
    numeric = sum(1 for cell in cells if NUMERIC_RE.match(_norm(cell)))
    return numeric / len(cells)


def classify(markdown: str, fallback_text: str = "") -> dict:
    """Return ``{class, confidence, signals, metrics}`` for one table Markdown."""
    text = _norm(markdown)
    rows = table_rows(markdown)
    header = _norm(header_band(markdown))
    columns = rows[0] if rows else []
    body = rows[1:] if len(rows) > 1 else []
    data_rows = [
        row for row in body if not SEPARATOR_RE.match("|" + "|".join(row) + "|")
    ]
    density = numeric_density(data_rows)
    cells = [cell for row in data_rows for cell in row if cell.strip()]
    long_ratio = (
        sum(1 for cell in cells if len(cell) > 35) / len(cells) if cells else 0.0
    )
    qualitative_values = sum(
        1 for cell in cells if QUALITATIVE_CELL_RE.match(_norm(cell).strip())
    )

    activity_metrics = sorted(
        set(find_activity_metrics(header))
        | {token.upper() for token in ACTIVITY_HEADER_RE.findall(header)}
    )
    pk_metrics = sorted({token.upper() for token in PK_HEADER_RE.findall(header)})
    analytical = bool(ANALYTICAL_RE.search(header))
    glossary = bool(GLOSSARY_RE.search(header))
    structure = bool(STRUCTURE_HEADER_RE.search(header))
    synthesis = bool(SYNTH_RE.search(header))
    unit_values = len(VALUE_UNIT_RE.findall(text))
    has_activity_header = bool(activity_metrics)

    signals = {
        "columns": len(columns),
        "data_rows": len(data_rows),
        "numeric_density": round(density, 2),
        "activity_metrics": activity_metrics,
        "pk_metrics": pk_metrics,
        "analytical": analytical,
        "glossary": glossary,
        "structure": structure,
        "synthesis": synthesis,
        "unit_values": unit_values,
        "long_ratio": round(long_ratio, 2),
        "qualitative_values": qualitative_values,
    }

    # Activity wins over analytical when both are present (a column of IC50 plus a
    # "Method"/LCMS column is still an activity table).
    if has_activity_header and not glossary:
        confidence = 0.95 if (density >= 0.2 or unit_values >= 2) else 0.75
        return {"class": "activity", "confidence": confidence, "signals": signals}

    if pk_metrics and (density >= 0.2 or unit_values >= 2):
        return {"class": "pk", "confidence": 0.8, "signals": signals}

    if analytical:
        return {"class": "analytical", "confidence": 0.85, "signals": signals}

    if glossary or (len(columns) <= 4 and density < 0.05 and data_rows):
        return {
            "class": "glossary",
            "confidence": 0.8 if glossary else 0.5,
            "signals": signals,
        }

    if synthesis:
        return {"class": "synthesis", "confidence": 0.6, "signals": signals}

    # No readable metric header: a dense numeric table with potency units is a
    # candidate worth a manual look rather than a silent drop.
    if unit_values >= 3 and density >= 0.15 and not analytical:
        return {"class": "activity?", "confidence": 0.45, "signals": signals}

    if fallback_text:
        return classify(fallback_text, "")

    return {"class": "other", "confidence": 0.5, "signals": signals}


def worker_init() -> None:
    global _WORKER_READY
    configure_runtime_provider(create_runtime_provider())
    # Warm the table recognizer once per process; the first crop would pay the
    # model load cost otherwise.
    _WORKER_READY = True


def _ocr_band(array, x0: int, y0: int, x1: int, y1: int) -> str:
    """Recognize one band of an image and return its joined text."""
    band = array[max(0, y0) : max(0, y1), max(0, x0) : max(0, x1)]
    if band.size == 0:
        return ""
    result = page_text.read_text_in_boxes(
        band, [("band", [0, 0, band.shape[1], band.shape[0]])]
    )
    return (result.get("band") or "").strip()


def markdown_from_bands(header: str, body: str) -> str:
    """Build a minimal pipe table from two OCR bands (header + values)."""
    header_lines = [line.strip() for line in header.splitlines() if line.strip()]
    body_lines = [line.strip() for line in body.splitlines() if line.strip()]
    if not header_lines and not body_lines:
        return ""
    lines = [f"| {line} |" for line in header_lines]
    lines.append("| --- |")
    lines.extend(f"| {line} |" for line in body_lines)
    return "\n".join(lines)


def shrink(image, max_side: int):
    """Downscale a crop so its longest side is at most *max_side* pixels."""
    if max_side <= 0:
        return image
    width, height = image.size
    longest = max(width, height)
    if longest <= max_side:
        return image
    scale = max_side / float(longest)
    return image.resize(
        (max(1, int(width * scale)), max(1, int(height * scale))),
        Image.LANCZOS,
    )


def structure_boxes(image) -> list[dict]:
    """MolDet boxes on the crop itself, as ``{token, bbox}`` in crop pixels."""
    result = get_runtime().moldet.detect_molecules(image)
    width, height = image.size
    boxes: list[dict] = []
    for detection in result.bboxes:
        x0, y0, x1, y1 = (float(value) for value in detection.bbox)
        boxes.append(
            {
                "token": f"[MOL:{len(boxes)}]",
                "bbox": [x0 * width, y0 * height, x1 * width, y1 * height],
            }
        )
    return boxes


def _paint_white(image, molecule_cells):
    array = np.asarray(image).copy()
    height, width = array.shape[:2]
    for item in molecule_cells:
        x0, y0, x1, y1 = (int(round(float(value))) for value in item["bbox"])
        x0, y0 = max(0, x0), max(0, y0)
        x1, y1 = min(width, x1), min(height, y1)
        if x1 > x0 and y1 > y0:
            array[y0:y1, x0:x1] = 255
    return array


def ocr_table(image) -> tuple[str, str, int]:
    """Return ``(markdown, source, structure_count)`` for one crop.

    MolDet runs first on the crop; its boxes are handed to SLANet as
    ``molecule_cells`` so the structure glyphs are blanked before cell OCR and
    replaced by ``[MOL:n]`` tokens. The table-structure inference still sees the
    untouched crop. Without MolDet hits this is the plain SLANet path.
    """
    if ENGINE == "masked_bands":
        molecule_cells = structure_boxes(image)
        masked = _paint_white(image, molecule_cells)
        height, width = masked.shape[:2]
        header = _ocr_band(masked, 0, 0, width, int(height * 0.38))
        body = _ocr_band(masked, 0, int(height * 0.32), width, int(height * 0.72))
        return markdown_from_bands(header, body), "bands", len(molecule_cells)

    molecule_cells = structure_boxes(image) if ENGINE == "masked" else []
    html = predict_table(image, molecule_cells=molecule_cells)
    markdown = html_table_to_markdown(html) if html else None
    if markdown:
        return markdown, "slanet", len(molecule_cells)
    text = page_text.read_text_in_boxes(
        _paint_white(image, molecule_cells),
        [("full", [0, 0, image.width, image.height])],
    )
    return (text.get("full", "") or "").strip(), "ocr", len(molecule_cells)


def worker_task(task: tuple) -> dict:
    crop_path, source, page, table = task
    started = time.perf_counter()
    try:
        with Image.open(crop_path) as handle:
            image = handle.convert("RGB")
            image = shrink(image, MAX_SIDE)
            markdown, source_kind, structure_count = ocr_table(image)
        result = classify(markdown)
        return {
            "file": crop_path,
            "source": source,
            "page": page,
            "table": table,
            "class": result["class"],
            "confidence": result["confidence"],
            "signals": result["signals"],
            "markdown": markdown[:4000],
            "ocr_source": source_kind,
            "structure_count": structure_count,
            "seconds": round(time.perf_counter() - started, 2),
        }
    except Exception as exc:  # noqa: BLE001 — one bad crop must not stop the run
        return {
            "file": crop_path,
            "source": source,
            "page": page,
            "table": table,
            "class": "error",
            "confidence": 0.0,
            "signals": {"error": str(exc)},
            "markdown": "",
            "ocr_source": "",
            "structure_count": 0,
            "seconds": round(time.perf_counter() - started, 2),
        }


CLASS_ORDER = (
    "activity",
    "activity?",
    "pk",
    "analytical",
    "glossary",
    "synthesis",
    "other",
    "error",
)


def merge_results(
    out_dir: Path, shard_paths: list[Path], crops_dir: Path
) -> list[dict]:
    rows: dict[str, dict] = {}
    for path in shard_paths:
        if not path.is_file():
            continue
        for line in path.read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            row = json.loads(line)
            rows[row["file"]] = row
    ordered = sorted(
        rows.values(), key=lambda row: (row["source"], row["page"], row["table"])
    )

    # Page-split tails: a fragment that prints values (numbers or qualitative
    # grades) adjacent to an activity table inherits its class for review.
    # Adjacency (same/next page, similar width) and a non-narrative shape are
    # required, so a structure+name+mass table beside an activity table is not
    # inherited.
    previous: dict[str, dict] = {}
    for row in ordered:
        source = row["source"]
        prior = previous.get(source)
        if (
            prior
            and row["class"] in {"other", "glossary"}
            and prior["class"] in {"activity", "pk"}
        ):
            adjacent = abs(row["page"] - prior["page"]) <= 1
            similar_width = (
                abs(
                    int(row["signals"].get("columns", 0))
                    - int(prior["signals"].get("columns", 0))
                )
                <= 1
            )
            density = row["signals"].get("numeric_density", 0.0)
            qualitative = int(row["signals"].get("qualitative_values", 0))
            long_ratio = float(row["signals"].get("long_ratio", 1.0))
            has_values = density >= 0.2 or qualitative >= 2
            if adjacent and similar_width and has_values and long_ratio <= 0.2:
                row["class"] = "activity?"
                row["confidence"] = 0.4
                row["signals"]["inherited_from"] = "adjacent activity table"
        previous[source] = row

    (out_dir / "all_classes.jsonl").write_text(
        "\n".join(json.dumps(row, ensure_ascii=False) for row in ordered) + "\n",
        encoding="utf-8",
    )

    selected = [
        row for row in ordered if row["class"] in {"activity", "activity?", "pk"}
    ]
    activity_dir = out_dir / "activity"
    activity_dir.mkdir(parents=True, exist_ok=True)
    for row in selected:
        target = activity_dir / row["source"] / Path(row["file"]).name
        target.parent.mkdir(parents=True, exist_ok=True)
        try:
            os.link(row["file"], target)
        except OSError:
            with Image.open(row["file"]) as handle:
                handle.save(target)

    with (out_dir / "activity_manifest.csv").open(
        "w", newline="", encoding="utf-8"
    ) as handle:
        fields = (
            "source",
            "page",
            "table",
            "class",
            "confidence",
            "metrics",
            "pk",
            "file",
        )
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        for row in selected:
            writer.writerow(
                {
                    "source": row["source"],
                    "page": row["page"],
                    "table": row["table"],
                    "class": row["class"],
                    "confidence": row["confidence"],
                    "metrics": ",".join(row["signals"].get("activity_metrics") or []),
                    "pk": ",".join(row["signals"].get("pk_metrics") or []),
                    "file": f"activity/{row['source']}/{Path(row['file']).name}",
                }
            )

    counts = {
        cls: sum(1 for row in ordered if row["class"] == cls) for cls in CLASS_ORDER
    }
    (out_dir / "summary.json").write_text(
        json.dumps({"total": len(ordered), "counts": counts}, indent=2),
        encoding="utf-8",
    )
    write_index(out_dir, selected, ordered, counts)
    print(
        json.dumps(
            {"total": len(ordered), "selected": len(selected), "counts": counts},
            indent=2,
        )
    )
    return ordered


def write_index(
    out_dir: Path, selected: list[dict], ordered: list[dict], counts: dict
) -> None:
    def cards(rows: list[dict], prefix: str) -> str:
        items: list[str] = []
        for row in rows:
            relative = prefix + row["source"] + "/" + Path(row["file"]).name
            image_src = relative
            if not (out_dir / relative).is_file():
                image_src = str(Path(row["file"]).resolve()).replace("\\", "/")
            metrics = ",".join(row["signals"].get("activity_metrics") or []) or "—"
            items.append(
                f'<figure><a href="{image_src}"><img loading="lazy" src="{image_src}"></a>'
                f"<figcaption>{row['source']} p{row['page']} · {row['class']} "
                f"({row['confidence']})<br>{metrics}</figcaption></figure>"
            )
        return "".join(items)

    html = (
        "<!doctype html><meta charset='utf-8'><title>activity tables</title>"
        "<style>body{font:14px system-ui;margin:24px;background:#fafafa}"
        "h2{margin-top:28px} .grid{display:grid;gap:14px;"
        "grid-template-columns:repeat(auto-fill,minmax(260px,1fr))}"
        "figure{margin:0;background:#fff;border:1px solid #ddd;border-radius:8px;padding:8px}"
        "img{max-width:100%;height:auto;border:1px solid #eee}"
        "figcaption{color:#666;font-size:12px;margin-top:6px}</style>"
        f"<h1>Activity candidates — {len(selected)} of {len(ordered)} tables</h1>"
        f"<p>{json.dumps(counts)}</p>"
        "<h2>activity / pk</h2><div class='grid'>"
        + cards(
            [row for row in selected if row["class"] in {"activity", "pk"}], "activity/"
        )
        + "</div><h2>activity? (needs review)</h2><div class='grid'>"
        + cards([row for row in selected if row["class"] == "activity?"], "activity/")
        + "</div>"
    )
    (out_dir / "activity_index.html").write_text(html, encoding="utf-8")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--crops-dir", required=True)
    parser.add_argument("--out-dir", required=True)
    parser.add_argument("--workers", type=int, default=1)
    parser.add_argument("--max-side", type=int, default=1400)
    parser.add_argument(
        "--engine", choices=("masked", "masked_bands", "plain"), default="masked"
    )
    parser.add_argument("--sources", default=None, help="comma-separated PDF names")
    parser.add_argument(
        "--tables-from",
        default=None,
        help="logical_tables.jsonl: only read activity/pk/activity? fragments",
    )
    parser.add_argument("--limit", type=int, default=None)
    args = parser.parse_args()

    global MAX_SIDE, ENGINE
    MAX_SIDE = args.max_side
    ENGINE = args.engine
    crops_dir = Path(args.crops_dir).resolve()
    out_dir = Path(args.out_dir).resolve()
    out_dir.mkdir(parents=True, exist_ok=True)
    manifest = crops_dir / "manifest.jsonl"
    if not manifest.is_file():
        raise SystemExit(f"missing {manifest}")

    crops = []
    for line in manifest.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        row = json.loads(line)
        crops.append(
            (str(crops_dir / row["file"]), row["source"], row["page"], row["table"])
        )
    if args.sources:
        allowed = {name.strip() for name in args.sources.split(",") if name.strip()}
        crops = [crop for crop in crops if crop[1] in allowed]
    if args.tables_from:
        selected_keys = set()
        for line in Path(args.tables_from).read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            row = json.loads(line)
            if row.get("class") not in {"activity", "pk", "activity?"}:
                continue
            for fragment in row.get("fragments") or []:
                selected_keys.add(
                    (
                        row["source"],
                        int(fragment["page"]),
                        int(fragment["table"]),
                    )
                )
        crops = [
            crop
            for crop in crops
            if (crop[1], int(crop[2]), int(crop[3])) in selected_keys
        ]
    if args.limit is not None:
        crops = crops[: args.limit]
    print(f"{len(crops)} crops to classify", flush=True)

    started = time.perf_counter()
    shard_paths: list[Path] = []
    if args.workers > 1:
        executor = ProcessPoolExecutor(
            max_workers=args.workers,
            mp_context=get_context("spawn"),
            initializer=worker_init,
        )
        with executor:
            futures = [executor.submit(worker_task, task) for task in crops]
            results = []
            for position, future in enumerate(as_completed(futures), start=1):
                results.append(future.result())
                if position % 100 == 0:
                    print(f"  {position}/{len(crops)}", flush=True)
    else:
        worker_init()
        results = []
        for position, task in enumerate(crops, start=1):
            results.append(worker_task(task))
            if position % 100 == 0:
                print(f"  {position}/{len(crops)}", flush=True)

    # One shard keeps the merge path identical for 1 and N workers.
    shard = out_dir / "all_classes.shard.jsonl"
    with shard.open("w", encoding="utf-8") as handle:
        for row in results:
            handle.write(json.dumps(row, ensure_ascii=False) + "\n")
    shard_paths = [shard]
    merge_results(out_dir, shard_paths, crops_dir)
    print(f"finished in {time.perf_counter() - started:.1f}s -> {out_dir}", flush=True)


if __name__ == "__main__":
    main()
