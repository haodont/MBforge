"""Read/update persistence for Markush review candidates.

Storage side of the review flow split out of the former
``core.chem.markush_review`` module before the P2 naming migration.
Exposes the queue-read operations
the HTTP router needs:

- ``list_candidates`` / ``get_candidate_detail`` for the review UI.
- ``update_candidate`` for editing a candidate's SMILES / label / role
  before a decision is taken (with optimistic-lock checks).

Decision application (``apply_decision``) and the role-transition
writes live in :mod:`mbforge.services.markush.review`; the shared state
machine in :mod:`mbforge.core.review`.

All writes target the caller-owned connection so the persist stage's
existing transaction is reused; no implicit commits.
"""

from __future__ import annotations

import sqlite3
from collections.abc import Iterable
from typing import Any

from ..core.review import (
    ReviewConflictError,
    ReviewNotFoundError,
    ReviewTransitionError,
)
from ..models.markush import (
    MarkushCandidate,
    MarkushCandidateDetail,
    MarkushDecisionItem,
    MarkushEvidenceItem,
)
from ..utils.files import safe_json_loads
from .review_audit import record_review_decision


def _row_to_candidate(row: sqlite3.Row) -> MarkushCandidate:
    """Convert one DB row into a Pydantic candidate."""
    properties = safe_json_loads(row["properties"], {})
    reasons = safe_json_loads(row["reasons"], [])
    return MarkushCandidate(
        candidate_id=row["candidate_id"],
        source_key=row["source_key"],
        doc_id=row["doc_id"],
        predicted_role=row["predicted_role"],
        smiles=row["smiles"],
        esmiles=row["esmiles"],
        name=row["name"],
        raw_label=row["raw_label"],
        normalized_label=row["normalized_label"],
        label_kind=row["label_kind"],
        page=row["page"],
        bbox_x0=row["bbox_x0"],
        bbox_y0=row["bbox_y0"],
        bbox_x1=row["bbox_x1"],
        bbox_y1=row["bbox_y1"],
        crop_relpath=row["crop_relpath"],
        moldet_confidence=row["moldet_confidence"],
        scribe_confidence=row["scribe_confidence"],
        composite_confidence=row["composite_confidence"],
        reasons=reasons,
        context_text=row["context_text"],
        properties=properties,
        recognition_status=row["recognition_status"],
        review_status=row["review_status"],
        review_version=row["review_version"],
        superseded_at=row["superseded_at"],
        created_at=row["created_at"],
        updated_at=row["updated_at"],
    )


def _row_to_evidence(row: sqlite3.Row) -> MarkushEvidenceItem:
    return MarkushEvidenceItem(
        evidence_id=row["evidence_id"],
        entity_type=row["entity_type"],
        entity_id=row["entity_id"],
        doc_id=row["doc_id"],
        page=row["page"],
        bbox_x0=row["bbox_x0"],
        bbox_y0=row["bbox_y0"],
        bbox_x1=row["bbox_x1"],
        bbox_y1=row["bbox_y1"],
        crop_relpath=row["crop_relpath"],
        context_text=row["context_text"],
        moldet_confidence=row["moldet_confidence"],
        scribe_confidence=row["scribe_confidence"],
        composite_confidence=row["composite_confidence"],
    )


def _row_to_decision(row: sqlite3.Row) -> MarkushDecisionItem:
    return MarkushDecisionItem(
        decision_id=row["decision_id"],
        action=row["action"],
        previous_state=row["previous_state"],
        new_state=row["new_state"],
        reason=row["reason"] or "",
        created_at=row["created_at"],
    )


def _fetch_one(
    conn: sqlite3.Connection, sql: str, params: Iterable[Any]
) -> sqlite3.Row | None:
    return conn.execute(sql, tuple(params)).fetchone()


