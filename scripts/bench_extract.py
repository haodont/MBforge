#!/usr/bin/env python
"""Extract-stage performance baseline harness.

Runs ``run_pipeline(stage="extract")`` over a fixed patent corpus, N repeats
each, and records three things:

1. wall / per-stage time (the runner's own ``elapsed_ms``);
2. per-model call counts and elapsed time — installed by monkeypatching the
   model boundaries at runtime, so **no production file is modified**;
3. a deterministic result fingerprint (evidence geometry, molecule SMILES,
   crop files), so a later optimization can prove "faster + identical results".

The counts are the point: they expose the duplicate work (each page rendered
twice, MolDet run twice per page) without reading the code.

Usage::

    uv run python scripts/bench_extract.py
    uv run python scripts/bench_extract.py --pdfs a.pdf b.pdf --repeats 3

Requires the local model weights (MolDetv2, MolParser-Mobile, Hiro-Layout,
SLANet-1M, RapidOCR) — see the Extract branch of ``docs/wiki/pipeline.md``.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import shutil
import sqlite3
import statistics
import sys
import threading
import time
from contextlib import contextmanager
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[1]

#: Default corpus — three real patents from the local e2e set.
DEFAULT_CORPUS: tuple[str, ...] = (
    ".tmp/e2e/pdfs/CN120329282A.pdf",
    ".tmp/e2e/pdfs/US20210128561A1.pdf",
    ".tmp/e2e/pdfs/WO2022152853A1.pdf",
)


class Perf:
    """Thread-safe call-count / elapsed-ms accumulator keyed by label."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._calls: dict[str, int] = {}
        self._ms: dict[str, float] = {}

    def reset(self) -> None:
        with self._lock:
            self._calls.clear()
            self._ms.clear()

    def bump(self, label: str, n: int = 1) -> None:
        with self._lock:
            self._calls[label] = self._calls.get(label, 0) + n

    def add_ms(self, label: str, ms: float) -> None:
        with self._lock:
            self._ms[label] = self._ms.get(label, 0.0) + ms

    @contextmanager
    def timer(self, label: str):
        start = time.perf_counter()
        try:
            yield
        finally:
            self.add_ms(label, (time.perf_counter() - start) * 1000.0)

    def snapshot(self) -> dict[str, dict[str, float]]:
        with self._lock:
            labels = sorted(set(self._calls) | set(self._ms))
            return {
                label: {
                    "calls": self._calls.get(label, 0),
                    "ms": round(self._ms.get(label, 0.0), 1),
                }
                for label in labels
            }


PERF = Perf()


def _install(
    target: Any, attr: str, label: str, *, count_arg: int | None = None
) -> None:
    """Wrap ``target.attr`` so each call bumps ``label`` and records its time.

    ``count_arg`` counts ``len(args[count_arg])`` as the call weight (image
    lists); ``None`` counts one per call.
    """
    original = getattr(target, attr)

    def wrapper(*args, **kwargs):
        weight = 1
        if count_arg is not None and len(args) > count_arg:
            try:
                weight = len(args[count_arg])
            except TypeError:
                weight = 1
        PERF.bump(label, weight)
        with PERF.timer(label):
            return original(*args, **kwargs)

    setattr(target, attr, wrapper)


def install_instrumentation() -> None:
    """Install timing/counting on every model boundary (runtime monkeypatch)."""
    import pymupdf

    from mbforge.foundation.inference import (
        hiro_layout,
        moldet_v2_ft,
        molparser,
        table_slanet,
    )
    from mbforge.foundation.inference.ocr import crop_labels, page_text
    from mbforge.service.pipeline.layout import parse as layout_parse

    # Total rasterizations (both producers) + the layout producer's own renders.
    _install(pymupdf.Page, "get_pixmap", "render.pixmap")
    _install(layout_parse, "render_page_rgb", "render.layout")
    _install(hiro_layout.HiroLayoutDetector, "predict_batch", "hiro", count_arg=1)
    _install(moldet_v2_ft.MolDetv2Detector, "detect_batch", "moldet", count_arg=1)
    _install(molparser, "predict_batch", "molparser", count_arg=0)
    _install(page_text, "read_text_in_boxes", "ocr.page_text")
    _install(crop_labels, "extract_label_reads", "ocr.labels")
    _install(table_slanet, "predict_table", "slanet")


