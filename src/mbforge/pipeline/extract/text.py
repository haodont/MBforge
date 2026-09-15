"""Full OCR extraction.

All page text, layout spans (text / table / formula / title / image), and
coordinate frames come from the cloud OCR chain (PaddleOCR). Native PyMuPDF
text extraction is no longer a pipeline source — page content is uniform so
the evidence model downstream (``source_evidence``) has a single coordinate
and ``block_type`` convention.

OCR config is read from AppConfig.ocr (see backend ocr.chain.build_backends).
"""

from __future__ import annotations

import re
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import pymupdf

from mbforge.pipeline.cancellation import CancelCheck
from mbforge.utils.logger import get_logger

logger = get_logger("mbforge.pipeline.extract.text")

#: Keep cloud OCR requests serialized by default to respect provider limits.
#: Override per ingest via ``ocr_config["ocr_max_concurrency"]`` when needed.
_OCR_MAX_CONCURRENCY = 1
#: Provider-level retries live in the PaddleOCR backend; avoid retry stacking.
_OCR_MAX_ATTEMPTS = 1
_OCR_RENDER_ZOOM = 2.0  # 144 DPI — matches _OCR_RENDER_PX_PER_PT in PaddleOCR.


@dataclass
class TextSpan:
    """One text, table, or image block from a PDF page with its bounding box."""

    text: str
    bbox: tuple[float, float, float, float]  # x0, y0, x1, y1 in PDF pts
    block_type: int = 0  # 0=text, 1=image, 2=table


@dataclass
class PageContent:
    page_num: int  # 1-based
    text: str
    ocr_dpi: int = 0
    text_spans: list[TextSpan] = field(default_factory=list)
    figure_bboxes: list[tuple[float, float, float, float]] = field(default_factory=list)
    """Figure/image region bboxes from OCR layout (x0, y0, x1, y1 in bottom-left coords)."""
    ocr_backend: str | None = None
    ocr_attempts: int = 0
    ocr_elapsed_ms: int = 0
    ocr_error: str | None = None
    ocr_images: list[str] = field(default_factory=list)  # filenames from OCR backend


@dataclass
class ExtractedDocument:
    raw_text: str
    page_count: int
    parser: str = "ocr"
    title: str | None = None
    pages: list[PageContent] = field(default_factory=list)
    ocr_stats: dict[str, Any] = field(default_factory=dict)


def extract_pdf_text(
    pdf_path: str,
    *,
    ocr_config: dict | None = None,
    save_images_dir: str | Path | None = None,
    cancel_check: CancelCheck | None = None,
) -> ExtractedDocument:
    """Extract text from a PDF via the cloud OCR chain.

    Every page is rendered at 144 DPI and sent through the configured OCR
    chain (PaddleOCR). ``save_images_dir`` is passed to the chain so images
    extracted by the backend are persisted alongside the document artifacts.
    ``cancel_check`` is a cooperative cancellation checkpoint polled per page
    and before each OCR retry; it raises ``TaskCancelledError`` to abort.

    Any page that exits the retry loop with empty text aborts the whole
    document so a partial evidence set is never silently ingested (the
    OCR-only contract does not degrade a page into "nothing read").
    """
    doc = pymupdf.open(pdf_path)
    try:
        page_count = doc.page_count
        # All pages start blank; text + spans come exclusively from OCR.
        pages = [PageContent(page_num=i + 1, text="") for i in range(page_count)]
        ocr_metrics: dict[int, Any] = {}
        ocr_texts = _ocr_pages(
            doc,
            list(range(page_count)),
            ocr_config,
            save_images_dir=save_images_dir,
            cancel_check=cancel_check,
            metrics=ocr_metrics,
        )
        for idx, ocr_text in enumerate(ocr_texts):
            pages[idx].text = ocr_text
        _apply_ocr_results(pages, list(range(page_count)), ocr_metrics)
        return _assemble_extracted(pages, page_count, ocr_metrics)
    finally:
        doc.close()


def extract_document_text(
    doc,
    pdf_path: str,
    *,
    ocr_config: dict | None = None,
    save_images_dir: str | Path | None = None,
    cancel_check: CancelCheck | None = None,
) -> ExtractedDocument:
    """Extract text for a pipeline run (OCR-only).

    Under the OCR-only contract the Document's import-time native cache is
    never used as an evidence source. ``doc`` is accepted for API stability
    but ignored: extraction always delegates to the full OCR pass over
    :data:`pdf_path`. (The native cache may still exist purely for preview.)
    """
    return extract_pdf_text(
        pdf_path,
        ocr_config=ocr_config,
        save_images_dir=save_images_dir,
        cancel_check=cancel_check,
    )


def build_from_document(doc) -> ExtractedDocument | None:
    """Removed: native extraction is no longer a pipeline source.

    Retained as a loud stand-in so stale callers fail on the documented
    rationale instead of silently getting non-OCR text.
    """
    raise NotImplementedError(
        "`build_from_document` native extraction was removed (OCR-only contract); "
        "use extract_pdf_text / extract_document_text for full OCR extraction."
    )


