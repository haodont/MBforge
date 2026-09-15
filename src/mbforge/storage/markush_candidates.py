"""Persistence path for Markush review candidates.

Writes ``markush_review_candidates`` rows, appends one
``markush_evidence`` row per detection, and writes a
``markush_decisions`` audit entry.

The re-import protection rule: same ``source_key`` + same
``content_hash`` is a no-op (preserving human state); same
``source_key`` + different ``content_hash`` supersedes the prior row
and inserts a new ``pending`` row; new ``source_key`` inserts a new
``pending`` row. Identity derivation lives in
:mod:`mbforge.core.provenance`.

The pipeline runs this service inside the same transaction it uses for
the other Markush writes so a single document persist either fully
succeeds or fully rolls back.
"""

from __future__ import annotations

import json
import sqlite3
from collections.abc import Iterable
from typing import TYPE_CHECKING, Any

from ..core.molecule import MarkushFragment, MarkushScaffold
from ..core.provenance import (
    _RECOGNITION_VERSION,
    _candidate_properties,
    _join_context_text,
    compute_content_hash,
    compute_source_key,
)
from ..utils.ids import short_id
from ..utils.logger import get_logger

if TYPE_CHECKING:
    from ..core.molecule import Molecule

logger = get_logger("mbforge.storage.markush_candidates")


def _existing_row(conn: sqlite3.Connection, source_key: str) -> sqlite3.Row | None:
    return conn.execute(
        "SELECT candidate_id, content_hash, review_status, review_version "
        "FROM markush_review_candidates WHERE source_key = ?",
        (source_key,),
    ).fetchone()


def _supersede_row(conn: sqlite3.Connection, candidate_id: str) -> None:
    conn.execute(
        "UPDATE markush_review_candidates "
        "SET review_status = 'superseded', superseded_at = datetime('now'), "
        "    updated_at = datetime('now') "
        "WHERE candidate_id = ?",
        (candidate_id,),
    )


