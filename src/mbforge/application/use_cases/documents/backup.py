"""Create recoverable snapshots before destructive document changes.

A backup captures *only* the affected document's data — the document's
``storage/`` tree and the document-scoped rows in the unified database —
rather than a copy of the entire ``library.db``.  Old snapshots are pruned
to a bounded number so the ``backups/`` directory cannot grow without limit.
"""

from __future__ import annotations

import contextlib
import json
import shutil
import sqlite3
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from mbforge.application.ports import get_database
from mbforge.foundation.layout import LibraryLayout

# Keep at most this many most-recent backups, pruning the oldest.
MAX_BACKUPS = 20

# Tables that expose a ``doc_id`` column and are scoped per document.
_DOC_TABLES = (
    "ingest_queue",
    "ingest_stage_deps",
    "ingest_runs",
    "ingest_logs",
    "molecule_detections",
    "text_molecule_links",
    "markush_scaffolds",
    "markush_fragments",
    "markush_review_candidates",
    "markush_evidence",
    "evidence",
    "source_evidence",
    "review_items",
    "activities",
)


def _rows_by_doc(
    conn: sqlite3.Connection, table: str, doc_id: str
) -> list[dict[str, Any]]:
    """Return all rows of *table* belonging to *doc_id*."""
    return [
        dict(row)
        for row in conn.execute(
            f"SELECT * FROM {table} WHERE doc_id = ?", (doc_id,)
        ).fetchall()
    ]


def _rows_in(
    conn: sqlite3.Connection, table: str, column: str, ids: list[str]
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


def _snapshot_doc_db(
    conn: sqlite3.Connection, doc_id: str
) -> dict[str, list[dict[str, Any]]]:
    """Export every database row owned by *doc_id*.

    Walks the document's identity plus its child rows (molecule image /
    relation / correction records and the Markush scaffold->site->option /
    mount hierarchy) so the snapshot is self-contained and restorable.
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
        relations = _rows_in(conn, "molecule_relations", "mol_a_id", mol_ids)
        relations.extend(_rows_in(conn, "molecule_relations", "mol_b_id", mol_ids))
        if relations:
            snapshot["molecule_relations"] = relations

    scaffold_ids = [row["scaffold_id"] for row in snapshot.get("markush_scaffolds", [])]
    if scaffold_ids:
        sites = _rows_in(conn, "markush_sites", "scaffold_id", scaffold_ids)
        if sites:
            snapshot["markush_sites"] = sites
            site_ids = [row["site_id"] for row in sites]
            options = _rows_in(conn, "markush_options", "site_id", site_ids)
            if options:
                snapshot["markush_options"] = options
            mounts = _rows_in(conn, "markush_mounts", "site_id", site_ids)
            if mounts:
                snapshot["markush_mounts"] = mounts

    candidate_ids = [
        row["candidate_id"] for row in snapshot.get("markush_review_candidates", [])
    ]
    if candidate_ids:
        decisions = _rows_in(conn, "markush_decisions", "entity_id", candidate_ids)
        if decisions:
            snapshot["markush_decisions"] = decisions

    return snapshot


def _rows_by_owner(
    conn: sqlite3.Connection, table: str, doc_id: str
) -> list[dict[str, Any]]:
    """Return rows of *table* owned by *doc_id* via ``source_doc`` (molecules)."""
    return [
        dict(row)
        for row in conn.execute(
            f"SELECT * FROM {table} WHERE source_doc = ?", (doc_id,)
        ).fetchall()
    ]


def _prune_old_backups(layout: LibraryLayout) -> None:
    """Delete oldest snapshots beyond ``MAX_BACKUPS``."""
    backups_dir = layout.metadata_dir / "backups"
    if not backups_dir.is_dir():
        return
    ordered = sorted(backups_dir.iterdir(), key=lambda p: p.name)
    for path in ordered[:-MAX_BACKUPS]:
        if path.is_dir():
            shutil.rmtree(path, ignore_errors=True)
        else:
            with contextlib.suppress(OSError):
                path.unlink(missing_ok=True)


def create_backup(
    library_root: str | Path,
    doc_id: str,
    operation: str,
) -> Path:
    """Snapshot the affected document before mutation.

    Stores the document's ``storage/`` tree plus a JSON export of the
    document-scoped database rows, and prunes to a bounded set.  Returns the
    created backup directory.
    """
    layout = LibraryLayout(library_root)
    timestamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%S%fZ")
    backup_root = layout.metadata_dir / "backups" / f"{timestamp}_{operation}_{doc_id}"
    backup_root.mkdir(parents=True, exist_ok=False)

    storage_dir = layout.storage_dir(doc_id)
    if storage_dir.exists():
        shutil.copytree(storage_dir, backup_root / "storage" / doc_id)

    db = get_database(str(layout.library_root))
    db.initialize()
    with db.mol_conn() as conn:
        db_snapshot = _snapshot_doc_db(conn, doc_id)

    (backup_root / "database.json").write_text(
        json.dumps(db_snapshot, ensure_ascii=False, default=str, indent=2),
        encoding="utf-8",
    )
    (backup_root / "manifest.json").write_text(
        json.dumps(
            {
                "doc_id": doc_id,
                "operation": operation,
                "created_at": timestamp,
                "tables": sorted(db_snapshot.keys()),
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )

    with contextlib.suppress(OSError):
        _prune_old_backups(layout)
    return backup_root


__all__ = ["create_backup", "MAX_BACKUPS"]