def _apply_ocr_results(
    pages: list[PageContent],
    page_indices: list[int],
    ocr_metrics: dict[int, Any],
) -> None:
    """Write OCR text, metrics, and spans back into *pages* in-place."""
    for idx in page_indices:
        metric = ocr_metrics.get(idx)
        if metric is not None:
            pages[idx].ocr_backend = metric.backend
            pages[idx].ocr_attempts = metric.chain_attempts
            pages[idx].ocr_elapsed_ms = metric.elapsed_ms
            pages[idx].ocr_error = metric.error
            # Record image filenames so Markdown stage can fix relative paths.
            images = getattr(metric, "images", None)
            if images:
                pages[idx].ocr_images = list(images.keys())
            spans = getattr(metric, "spans", None)
            if spans:
                # Separate figure bboxes from text spans
                figure_bboxes = []
                text_spans = []
                for s in spans:
                    if s.block_type == 1:  # image/figure
                        figure_bboxes.append(s.bbox)
                    else:
                        text_spans.append(
                            TextSpan(text=s.text, bbox=s.bbox, block_type=s.block_type)
                        )
                pages[idx].text_spans = text_spans
                pages[idx].figure_bboxes = figure_bboxes


def _build_ocr_stats(
    pages: list[PageContent],
    pages_requested: list[int],
    ocr_metrics: dict[int, Any],
) -> dict[str, Any]:
    """Aggregate per-page OCR outcomes into the stats dict."""
    backend_counts: dict[str, int] = {}
    for metric in ocr_metrics.values():
        if metric.backend:
            backend_counts[metric.backend] = backend_counts.get(metric.backend, 0) + 1
    return {
        "pages_requested": len(pages_requested),
        "pages_succeeded": sum(1 for idx in pages_requested if pages[idx].text.strip()),
        "pages_failed": sum(
            1 for idx in pages_requested if not pages[idx].text.strip()
        ),
        "backend_counts": backend_counts,
        "retry_count": sum(
            max(0, metric.chain_attempts - 1) for metric in ocr_metrics.values()
        ),
        "elapsed_ms": sum(metric.elapsed_ms for metric in ocr_metrics.values()),
    }


def _assemble_extracted(
    pages: list[PageContent],
    page_count: int,
    ocr_metrics: dict[int, Any],
) -> ExtractedDocument:
    """Build the final :class:`ExtractedDocument` from per-page OCR results."""
    all_pages = list(range(page_count))
    full_text = "\n\n".join(p.text for p in pages if p.text.strip())
    ocr_stats = _build_ocr_stats(pages, all_pages, ocr_metrics)
    title = _extract_title(pages[0].text if pages else "")
    return ExtractedDocument(
        raw_text=full_text,
        page_count=page_count,
        parser="ocr",
        pages=pages,
        title=title,
        ocr_stats=ocr_stats,
    )


def _ocr_pages(
    doc,
    page_indices: list[int],
    ocr_config: dict | None = None,
    save_images_dir: str | Path | None = None,
    cancel_check: CancelCheck | None = None,
    metrics: dict[int, Any] | None = None,
) -> list[str]:
    """OCR pages through the fallback chain with bounded concurrency.

    Results align positionally with ``page_indices``. ``cancel_check`` is
    polled per page and before each retry; a ``TaskCancelledError`` is never
    swallowed. A page that exits the retry loop with empty text aborts the
    whole OCR run (the OCR-only contract never ingests a page it could not
    read), so downstream evidence always covers every page.
    """
    check = cancel_check or (lambda: None)
    check()
    from mbforge.backends.ocr import build_backends, extract_text_with_chain
    from mbforge.backends.ocr.chain import OCRUnavailableError

    backends = build_backends(ocr_config)
    if not backends:
        # Preserve cooperative cancellation semantics even when no provider
        # can be initialized for the document.
        check()
        raise OCRUnavailableError("no configured cloud OCR backend available")

    try:
        max_workers = max(
            1,
            int((ocr_config or {}).get("ocr_max_concurrency", _OCR_MAX_CONCURRENCY)),
        )
    except (TypeError, ValueError):
        max_workers = _OCR_MAX_CONCURRENCY

    metrics_lock = threading.Lock()
    results: list[str] = [""] * len(page_indices)

    def _ocr_one(pos: int, page_idx: int) -> tuple[int, str, bool]:
        check()
        page = doc.load_page(page_idx)
        mat = pymupdf.Matrix(_OCR_RENDER_ZOOM, _OCR_RENDER_ZOOM)
        pix = page.get_pixmap(matrix=mat, alpha=False)
        image_bytes = pix.tobytes("png")
        text = ""
        succeeded = False
        for attempt in range(_OCR_MAX_ATTEMPTS):
            check()
            try:
                result = extract_text_with_chain(
                    image_bytes,
                    ocr_config,
                    save_images_dir=save_images_dir,
                    backends=backends,
                )
                text = result.text or ""
                succeeded = bool(text.strip())
                if metrics is not None:
                    with metrics_lock:
                        metrics[page_idx] = result
                if succeeded:
                    break
            except Exception as ocr_exc:  # noqa: BLE001
                text = ""
                succeeded = False
                logger.warning(
                    "OCR attempt %d/%d failed for page %d: %s",
                    attempt + 1,
                    _OCR_MAX_ATTEMPTS,
                    page_idx + 1,
                    ocr_exc,
                )
            if attempt < _OCR_MAX_ATTEMPTS - 1:
                time.sleep(1 * (3**attempt))  # 1s, 3s, 9s
        if not succeeded:
            logger.warning(
                "OCR gave up on page %d after %d attempts",
                page_idx + 1,
                _OCR_MAX_ATTEMPTS,
            )
        return pos, text, succeeded

    tasks = list(enumerate(page_indices))
    if max_workers == 1 or len(tasks) <= 1:
        for pos, page_idx in tasks:
            r_pos, text, _ = _ocr_one(pos, page_idx)
            results[r_pos] = text
    else:
        with ThreadPoolExecutor(
            max_workers=max_workers, thread_name_prefix="ocr"
        ) as executor:
            futures = [
                executor.submit(_ocr_one, pos, page_idx) for pos, page_idx in tasks
            ]
            for future in futures:
                check()
                pos, text, _ = future.result()
                results[pos] = text

    for pos, page_idx in enumerate(page_indices):
        if not results[pos].strip():
            raise OCRUnavailableError(
                f"page {page_idx + 1} yielded no OCR text after "
                f"{_OCR_MAX_ATTEMPTS} attempts; refusing a partial document"
            )
    return results