def list_candidates(
    conn: sqlite3.Connection,
    *,
    doc_id: str | None = None,
    review_status: str | None = None,
    predicted_role: str | None = None,
    reason: str | None = None,
    page: int = 1,
    page_size: int = 50,
) -> tuple[list[MarkushCandidate], int]:
    """Return one page of candidates and the unpaged total count.

    The ``reason`` filter does a JSON-array substring match against the
    ``reasons`` column. It is intentionally loose because the
    classifier appends reason codes incrementally and we want the UI to
    be able to filter by any of them without changing the schema.
    """
    clauses: list[str] = ["superseded_at IS NULL"]
    params: list[Any] = []
    if doc_id is not None:
        clauses.append("doc_id = ?")
        params.append(doc_id)
    if review_status is not None:
        clauses.append("review_status = ?")
        params.append(review_status)
    if predicted_role is not None:
        clauses.append("predicted_role = ?")
        params.append(predicted_role)
    if reason is not None:
        clauses.append("reasons LIKE ?")
        params.append(f"%{reason}%")
    where = " AND ".join(clauses)
    total = conn.execute(
        f"SELECT COUNT(*) FROM markush_review_candidates WHERE {where}",
        params,
    ).fetchone()[0]
    offset = (page - 1) * page_size
    rows = conn.execute(
        f"SELECT * FROM markush_review_candidates WHERE {where} "
        f"ORDER BY created_at DESC, candidate_id LIMIT ? OFFSET ?",
        params + [page_size, offset],
    ).fetchall()
    return [_row_to_candidate(row) for row in rows], int(total)


def _candidate_destination(
    conn: sqlite3.Connection,
    candidate_id: str,
    properties: dict[str, Any],
) -> tuple[str | None, str | None]:
    """Resolve destination IDs from canonical rows, with legacy scaffold fallback."""
    scaffold = conn.execute(
        """
        SELECT scaffold_id
        FROM markush_scaffolds
        WHERE json_extract(properties, '$.review_candidate_id') = ?
        ORDER BY created_at DESC, scaffold_id DESC
        LIMIT 1
        """,
        (candidate_id,),
    ).fetchone()
    fragment = conn.execute(
        """
        SELECT fragment_id
        FROM markush_fragments
        WHERE json_extract(properties, '$.review_candidate_id') = ?
        ORDER BY created_at DESC, fragment_id DESC
        LIMIT 1
        """,
        (candidate_id,),
    ).fetchone()
    scaffold_id = scaffold["scaffold_id"] if scaffold else None
    if scaffold_id is None:
        legacy_id = properties.get("scaffold_id")
        scaffold_id = legacy_id if isinstance(legacy_id, str) and legacy_id else None
    return scaffold_id, fragment["fragment_id"] if fragment else None


def _enumeration_eligibility(
    conn: sqlite3.Connection,
    scaffold_id: str | None,
) -> tuple[bool, list[str]]:
    """Return whether a confirmed scaffold has an enumerable confirmed relation."""
    if scaffold_id is None:
        return False, ["candidate is not a confirmed scaffold"]
    scaffold = conn.execute(
        "SELECT status FROM markush_scaffolds WHERE scaffold_id = ?",
        (scaffold_id,),
    ).fetchone()
    if scaffold is None or scaffold["status"] != "confirmed":
        return False, ["candidate is not a confirmed scaffold"]
    site = conn.execute(
        """
        SELECT 1 FROM markush_sites
        WHERE scaffold_id = ? AND status = 'confirmed'
        LIMIT 1
        """,
        (scaffold_id,),
    ).fetchone()
    if site is None:
        return False, ["no confirmed attachment site"]
    relation = conn.execute(
        """
        SELECT 1
        FROM markush_sites AS site
        JOIN markush_fragments AS fragment ON fragment.status = 'confirmed'
        LEFT JOIN markush_options AS option
          ON option.site_id = site.site_id
         AND option.fragment_id = fragment.fragment_id
         AND option.status = 'confirmed'
        LEFT JOIN markush_mounts AS mount
          ON mount.site_id = site.site_id
         AND mount.fragment_id = fragment.fragment_id
         AND mount.status = 'confirmed'
        WHERE site.scaffold_id = ?
          AND site.status = 'confirmed'
          AND (option.option_id IS NOT NULL OR mount.mount_id IS NOT NULL)
        LIMIT 1
        """,
        (scaffold_id,),
    ).fetchone()
    if relation is None:
        return False, ["no confirmed fragment relationship"]
    return True, []


