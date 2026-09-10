"""Unit tests for DatabaseManager — schema init, CRUD, and transaction boundaries."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from mbforge.storage.sqlite.database import DatabaseManager, record_ingest_event


def test_database_initializes_schema(tmp_path: Path) -> None:
    """Initializing a DatabaseManager creates both SQLite files and tables."""
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
        assert "evidence" in tables
        assert "source_evidence" in tables
        assert "markush_scaffolds" in tables
        assert "markush_fragments" in tables


def test_markush_table_indices(tmp_path: Path) -> None:
    """New libraries expose Markush indexes."""
    db = DatabaseManager(str(tmp_path))
    db.initialize()

    with db.mol_conn() as conn:
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


@pytest.mark.parametrize("fail_kb", [True, False])
def test_transaction_rollback_on_single_database_failure(
    tmp_path: Path, fail_kb: bool
) -> None:
    """A failure in one database rolls back both, leaving no partial state."""
    db = DatabaseManager(str(tmp_path))
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

    assert db.count_documents() == 0
    assert db.count_molecules() == 0


def test_cached_instance_per_project_root(tmp_path: Path) -> None:
    """DatabaseManager.get caches instances by resolved absolute path."""
    db1 = DatabaseManager.get(str(tmp_path))
    db2 = DatabaseManager.get(str(tmp_path))
    assert db1 is db2


def test_record_ingest_event_writes_log_row_and_updates_queue(tmp_path: Path) -> None:
    """record_ingest_event persists a log row with all fields and updates the
    matching ingest_queue row."""
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
        status="processing",
        update_stage="extract",
    )

    log_rows = db.execute(
        "SELECT doc_id, stage, level, message, task_id, data FROM ingest_logs WHERE task_id=?",
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
    assert queue_row["status"] == "processing"
    assert queue_row["stage"] == "extract"


def test_record_ingest_event_swallows_exception(tmp_path: Path) -> None:
    """A failure while writing the log should not raise to the caller."""
    db = DatabaseManager(str(tmp_path))

    # Close the underlying DB file by deleting the parent directory so the
    # next write fails without needing to mock internals.
    db.initialize()
    db._kb_path.unlink()

    record_ingest_event(
        db,
        task_id="task-3",
        doc_id="doc-3",
        stage="persist",
        level="error",
        message="Disk full",
        data={"error_code": "PERSIST_FAILED"},
    )

    # No exception raised; function returns None on failure.
    assert True


def test_kb_and_mol_conn_share_connection_in_unified_layout(tmp_path: Path) -> None:
    """In the unified single-DB layout, kb_conn and mol_conn use one connection."""
    db = DatabaseManager(str(tmp_path))
    db.initialize()
    with db.kb_conn() as kb, db.mol_conn() as mol:
        assert kb is mol


def test_transaction_uses_shared_connection_in_unified_layout(tmp_path: Path) -> None:
    """transaction() reuses the shared connection when kb_path == mol_path."""
    db = DatabaseManager(str(tmp_path))
    db.initialize()
    with db.transaction() as (kb, mol):
        assert kb is mol


@pytest.mark.asyncio
async def test_kb_conn_with_asyncio_to_thread(tmp_path: Path) -> None:
    """kb_conn works when called via asyncio.to_thread from the event loop."""
    import asyncio

    db = DatabaseManager(str(tmp_path))
    db.initialize()

    def _fetch() -> int:
        with db.kb_conn() as conn:
            return conn.execute("SELECT COUNT(*) FROM ingest_queue").fetchone()[0]

    # Pre-warm a connection on the main thread.
    with db.kb_conn():
        pass

    count = await asyncio.to_thread(_fetch)
    assert count == 0


@pytest.mark.asyncio
async def test_concurrent_asyncio_to_thread_db_access(tmp_path: Path) -> None:
    """Concurrent pipeline_queue-style calls must not raise cross-thread errors.

    ``pipeline_queue`` fetches ``DatabaseManager`` on the event-loop thread
    and then runs queries via ``asyncio.to_thread``; this verifies that
    pattern under concurrency.
    """
    import asyncio

    db = DatabaseManager(str(tmp_path))
    db.initialize()

    # Pre-warm a connection on the main thread, mirroring real usage.
    with db.kb_conn() as conn:
        conn.execute("SELECT COUNT(*) FROM ingest_queue")

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


def test_delete_molecule_records_chunked_preselect(tmp_path: Path) -> None:
    """delete_molecule_records with more than 999 ids must not raise.

    Regression test: the pre-check SELECT used to bind all ids in a single
    ``IN (?, ...)`` clause, tripping SQLite's SQLITE_MAX_VARIABLE_NUMBER
    (999) with an ``OperationalError``. The SELECT is now chunked like the
    DELETEs, so arbitrarily large id lists work.
    """
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


def test_delete_molecule_records_cleans_unanchored_alias_evidence(
    tmp_path: Path,
) -> None:
    """Evidence sharing a deleted molecule's canonical smiles but anchored to no
    mol_id is removed, even though the molecules query is now empty."""
    db = DatabaseManager(str(tmp_path))
    db.initialize()

    with db.mol_conn() as conn:
        conn.execute(
            "INSERT INTO molecules (mol_id, smiles, canonical_smiles) VALUES (?, ?, ?)",
            ("dead", "CCO", "CCO"),
        )
        conn.execute(
            "INSERT INTO evidence (canonical_smiles, doc_id, kind) "
            "VALUES ('CCO', 'doc-1', 'figure')"
        )
        deleted = DatabaseManager.delete_molecule_records(conn, ["dead"])

    assert deleted == 1
    with db.mol_conn() as conn:
        assert (
            conn.execute(
                "SELECT 1 FROM evidence WHERE canonical_smiles = 'CCO'"
            ).fetchone()
            is None
        )


def test_delete_molecule_records_keeps_evidence_owned_by_surviving_duplicate(
    tmp_path: Path,
) -> None:
    """When a duplicate molecule with the same canonical smiles survives, an
    evidence row anchored to it must not be removed by the alias cleanup."""
    db = DatabaseManager(str(tmp_path))
    db.initialize()

    with db.mol_conn() as conn:
        conn.execute(
            "INSERT INTO molecules (mol_id, smiles, canonical_smiles) "
            "VALUES (?, ?, ?), (?, ?, ?)",
            ("dead", "CCO", "CCO", "twin", "CCO", "CCO"),
        )
        conn.execute(
            "INSERT INTO evidence (canonical_smiles, mol_id, doc_id, kind) "
            "VALUES ('CCO', 'twin', 'doc-2', 'detected')"
        )
        deleted = DatabaseManager.delete_molecule_records(conn, ["dead"])

    assert deleted == 1
    with db.mol_conn() as conn:
        assert (
            conn.execute("SELECT 1 FROM evidence WHERE mol_id = 'twin'").fetchone()
            is not None
        )


def test_delete_document_molecule_data_cleans_markush_decisions_audit_rows(
    tmp_path: Path,
) -> None:
    """Deleting a document's review candidates also removes the audit rows in
    markush_decisions keyed on those candidate ids."""
    db = DatabaseManager(str(tmp_path))
    db.initialize()

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
