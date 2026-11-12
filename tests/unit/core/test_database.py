"""Unit tests for DatabaseManager — schema init, CRUD, and transaction boundaries.

Covers ``mbforge.db.sqlite.database`` (``DatabaseManager`` and
``record_ingest_event``): the initialized schema + indexes, transaction
commit/rollback across the unified database, nested connection scopes,
threaded access, and the bulk-deletion cleanup paths.
"""

from __future__ import annotations

import asyncio
import json
from pathlib import Path

import pytest

from mbforge.db.sqlite.database import (
    DatabaseManager,
    record_ingest_event,
)


def test_database_initializes_schema_and_indices(tmp_path: Path) -> None:
    """Initializing a DatabaseManager creates the database file, the expected
    tables, and the molecule lookup indexes."""
    db = DatabaseManager(str(tmp_path))
    db.initialize()

    assert db.db_path.exists()

    with db.connection() as conn:
        tables = {
            r[0]
            for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")
        }
        assert "ingest_queue" in tables
        assert "tasks" not in tables
        assert "molecules" in tables
        assert "molecule_detections" in tables
        assert "evidence" not in tables
        assert "source_evidence" in tables

        indices = {
            row[0]
            for row in conn.execute(
                "SELECT name FROM sqlite_master WHERE type = 'index'"
            )
        }
    assert {
        "idx_m_smiles",
        "idx_m_source",
        "idx_m_status",
        "idx_m_canonical",
    } <= indices


def test_transaction_commits_queue_and_molecule_writes(tmp_path: Path) -> None:
    """A successful transaction() commits writes to both table families."""
    db = DatabaseManager(str(tmp_path))
    db.initialize()

    with db.transaction() as conn:
        conn.execute(
            "INSERT INTO ingest_queue (id, file_path) VALUES (?, ?)",
            ("task-1", "/tmp/test.pdf"),
        )
        conn.execute(
            "INSERT INTO molecules (mol_id, smiles) VALUES (?, ?)",
            ("mol-1", "CCO"),
        )

    assert db.count_documents() == 1
    assert db.count_molecules() == 1


def test_transaction_rolls_back_all_writes_on_failure(tmp_path: Path) -> None:
    """A failure inside the transaction rolls back every write, leaving no
    partial state."""
    for fail_early in (True, False):
        root = tmp_path / f"rollback-{fail_early}"
        root.mkdir()
        db = DatabaseManager(str(root))
        db.initialize()

        exc = "Simulated early failure" if fail_early else "Simulated late failure"
        with (
            pytest.raises(Exception, match=exc),
            db.transaction() as conn,
        ):
            conn.execute(
                "INSERT INTO ingest_queue (id, file_path) VALUES (?, ?)",
                ("task-1", "/tmp/test.pdf"),
            )
            conn.execute(
                "INSERT INTO molecules (mol_id, smiles) VALUES (?, ?)",
                ("mol-1", "CCO"),
            )
            raise Exception(exc)

        assert db.count_documents() == 0, f"fail_early={fail_early}"
        assert db.count_molecules() == 0, f"fail_early={fail_early}"


def test_cached_instance_per_project_root(tmp_path: Path) -> None:
    """DatabaseManager.get caches instances by resolved absolute path."""
    db1 = DatabaseManager.get(str(tmp_path))
    db2 = DatabaseManager.get(str(tmp_path))
    assert db1 is db2