def _insert_candidate(
    conn: sqlite3.Connection,
    *,
    candidate_id: str,
    source_key: str,
    doc_id: str,
    predicted_role: str,
    molecule: Molecule,
    label: str,
    content_hash: str,
) -> None:
    properties = _candidate_properties(molecule)
    detection = molecule.detections[0] if molecule.detections else None
    bbox = detection.bbox if detection else None
    page = detection.page if detection else None
    crop_relpath = detection.image_path if detection else None
    conn.execute(
        """
        INSERT INTO markush_review_candidates (
            candidate_id, source_key, doc_id, predicted_role,
            smiles, esmiles, name,
            raw_label, normalized_label, label_kind,
            page, bbox_x0, bbox_y0, bbox_x1, bbox_y1,
            crop_relpath,
            moldet_confidence, scribe_confidence, composite_confidence,
            reasons, context_text, properties, content_hash
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            candidate_id,
            source_key,
            doc_id,
            predicted_role,
            molecule.canonical_smiles,
            molecule.esmiles or "",
            molecule.name or "",
            molecule.properties.get("raw_coref_label", ""),
            label,
            molecule.properties.get("label_kind", "unknown"),
            page,
            bbox[0] if bbox else None,
            bbox[1] if bbox else None,
            bbox[2] if bbox else None,
            bbox[3] if bbox else None,
            crop_relpath,
            detection.conf_moldet if detection else None,
            None,
            detection.confidence if detection else None,
            json.dumps(
                molecule.properties.get("structure_role_reasons", []),
                ensure_ascii=False,
            ),
            _join_context_text(molecule),
            json.dumps(properties, ensure_ascii=False),
            content_hash,
        ),
    )


def _append_evidence(
    conn: sqlite3.Connection,
    *,
    candidate_id: str,
    doc_id: str,
    molecule: Molecule,
) -> None:
    """Append one ``markush_evidence`` row per detection."""
    context_text = _join_context_text(molecule)
    values = [
        (
            "review_candidate",
            candidate_id,
            doc_id,
            detection.page,
            detection.bbox[0] if detection.bbox else None,
            detection.bbox[1] if detection.bbox else None,
            detection.bbox[2] if detection.bbox else None,
            detection.bbox[3] if detection.bbox else None,
            detection.image_path,
            context_text,
            detection.conf_moldet,
            None,
            detection.confidence,
        )
        for detection in molecule.detections
    ]
    if values:
        conn.executemany(
            """
            INSERT INTO markush_evidence (
                entity_type, entity_id, doc_id, page,
                bbox_x0, bbox_y0, bbox_x1, bbox_y1,
                crop_relpath, context_text,
                moldet_confidence, scribe_confidence, composite_confidence
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            values,
        )


def _record_decision(
    conn: sqlite3.Connection,
    *,
    candidate_id: str,
    action: str,
    new_state: str,
    snapshot: dict[str, Any],
) -> None:
    conn.execute(
        """
        INSERT INTO markush_decisions (
            decision_id, entity_type, entity_id, action, new_state, snapshot
        ) VALUES (?, ?, ?, ?, ?, ?)
        """,
        (
            short_id(),
            "review_candidate",
            candidate_id,
            action,
            new_state,
            json.dumps(snapshot, ensure_ascii=False),
        ),
    )


def persist_review_candidates(
    doc_id: str,
    candidates: Iterable[Molecule],
    conn: sqlite3.Connection,
    recognition_version: int = _RECOGNITION_VERSION,
) -> int:
    """Persist ``review_required`` molecules into the review queue.

    Returns the number of *new* rows inserted (zero when re-imports hit
    existing source_keys with the same content hash, in which case the
    existing human state is preserved).

    The caller owns the transaction so this routine is safe to invoke
    from inside the persist stage's existing connection.
    """
    inserted = 0
    for molecule in candidates:
        if molecule.status == "rejected":
            continue
        if molecule.properties.get("structure_role") != "review_required":
            continue
        detection = molecule.detections[0] if molecule.detections else None
        if detection is None:
            logger.warning(
                "Skipping review candidate without a detection: doc=%s smiles=%s",
                doc_id,
                molecule.esmiles,
            )
            continue
        normalized_label = molecule.properties.get("normalized_label") or ""
        raw_label = molecule.properties.get("raw_coref_label") or normalized_label
        # ``source_key`` carries the normalized label so R₁ and R1 land
        # on the same row; ``raw_label`` is preserved separately for the
        # audit log.
        source_key = compute_source_key(
            doc_id=doc_id,
            page=detection.page,
            bbox=detection.bbox,
            normalized_label=str(normalized_label),
        )
        content_hash = compute_content_hash(
            canonical_smiles=molecule.canonical_smiles or "",
            esmiles=molecule.esmiles or "",
            context=_join_context_text(molecule),
            recognition_version=recognition_version,
        )

        existing = _existing_row(conn, source_key)
        if existing is not None:
            if existing["content_hash"] == content_hash:
                # Same source, same content — preserve human state.
                # Only update the doc_id if it was carried forward
                # without one (defensive; the column is NOT NULL so a
                # blank here would be impossible, but the assertion is
                # cheap insurance against future migration bugs).
                continue
            # Same source, different content — supersede old, insert new.
            _supersede_row(conn, existing["candidate_id"])

        candidate_id = short_id()
        _insert_candidate(
            conn,
            candidate_id=candidate_id,
            source_key=source_key,
            doc_id=doc_id,
            predicted_role="review_required",
            molecule=molecule,
            label=str(normalized_label),
            content_hash=content_hash,
        )
        _append_evidence(
            conn,
            candidate_id=candidate_id,
            doc_id=doc_id,
            molecule=molecule,
        )
        _record_decision(
            conn,
            candidate_id=candidate_id,
            action="candidate_created",
            new_state="pending",
            snapshot={
                "doc_id": doc_id,
                "smiles": molecule.canonical_smiles,
                "normalized_label": normalized_label,
                "raw_label": raw_label,
                "source_key": source_key,
                "content_hash": content_hash,
            },
        )
        inserted += 1
    return inserted


# ---------------------------------------------------------------------------
# Entity read helpers — return typed value objects instead of raw rows
# ---------------------------------------------------------------------------


def get_scaffolds_by_doc(
    conn: sqlite3.Connection,
    doc_id: str,
) -> list[MarkushScaffold]:
    """Return all scaffolds for a document as :class:`MarkushScaffold` entities."""
    rows = conn.execute(
        "SELECT * FROM markush_scaffolds WHERE doc_id = ? ORDER BY created_at",
        (doc_id,),
    ).fetchall()
    return [MarkushScaffold.from_row(dict(r)) for r in rows]


def get_fragments_by_doc(
    conn: sqlite3.Connection,
    doc_id: str,
    *,
    scaffold_id: str | None = None,
) -> list[MarkushFragment]:
    """Return fragments for a document, optionally filtered by scaffold.

    Returns :class:`MarkushFragment` entities.
    """
    if scaffold_id is not None:
        rows = conn.execute(
            "SELECT * FROM markush_fragments "
            "WHERE doc_id = ? AND scaffold_id = ? ORDER BY created_at",
            (doc_id, scaffold_id),
        ).fetchall()
    else:
        rows = conn.execute(
            "SELECT * FROM markush_fragments WHERE doc_id = ? ORDER BY created_at",
            (doc_id,),
        ).fetchall()
    return [MarkushFragment.from_row(dict(r)) for r in rows]


__all__ = [
    "get_fragments_by_doc",
    "get_scaffolds_by_doc",
    "persist_review_candidates",
]