def get_candidate_detail(
    conn: sqlite3.Connection, candidate_id: str
) -> MarkushCandidateDetail:
    """Return the candidate, evidence chain, and decision log."""
    row = _fetch_one(
        conn,
        "SELECT * FROM markush_review_candidates WHERE candidate_id = ?",
        (candidate_id,),
    )
    if row is None:
        raise ReviewNotFoundError(candidate_id)
    evidence = conn.execute(
        "SELECT * FROM markush_evidence WHERE entity_id = ? AND entity_type = 'review_candidate' "
        "ORDER BY evidence_id",
        (candidate_id,),
    ).fetchall()
    decisions = conn.execute(
        "SELECT * FROM markush_decisions WHERE entity_id = ? "
        "AND entity_type = 'review_candidate' ORDER BY created_at",
        (candidate_id,),
    ).fetchall()
    candidate = _row_to_candidate(row)
    scaffold_id, fragment_id = _candidate_destination(
        conn,
        candidate_id,
        candidate.properties,
    )
    enumeration_eligible, enumeration_block_reasons = _enumeration_eligibility(
        conn,
        scaffold_id,
    )
    return MarkushCandidateDetail(
        **candidate.model_dump(),
        scaffold_id=scaffold_id,
        fragment_id=fragment_id,
        enumeration_eligible=enumeration_eligible,
        enumeration_block_reasons=enumeration_block_reasons,
        evidence=[_row_to_evidence(r) for r in evidence],
        decisions=[_row_to_decision(r) for r in decisions],
    )


def update_candidate(
    conn: sqlite3.Connection,
    *,
    candidate_id: str,
    expected_version: int,
    smiles: str | None = None,
    esmiles: str | None = None,
    normalized_label: str | None = None,
    raw_label: str | None = None,
    predicted_role: str | None = None,
    note: str = "",
) -> MarkushCandidate:
    """Edit the editable fields of a pending candidate.

    Returns the updated candidate. Raises :class:`ReviewConflictError`
    when ``expected_version`` does not match the stored row.
    """
    current = _fetch_one(
        conn,
        "SELECT review_version, review_status FROM markush_review_candidates "
        "WHERE candidate_id = ?",
        (candidate_id,),
    )
    if current is None:
        raise ReviewNotFoundError(candidate_id)
    if current["review_version"] != expected_version:
        raise ReviewConflictError(
            f"expected_version={expected_version} but stored={current['review_version']}"
        )
    if current["review_status"] != "pending":
        raise ReviewTransitionError(
            f"cannot edit candidate in state {current['review_status']}"
        )

    fields: list[str] = []
    params: list[Any] = []
    if smiles is not None:
        fields.append("smiles = ?")
        params.append(smiles)
    if esmiles is not None:
        fields.append("esmiles = ?")
        params.append(esmiles)
    if normalized_label is not None:
        fields.append("normalized_label = ?")
        params.append(normalized_label)
    if raw_label is not None:
        fields.append("raw_label = ?")
        params.append(raw_label)
    if predicted_role is not None:
        fields.append("predicted_role = ?")
        params.append(predicted_role)
    if not fields:
        return get_candidate_detail(conn, candidate_id)
    fields.append("review_version = review_version + 1")
    fields.append("updated_at = datetime('now')")
    params.append(candidate_id)
    conn.execute(
        f"UPDATE markush_review_candidates SET {', '.join(fields)} "
        "WHERE candidate_id = ?",
        params,
    )
    # Audit entry; ``note`` is stored in the existing ``reason`` column
    # so the audit log keeps its single-string shape.
    record_review_decision(
        conn,
        entity_type="review_candidate",
        entity_id=candidate_id,
        action="update",
        previous_state=current["review_status"],
        new_state="pending",
        reason=note,
    )
    return get_candidate_detail(conn, candidate_id)


def _copy_evidence(
    conn: sqlite3.Connection,
    row: sqlite3.Row,
    entity_type: str,
    entity_id: str,
    doc_id: str,
) -> None:
    """Copy every ``review_candidate`` evidence row to *entity_type*/*entity_id*.

    Called as part of the role-transition transaction so the destination
    table inherits the same audit chain that the candidate carried.
    """
    rows = conn.execute(
        "SELECT * FROM markush_evidence WHERE entity_id = ? AND entity_type = 'review_candidate'",
        (row["candidate_id"],),
    ).fetchall()
    for ev in rows:
        conn.execute(
            """
            INSERT INTO markush_evidence
                (entity_type, entity_id, doc_id, page,
                 bbox_x0, bbox_y0, bbox_x1, bbox_y1,
                 crop_relpath, context_text,
                 moldet_confidence, scribe_confidence, composite_confidence)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                entity_type,
                entity_id,
                doc_id,
                ev["page"],
                ev["bbox_x0"],
                ev["bbox_y0"],
                ev["bbox_x1"],
                ev["bbox_y1"],
                ev["crop_relpath"],
                ev["context_text"],
                ev["moldet_confidence"],
                ev["scribe_confidence"],
                ev["composite_confidence"],
            ),
        )


__all__ = [
    "get_candidate_detail",
    "list_candidates",
    "update_candidate",
]
