"""Restore stage state from raw branch artifacts and SQL evidence."""

from __future__ import annotations

from collections.abc import Sequence
from pathlib import Path
from typing import TYPE_CHECKING, Any

from mbforge.application.pipeline.artifacts.branch_io import (
    _DETECTION_FILE,
    _EXTRACT_FILE,
    _extracted_from_artifact,
    branch_path,
    detection_results,
    load_detection_branch,
    load_extract_branch,
)
from mbforge.application.pipeline.artifacts.evidence_join import (
    _candidates_from_evidence,
    _extract_frames,
    load_document_evidence,
    summarize_molecules,
)
from mbforge.application.pipeline.artifacts.json_io import read_json_object
from mbforge.application.pipeline.extract.text import (
    ExtractedDocument,
    PageContent,
    TextSpan,
)
from mbforge.domain.evidence import SourceEvidence
from mbforge.domain.evidence_kind import (
    IMAGE,
    TABLE,
    category_of,
    is_text,
    register_kind_vocab,
)
from mbforge.domain.molecule import Molecule
from mbforge.foundation.layout import LibraryLayout
from mbforge.foundation.logger import get_logger

if TYPE_CHECKING:
    from mbforge.application.pipeline.run.context import PipelineContext

logger = get_logger("mbforge.application.pipeline.artifacts.hydration")


def _extracted_from_evidence(
    raw_artifact: Any, evidence: Sequence[SourceEvidence] | None = None
) -> ExtractedDocument:
    """Rebuild ExtractedDocument metadata from raw branch + SQL facts."""
    if evidence is None:
        evidence = list(getattr(raw_artifact, "evidence", []))
    raw_document = _extracted_from_artifact(raw_artifact)
    raw_pages = {page.page_num: page for page in raw_document.pages}
    frame_pages = _extract_frames(raw_artifact)
    pages: list[PageContent] = []
    for frame in frame_pages:
        page_items = [item for item in evidence if item.page == frame.page]
        text_items = [item for item in page_items if is_text(item.kind)]
        image_items = [item for item in page_items if category_of(item.kind) == IMAGE]
        raw_page = raw_pages.get(frame.page)
        pages.append(
            PageContent(
                page_num=frame.page,
                text="\n".join(item.raw_text for item in text_items),
                text_spans=[
                    TextSpan(
                        text=item.raw_text,
                        bbox=item.bbox,
                        block_type=2 if category_of(item.kind) == TABLE else 0,
                    )
                    for item in text_items
                ],
                figure_bboxes=[item.bbox for item in image_items],
                ocr_dpi=raw_page.ocr_dpi if raw_page else 0,
                ocr_backend=raw_page.ocr_backend if raw_page else None,
                ocr_attempts=raw_page.ocr_attempts if raw_page else 0,
                ocr_elapsed_ms=raw_page.ocr_elapsed_ms if raw_page else 0,
                ocr_error=raw_page.ocr_error if raw_page else None,
            )
        )
    meta = getattr(raw_artifact, "meta", {})
    parser = str(meta.get("parser", "pymupdf"))
    title = meta.get("title")
    return ExtractedDocument(
        raw_text="\n\n".join(page.text for page in pages if page.text),
        page_count=len(pages),
        parser=parser,
        title=title,
        pages=pages,
        ocr_stats=dict(meta.get("ocr_stats", {})),
    )


def load_extracted(
    library_root: str | Path, doc_id: str, run_id: str | None = None
) -> ExtractedDocument | None:
    """Restore text metadata from the raw branch and bbox/text from SQL."""
    register_branch_kind_vocab(library_root, doc_id)
    effective_run_id = run_id or _latest_branch_run_id(
        library_root, doc_id, _EXTRACT_FILE
    )
    if effective_run_id is not None:
        branch = load_extract_branch(library_root, doc_id, effective_run_id)
        if branch is not None:
            evidence = load_document_evidence(library_root, doc_id)
            return _extracted_from_evidence(branch, evidence)
    return None


def _latest_branch_run_id(
    library_root: str | Path, doc_id: str, filename: str
) -> str | None:
    """Read the run ID embedded in the fixed branch file."""
    path = branch_path(library_root, doc_id, filename)
    data = read_json_object(path)
    if data is None:
        return None
    run_id = data.get("run_id")
    return run_id if isinstance(run_id, str) and run_id else None


