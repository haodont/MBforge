"""Committed Patent-analysis state: the authoritative snapshot per document.

``patent_facts.json`` is a rebuildable projection of this row and
``source_evidence`` remains the only raw-evidence source. One commit writes the
snapshot, the accumulated human decisions and the permitted derived rows in a
single transaction, so the published facts and the derived molecules cannot
disagree; the caller then refreshes the file projection.
"""

from __future__ import annotations

import json
from collections.abc import Sequence
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from mbforge.db.measurement_store import (
    delete_document_measurements,
    insert_attributions_in_transaction,
    insert_measurements_in_transaction,
)
from mbforge.db.molecule_store import persist_candidates_in_transaction
from mbforge.db.sqlite.database import DatabaseManager
from mbforge.foundation.errors import ConflictError

_TABLE = "patent_analysis_state"


def load_state(library_root: str | Path, doc_id: str) -> dict[str, Any] | None:
    """Return the committed state for *doc_id*, or ``None`` when absent."""
    db = DatabaseManager.get(str(library_root))
    db.initialize()
    with db.mol_conn() as conn:
        row = conn.execute(
            f"SELECT * FROM {_TABLE} WHERE doc_id = ?", (doc_id,)
        ).fetchone()
    if row is None:
        return None
    return {
        "doc_id": row["doc_id"],
        "revision": int(row["revision"]),
        "evidence_signature": row["evidence_signature"],
        "analysis_status": row["analysis_status"],
        "extraction_mode": row["extraction_mode"],
        "payload": json.loads(row["payload"] or "{}"),
        "decisions": json.loads(row["decisions"] or "{}"),
        "updated_at": row["updated_at"],
    }


def commit_document_facts(
    library_root: str | Path,
    *,
    doc_id: str,
    evidence_signature: str,
    analysis_status: str,
    extraction_mode: str,
    payload: dict[str, Any],
    candidates: Sequence[Any] = (),
    activity_updates: Sequence[dict[str, Any]] | None = None,
    measurements: Sequence[Any] = (),
    attributions: Sequence[Any] = (),
    decisions: dict[str, Any] | None = None,
    forget_decisions: Sequence[str] = (),
    expected_revision: int | None = None,
) -> int:
    """Commit one revision plus its derived rows; return the new revision.

    The readings and their attributions are document-scoped and rewritten in the
    same transaction, so a re-run replaces them instead of accumulating and the
    committed facts can never disagree with the readings they were built from.
    """
    db = DatabaseManager.get(str(library_root))
    db.initialize()
    now = datetime.now(UTC).strftime("%Y-%m-%d %H:%M:%S")
    with db.transaction() as (_kb_conn, conn):
        row = conn.execute(
            f"SELECT revision, decisions FROM {_TABLE} WHERE doc_id = ?", (doc_id,)
        ).fetchone()
        current = int(row["revision"]) if row is not None else 0
        if expected_revision is not None and expected_revision != current:
            raise ConflictError(
                f"stale patent analysis revision for {doc_id}: "
                f"expected {expected_revision}, found {current}"
            )
        revision = current + 1
        stored_decisions = (
            json.loads(row["decisions"] or "{}") if row is not None else {}
        )
        if decisions:
            stored_decisions.update(decisions)
        for slot_id in forget_decisions:
            stored_decisions.pop(slot_id, None)
        persist_candidates_in_transaction(
            conn, db, doc_id, candidates, activity_updates
        )
        # Readings are stored independently of structure: the measured facts the
        # document printed must survive an association that could not resolve.
        delete_document_measurements(conn, doc_id)
        insert_measurements_in_transaction(conn, measurements)
        insert_attributions_in_transaction(conn, attributions)
        conn.execute(
            f"""
            INSERT INTO {_TABLE}
                (doc_id, revision, evidence_signature, analysis_status,
                 extraction_mode, payload, decisions, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(doc_id) DO UPDATE SET
                revision = excluded.revision,
                evidence_signature = excluded.evidence_signature,
                analysis_status = excluded.analysis_status,
                extraction_mode = excluded.extraction_mode,
                payload = excluded.payload,
                decisions = excluded.decisions,
                updated_at = excluded.updated_at
            """,
            (
                doc_id,
                revision,
                evidence_signature,
                analysis_status,
                extraction_mode,
                json.dumps(payload, ensure_ascii=False),
                json.dumps(stored_decisions, ensure_ascii=False),
                now,
            ),
        )
    return revision


def clear_payload(library_root: str | Path, doc_id: str) -> int:
    """Drop the committed facts but keep the human decisions; return the revision."""
    db = DatabaseManager.get(str(library_root))
    db.initialize()
    now = datetime.now(UTC).strftime("%Y-%m-%d %H:%M:%S")
    with db.transaction() as (_kb_conn, conn):
        row = conn.execute(
            f"SELECT revision FROM {_TABLE} WHERE doc_id = ?", (doc_id,)
        ).fetchone()
        if row is None:
            return 0
        revision = int(row["revision"]) + 1
        conn.execute(
            f"""
            UPDATE {_TABLE}
               SET revision = ?, payload = ?, analysis_status = 'disabled',
                   extraction_mode = 'deterministic', updated_at = ?
             WHERE doc_id = ?
            """,
            (revision, "{}", now, doc_id),
        )
    return revision


def delete_document_state(library_root: str | Path, doc_id: str) -> int:
    """Remove the document's state entirely (document deletion)."""
    db = DatabaseManager.get(str(library_root))
    db.initialize()
    with db.mol_conn() as conn:
        cursor = conn.execute(f"DELETE FROM {_TABLE} WHERE doc_id = ?", (doc_id,))
        conn.commit()
        return int(cursor.rowcount or 0)


__all__ = [
    "clear_payload",
    "commit_document_facts",
    "delete_document_state",
    "load_state",
]
