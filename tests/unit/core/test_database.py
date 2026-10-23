"""Unit tests for DatabaseManager — schema init, CRUD, and transaction boundaries.

Covers ``mbforge.db.sqlite.database`` (``DatabaseManager`` and
``record_ingest_event``): the initialized schema + indexes, transaction
commit/rollback across both databases, the shared-connection unified layout,
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
    """Initializing a DatabaseManager creates both SQLite files, the expected
    tables, and the Markush lookup indexes."""
    db = DatabaseManager(str(tmp_path))
    db.initialize()

    assert db.kb_path.exists()
    assert db.mol_path.exists()

    with db.kb_conn() as conn:
        tables = {
            r[0]
            for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")
        }
        assert "ingest_queue" in tables
        assert "tasks" not in tables

    with db.mol_conn() as conn:
        tables = {
            r[0]
            for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")
        }
        assert "molecules" in tables
        assert "molecule_detections" in tables
        assert "evidence" not in tables
        assert "source_evidence" in tables
        assert "markush_scaffolds" in tables
        assert "markush_fragments" in tables

        indices = {
            row[0]
            for row in conn.execute(
                "SELECT name FROM sqlite_master WHERE type = 'index' "
                "AND (name LIKE 'idx_ms_%' OR name LIKE 'idx_mf_%')"
            )
        }
    assert {
        "idx_ms_doc",
        "idx_ms_status",
        "idx_mf_doc",
        "idx_mf_scaffold",
        "idx_mf_status",
    } <= indices


def test_transaction_commits_both_databases(tmp_path: Path) -> None:
    """A successful transaction() commits writes to both databases."""
    db = DatabaseManager(str(tmp_path))
    db.initialize()

    with db.transaction() as (kb_conn, mol_conn):
        kb_conn.execute(
            "INSERT INTO ingest_queue (id, file_path) VALUES (?, ?)",
            ("task-1", "/tmp/test.pdf"),
        )
        mol_conn.execute(
            "INSERT INTO molecules (mol_id, smiles) VALUES (?, ?)",
            ("mol-1", "CCO"),
        )

    assert db.count_documents() == 1
    assert db.count_molecules() == 1


def test_transaction_rolls_back_both_databases_on_failure(tmp_path: Path) -> None:
    """A failure on either side of the transaction rolls back both, leaving no
    partial state."""
    for fail_kb in (True, False):
        root = tmp_path / f"rollback-{fail_kb}"
        root.mkdir()
        db = DatabaseManager(str(root))
        db.initialize()

        exc = "Simulated KB failure" if fail_kb else "Simulated mol failure"
        with (
            pytest.raises(Exception, match=exc),
            db.transaction() as (kb_conn, mol_conn),
        ):
            kb_conn.execute(
                "INSERT INTO ingest_queue (id, file_path) VALUES (?, ?)",
                ("task-1", "/tmp/test.pdf"),
            )
            mol_conn.execute(
                "INSERT INTO molecules (mol_id, smiles) VALUES (?, ?)",
                ("mol-1", "CCO"),
            )
            raise Exception(exc)

        assert db.count_documents() == 0, f"fail_kb={fail_kb}"
        assert db.count_molecules() == 0, f"fail_kb={fail_kb}"


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
    with db.kb_conn() as conn:
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
        db="kb",
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
        db="kb",
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
    broken._kb_path.unlink()
    record_ingest_event(
        broken,
        task_id="task-3",
        doc_id="doc-3",
        stage="extract",
        level="error",
        message="Disk full",
        data={"error_code": "PERSIST_FAILED"},
    )


def test_unified_layout_shares_one_connection(tmp_path: Path) -> None:
    """In the single-DB layout kb_conn, mol_conn and transaction() all reuse
    the one shared connection."""
    db = DatabaseManager(str(tmp_path))
    db.initialize()
    with db.kb_conn() as kb, db.mol_conn() as mol:
        assert kb is mol
    with db.transaction() as (kb, mol):
        assert kb is mol


@pytest.mark.asyncio
async def test_connection_is_usable_from_worker_threads(tmp_path: Path) -> None:
    """kb_conn works through asyncio.to_thread, including concurrently — the
    pattern ``pipeline_queue`` uses from the event loop."""
    db = DatabaseManager(str(tmp_path))
    db.initialize()

    def _fetch() -> int:
        with db.kb_conn() as conn:
            return conn.execute("SELECT COUNT(*) FROM ingest_queue").fetchone()[0]

    # Pre-warm a connection on the main thread, mirroring real usage.
    with db.kb_conn():
        pass

    assert await asyncio.to_thread(_fetch) == 0

    async def _insert(name: str) -> None:
        def _work() -> None:
            with db.kb_conn() as conn:
                conn.execute(
                    "INSERT INTO ingest_queue (id, file_path) VALUES (?, ?)",
                    (name, name),
                )

        await asyncio.to_thread(_work)

    await asyncio.gather(*[_insert(f"task-{i}") for i in range(10)])

    rows = db.execute("SELECT id FROM ingest_queue ORDER BY id", db="kb")
    assert {r["id"] for r in rows} == {f"task-{i}" for i in range(10)}


def test_deletion_paths_clean_related_rows_without_binding_limits(
    tmp_path: Path,
) -> None:
    """Bulk molecule deletion must not bind every id in one IN() clause
    (SQLITE_MAX_VARIABLE_NUMBER), and document deletion must remove the review
    candidates plus their markush_decisions audit rows."""
    db = DatabaseManager(str(tmp_path))
    db.initialize()

    mol_ids = [f"mol-{i:04d}" for i in range(1500)]

    with db.transaction() as (_, mol_conn):
        mol_conn.executemany(
            "INSERT INTO molecules (mol_id, smiles) VALUES (?, ?)",
            [(mol_id, "CCO") for mol_id in mol_ids],
        )
        # Include ids that do not exist plus duplicates to exercise the
        # filtered SELECT path across chunk boundaries.
        extra_ids = ["missing-1", "missing-2"] + mol_ids[:10]
        deleted = DatabaseManager.delete_molecule_records(mol_conn, mol_ids + extra_ids)

    assert deleted == len(mol_ids)
    assert db.count_molecules() == 0

    with db.mol_conn() as conn:
        conn.execute(
            "INSERT INTO markush_review_candidates "
            "(candidate_id, source_key, doc_id, predicted_role) "
            "VALUES (?, ?, ?, ?)",
            ("cand-1", "src-1", "doc-1", "review"),
        )
        conn.execute(
            "INSERT INTO markush_decisions "
            "(decision_id, entity_type, entity_id, action, snapshot) "
            "VALUES (?, 'review_candidate', 'cand-1', 'approve', '{}')",
            ("dec-1",),
        )
        deleted = DatabaseManager.delete_document_molecule_data(conn, "doc-1")

    with db.mol_conn() as conn:
        assert (
            conn.execute(
                "SELECT 1 FROM markush_review_candidates WHERE candidate_id = 'cand-1'"
            ).fetchone()
            is None
        )
        assert (
            conn.execute(
                "SELECT 1 FROM markush_decisions WHERE decision_id = 'dec-1'"
            ).fetchone()
            is None
        )
    assert deleted == 0
