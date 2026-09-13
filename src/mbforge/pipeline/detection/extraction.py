"""Public molecule extraction entry points.

PDF image extraction is coordinated here while page rendering, page-level
MolDet, and crop/MolParser processing live in focused components. Native text
SMILES extraction remains available through the same compatibility API.
"""

from __future__ import annotations

import asyncio
import contextlib
import hashlib
import queue as queue_module
import re
import shutil  # noqa: F401 — tests patch this legacy module attribute
import threading
from collections.abc import Iterable
from pathlib import Path

from ...utils.logger import get_logger
from ..cancellation import CancelCheck
from .extraction_components import (
    DEFAULT_SCRIBE_BATCH_SIZE as _DEFAULT_SCRIBE_BATCH_SIZE,
)
from .extraction_components import (
    MAX_SCRIBE_BATCH_SIZE as _MAX_SCRIBE_BATCH_SIZE,
)
from .extraction_components import (
    CropProcessor,
    clamp_scribe_batch_size,
    fill_ocr_slot,
    ocr_label_image,
)
from .extraction_config import (
    DEFAULT_RENDER_DPI as _DEFAULT_RENDER_DPI,
)
from .extraction_config import (
    DEFAULT_TEXT_PAGE_CHAR_THRESHOLD as _DEFAULT_TEXT_PAGE_CHAR_THRESHOLD,
)
from .extraction_config import (
    load_extraction_config,
)
from .page_detection import PageDetector
from .page_renderer import PageRenderer
from .types import ExtractionResult

logger = get_logger("mbforge.pipeline.detection.extraction")

# Compatibility aliases retained for existing callers and focused tests.
_clamp_scribe_batch_size = clamp_scribe_batch_size
_ocr_label_image = ocr_label_image
_fill_ocr_slot = fill_ocr_slot
DEFAULT_RENDER_DPI = _DEFAULT_RENDER_DPI
DEFAULT_SCRIBE_BATCH_SIZE = _DEFAULT_SCRIBE_BATCH_SIZE
MAX_SCRIBE_BATCH_SIZE = _MAX_SCRIBE_BATCH_SIZE
_TEXT_PAGE_CHAR_THRESHOLD = _DEFAULT_TEXT_PAGE_CHAR_THRESHOLD

_SMILES_LIKE_PATTERN = re.compile(r"[A-Za-z0-9\(\)\[\]\=\#\+\-\\\\/@\.]{3,}")


def make_candidate_id(
    doc_id: str,
    canonical_smiles: str,
    page_number: int | None,
    bbox: Iterable[float] | None,
) -> str:
    """Return a deterministic stable identity for a molecule candidate."""
    page_part = "" if page_number is None else str(page_number)
    bbox_part = ",".join(f"{value:.2f}" for value in bbox) if bbox else ""
    payload = "|".join((doc_id, canonical_smiles, page_part, bbox_part))
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()[:16]


def _nearby_page_text(
    page_blocks: object,
    bbox_top_left: tuple[float, float, float, float],
) -> str:
    """Return native PDF text near a detected molecule bbox."""
    if not isinstance(page_blocks, (list, tuple)):
        return ""

    x0, y0, x1, y1 = bbox_top_left
    width = max(1.0, x1 - x0)
    height = max(1.0, y1 - y0)
    pad_x = max(18.0, width * 0.75)
    pad_y = max(24.0, height * 1.5)
    query = (x0 - pad_x, y0 - pad_y, x1 + pad_x, y1 + pad_y)

    nearby: list[tuple[float, str]] = []
    for block in page_blocks:
        if not isinstance(block, (list, tuple)) or len(block) < 5:
            continue
        try:
            bx0, by0, bx1, by1 = (float(value) for value in block[:4])
        except (TypeError, ValueError):
            continue
        text = block[4].strip() if isinstance(block[4], str) else ""
        if not text:
            continue
        if bx1 < query[0] or bx0 > query[2] or by1 < query[1] or by0 > query[3]:
            continue
        distance = abs((bx0 + bx1) / 2 - (x0 + x1) / 2) + abs(
            (by0 + by1) / 2 - (y0 + y1) / 2
        )
        nearby.append((distance, text))

    nearby.sort(key=lambda item: item[0])
    return " ".join(text for _, text in nearby[:4])[:1000]