def _extract_title(text: str) -> str | None:
    """Extract a title from the first page text.

    Strategy:
    1. If a line starts with ``Title:`` / ``标题：`` / ``题目：``, take the rest.
    2. WIPO bibliographic pages carry the real title on the ``(54)`` line
       (``(54) Title: ...`` / ``(54) 发明名称: ...``) — prefer it over any
       heuristic candidate, and prefer the CJK variant when both an English
       and a native-language ``(54)`` line exist.
    3. Otherwise pick the first substantive non-empty line, skipping:
       - PCT/WIPO bibliographic headers (``(NN) ...``)
       - Classification codes (``(51) ...``)
       - Image references and date-like lines (publication date, etc.)
       - Long ALL-CAPS lines
    4. Cap at 200 chars.
    """
    if not text:
        return None

    # 1. explicit prefix wins
    for line in text.split("\n")[:30]:
        for prefix in ["Title:", "标题：", "题目："]:
            if line.strip().startswith(prefix):
                rest = line.strip()[len(prefix) :].strip()
                if rest and 3 < len(rest) < 200:
                    return rest

    # 2. WIPO (54) title line — the authoritative title on bibliographic
    # pages, which the generic ``(NN)`` skip below would otherwise discard.
    # Scan deep: the (54) block sits after applicants/inventors (~line 50).
    _wipo_title = re.compile(r"^\(54\)\s*(?:Title|发明名称|题目)?\s*[:：]?\s*(.+)$")
    _cjk = re.compile(r"[一-鿿]")
    wipo_titles = [
        m.group(1).strip()
        for line in text.split("\n")[:100]
        if (m := _wipo_title.match(line.strip())) and 3 < len(m.group(1).strip()) < 200
    ]
    if wipo_titles:
        return next((t for t in wipo_titles if _cjk.search(t)), wipo_titles[0])

    # 3. heuristic: skip bibliographic lines
    _biblio = re.compile(r"^\(\d{1,3}\)\s+")
    _all_caps = re.compile(r"^[A-Z][A-Z\s&\-,/]{4,}$")
    # Skip known patent header phrases
    _header_phrases = {
        "INTERNATIONAL APPLICATION PUBLISHED UNDER THE PATENT COOPERATION TREATY (PCT)",
        "INTERNATIONAL APPLICATION PUBLISHED UNDER THE PATENT COOPERATION TREATY",
    }
    # Publication/application dates must never become the document title
    # (they are the first non-bibliographic line after ``(43)``/``(22)``).
    _date_like = re.compile(
        r"^(?:\d{4}\s*年\s*\d{1,2}\s*月|\d{1,2}[./-]\d{1,2}[./-]\d{2,4}|"
        r"\d{4}[./-]\d{1,2}[./-]\d{1,2}|[A-Z][a-z]+\s+\d{1,2},\s*\d{4})"
    )
    candidate_with_caps = None  # remember the first ALL-CAPS line as fallback
    _image_link = re.compile(r"^!\[.*\]\(.*\)\s*$")
    for line in text.split("\n")[:30]:
        s = line.strip()
        if not s:
            continue
        if not (3 < len(s) < 200):
            continue
        if s.isdigit():
            continue
        if _image_link.match(s):
            # OCR markdown may open with a logo/figure image reference.
            continue
        if _date_like.match(s):
            continue
        if _biblio.match(s):
            continue
        if s in _header_phrases:
            continue
        if _all_caps.match(s):
            # Patent titles are often ALL-CAPS — remember as fallback but keep
            # scanning for a more specific line.
            if candidate_with_caps is None:
                candidate_with_caps = s
            continue
        # Looks like a real title — return it
        return s
    return candidate_with_caps
