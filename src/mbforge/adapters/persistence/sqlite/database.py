"""SQLite database manager — schema creation and connection management.

A single unified database per library (``{root}/.mbforge/library.db``)
holds all business tables: ingest queue,
semantic cache, molecules, images, relations, detections, evidence, and
the FTS5 search index.
"""

from __future__ import annotations

import functools
import sqlite3
import threading
from collections.abc import Iterable, Iterator
from contextlib import contextmanager
from pathlib import Path
from typing import Any

from mbforge.adapters.persistence.sqlite.schema import (
    _ACTIVITIES_SCHEMA,
    _EVIDENCE_SCHEMA,
    _KB_SCHEMA,
    _MOL_FTS,
    _MOL_SCHEMA,
    _REVIEW_V12_SCHEMA,
    _SOURCE_EVIDENCE_SCHEMA,
)
from mbforge.domain.molecule import Molecule
from mbforge.foundation.logger import get_logger

logger = get_logger("mbforge.adapters.persistence.sqlite.database")


# Terminal states of an ``ingest_queue`` row. A terminal row is never
# claimed, reclaimed, or transitioned again; the worker and the pipeline
# router share this definition so the queue state machine has a single
# source of truth.
#
# Bumped whenever a retired stage must be dropped from persisted queue DAGs
# (see ``DatabaseManager._migrate_ingest_dag``).
#
# 1 — removed the retired ``detection`` node (molecule detection moved into
#     ``extract``).
# 2 — removed the retired ``join`` node (extract persists evidence directly).
_INGEST_DAG_VERSION = 2

#: Retired stage names, removed from any persisted queue DAG.
_RETIRED_STAGES = ("detection", "join")


