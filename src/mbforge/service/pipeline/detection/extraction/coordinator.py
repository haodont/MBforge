"""The molecule pass: render, detect, then recognize every molecule per page.

Three stages run concurrently over a bounded pair of queues:

    PageRenderer  --page queue-->  PageDetector  --crop queue-->  CropProcessor
    (own PDF handle)               (MolDet)                      (MolParser + archive)

Each arrow is a bounded queue, so a slow stage throttles the ones behind it
instead of buffering the whole document. The stages exchange the records in
:mod:``records`` rather than positional tuples.

Both GPU detectors are process-wide singletons; the recognizer serializes its
own inference, so the three-thread schedule here is about overlapping CPU work
(preprocessing, archiving, OCR) with GPU work, not about parallel inference.
"""

from __future__ import annotations

import asyncio
import contextlib
import queue
import threading
from collections.abc import Callable
from pathlib import Path

from mbforge.domain.types import ExtractionResult
from mbforge.foundation.logger import get_logger
from mbforge.service.pipeline.cancellation import CancelCheck
from mbforge.service.pipeline.detection.extraction.config import (
    load_extraction_config,
)
from mbforge.service.pipeline.detection.extraction.crop_processor import (
    CropProcessor,
    fill_ocr_slot,
    ocr_label_image,
)
from mbforge.service.pipeline.detection.extraction.nearby_text import nearby_block_text
from mbforge.service.pipeline.detection.extraction.page_detector import PageDetector
from mbforge.service.pipeline.detection.extraction.page_renderer import PageRenderer
from mbforge.service.pipeline.detection.extraction.pdf_probe import (
    open_pdf_errors,
    read_page_count,
)
from mbforge.service.pipeline.detection.extraction.records import (
    DetectedPage,
    RenderedPage,
)

logger = get_logger("mbforge.service.pipeline.detection.extraction.coordinator")

#: Bound on each stage-to-stage queue. Small on purpose: the queues exist to
#: overlap the stages, not to buffer a document, and a shallow queue is what
#: keeps peak memory close to one page plus one batch.
_STAGE_QUEUE_SIZE = 2
#: How long a producer waits for a full queue before re-checking cancellation.
_QUEUE_PUT_TIMEOUT = 0.1


def _put_bounded(
    target: queue.Queue,
    item: object,
    check: CancelCheck,
    consumer_alive: Callable[[], bool] | None = None,
) -> bool:
    """Put *item* on a bounded queue, observing cancellation and liveness.

    Returns False when the queue's consumer has already died, which tells the
    producer to stop rather than wait on a queue nobody will drain.
    """
    while True:
        check()
        try:
            target.put(item, timeout=_QUEUE_PUT_TIMEOUT)
            return True
        except queue.Full:
            if consumer_alive is not None and not consumer_alive():
                return False


def _run_page_pipeline(
    *,
    page_q: queue.Queue,
    crop_q: queue.Queue,
    renderer: PageRenderer,
    page_detector: PageDetector,
    processor: CropProcessor,
    check: CancelCheck,
) -> None:
    """Run renderer -> detector -> crop worker until the pages run out."""
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
            page = page_q.get()
            if page is None:
                break
            check()
            bboxes = page_detector.detect(page)
            if not bboxes:
                continue
            if not _put_bounded(
                crop_q,
                DetectedPage(page=page, bboxes=bboxes),
                check,
                consumer_alive=worker.is_alive,
            ):
                break
    finally:
        # Sentinel first, then join: the crop worker must see the sentinel even
        # when this loop exits early, or its queue would keep it alive forever.
        while True:
            try:
                crop_q.put(None, timeout=_QUEUE_PUT_TIMEOUT)
                break
            except queue.Full:
                if not worker.is_alive():
                    break
        worker.join()

        # Drain page_q so a renderer blocked on a full queue can notice the
        # sentinel and exit.
        while renderer_thread.is_alive():
            with contextlib.suppress(queue.Empty):
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
    """Render a PDF and recognize every molecule MolDet finds on its pages.

    Crops are archived under ``staging_dir`` when given (the staged run promotes
    them later) and under the library crop directory otherwise.

    Returns the molecule observations in page, then reading order. An
    unavailable MolDet degrades to no molecules: this pass enriches a document
    the layout producer already owns, so it must not fail the run.
    """
    from mbforge.foundation.layout import LibraryLayout
    from mbforge.service.ports import get_runtime

    check = cancel_check or (lambda: None)
    config = load_extraction_config()
    runtime = get_runtime()

    detector = runtime.moldet.get_moldet()
    if not detector.is_available():
        logger.warning("MolDetv2 unavailable, skipping image molecule extraction")
        return []

    logger.info("Loading MolParser model for document %s", doc_id)
    runtime.molparser.load()
    logger.info("MolParser availability: %s", runtime.molparser.health())

    crop_dir = LibraryLayout(library_root).crops_dir(doc_id)
    write_dir = Path(staging_dir) / "crops" if staging_dir else crop_dir
    write_dir.mkdir(parents=True, exist_ok=True)

    open_errors = open_pdf_errors()
    page_count = read_page_count(pdf_path, open_errors)
    if page_count is None:
        return []

    page_q: queue.Queue[RenderedPage | None] = queue.Queue(maxsize=_STAGE_QUEUE_SIZE)
    crop_q: queue.Queue[DetectedPage | None] = queue.Queue(maxsize=_STAGE_QUEUE_SIZE)

    def put_bounded(target: queue.Queue, item: object) -> bool:
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
        molparser_batch_size=config.molparser_batch_size,
        check=check,
        nearby_block_text=nearby_block_text,
        molparser=runtime.molparser,
        ocr_reader=ocr_label_image,
        ocr_slot_filler=fill_ocr_slot,
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
        page_detector=page_detector,
        processor=processor,
        check=check,
    )

    if renderer.error:
        raise renderer.error
    if processor.error:
        raise processor.error

    # Label OCR runs on its own pool and feeds the results in as it completes, so
    # it is joined last: only now is every crop's label set final.
    for handle in processor.ocr_futures:
        with contextlib.suppress(Exception):
            handle.result()
    processor.batcher.enrich_ocr_labels()

    logger.info(
        "Extracted %d molecule image candidates from %s "
        "(%d pure-text pages skipped, dpi=%s, molparser_batch=%d)",
        len(processor.results),
        doc_id,
        renderer.skipped_pure_text,
        config.render_dpi,
        config.molparser_batch_size,
    )
    return processor.results


async def extract_molecules_from_pdf_async(
    pdf_path: str,
    library_root: str,
    doc_id: str,
    max_pages: int | None = None,
    cancel_check: CancelCheck | None = None,
    staging_dir: str | Path | None = None,
    ocr_spans_by_page: dict[int, list[dict]] | None = None,
) -> list[ExtractionResult]:
    """Run the synchronous PDF extractor outside the event loop."""
    return await asyncio.to_thread(
        extract_molecules_from_pdf,
        pdf_path,
        library_root,
        doc_id,
        max_pages,
        cancel_check,
        staging_dir,
        ocr_spans_by_page,
    )