def _put_bounded(
    target: object,
    item: object,
    check: CancelCheck,
    consumer_alive=None,
) -> bool:
    """Put into a bounded queue while observing cancellation and liveness."""
    while True:
        check()
        try:
            target.put(item, timeout=0.1)
            return True
        except queue_module.Full:
            if consumer_alive is not None and not consumer_alive():
                return False


def _load_pdf_open_errors() -> tuple[type[Exception], ...]:
    import pymupdf

    errors: tuple[type[Exception], ...] = (RuntimeError,)
    if hasattr(pymupdf, "FileDataError"):
        errors += (pymupdf.FileDataError,)
    return errors


def _read_page_count(
    pdf_path: str, open_errors: tuple[type[Exception], ...]
) -> int | None:
    import pymupdf

    try:
        probe = pymupdf.open(pdf_path)
        try:
            return len(probe)
        finally:
            probe.close()
    except open_errors as exc:
        logger.error("Failed to open PDF %s: %s", pdf_path, exc)
        return None


def _run_page_pipeline(
    *,
    page_q: queue_module.Queue,
    crop_q: queue_module.Queue,
    renderer: PageRenderer,
    processor: CropProcessor,
    page_detector: PageDetector,
    check: CancelCheck,
) -> None:
    """Run the bounded renderer → detector → crop-worker pipeline."""
    worker = threading.Thread(
        target=processor.run,
        name="mbforge-detect-preprocess",
        daemon=True,
    )
    renderer_thread = threading.Thread(
        target=renderer.run,
        name="mbforge-detect-render",
        daemon=True,
    )
    worker.start()
    renderer_thread.start()

    try:
        while True:
            item = page_q.get()
            if item is None:
                break
            page_idx, image, page_blocks, page_w_pts, page_h_pts = item
            check()
            bboxes = page_detector.detect(
                page_idx=page_idx,
                image=image,
                page_w_pts=page_w_pts,
                page_h_pts=page_h_pts,
            )
            if not bboxes:
                continue

            scale_x = page_w_pts / image.width if image.width > 0 else 0
            scale_y = page_h_pts / image.height if image.height > 0 else 0
            if not _put_bounded(
                crop_q,
                (
                    page_idx,
                    image,
                    bboxes,
                    scale_x,
                    scale_y,
                    page_h_pts,
                    page_blocks,
                ),
                check,
                consumer_alive=worker.is_alive,
            ):
                break
    finally:
        while True:
            try:
                crop_q.put(None, timeout=0.1)
                break
            except queue_module.Full:
                if not worker.is_alive():
                    break
        worker.join()

        # If the main loop exits early, drain page_q so the renderer can exit.
        while renderer_thread.is_alive():
            with contextlib.suppress(queue_module.Empty):
                page_q.get(timeout=0.2)
            renderer_thread.join(timeout=0.1)
        renderer_thread.join()