class DatabaseManager:
    """Manages SQLite connections to the library's unified database."""

    def __init__(self, library_root: str | Path) -> None:
        from mbforge.foundation.layout import LibraryLayout

        self._root = Path(library_root).expanduser().resolve()
        self._layout = LibraryLayout(library_root)
        self._layout.ensure_metadata_dir()
        self._db_path = self._layout.database_path
        self._kb_path = self._db_path
        self._mol_path = self._db_path
        self._lock = threading.Lock()
        # threading.Event gives a clearer double-checked-locking pattern than
        # a plain bool and avoids the (theoretical) re-ordering issues of a
        # naked flag across threads.
        self._initialized = threading.Event()
        # In the unified single-DB layout, each thread gets its own SQLite
        # connection. SQLite connections are bound to the thread that created
        # them (check_same_thread defaults to True), so a single shared
        # connection cannot safely be handed across asyncio thread pools.
        self._local = threading.local()

    @staticmethod
    def molecule_schema() -> str:
        """Return SQL for molecule, source-evidence, activity and FTS tables."""
        return (
            _MOL_SCHEMA
            + _SOURCE_EVIDENCE_SCHEMA
            + _EVIDENCE_SCHEMA
            + _REVIEW_V12_SCHEMA
            + _ACTIVITIES_SCHEMA
            + _MOL_FTS
        )

    @staticmethod
    def delete_molecule_records(
        conn: sqlite3.Connection, mol_ids: Iterable[str]
    ) -> int:
        """Delete molecule rows and all rows owned by those molecule IDs."""
        ids = sorted({mol_id for mol_id in mol_ids if mol_id})
        if not ids:
            return 0
        # SQLite's default ``SQLITE_MAX_VARIABLE_NUMBER`` is 999; building
        # ``IN (?, ?, ...)`` placeholders with more ids would raise
        # ``OperationalError: too many SQL variables``. We chunk the
        # pre-check SELECT and the deletes so this routine works for
        # arbitrarily large selections.
        chunk_size = 500
        # The pre-check SELECT must be chunked for the same reason: with more
        # than 999 ids the placeholder list would exceed the variable limit.
        actual_ids: list[str] = []
        for start in range(0, len(ids), chunk_size):
            chunk = ids[start : start + chunk_size]
            chunk_placeholders = ",".join("?" for _ in chunk)
            rows = conn.execute(
                f"SELECT mol_id FROM molecules WHERE mol_id IN ({chunk_placeholders})",
                chunk,
            ).fetchall()
            actual_ids.extend(row[0] for row in rows)
        if not actual_ids:
            return 0

        # Capture canonical SMILES before the molecules themselves are
        # deleted. The residual-alias cleanup below runs after those rows are
        # gone, so querying ``molecules`` at that point would be empty and
        # silently delete nothing.
        deleted_canons: list[str] = []
        for start in range(0, len(actual_ids), chunk_size):
            chunk = actual_ids[start : start + chunk_size]
            chunk_placeholders = ",".join("?" for _ in chunk)
            rows = conn.execute(
                f"SELECT DISTINCT canonical_smiles FROM molecules "
                f"WHERE mol_id IN ({chunk_placeholders})",
                chunk,
            ).fetchall()
            deleted_canons.extend(row[0] for row in rows if row[0])
        # Deduplicate and keep insertion order.
        deleted_canons = list(dict.fromkeys(deleted_canons))

        def _chunked(table: str, where: str, params: list[str]) -> None:
            for start in range(0, len(params), chunk_size):
                chunk = params[start : start + chunk_size]
                chunk_placeholders = ",".join("?" for _ in chunk)
                conn.execute(
                    f"DELETE FROM {table} WHERE {where} IN ({chunk_placeholders})",
                    chunk,
                )

        # molecule_relations references molecules from both sides, so pass
        # the id list twice. Each chunk sees at most chunk_size ids per side.
        for start in range(0, len(actual_ids), chunk_size):
            chunk = actual_ids[start : start + chunk_size]
            chunk_placeholders = ",".join("?" for _ in chunk)
            conn.execute(
                f"DELETE FROM molecule_relations "
                f"WHERE mol_a_id IN ({chunk_placeholders}) "
                f"OR mol_b_id IN ({chunk_placeholders})",
                chunk + chunk,
            )

        _chunked("molecule_images", "mol_id", actual_ids)
        _chunked("molecule_detections", "mol_id", actual_ids)
        _chunked("text_molecule_links", "mol_id", actual_ids)
        # ``activities`` has a CASCADE FK on ``mol_id`` but we
        # also issue an explicit DELETE here so the cleanup is visible in
        # this routine and works on connections that have
        # ``PRAGMA foreign_keys`` off.
        _chunked("activities", "mol_id", actual_ids)
        _chunked("evidence", "mol_id", actual_ids)
        _chunked("molecules", "mol_id", actual_ids)
        # Any evidence rows that share a canonical_smiles with a deleted
        # molecule but were not anchored to that mol_id (e.g. un-anchored
        # figure rows or aliased duplicates) go too. Evidence whose smiles is
        # still owned by a surviving molecule is kept so it stays
        # attributable. Chunked for the same reason.
        for start in range(0, len(deleted_canons), chunk_size):
            chunk = deleted_canons[start : start + chunk_size]
            chunk_placeholders = ",".join("?" for _ in chunk)
            conn.execute(
                f"DELETE FROM evidence WHERE canonical_smiles IN ({chunk_placeholders}) "
                f"AND NOT EXISTS (SELECT 1 FROM molecules m "
                f"WHERE m.canonical_smiles = evidence.canonical_smiles)",
                chunk,
            )
        # This FTS table uses molecules as external content. Rebuilding after
        # the base rows are gone is reliable across SQLite/FTS5 versions,
        # whereas the incremental external-content delete syntax is not.
        conn.execute("INSERT INTO mol_search(mol_search) VALUES ('rebuild')")
        return len(actual_ids)

    @staticmethod
    def delete_molecule_from_mol_search(conn: sqlite3.Connection, mol_id: str) -> None:
        """Remove a molecule's old entries from the external-content FTS5 index.

        Must be called **before** updating ``molecules`` for an existing row:
        FTS5 external-content DELETE uses the current content-table values to
        decide which terms to remove, so the old content must still be present
        when this runs. The operation is a no-op if the molecule has not been
        indexed yet.
        """
        row = conn.execute(
            "SELECT rowid FROM molecules WHERE mol_id = ?", (mol_id,)
        ).fetchone()
        if row is None:
            return
        # Query the FTS5 shadow table; ``SELECT ... FROM mol_search`` would
        # return rows for any rowid that exists in the external content table.
        existing = conn.execute(
            "SELECT 1 FROM mol_search_docsize WHERE rowid = ?", (row["rowid"],)
        ).fetchone()
        if existing is not None:
            conn.execute("DELETE FROM mol_search WHERE rowid = ?", (row["rowid"],))

    @staticmethod
    def sync_molecule_to_mol_search(conn: sqlite3.Connection, mol_id: str) -> None:
        """Insert/refresh a single molecule row in the external-content FTS5 index.

        Must be called **after** ``molecules`` has been written with its latest
        ``name``, ``notes``, and ``smiles``. For UPDATEs callers must first run
        ``delete_molecule_from_mol_search`` while the old row content is still
        in place. The operation is idempotent.
        """
        row = conn.execute(
            "SELECT rowid, name, notes, smiles FROM molecules WHERE mol_id = ?",
            (mol_id,),
        ).fetchone()
        if row is None:
            return
        conn.execute(
            "INSERT INTO mol_search(rowid, name, notes, smiles) VALUES (?, ?, ?, ?)",
            (row["rowid"], row["name"], row["notes"], row["smiles"]),
        )

    @staticmethod
    def sync_molecule_fingerprint(conn: sqlite3.Connection, mol_id: str) -> None:
        """Compute and store the Morgan fingerprint for a molecule.

        Uses the ``smiles`` column as the fingerprint source. If RDKit cannot
        parse the SMILES, ``fingerprint`` is left unchanged (or NULL) and a
        warning is logged. The operation is idempotent.
        """
        row = conn.execute(
            "SELECT smiles FROM molecules WHERE mol_id = ?", (mol_id,)
        ).fetchone()
        if row is None or not row["smiles"]:
            return
        mol = Molecule(mol_id="", canonical_smiles=row["smiles"])
        fp = mol.fingerprint
        if fp is None:
            logger.warning("Failed to compute fingerprint for %s", mol_id)
            return
        conn.execute(
            "UPDATE molecules SET fingerprint = ? WHERE mol_id = ?",
            (fp, mol_id),
        )

    @staticmethod
    def delete_document_molecule_data(conn: sqlite3.Connection, doc_id: str) -> int:
        """Remove a document's evidence and orphaned molecule rows."""
        candidate_rows = conn.execute(
            """
            SELECT mol_id FROM molecules WHERE source_doc = ?
            UNION
            SELECT mol_id FROM evidence WHERE doc_id = ? AND mol_id IS NOT NULL
            UNION
            SELECT mol_id FROM molecule_detections WHERE doc_id = ? AND mol_id IS NOT NULL
            UNION
            SELECT mol_id FROM text_molecule_links WHERE doc_id = ?
            """,
            (doc_id, doc_id, doc_id, doc_id),
        ).fetchall()
        candidates = [row[0] for row in candidate_rows if row[0]]

        conn.execute("DELETE FROM evidence WHERE doc_id = ?", (doc_id,))
        conn.execute("DELETE FROM source_evidence WHERE doc_id = ?", (doc_id,))
        conn.execute("DELETE FROM molecule_detections WHERE doc_id = ?", (doc_id,))
        conn.execute("DELETE FROM text_molecule_links WHERE doc_id = ?", (doc_id,))
        # Capture the document's review candidate IDs before deleting the
        # candidates: the decisions table is keyed on those IDs, so deleting
        # candidates first would make the audit cleanup no-op and leave
        # orphaned decision rows behind.
        review_candidate_ids = [
            row[0]
            for row in conn.execute(
                "SELECT candidate_id FROM markush_review_candidates WHERE doc_id = ?",
                (doc_id,),
            ).fetchall()
        ]
        conn.execute("DELETE FROM markush_fragments WHERE doc_id = ?", (doc_id,))
        conn.execute("DELETE FROM markush_scaffolds WHERE doc_id = ?", (doc_id,))
        conn.execute("DELETE FROM markush_evidence WHERE doc_id = ?", (doc_id,))
        if review_candidate_ids:
            placeholders = ",".join("?" for _ in review_candidate_ids)
            conn.execute(
                "DELETE FROM markush_decisions WHERE entity_type = 'review_candidate' "
                f"AND entity_id IN ({placeholders})",
                review_candidate_ids,
            )
        conn.execute(
            "DELETE FROM markush_review_candidates WHERE doc_id = ?", (doc_id,)
        )
        conn.execute("DELETE FROM activities WHERE doc_id = ?", (doc_id,))
        # Pipeline-generated review items are re-derived on every ingest;
        # leaving them behind would present stale queue entries for a
        # document whose molecule rows no longer exist.
        conn.execute("DELETE FROM review_items WHERE doc_id = ?", (doc_id,))

        if not candidates:
            return 0
        placeholders = ",".join("?" for _ in candidates)
        orphan_rows = conn.execute(
            f"""
            SELECT m.mol_id
            FROM molecules m
            WHERE m.mol_id IN ({placeholders})
              AND (m.source_doc = ? OR m.source_doc IS NULL)
              AND NOT EXISTS (SELECT 1 FROM evidence e WHERE e.mol_id = m.mol_id)
              AND NOT EXISTS (
                SELECT 1 FROM molecule_detections d WHERE d.mol_id = m.mol_id
              )
              AND NOT EXISTS (
                SELECT 1 FROM text_molecule_links t WHERE t.mol_id = m.mol_id
              )
            """,
            candidates + [doc_id],
        ).fetchall()
        return DatabaseManager.delete_molecule_records(
            conn, [row[0] for row in orphan_rows]
        )

    @classmethod
    @functools.lru_cache(maxsize=128)
    def get(cls, library_root: str | Path) -> DatabaseManager:
        """Return a cached instance keyed by resolved absolute path."""
        return cls(library_root)

    def initialize(self) -> None:
        if self._initialized.is_set():
            return
        with self._lock:
            if self._initialized.is_set():
                return
            conn = sqlite3.connect(str(self._kb_path))
            try:
                conn.execute("PRAGMA journal_mode=WAL")
                conn.execute("PRAGMA foreign_keys=ON")
                conn.executescript(_KB_SCHEMA)
                # The activities table is defined in _ACTIVITIES_SCHEMA but not
                # included in _KB_SCHEMA, so it is created explicitly here.
                conn.executescript(_ACTIVITIES_SCHEMA)
                self._migrate_ingest_dag(conn)
                conn.commit()
            finally:
                conn.close()
            conn = sqlite3.connect(str(self._mol_path))
            try:
                conn.execute("PRAGMA journal_mode=WAL")
                conn.execute("PRAGMA foreign_keys=ON")
                conn.executescript(DatabaseManager.molecule_schema())
                conn.commit()
            finally:
                conn.close()
            self._initialized.set()
            logger.info("DB initialized: %s", self._db_path)

    @staticmethod
    def _migrate_ingest_dag(conn: sqlite3.Connection) -> None:
        """Drop retired stage nodes from a persisted ingest queue DAG.

        Molecule detection now lives inside the Extract stage, and Extract
        persists its own evidence — so a leftover ``detection`` or ``join`` node
        would keep its document stuck forever: the stale edge stops
        ``advance_dependents`` from ever promoting the next stage, and
        ``all_stages_done`` can never be true because the retired node is never
        ``done``. Runs once per database file.
        """
        version = conn.execute("PRAGMA user_version").fetchone()[0]
        if version >= _INGEST_DAG_VERSION:
            return
        placeholders = ", ".join("?" for _ in _RETIRED_STAGES)
        conn.execute(
            "DELETE FROM ingest_stage_deps "
            f"WHERE stage IN ({placeholders}) OR depends_on IN ({placeholders})",
            (*_RETIRED_STAGES, *_RETIRED_STAGES),
        )
        conn.execute(
            f"DELETE FROM ingest_queue WHERE stage IN ({placeholders})",
            _RETIRED_STAGES,
        )
        conn.execute(f"PRAGMA user_version = {_INGEST_DAG_VERSION}")
        logger.info(
            "Ingest DAG migrated: removed retired stages %s", list(_RETIRED_STAGES)
        )

    def _thread_connection(self) -> sqlite3.Connection:
        """Return a per-thread SQLite connection for the unified database.

        Connections are lazily created and bound to the calling thread so that
        ``kb_conn()`` / ``mol_conn()`` / ``transaction()`` can safely be used
        across ``asyncio.to_thread`` or other thread-pool boundaries. A
        per-thread refcount keeps the connection open during nested context
        manager entries and closes it once the outermost one exits.
        """
        if not hasattr(self._local, "conn") or self._local.conn is None:
            self._local.conn = sqlite3.connect(str(self._db_path))
            self._local.conn.row_factory = sqlite3.Row
            self._local.conn.execute("PRAGMA foreign_keys=ON")
            self._local.refcount = 0
        return self._local.conn

    @contextmanager
    def _shared_connection(self) -> Iterator[sqlite3.Connection]:
        """Yield the current thread's connection for the unified database.

        In the unified single-DB layout ``kb_conn()`` and ``mol_conn()`` share
        the same physical connection *within* the calling thread, matching the
        previous refcounted behavior without pinning a connection to one thread.
        """
        conn = self._thread_connection()
        self._local.refcount += 1
        try:
            yield conn
            conn.commit()
        except Exception:
            conn.rollback()
            raise
        finally:
            self._local.refcount -= 1
            if self._local.refcount <= 0:
                conn.close()
                self._local.conn = None

    @contextmanager
    def kb_conn(self):
        self.initialize()
        with self._shared_connection() as conn:
            yield conn

    @contextmanager
    def mol_conn(self):
        self.initialize()
        with self._shared_connection() as conn:
            yield conn

    @contextmanager
    def transaction(self):
        """Transaction over the unified library database.

        Yields a tuple ``(kb_conn, mol_conn)``; both entries are the same
        physical connection to the single unified database, so a failure
        anywhere rolls back every write made inside the block.
        """
        self.initialize()
        with self._shared_connection() as kb_conn:
            yield kb_conn, kb_conn

    def execute(
        self,
        sql: str,
        parameters: tuple | list | dict | None = None,
        *,
        db: str = "kb",
    ) -> list[sqlite3.Row]:
        """Execute a single statement and return all rows.

        Convenience helper for simple CRUD operations. For multi-statement
        transactions prefer ``transaction()``.
        """
        parameters = parameters or ()
        conn_manager = self.kb_conn if db == "kb" else self.mol_conn
        with conn_manager() as conn:
            return conn.execute(sql, parameters).fetchall()

    def count_documents(self) -> int:
        """Return the number of documents currently tracked in the ingest queue."""
        rows = self.execute("SELECT COUNT(*) as cnt FROM ingest_queue", db="kb")
        return rows[0]["cnt"] if rows else 0

    def count_molecules(self) -> int:
        """Return the number of molecules currently persisted."""
        rows = self.execute("SELECT COUNT(*) as cnt FROM molecules", db="mol")
        return rows[0]["cnt"] if rows else 0

    @property
    def kb_path(self) -> Path:
        return self._kb_path

    @property
    def mol_path(self) -> Path:
        return self._mol_path


