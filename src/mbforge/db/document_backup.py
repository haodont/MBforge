"""Database snapshot export for document backups.

Exports every database row owned by a ``doc_id`` (the document's identity plus
its child rows) so a backup is self-contained and restorable.  The filesystem
half of a backup (storage tree, manifest, pruning) stays in the service layer.
"""

from __future__ import annotations

from typing import Any

from mbforge.db.sqlite.database import DatabaseManager

# Tables that expose a ``doc_id`` column and are scoped per document.
_DOC_TABLES = (
    "documents",
    "ingest_queue",
    "ingest_stage_deps",
    "ingest_runs",
    "ingest_logs",
    "molecule_detections",
    "source_evidence",
    "review_items",
    "measurements",
    "measurement_attribution",
)


def _rows_by_doc(conn: Any, table: str, doc_id: str) -> list[dict[str, Any]]:
    """Return all rows of *table* belonging to *doc_id*."""
    return [
        dict(row)
        for row in conn.execute(
            f"SELECT * FROM {table} WHERE doc_id = ?", (doc_id,)
        ).fetchall()
    ]


def _rows_in(
    conn: Any, table: str, column: str, ids: list[str]
) -> list[dict[str, Any]]:
    """Return rows of *table* whose *column* value is in *ids*."""
    if not ids:
        return []
    placeholders = ",".join("?" for _ in ids)
    return [
        dict(row)
        for row in conn.execute(
            f"SELECT * FROM {table} WHERE {column} IN ({placeholders})", ids
        ).fetchall()
    ]


def _rows_by_owner(conn: Any, table: str, doc_id: str) -> list[dict[str, Any]]:
    """Return rows of *table* owned by *doc_id* via ``source_doc`` (molecules)."""
    return [
        dict(row)
        for row in conn.execute(
            f"SELECT * FROM {table} WHERE source_doc = ?", (doc_id,)
        ).fetchall()
    ]


def _snapshot(conn: Any, doc_id: str) -> dict[str, list[dict[str, Any]]]:
    """Export every database row owned by *doc_id*.

    Walks the document's identity plus its child rows (molecule image and
    correction records) so the snapshot is self-contained and restorable.
    """
    snapshot: dict[str, list[dict[str, Any]]] = {}
    for table in _DOC_TABLES:
        rows = _rows_by_doc(conn, table, doc_id)
        if rows:
            snapshot[table] = rows

    molecules = _rows_by_owner(conn, "molecules", doc_id)
    if molecules:
        snapshot["molecules"] = molecules
        mol_ids = [row["mol_id"] for row in molecules]
        images = _rows_in(conn, "molecule_images", "mol_id", mol_ids)
        if images:
            snapshot["molecule_images"] = images
        corrections = _rows_in(conn, "molecule_corrections", "mol_id", mol_ids)
        if corrections:
            snapshot["molecule_corrections"] = corrections

    return snapshot


def snapshot_doc_db(
    manager: DatabaseManager, doc_id: str
) -> dict[str, list[dict[str, Any]]]:
    """Return the document's database rows after ensuring the DB is ready."""
    manager.initialize()
    with manager.connection() as conn:
        return _snapshot(conn, doc_id)


__all__ = ["snapshot_doc_db"]
