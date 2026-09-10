"""Persist normalized molecule candidates to the database.

For each candidate (a single canonical SMILES, possibly with multiple
detections), the persist step:

1. Upserts a `molecules` row keyed by `canonical_smiles` so the same
   molecule observed in different documents collapses to a single record.
2. Inserts one `molecule_detections` row per primary detection (legacy table
   still maintained for back-compat readers).
3. Inserts one first-class `evidence` row (kind='figure') per primary
   detection. The evidence table is the new aggregate store and is the
   primary surface the molecule router reads.

Page semantics: `molecule_detections.page` stays a 0-based `PageIndex`;
`evidence.page` and all activity matching use a 1-based `PageNumber`.
See :mod:`mbforge.pipeline.extract.pages` for the contract.
"""

from __future__ import annotations

import sqlite3
from contextlib import nullcontext
from typing import Any

from ...storage.sqlite.database import DatabaseManager
from ...utils.logger import get_logger
from ..activity.matching import (
    ACTIVITY_PAGE_FALLBACK,
    ActivityMatch,
    match_activities,
)
from ..activity.normalization import canonical_value_for_legacy
from ..detection.normalization import NormalizedMolecule

logger = get_logger(__name__)

# Document-scoped tables cleaned by the persistence compensation path, in
# deletion order. The shared ``molecules`` table is intentionally absent:
# the same canonical SMILES may be referenced by other documents.
DOC_SCOPED_MOLECULE_TABLES: tuple[str, ...] = (
    "molecule_detections",
    "evidence",
    "text_molecule_links",
    "markush_fragments",
    "markush_review_candidates",
    "markush_evidence",
    "markush_scaffolds",
    "activities",
)


def delete_document_molecule_rows(
    conn: sqlite3.Connection, doc_id: str
) -> dict[str, int]:
    """Delete all document-scoped molecule rows on an existing connection.

    Used by ``PersistStage`` to compensate a failed document persist. The
    caller owns the transaction: wrap the call in ``db.transaction()`` so a
    failure in any DELETE rolls back all of them instead of leaving a
    half-compensated document.

    Args:
        conn: Open molecules DB connection.
        doc_id: Document whose rows are removed.

    Returns:
        Per-table deleted row counts (contains no molecule data).
    """
    deleted: dict[str, int] = {}
    for table in DOC_SCOPED_MOLECULE_TABLES:
        cursor = conn.execute(f"DELETE FROM {table} WHERE doc_id = ?", (doc_id,))
        deleted[table] = cursor.rowcount
    return deleted


# Caps for the merged evidence context text (PIPE-05, repair plan section
# 5.1). The total cap preserves the historical 500-char storage budget of
# ``evidence.context_text``; the per-item cap keeps one huge excerpt from
# starving the others. Truncation is stable: items are capped before
# joining, then the joined text is capped in total.
_CONTEXT_ITEM_CAP = 300
_CONTEXT_TOTAL_CAP = 500
DOCUMENT_CONTEXT_MARKER = "[context:document]"


def _clean_contexts(texts: Any, *, exclude: set[str] | None = None) -> list[str]:
    """Trim, cap and stably dedupe context strings, preserving order."""
    if not isinstance(texts, list):
        return []
    cleaned: list[str] = []
    seen: set[str] = set(exclude) if exclude else set()
    for text in texts:
        if not isinstance(text, str):
            continue
        item = text.strip()[:_CONTEXT_ITEM_CAP]
        if not item or item in seen:
            continue
        seen.add(item)
        cleaned.append(item)
    return cleaned


def _candidate_context_text(candidate: NormalizedMolecule) -> str:
    properties = getattr(candidate, "properties", {})
    if not isinstance(properties, dict):
        return ""
    raw = _clean_contexts(properties.get("context_texts"))
    document_context = _clean_contexts(
        properties.get("role_contexts"), exclude=set(raw)
    )
    sections: list[str] = []
    if raw:
        sections.append("\n".join(raw))
    if document_context:
        sections.append(DOCUMENT_CONTEXT_MARKER + "\n" + "\n".join(document_context))
    return "\n".join(sections)[:_CONTEXT_TOTAL_CAP]