def extract_molecules_from_pdf(
    pdf_path: str,
    library_root: str,
    doc_id: str,
    max_pages: int | None = None,
    cancel_check: CancelCheck | None = None,
    staging_dir: str | Path | None = None,
    ocr_spans_by_page: dict[int, list[dict]] | None = None,
) -> list[ExtractionResult]:
    """Render a PDF and extract molecule structures via MolDet and MolParser.

    The coordinator preserves the existing three-thread schedule: rendering
    stays ahead in one thread, the caller runs page-level MolDet, and a worker
    preprocesses crops while flushing bounded MolParser batches.
    """
    from ...backends import molparser
    from ...backends.moldet_v2_ft import get_moldet
    from ...storage.layout import LibraryLayout

    check = cancel_check or (lambda: None)
    config = load_extraction_config()
    detector = get_moldet()
    if not detector.is_available():
        logger.warning("MolDetv2 unavailable, skipping image molecule extraction")
        return []

    logger.info("Loading MolParser model for document %s", doc_id)
    molparser.load()
    logger.info("MolParser availability: %s", molparser.health())

    crop_dir = LibraryLayout(library_root).crops_dir(doc_id)
    write_dir = Path(staging_dir) / "crops" if staging_dir else crop_dir
    write_dir.mkdir(parents=True, exist_ok=True)

    open_errors = _load_pdf_open_errors()
    page_count = _read_page_count(pdf_path, open_errors)
    if page_count is None:
        return []

    page_q: queue_module.Queue = queue_module.Queue(maxsize=2)
    crop_q: queue_module.Queue = queue_module.Queue(maxsize=2)

    def put_bounded(target: queue_module.Queue, item: object) -> bool:
        return _put_bounded(target, item, check)

    renderer = PageRenderer(
        pdf_path=pdf_path,
        page_count=page_count,
        max_pages=max_pages if max_pages is not None else config.max_pages,
        render_dpi=config.render_dpi,
        text_page_char_threshold=config.text_page_char_threshold,
        page_q=page_q,
        check=check,
        put_bounded=put_bounded,
        open_errors=open_errors,
    )
    processor = CropProcessor(
        crop_q=crop_q,
        crop_dir=crop_dir,
        write_dir=write_dir,
        doc_id=doc_id,
        scribe_batch_size=config.scribe_batch_size,
        check=check,
        nearby_page_text=_nearby_page_text,
        molparser=molparser,
        ocr_reader=_ocr_label_image,
        ocr_slot_filler=_fill_ocr_slot,
    )
    page_detector = PageDetector(
        detector=detector,
        detection_batch_size=config.detection_batch_size,
        doc_id=doc_id,
        ocr_spans_by_page=ocr_spans_by_page,
    )

    _run_page_pipeline(
        page_q=page_q,
        crop_q=crop_q,
        renderer=renderer,
        processor=processor,
        page_detector=page_detector,
        check=check,
    )

    if renderer.error:
        raise renderer.error
    if processor.error:
        raise processor.error

    for future in processor.ocr_futures:
        with contextlib.suppress(Exception):
            future.result()
    processor.batcher.enrich_ocr_labels()

    logger.info(
        "Extracted %d molecule image candidates from %s "
        "(%d pure-text pages skipped, dpi=%s, batch=%d, scribe_batch=%d)",
        len(processor.results),
        doc_id,
        renderer.skipped_pure_text,
        config.render_dpi,
        config.detection_batch_size,
        config.scribe_batch_size,
    )
    return processor.results


async def extract_molecules_from_pdf_async(
    pdf_path: str,
    library_root: str,
    doc_id: str,
    max_pages: int | None = None,
) -> list[ExtractionResult]:
    """Run the synchronous PDF extractor outside the event loop."""
    return await asyncio.to_thread(
        extract_molecules_from_pdf,
        pdf_path,
        library_root,
        doc_id,
        max_pages,
    )


def extract_molecules_from_text(text: str, doc_id: str) -> list[ExtractionResult]:
    """Extract SMILES strings from raw text and validate them with RDKit."""
    from rdkit import Chem

    results: list[ExtractionResult] = []
    seen: set[str] = set()
    for match in _SMILES_LIKE_PATTERN.finditer(text):
        candidate = match.group(0)
        try:
            mol = Chem.MolFromSmiles(candidate)
            if mol is None:
                continue
            canonical = Chem.MolToSmiles(mol, canonical=True, isomericSmiles=True)
        except Exception as exc:
            logger.debug("RDKit failed to parse candidate %r: %s", candidate, exc)
            continue
        if canonical in seen:
            continue
        seen.add(canonical)
        start = max(0, match.start() - 200)
        end = min(len(text), match.end() + 200)
        results.append(
            ExtractionResult(
                esmiles=canonical,
                name="",
                source="text",
                context_text=text[start:end],
                status="pending",
            )
        )

    logger.info("Extracted %d text SMILES candidates from %s", len(results), doc_id)
    return results


async def extract_molecules_from_text_async(
    text: str,
    doc_id: str,
) -> list[ExtractionResult]:
    """Run native text extraction outside the event loop."""
    return await asyncio.to_thread(extract_molecules_from_text, text, doc_id)