def configure_runtime() -> None:
    """Install the repository factory + runtime provider the pipeline needs.

    Mirrors the composition root in ``mbforge.server.app.create_app``: the
    pipeline resolves its ports through both seams, so a direct
    ``run_pipeline`` call must configure them first.
    """
    from mbforge.db.sqlite.repositories import create_repositories
    from mbforge.server.runtime_provider import create_runtime_provider
    from mbforge.service.ports import (
        configure_repository_factory,
        configure_runtime_provider,
    )

    configure_repository_factory(create_repositories)
    configure_runtime_provider(create_runtime_provider())


def warm_models() -> dict[str, Any]:
    """Load every backend and run one tiny forward each (excluded from timing)."""
    import numpy as np
    from PIL import Image

    from mbforge.foundation.inference import (
        hiro_layout,
        moldet_v2_ft,
        molparser,
        table_slanet,
    )
    from mbforge.foundation.inference.ocr import crop_labels, page_text

    status: dict[str, Any] = {}
    moldet = moldet_v2_ft.get_moldet()
    status["moldet"] = moldet.is_available()
    hiro = hiro_layout.get_hiro()
    status["hiro"] = hiro.is_available()
    molparser.load()
    status["molparser"] = molparser.health().get("status")
    table_slanet.load()
    status["slanet"] = table_slanet.health().get("status")
    status["ocr.page_text"] = page_text._get_engine() is not None
    status["ocr.labels"] = crop_labels._get_engine() is not None

    blanks = np.zeros((640, 640, 3), dtype=np.uint8)
    for warm in (
        lambda: moldet.detect(np.zeros((960, 960, 3), dtype=np.uint8)),
        lambda: hiro.predict(blanks),
        lambda: molparser.predict(Image.new("RGB", (224, 224), "white")),
        lambda: table_slanet.predict_table(blanks),
        lambda: page_text.read_text_in_boxes(blanks, [("r", [0, 0, 320, 320])]),
        lambda: crop_labels.extract_label_reads(Image.new("RGB", (64, 64), "white")),
    ):
        try:
            warm()
        except Exception as exc:  # noqa: BLE001 — warm-up failures must not abort
            print(f"  warm-up step failed (ignored): {exc}", file=sys.stderr)
    return status


def _file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _canonical_sha256(value: Any) -> str:
    blob = json.dumps(value, sort_keys=True, ensure_ascii=False, separators=(",", ":"))
    return hashlib.sha256(blob.encode("utf-8")).hexdigest()


def env_snapshot() -> dict[str, Any]:
    """Record the environment + config that any baseline number depends on."""
    import torch

    from mbforge.foundation.config import load_global_config
    from mbforge.foundation.paths import get_model_cache_dir

    cfg = load_global_config()
    cache = Path(get_model_cache_dir())
    weights = {
        "moldet": cache / "MolDetv2" / "moldet_v2_yolo26n_960_doc.pt",
        "hiro_layout": cache / "Hiro-Layout" / "layout_model" / "RT-DETR_25.onnx",
        "molparser": cache / "MolParser-Mobile" / "model.safetensors",
        "slanet_table": cache / "SLANet-1M" / "slanet_1m.onnx",
    }
    info: dict[str, Any] = {
        "python": sys.version.split()[0],
        "torch": torch.__version__,
        "cuda_available": bool(torch.cuda.is_available()),
        "gpu": torch.cuda.get_device_name(0) if torch.cuda.is_available() else None,
        "config": {
            "moldet.device": cfg.moldet.device,
            "moldet.detection_dpi": cfg.moldet.detection_dpi,
            "moldet.detection_batch_size": cfg.moldet.detection_batch_size,
            "moldet.molparser_batch_size": cfg.moldet.molparser_batch_size,
            "moldet.ocr_engine": cfg.moldet.ocr_engine,
            "moldet.ocr_mode": cfg.moldet.ocr_mode,
            "layout.cross_model": cfg.layout.cross_model,
            "ingest.max_concurrency": cfg.ingest.max_concurrency,
        },
        "models_sha256": {
            name: (_file_sha256(path) if path.is_file() else None)
            for name, path in weights.items()
        },
    }
    try:
        import onnxruntime as ort

        info["onnxruntime"] = ort.__version__
    except Exception:  # noqa: BLE001
        info["onnxruntime"] = None
    try:
        import ultralytics

        info["ultralytics"] = ultralytics.__version__
    except Exception:  # noqa: BLE001
        info["ultralytics"] = None
    return info


