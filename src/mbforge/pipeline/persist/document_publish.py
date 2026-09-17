"""Document publication and compensation for the persist stage.

Owns the filesystem half of the persist stage:

- ``persist_document`` writes page texts and ``report.json`` under
  ``storage/{doc_id}/`` with rollback on failure (written files are
  removed before the error propagates).
- ``compensate_molecule_persistence`` deletes the document-scoped
  molecule rows a failed persist already committed, so the DB does not
  reference a document that was not fully persisted.

The stage keeps the single-transaction molecule/activity writes; this
module is called by :mod:`mbforge.pipeline.stages.persist_stage` around
them.
"""

from __future__ import annotations

import shutil
from typing import Any

from mbforge.pipeline.run.context import PipelineContext
from mbforge.storage.layout import LibraryLayout
from mbforge.storage.sqlite.database import DatabaseManager
from mbforge.utils.files import ensure_dir, save_json
from mbforge.utils.logger import get_logger

logger = get_logger("mbforge.pipeline.persist.document_publish")

# Structured reason code logged when compensation itself fails
# (see the repair plan, section 11).
PERSIST_COMPENSATION_FAILED = "PERSIST_COMPENSATION_FAILED"


def persist_document(ctx: PipelineContext) -> None:
    """Save page texts and report to filesystem with rollback on failure."""
    resolver = LibraryLayout(ctx.library_root)
    written_files: list[Any] = []

    review_candidates = [
        candidate
        for candidate in ctx.candidates
        if candidate.status != "rejected"
        and candidate.properties.get("structure_role") == "review_required"
    ]
    review_payload = []
    for candidate in review_candidates:
        detections = [
            {
                "page": detection.page,
                "bbox": detection.bbox,
                "image_path": detection.image_path,
                "confidence": detection.confidence,
            }
            for detection in candidate.detections
        ]
        review_payload.append(
            {
                "canonical_smiles": candidate.canonical_smiles,
                "esmiles": candidate.esmiles,
                "name": candidate.name,
                "reasons": candidate.properties.get("structure_role_reasons", []),
                "detections": detections,
            }
        )

    try:
        source_pdf = resolver.source_pdf(ctx.doc_id)
        if not source_pdf.exists() and ctx.pdf_path.is_file():
            ensure_dir(source_pdf.parent)
            shutil.copy2(ctx.pdf_path, source_pdf)
            written_files.append(source_pdf)

        # Write page results as JSON (text + metadata)
        pages_dir = resolver.pages_dir(ctx.doc_id)
        ensure_dir(pages_dir)
        for page in ctx.extracted.pages:
            page_file = resolver.page_text(ctx.doc_id, page.page_num)
            save_json(
                page_file,
                {
                    "page_num": page.page_num,
                    "text": page.text,
                    "figure_bboxes": [
                        list(bbox) for bbox in getattr(page, "figure_bboxes", [])
                    ],
                    "ocr_backend": getattr(page, "ocr_backend", None),
                    "ocr_elapsed_ms": getattr(page, "ocr_elapsed_ms", 0),
                    "ocr_error": getattr(page, "ocr_error", None),
                },
            )
            written_files.append(page_file)

        # Write report.json
        report_dir = resolver.storage_dir(ctx.doc_id)
        ensure_dir(report_dir)
        report = {
            "doc_id": ctx.doc_id,
            "page_count": ctx.extracted.page_count,
            "parser": ctx.extracted.parser,
            "title": ctx.extracted.title,
            "molecule_count": ctx.molecule_stats.get("molecule_count", 0),
            "molecule_pending_review_count": ctx.molecule_stats.get(
                "pending_review_count", 0
            ),
            "molecule_rejected_count": ctx.molecule_stats.get("rejected_count", 0),
            "molecule_sources": ctx.molecule_stats.get("sources", []),
            "activity_count": ctx.activity_count_written,
            "source_evidence_count": ctx.source_evidence_count,
            "structure_role_counts": getattr(ctx, "structure_role_counts", {}),
            "molecule_review_candidates": review_payload,
            "activity_stats": dict(getattr(ctx, "activity_stats", {})),
        }
        report_path = resolver.report_json(ctx.doc_id)
        save_json(report_path, report)
        written_files.append(report_path)

        logger.info("Document persisted for %s", ctx.doc_id)

    except Exception:
        # Roll back any files we already wrote
        for path in written_files:
            try:
                path.unlink(missing_ok=True)
            except Exception as cleanup_exc:
                logger.warning(
                    "Failed to remove partial artifact %s during rollback: %s",
                    path,
                    cleanup_exc,
                )
        raise


def compensate_molecule_persistence(ctx: PipelineContext) -> None:
    """Remove doc-specific molecule rows written during a failed persist.

    All DELETEs run inside a single ``db.transaction()``: either every
    document-scoped row is removed or the whole compensation is rolled
    back. A failure propagates to the caller so the stage result can
    report ``compensation_failed`` instead of silently logging.

    The shared ``molecules`` table is intentionally left untouched because
    the same canonical SMILES may be referenced by other documents.
    """
    from mbforge.pipeline.persist.molecules import delete_document_molecule_rows

    db = DatabaseManager.get(str(ctx.library_root))
    with db.transaction() as (_kb_conn, mol_conn):
        deleted = delete_document_molecule_rows(mol_conn, ctx.doc_id)
    logger.info(
        "Compensated molecule persistence for %s: deleted_rows=%s",
        ctx.doc_id,
        deleted,
    )