def persist_molecule_candidates(
    library_root: str,
    doc_id: str,
    candidates: list[NormalizedMolecule],
    conn: sqlite3.Connection | None = None,
    activity_records: list[Any] | None = None,
    activity_guard: Any | None = None,
    activity_vetoes: list[Any] | None = None,
) -> None:
    """Upsert canonical molecule rows + insert detection / evidence rows.

    Args:
        library_root: Project root directory.
        doc_id: Source document ID.
        candidates: Normalized molecule candidates produced by
            :mod:`mbforge.pipeline.detection.normalization`.
        conn: Optional open molecules DB connection. When provided, writes are
            performed on this connection and the caller is responsible for
            commit/rollback (used by the pipeline transaction wrapper).
        activity_guard: Optional per-candidate veto callable forwarded to
            :func:`match_activities` (see ``candidate_guard`` there).
        activity_vetoes: Optional list populated with vetoes reported by
            the matcher, for review-queue reporting by the caller.
    """
    db = DatabaseManager.get(library_root)
    db.initialize()

    conn_manager = nullcontext(conn) if conn is not None else db.mol_conn()
    persisted = 0
    with conn_manager as active_conn:
        if active_conn is None:
            raise RuntimeError("No database connection available")
        # Apply the skip rules up front so the shared matcher never
        # consumes activity rows on behalf of candidates that cannot be
        # persisted (rejected, non-complete, no detections, no page, no
        # canonical SMILES).
        persistable = filter_persistable_candidates(doc_id, candidates)
        # PIPE-08: activity matching is shared with ``persist_activities``
        # via :func:`match_activities` — one pure matcher, one owner of
        # used_rows/used_pages, identical results on both write paths.
        matches_by_key: dict[str, ActivityMatch] = {}
        if activity_records:
            for match in match_activities(
                persistable,
                activity_records,
                candidate_guard=activity_guard,
                vetoes=activity_vetoes,
            ):
                matches_by_key.setdefault(match.candidate_key, match)
        for c in persistable:
            primary = c.detections[0]
            bbox = primary.bbox
            conf_moldet = primary.conf_moldet
            # Page contract boundary: ``primary.page`` is a 0-based
            # ``PageIndex``; activity records, evidence rows and the UI use
            # 1-based ``PageNumber``. Convert once here.
            primary_page_number = primary.page + 1

            # 1. Upsert molecules row keyed by canonical_smiles (canonical
            #    aggregate). The mol_id IS the canonical_smiles. Non-empty
            #    is guaranteed by the pre-filter.
            canonical_smiles = c.canonical_smiles
            context_text = _candidate_context_text(c)
            evidence_kind = "figure" if primary.image_path else "text"
            evidence_source = getattr(primary, "source", "image")
            if evidence_source not in {"image", "text", "manual"}:
                evidence_source = "image"
            # Remove any stale FTS entries before touching the row so that
            # FTS5 external-content DELETE can still see the old values.
            DatabaseManager.delete_molecule_from_mol_search(
                active_conn, canonical_smiles
            )
            active_conn.execute(
                """
                INSERT INTO molecules
                    (mol_id, smiles, esmiles, name, source_doc, source_type,
                     status, canonical_smiles)
                VALUES (?, ?, ?, ?, ?, ?, 'pending', ?)
                ON CONFLICT(mol_id) DO UPDATE SET
                    canonical_smiles = COALESCE(molecules.canonical_smiles, excluded.canonical_smiles),
                    source_doc = COALESCE(NULLIF(molecules.source_doc, ''), excluded.source_doc),
                    name = CASE
                        WHEN TRIM(COALESCE(molecules.name, '')) = '' THEN excluded.name
                        ELSE molecules.name
                    END
                """,
                (
                    canonical_smiles,
                    canonical_smiles,
                    c.esmiles,
                    c.name or "",
                    doc_id,
                    evidence_source,
                    canonical_smiles,
                ),
            )
            DatabaseManager.sync_molecule_to_mol_search(active_conn, canonical_smiles)
            DatabaseManager.sync_molecule_fingerprint(active_conn, canonical_smiles)
            # 2. Insert molecule_detections row (mol_id now non-null).
            #    molecule_detections.page stays a 0-based PageIndex used by
            #    the detection-cache API (see pipeline.pages).
            active_conn.execute(
                """
                INSERT INTO molecule_detections (
                    mol_id, doc_id, page, bbox_x0, bbox_y0, bbox_x1, bbox_y1,
                    crop_relpath, conf_moldet,
                    vlm_verified_esmiles
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    canonical_smiles,
                    doc_id,
                    primary.page,
                    bbox[0] if bbox else None,
                    bbox[1] if bbox else None,
                    bbox[2] if bbox else None,
                    bbox[3] if bbox else None,
                    primary.image_path,
                    conf_moldet,
                    c.esmiles,
                ),
            )
            # 3. Insert first-class evidence row. The evidence confidence is
            #    the MolDet detection score.
            #    evidence.page is a 1-based PageNumber (see pipeline.pages).
            active_conn.execute(
                """
                INSERT INTO evidence
                    (canonical_smiles, mol_id, doc_id, page,
                     bbox_x0, bbox_y0, bbox_x1, bbox_y1,
                     crop_relpath, context_text, role, kind, confidence, source_type)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'detected', ?, ?, ?)
                """,
                (
                    canonical_smiles,
                    canonical_smiles,
                    doc_id,
                    primary_page_number,
                    bbox[0] if bbox else None,
                    bbox[1] if bbox else None,
                    bbox[2] if bbox else None,
                    bbox[3] if bbox else None,
                    primary.image_path,
                    context_text,
                    evidence_kind,
                    primary.confidence,
                    evidence_source,
                ),
            )

            # 4. Activity write from the shared matcher results — row-level
            #    match (kind='table_row') first, otherwise the explicitly
            #    low-confidence same-page fallback (kind='table').
            match = matches_by_key.get(canonical_smiles)
            if match is not None and match.kind == "table_row":
                # Row-alignment match — write kind='table_row' evidence with
                # table_idx / row_idx / col_idx for front-end table-cell lookup.
                active_rec = activity_records[match.record_key]
                active_conn.execute(
                    """
                    UPDATE molecules
                    SET activity = ?,
                        activity_type = ?,
                        units = ?
                    WHERE mol_id = ?
                    """,
                    (
                        canonical_value_for_legacy(active_rec),
                        active_rec.activity_type,
                        getattr(active_rec, "unit_canonical", None) or active_rec.unit,
                        canonical_smiles,
                    ),
                )
                active_conn.execute(
                    """
                    INSERT INTO evidence
                        (canonical_smiles, mol_id, doc_id, page,
                         context_text, role, kind, confidence, source_type,
                         row_label, table_idx, row_idx, col_idx)
                    VALUES (?, ?, ?, ?, ?, 'activity_data', 'table_row', ?, 'llm_extraction',
                            ?, ?, ?, ?)
                    """,
                    (
                        canonical_smiles,
                        canonical_smiles,
                        doc_id,
                        getattr(active_rec, "page_num", None),
                        (getattr(active_rec, "raw_text", "") or "")[:500],
                        active_rec.confidence,
                        getattr(active_rec, "row_label", None),
                        getattr(active_rec, "table_idx", None),
                        getattr(active_rec, "row_idx", None),
                        getattr(active_rec, "col_idx", None),
                    ),
                )
            elif match is not None:
                # Low-confidence same-page fallback: write kind='table'.
                # The matcher's ``page_number`` is the 1-based PageNumber
                # converted from the 0-based detection PageIndex.
                rec = activity_records[match.record_key]
                logger.info(
                    "Activity match: reason=%s doc=%s page=%d kind=table",
                    ACTIVITY_PAGE_FALLBACK,
                    doc_id,
                    primary_page_number,
                )
                active_conn.execute(
                    """
                    UPDATE molecules
                    SET activity = ?,
                        activity_type = ?,
                        units = ?
                    WHERE mol_id = ?
                    """,
                    (
                        canonical_value_for_legacy(rec),
                        rec.activity_type,
                        getattr(rec, "unit_canonical", None) or rec.unit,
                        canonical_smiles,
                    ),
                )
                active_conn.execute(
                    """
                    INSERT INTO evidence
                        (canonical_smiles, mol_id, doc_id, page,
                         context_text, role, kind, confidence, source_type)
                    VALUES (?, ?, ?, ?, ?, 'activity_data', 'table', ?, 'llm_extraction')
                    """,
                    (
                        canonical_smiles,
                        canonical_smiles,
                        doc_id,
                        rec.page_num,
                        (rec.raw_text or "")[:500],
                        rec.confidence,
                    ),
                )
            persisted += 1

    logger.info(
        "Persisted %d molecule candidates for %s",
        persisted,
        doc_id,
    )


def filter_persistable_candidates(
    doc_id: str,
    candidates: list[NormalizedMolecule],
    *,
    warn: bool = True,
) -> list[NormalizedMolecule]:
    """Apply the persist loop's skip rules, preserving candidate order.

    Filtering before matching keeps the shared activity matcher from
    consuming rows on behalf of candidates that can never be persisted:
    rejected, non-``complete`` structure role, no detections, no detection
    page, or no canonical SMILES.

    Also used by read paths (by-location overlay queries) to reproduce the
    persisted subset from the normalized Detection branch; pass ``warn=False``
    there — skipped candidates are the normal case for a read, not a
    persistence anomaly worth logging.
    """
    persistable: list[NormalizedMolecule] = []
    for c in candidates:
        if c.status == "rejected":
            continue
        properties = getattr(c, "properties", {})
        role = (
            properties.get("structure_role") if isinstance(properties, dict) else None
        )
        if role is None:
            # This function is also used directly by a few integrations;
            # do not let an unclassified candidate bypass the Markush
            # boundary merely because PersistStage was skipped.
            from ..detection.structure_role import classify_structure_role

            role = classify_structure_role(c)
        if role != "complete":
            continue
        if not c.detections:
            if warn:
                logger.warning(
                    "Skipping candidate with no detections for %s (%s)",
                    doc_id,
                    c.esmiles,
                )
            continue
        if c.detections[0].page is None:
            # ``molecule_detections.page`` is NOT NULL and a detection
            # without a page must never be defaulted to the first page,
            # so skip the candidate instead of aborting the whole
            # document persist with an IntegrityError.
            if warn:
                logger.warning(
                    "Skipping candidate with no detection page for %s (%s)",
                    doc_id,
                    c.esmiles,
                )
            continue
        if not c.canonical_smiles:
            if warn:
                logger.warning(
                    "Skipping candidate with no canonical_smiles for %s",
                    doc_id,
                )
            continue
        persistable.append(c)
    return persistable