def fingerprint(root: Path, doc_id: str) -> dict[str, Any]:
    """Deterministic result fingerprint: evidence geometry, SMILES, crop files."""
    rows: list[tuple] = []
    db = root / "library.db"
    if db.is_file():
        conn = sqlite3.connect(str(db))
        try:
            rows = conn.execute(
                "SELECT evidence_id, page, bbox_x0, bbox_y0, bbox_x1, bbox_y1, "
                "kind, raw_text FROM source_evidence WHERE doc_id = ? "
                "ORDER BY evidence_id",
                (doc_id,),
            ).fetchall()
        finally:
            conn.close()

    geometry: list[list[Any]] = []
    molecules: list[list[str]] = []
    for eid, page, x0, y0, x1, y1, kind, raw in rows:
        geometry.append(
            [eid, page, round(x0, 2), round(y0, 2), round(x1, 2), round(y1, 2), kind]
        )
        if kind == "molecule":
            try:
                payload = json.loads(raw)
            except Exception:  # noqa: BLE001
                payload = {}
            molecules.append(
                [str(payload.get("smiles", "")), str(payload.get("esmiles", ""))]
            )

    crops: list[list[str]] = []
    doc_root = root / "storage" / doc_id
    if doc_root.is_dir():
        for path in sorted(doc_root.rglob("*")):
            # Only the crop images. ``.staging/`` also holds per-run checkpoint
            # JSON (run ids, timestamps), which must not enter the fingerprint.
            if path.is_file() and path.suffix.lower() == ".png":
                rel = str(path.relative_to(doc_root)).replace("\\", "/")
                crops.append([rel, _file_sha256(path)])

    return {
        "evidence_rows": len(rows),
        "molecule_rows": len(molecules),
        "crop_files": len(crops),
        "fingerprint_sha256": _canonical_sha256(
            {"geometry": geometry, "molecules": molecules, "crops": crops}
        ),
        "geometry_sha256": _canonical_sha256(geometry),
        "molecules_sha256": _canonical_sha256(molecules),
        "crops_sha256": _canonical_sha256(crops),
    }


def run_once(pdf: Path, doc_id: str, scratch: Path) -> dict[str, Any]:
    """Run Extract once against a fresh scratch library and capture everything."""
    from mbforge.service.pipeline.runner import run_pipeline

    if scratch.exists():
        shutil.rmtree(scratch, ignore_errors=True)
    scratch.mkdir(parents=True, exist_ok=True)

    PERF.reset()
    started = time.perf_counter()
    result = run_pipeline(str(pdf), str(scratch), doc_id=doc_id, stage="extract")
    wall_ms = (time.perf_counter() - started) * 1000.0

    return {
        "wall_ms": round(wall_ms, 1),
        "duration_ms": result.duration_ms,
        "stage_timings": dict(result.stage_timings),
        "page_count": result.page_count,
        "perf": PERF.snapshot(),
        "fingerprint": fingerprint(scratch, doc_id),
    }


def _median(values: list[float]) -> float:
    return round(statistics.median(values), 1) if values else 0.0


def _aggregate(runs: list[dict[str, Any]]) -> dict[str, Any]:
    """Median wall/stage/perf across repeats; counts must be identical."""
    labels = sorted({label for run in runs for label in run["perf"]})
    perf: dict[str, Any] = {}
    for label in labels:
        perf[label] = {
            "calls": [run["perf"].get(label, {}).get("calls", 0) for run in runs],
            "median_ms": _median(
                [run["perf"].get(label, {}).get("ms", 0.0) for run in runs]
            ),
        }
    fps = [run["fingerprint"] for run in runs]
    return {
        "wall_ms": {
            "values": [run["wall_ms"] for run in runs],
            "median": _median([run["wall_ms"] for run in runs]),
        },
        "extract_ms": {
            "values": [run["stage_timings"].get("extract", 0) for run in runs],
            "median": _median([run["stage_timings"].get("extract", 0) for run in runs]),
        },
        "pages": runs[0]["page_count"] if runs else 0,
        "perf": perf,
        "fingerprint": fps[0] if fps else {},
        "deterministic": len({fp["fingerprint_sha256"] for fp in fps}) <= 1,
    }