def record_ingest_event(
    db: DatabaseManager,
    *,
    task_id: str,
    run_id: str | None = None,
    doc_id: str | None,
    stage: str,
    level: str,
    message: str,
    data: dict[str, Any] | None = None,
    status: str | None = None,
    update_stage: str | None = None,
) -> None:
    """Write a pipeline event to the ``ingest_logs`` table.

    This is the persistence target for ``runner._maybe_record``. Failures are
    swallowed by the caller so a logging problem never crashes the pipeline.

    ``update_stage`` is the checkpoint column value supplied by the caller
    (the runner validates it against the stage registry); storage does not
    know pipeline stage names.
    """
    import json
    import time

    db.initialize()
    try:
        with db.kb_conn() as conn:
            data_json = json.dumps(data, ensure_ascii=False) if data else None
            conn.execute(
                """
                INSERT INTO ingest_logs
                    (doc_id, stage, level, message, ts_ms, task_id, run_id, data)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    doc_id or "",
                    stage,
                    level,
                    message,
                    int(time.time() * 1000),
                    task_id,
                    run_id,
                    data_json,
                ),
            )
            if status is not None or update_stage is not None:
                conn.execute(
                    """
                    UPDATE ingest_queue
                    SET status = COALESCE(?, status),
                        stage = COALESCE(?, stage),
                        updated_at = datetime('now')
                    WHERE id = ?
                    """,
                    (status, update_stage, task_id),
                )
        logger.debug("Recorded ingest event for %s: %s", task_id, message)
    except Exception as exc:  # noqa: BLE001
        logger.warning("Failed to record ingest event for %s: %s", task_id, exc)