def test_record_ingest_event_writes_log_and_swallows_failure(tmp_path: Path) -> None:
    """record_ingest_event persists a log row and mirrors the stage onto the
    matching ingest_queue row (node status stays with the worker); a broken
    database must not raise to the caller."""
    db = DatabaseManager(str(tmp_path))
    with db.connection() as conn:
        conn.execute(
            "INSERT INTO ingest_queue (id, file_path, status) VALUES (?, ?, ?)",
            ("task-2", "/tmp/test.pdf", "pending"),
        )

    record_ingest_event(
        db,
        task_id="task-2",
        doc_id="doc-2",
        stage="extract",
        level="start",
        message="Extracting text...",
        data={"molecule_count": 3, "rejected_count": 0},
        update_stage="extract",
    )

    log_rows = db.execute(
        "SELECT doc_id, stage, level, message, task_id, data "
        "FROM ingest_logs WHERE task_id=?",
        ("task-2",),
    )
    assert len(log_rows) == 1
    log_row = log_rows[0]
    assert log_row["doc_id"] == "doc-2"
    assert log_row["stage"] == "extract"
    assert log_row["level"] == "start"
    assert log_row["message"] == "Extracting text..."
    assert log_row["task_id"] == "task-2"
    assert json.loads(log_row["data"]) == {"molecule_count": 3, "rejected_count": 0}

    queue_rows = db.execute(
        "SELECT status, stage FROM ingest_queue WHERE id=?",
        ("task-2",),
    )
    assert len(queue_rows) == 1
    queue_row = queue_rows[0]
    # The event sink never writes status; the pending status is untouched.
    assert queue_row["status"] == "pending"
    assert queue_row["stage"] == "extract"

    # A failure while writing the log must not raise to the caller.
    (tmp_path / "broken").mkdir()
    broken = DatabaseManager(str(tmp_path / "broken"))
    broken.initialize()
    broken._db_path.unlink()
    record_ingest_event(
        broken,
        task_id="task-3",
        doc_id="doc-3",
        stage="extract",
        level="error",
        message="Disk full",
        data={"error_code": "PERSIST_FAILED"},
    )


def test_nested_scopes_share_one_connection(tmp_path: Path) -> None:
    """Nested connection()/transaction() scopes reuse the one per-thread
    connection, and the outermost exit closes it."""
    db = DatabaseManager(str(tmp_path))
    db.initialize()
    with db.connection() as outer, db.connection() as inner:
        assert outer is inner
    with db.transaction() as conn, db.connection() as nested:
        assert conn is nested


@pytest.mark.asyncio
async def test_connection_is_usable_from_worker_threads(tmp_path: Path) -> None:
    """connection() works through asyncio.to_thread, including concurrently — the
    pattern ``pipeline_queue`` uses from the event loop."""
    db = DatabaseManager(str(tmp_path))
    db.initialize()

    def _fetch() -> int:
        with db.connection() as conn:
            return conn.execute("SELECT COUNT(*) FROM ingest_queue").fetchone()[0]

    # Pre-warm a connection on the main thread, mirroring real usage.
    with db.connection():
        pass

    assert await asyncio.to_thread(_fetch) == 0

    async def _insert(name: str) -> None:
        def _work() -> None:
            with db.connection() as conn:
                conn.execute(
                    "INSERT INTO ingest_queue (id, file_path) VALUES (?, ?)",
                    (name, name),
                )

        await asyncio.to_thread(_work)

    await asyncio.gather(*[_insert(f"task-{i}") for i in range(10)])

    rows = db.execute("SELECT id FROM ingest_queue ORDER BY id")
    assert {r["id"] for r in rows} == {f"task-{i}" for i in range(10)}


def test_deletion_paths_clean_related_rows_without_binding_limits(
    tmp_path: Path,
) -> None:
    """Bulk molecule deletion must not bind every id in one IN() clause
    (SQLITE_MAX_VARIABLE_NUMBER), and document deletion must remove the
    document's pipeline-generated review items."""
    db = DatabaseManager(str(tmp_path))
    db.initialize()

    mol_ids = [f"mol-{i:04d}" for i in range(1500)]

    with db.transaction() as conn:
        conn.executemany(
            "INSERT INTO molecules (mol_id, smiles) VALUES (?, ?)",
            [(mol_id, "CCO") for mol_id in mol_ids],
        )
        # Include ids that do not exist plus duplicates to exercise the
        # filtered SELECT path across chunk boundaries.
        extra_ids = ["missing-1", "missing-2"] + mol_ids[:10]
        deleted = DatabaseManager.delete_molecule_records(conn, mol_ids + extra_ids)

    assert deleted == len(mol_ids)
    assert db.count_molecules() == 0

    with db.connection() as conn:
        conn.execute(
            "INSERT INTO review_items (item_id, kind, doc_id) VALUES (?, ?, ?)",
            ("rev-1", "low_conf_molecule", "doc-1"),
        )
        deleted = DatabaseManager.delete_document_molecule_data(conn, "doc-1")

    with db.connection() as conn:
        assert (
            conn.execute(
                "SELECT 1 FROM review_items WHERE item_id = 'rev-1'"
            ).fetchone()
            is None
        )
    assert deleted == 0