def load_branch_meta(
    library_root: str | Path, doc_id: str, filename: str
) -> dict[str, Any]:
    """Read only the ``meta`` block of a branch artifact."""
    data = read_json_object(branch_path(library_root, doc_id, filename))
    if data is None:
        return {}
    meta = data.get("meta")
    return dict(meta) if isinstance(meta, dict) else {}


#: Documents whose declared kind vocabulary has already been registered.  A
#: producer's vocabulary only changes when the document is re-ingested, so
#: caching per (library_root, doc_id) is safe for a process lifetime.
_KIND_VOCAB_REGISTERED: set[tuple[str, str]] = set()


def register_branch_kind_vocab(library_root: str | Path, doc_id: str) -> None:
    """Register the ``kind`` vocabularies this document's evidence was minted with.

    A producer names its regions freely and SQL stores only that label, so a
    reader that maps labels to categories needs the declarations.  **Both**
    branches contribute rows — the Extract/layout producer mints text and figure
    regions (``bib`` / ``figcx`` / …) and declares them in its own ``meta``, and
    Detection mints molecules — so both are read.  Registering only one leaves
    the other producer's labels unmapped, which fails closed as ``UnknownKind``.
    One read per branch, cached per process.
    """
    key = (str(library_root), doc_id)
    if key in _KIND_VOCAB_REGISTERED:
        return
    for filename in (_EXTRACT_FILE, _DETECTION_FILE):
        register_kind_vocab(load_branch_meta(library_root, doc_id, filename))
    _KIND_VOCAB_REGISTERED.add(key)


def load_detections(
    library_root: str | Path, doc_id: str, run_id: str | None = None
) -> tuple[list[Molecule], dict[str, Any]] | None:
    """Restore normalized candidates from raw results plus SQL evidence."""
    effective_run_id = run_id or _latest_branch_run_id(
        library_root, doc_id, _DETECTION_FILE
    )
    if effective_run_id is not None:
        branch = load_detection_branch(library_root, doc_id, effective_run_id)
        if branch is not None:
            evidence = load_document_evidence(library_root, doc_id)
            results = detection_results(branch)
            candidates = _candidates_from_evidence(results, evidence)
            return candidates, summarize_molecules(
                candidates, dict(branch.meta.get("molecule_stats", {}))
            )
    return None


# --- context hydration -------------------------------------------------------


def hydrate_context_from_artifacts(ctx: PipelineContext) -> None:
    """Fill missing PipelineContext fields from stage artifacts (idempotent).

    ``rough_md_path`` is intentionally not hydrated: it is a staging temp
    file that stages regenerate when absent.
    """
    layout = LibraryLayout(ctx.library_root)
    if ctx.run_id:
        # Each worker claim mints its own run ID, so a later stage must
        # resolve the extract/detection branches through the checkpoint's
        # per-stage records instead of assuming they share ctx.run_id.
        from mbforge.application.pipeline.run.checkpoint import latest_stage_run_id

        evidence = load_document_evidence(ctx.library_root, ctx.doc_id)
        ctx.document_evidence = evidence
        extract_run_id = latest_stage_run_id(ctx.staging_dir, "extract") or ctx.run_id
        extract_branch = load_extract_branch(
            ctx.library_root, ctx.doc_id, extract_run_id
        )
        if ctx.extracted is None and extract_branch is not None:
            ctx.extracted = _extracted_from_evidence(extract_branch, evidence)
        if not ctx.candidates:
            detection_run_id = (
                latest_stage_run_id(ctx.staging_dir, "detection") or ctx.run_id
            )
            detection_branch = load_detection_branch(
                ctx.library_root, ctx.doc_id, detection_run_id
            )
            if detection_branch is not None:
                candidates = _candidates_from_evidence(
                    detection_results(detection_branch), evidence
                )
                ctx.candidates = candidates
                ctx.molecule_stats = summarize_molecules(
                    candidates, dict(detection_branch.meta.get("molecule_stats", {}))
                )

    if ctx.document_md_path is None:
        candidate = layout.document_md(ctx.doc_id)
        if candidate.exists():
            ctx.document_md_path = candidate
    logger.debug(
        "Context hydration for %s: extracted=%s candidates=%d md=%s",
        ctx.doc_id,
        ctx.extracted is not None,
        len(ctx.candidates),
        ctx.document_md_path,
    )


__all__ = ["hydrate_context_from_artifacts", "load_detections", "load_extracted"]
