"""Restore stage state from the SQL source-evidence index.

Extract publishes nothing but SQL rows, crops and page artifacts, so every later
stage rebuilds its context from ``source_evidence`` — there is no run-scoped
branch file to read.
"""

from __future__ import annotations

from collections.abc import Sequence
from pathlib import Path
from typing import TYPE_CHECKING, Any

from mbforge.application.pipeline.artifacts.evidence_join import (
    _candidates_from_evidence,
    load_document_evidence,
    observation_from_payload,
    page_frames_from_pdf,
    summarize_molecules,
)
from mbforge.application.pipeline.artifacts.evidence_models import PageFrame
from mbforge.application.pipeline.extract.text import (
    ExtractedDocument,
    PageContent,
    TextSpan,
)
from mbforge.application.pipeline.layout.labels import kind_vocab
from mbforge.domain.evidence import SourceEvidence
from mbforge.domain.evidence_kind import (
    IMAGE,
    MOLECULE,
    TABLE,
    category_of,
    is_text,
    register_kinds,
)
from mbforge.domain.molecule import Molecule
from mbforge.domain.types import ExtractionResult
from mbforge.foundation.layout import LibraryLayout
from mbforge.foundation.logger import get_logger

if TYPE_CHECKING:
    from mbforge.application.pipeline.run.context import PipelineContext

logger = get_logger("mbforge.application.pipeline.artifacts.hydration")

_KINDS_REGISTERED = False


def register_evidence_kinds() -> None:
    """Install the producer label vocabulary from code (idempotent).

    The closed label → category mapping is a static table in
    :mod:`mbforge.application.pipeline.layout.labels`; there is no producer
    artifact to declare it, so a reader process installs it here.
    """
    global _KINDS_REGISTERED
    if _KINDS_REGISTERED:
        return
    register_kinds(kind_vocab())
    _KINDS_REGISTERED = True


def _frames(
    library_root: str | Path,
    doc_id: str,
    pdf_path: str | Path | None = None,
) -> list[PageFrame]:
    """Page frames from the source PDF, or ``[]`` when it is unavailable."""
    path = (
        Path(pdf_path)
        if pdf_path is not None
        else LibraryLayout(library_root).source_pdf(doc_id)
    )
    if not path.is_file():
        return []
    return page_frames_from_pdf(path)


def _extracted_from_evidence(
    evidence: Sequence[SourceEvidence],
    frames: Sequence[PageFrame],
    meta: dict[str, Any] | None = None,
) -> ExtractedDocument:
    """Rebuild an ``ExtractedDocument`` from SQL facts plus page geometry."""
    meta = meta or {}
    page_numbers = [frame.page for frame in frames] or sorted(
        {item.page for item in evidence}
    )
    pages: list[PageContent] = []
    for page_number in page_numbers:
        page_items = [item for item in evidence if item.page == page_number]
        text_items = [item for item in page_items if is_text(item.kind)]
        image_items = [item for item in page_items if category_of(item.kind) == IMAGE]
        pages.append(
            PageContent(
                page_num=page_number,
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
                ocr_dpi=int(meta.get("ocr_dpi", 0)),
                ocr_backend=meta.get("ocr_backend"),
            )
        )
    return ExtractedDocument(
        raw_text="\n\n".join(page.text for page in pages if page.text),
        page_count=len(pages),
        parser=str(meta.get("parser", "layout")),
        title=meta.get("title"),
        pages=pages,
        ocr_stats=dict(meta.get("ocr_stats", {})),
    )


def _extract_meta(staging_dir: Path | None) -> dict[str, Any]:
    """Read the extract stage's own summary context (parser, title, OCR)."""
    if staging_dir is None:
        return {}
    from mbforge.application.pipeline.run.checkpoint import load_stage_summary

    summary = load_stage_summary(staging_dir, "extract") or {}
    context = summary.get("context")
    return dict(context) if isinstance(context, dict) else {}


def _molecule_results(evidence: Sequence[SourceEvidence]) -> list[ExtractionResult]:
    """Decode every molecule row's payload into a located observation."""
    return [
        observation_from_payload(item.raw_text, page=item.page, bbox=item.bbox)
        for item in evidence
        if category_of(item.kind) == MOLECULE
    ]


def load_extracted(
    library_root: str | Path, doc_id: str, run_id: str | None = None
) -> ExtractedDocument | None:
    """Rebuild the Extract document view from SQL evidence plus page geometry."""
    register_evidence_kinds()
    evidence = load_document_evidence(library_root, doc_id)
    if not evidence:
        return None
    return _extracted_from_evidence(evidence, _frames(library_root, doc_id))


def load_detections(
    library_root: str | Path, doc_id: str, run_id: str | None = None
) -> tuple[list[Molecule], dict[str, Any]] | None:
    """Restore normalized candidates from the molecule rows' own payloads."""
    register_evidence_kinds()
    evidence = load_document_evidence(library_root, doc_id)
    results = _molecule_results(evidence)
    if not results:
        return None
    candidates = _candidates_from_evidence(results, evidence)
    return candidates, summarize_molecules(candidates)


# --- context hydration -------------------------------------------------------


def hydrate_context_from_evidence(ctx: PipelineContext) -> None:
    """Fill missing PipelineContext fields from SQL evidence (idempotent).

    ``rough_md_path`` is intentionally not hydrated: it is a staging temp file
    that stages regenerate when absent.
    """
    layout = LibraryLayout(ctx.library_root)
    if ctx.run_id:
        register_evidence_kinds()
        evidence = load_document_evidence(ctx.library_root, ctx.doc_id)
        ctx.document_evidence = evidence
        if ctx.extracted is None and evidence:
            ctx.extracted = _extracted_from_evidence(
                evidence,
                _frames(ctx.library_root, ctx.doc_id, ctx.pdf_path),
                _extract_meta(ctx.staging_dir),
            )
        if not ctx.candidates and evidence:
            candidates = _candidates_from_evidence(
                _molecule_results(evidence), evidence
            )
            ctx.candidates = candidates
            ctx.molecule_stats = summarize_molecules(
                candidates, dict(ctx.molecule_stats or {})
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


__all__ = [
    "hydrate_context_from_evidence",
    "load_detections",
    "load_extracted",
    "register_evidence_kinds",
]