def _print_report(results: dict[str, Any]) -> None:
    for name, agg in results.items():
        pages = agg["pages"]
        print(
            f"\n=== {name}  ({pages} pages, {len(agg['wall_ms']['values'])} runs) ==="
        )
        print(
            f"  wall median {agg['wall_ms']['median']} ms "
            f"(min {min(agg['wall_ms']['values'])} / all {agg['wall_ms']['values']})"
        )
        print(f"  extract stage median {agg['extract_ms']['median']} ms")
        print(f"  deterministic: {agg['deterministic']}")
        for label, data in agg["perf"].items():
            calls = data["calls"]
            call_str = f"{calls[0]}" if len(set(calls)) == 1 else f"{calls}"
            print(
                f"    {label:<16} calls={call_str:<6} median={data['median_ms']:>9.1f} ms"
            )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--pdfs", nargs="*", default=None, help="override corpus paths")
    parser.add_argument("--repeats", type=int, default=3)
    parser.add_argument(
        "--out", default="docs/qa/bench-extract-baseline.json", help="JSON output path"
    )
    parser.add_argument("--scratch", default=".tmp/bench", help="scratch root")
    args = parser.parse_args(argv)

    raw = args.pdfs or list(DEFAULT_CORPUS)
    pdfs = [Path(p) if Path(p).is_absolute() else REPO_ROOT / p for p in raw]
    missing = [p for p in pdfs if not p.is_file()]
    if missing:
        print(
            "missing corpus PDFs:",
            *(f"  {p}" for p in missing),
            sep="\n",
            file=sys.stderr,
        )
        return 2

    print("configuring runtime...")
    configure_runtime()
    print("warming models...")
    warm_status = warm_models()
    print(f"  {warm_status}")
    install_instrumentation()

    env = env_snapshot()
    print(
        f"environment: {env['gpu']} (cuda={env['cuda_available']}), torch {env['torch']}"
    )

    scratch_root = REPO_ROOT / args.scratch
    corpus: list[dict[str, Any]] = []
    results: dict[str, Any] = {}
    failed = False

    for pdf in pdfs:
        doc_id = f"bench_{pdf.stem}"
        print(f"\nbenchmarking {pdf.name} ...")
        runs: list[dict[str, Any]] = []
        for rep in range(args.repeats):
            scratch = scratch_root / f"{pdf.stem}_{rep}" / "library"
            try:
                run = run_once(pdf, doc_id, scratch)
            except Exception as exc:  # noqa: BLE001 — one bad doc must not abort
                print(f"  run {rep + 1} FAILED: {exc}", file=sys.stderr)
                failed = True
                break
            runs.append(run)
            print(
                f"  run {rep + 1}: wall={run['wall_ms']:.0f} ms "
                f"extract={run['stage_timings'].get('extract', 0)} ms "
                f"molecules={run['fingerprint']['molecule_rows']} "
                f"crops={run['fingerprint']['crop_files']}"
            )
        if runs:
            agg = _aggregate(runs)
            results[pdf.name] = agg
            if not agg["deterministic"]:
                print(
                    f"  !! NON-DETERMINISTIC across repeats for {pdf.name}",
                    file=sys.stderr,
                )
                failed = True
        corpus.append(
            {
                "file": pdf.name,
                "sha256": _file_sha256(pdf),
                "pages": runs[0]["page_count"] if runs else 0,
            }
        )

    _print_report(results)

    payload = {
        "note": (
            "Extract-stage baseline. Machine-specific: numbers depend on the GPU, "
            "driver and the model weights whose sha256 are recorded here."
        ),
        "generated_at": time.strftime("%Y-%m-%dT%H:%M:%S"),
        "environment": env,
        "warm_status": warm_status,
        "corpus": corpus,
        "results": results,
    }
    out_path = Path(args.out) if Path(args.out).is_absolute() else REPO_ROOT / args.out
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(
        json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
    )
    print(f"\nwrote {out_path}")
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
