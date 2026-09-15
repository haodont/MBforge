"""Unit tests for the durable per-library queue worker.

Covers atomic row claiming (multiple workers can never double-run a task),
orphan reclamation after a crash/restart, the single-owner library lock, and
the claim→execute lifecycle driven by ``ensure_queue_worker``.
"""

from __future__ import annotations

import asyncio
from pathlib import Path

from mbforge.infra.ingest import worker
from mbforge.infra.process.filelock import (
    LockMeta,
    queue_lock_path,
    try_lock_file,
    unlock_file,
)
from mbforge.storage.sqlite.database import DatabaseManager


def _library(tmp_path: Path, name: str = "library") -> str:
    root = tmp_path / name
    root.mkdir(parents=True, exist_ok=True)
    return str(root)


def _seed(db: DatabaseManager, rows: list[dict]) -> None:
    with db.kb_conn() as conn:
        for row in rows:
            conn.execute(
                "INSERT INTO ingest_queue (id, file_path, status, claimed_by, heartbeat_ts) "
                "VALUES (?, ?, ?, ?, ?)",
                (
                    row.get("id"),
                    row.get("file_path") or f"{row['id']}.pdf",
                    row.get("status", "pending"),
                    row.get("claimed_by"),
                    row.get("heartbeat_ts"),
                ),
            )


def _queue_row(db: DatabaseManager, task_id: str) -> dict:
    with db.kb_conn() as conn:
        row = conn.execute(
            "SELECT * FROM ingest_queue WHERE id = ?", (task_id,)
        ).fetchone()
    return dict(row)


def test_claim_rows_atomically_guards_against_double_run(tmp_path: Path) -> None:
    """Two workers claiming the same rows never get the same task id."""
    root = _library(tmp_path)
    db = DatabaseManager.get(root)
    db.initialize()
    _seed(db, [{"id": "t1"}, {"id": "t2"}, {"id": "t3"}])

    first = worker._claim_rows(root, "worker-a", 2)
    assert {row["id"] for row in first} == {"t1", "t2"}

    # worker-b can only claim the untouched row; worker-a's claims are gone.
    second = worker._claim_rows(root, "worker-b", 8)
    assert [row["id"] for row in second] == ["t3"]

    rest = worker._claim_rows(root, "worker-a", 8)
    assert rest == []

    for claimed in first + second:
        row = _queue_row(db, claimed["id"])
        assert row["status"] == "processing"
        assert row["claimed_by"] is not None
        assert row["heartbeat_ts"] is not None


def test_reclaim_orphans_resets_stale_processing_rows(tmp_path: Path) -> None:
    """Rows orphaned by a dead worker return to ``pending`` and are claimable."""
    root = _library(tmp_path)
    db = DatabaseManager.get(root)
    db.initialize()
    _seed(
        db,
        [
            {
                "id": "stale",
                "status": "processing",
                "claimed_by": "dead-host:1:aaaa",
                "heartbeat_ts": "2024-01-01 00:00:00",
            },
            {
                "id": "fresh",
                "status": "processing",
                "claimed_by": "live-host:2:bbbb",
                "heartbeat_ts": "2099-01-01 00:00:00",
            },
            {"id": "pending", "status": "pending"},
        ],
    )

    reclaimed = worker._reclaim_orphans(root)
    assert reclaimed == 1

    stale = _queue_row(db, "stale")
    assert stale["status"] == "pending"
    assert stale["claimed_by"] is None
    assert stale["heartbeat_ts"] is None

    fresh = _queue_row(db, "fresh")
    assert fresh["status"] == "processing"

    # The reclaimed row is immediately claimable again (restart resume).
    claimed = worker._claim_rows(root, "worker-c", 8)
    assert "stale" in {row["id"] for row in claimed}


def _stage_status(db: DatabaseManager, stage: str) -> str:
    with db.kb_conn() as conn:
        row = conn.execute(
            "SELECT status FROM ingest_queue "
            "WHERE doc_id = 'dag-doc' AND run_id = 'run-1' AND stage = ?",
            (stage,),
        ).fetchone()
    return row["status"]


def _node_id(db: DatabaseManager, stage: str) -> str:
    with db.kb_conn() as conn:
        row = conn.execute(
            "SELECT id FROM ingest_queue "
            "WHERE doc_id = 'dag-doc' AND run_id = 'run-1' AND stage = ?",
            (stage,),
        ).fetchone()
    return row["id"]


def _seed_dag(tmp_path: Path) -> tuple[str, DatabaseManager]:
    from mbforge.infra.ingest import queue

    root = _library(tmp_path)
    db = DatabaseManager.get(root)
    db.initialize()
    queue.insert_dag(root, file_path="doc.pdf", doc_id="dag-doc", run_id="run-1")
    return root, db


def test_advance_dependents_promotes_join_only_once(tmp_path: Path) -> None:
    """Join turns pending only after both branches are done, and only once."""
    from mbforge.infra.ingest import queue

    root, db = _seed_dag(tmp_path)

    assert _stage_status(db, "extract") == "pending"
    assert _stage_status(db, "detection") == "pending"
    assert _stage_status(db, "join") == "blocked"

    worker._claim_rows(root, "w", 8)

    queue.set_node_status(root, _node_id(db, "extract"), "done")
    assert (
        queue.advance_dependents(
            root, doc_id="dag-doc", run_id="run-1", completed_stage="extract"
        )
        == []
    )
    assert _stage_status(db, "join") == "blocked"

    queue.set_node_status(root, _node_id(db, "detection"), "done")
    assert queue.advance_dependents(
        root, doc_id="dag-doc", run_id="run-1", completed_stage="detection"
    ) == ["join"]
    assert _stage_status(db, "join") == "pending"

    # Idempotent: a second completion of the same node never re-flips join.
    assert (
        queue.advance_dependents(
            root, doc_id="dag-doc", run_id="run-1", completed_stage="detection"
        )
        == []
    )


def test_node_failure_cascades_and_reset_reopens_dependents(tmp_path: Path) -> None:
    """A failed branch cascades downstream; retrying it re-blocks them."""
    from mbforge.infra.ingest import queue

    root, db = _seed_dag(tmp_path)
    worker._claim_rows(root, "w", 8)
    extract_id = _node_id(db, "extract")

    queue.set_node_status(root, extract_id, "failed", "boom")
    cascaded = queue.fail_cascade(
        root, doc_id="dag-doc", run_id="run-1", failed_stage="extract", error="boom"
    )
    assert set(cascaded) == {"join", "markdown", "patent"}
    for stage in ("join", "markdown", "patent"):
        assert _stage_status(db, stage) == "failed"

    assert queue.reset_node(root, extract_id) is True
    assert _stage_status(db, "extract") == "pending"
    assert _stage_status(db, "join") == "blocked"


def test_startup_reclaims_terminal_claims(tmp_path: Path) -> None:
    """A restarted worker clears claims left on cancelled terminal rows."""
    root = _library(tmp_path)
    db = DatabaseManager.get(root)
    db.initialize()
    _seed(
        db,
        [
            {
                "id": "cancelled-orphan",
                "status": "cancelled",
                "claimed_by": "dead-worker",
                "heartbeat_ts": "2024-01-01 00:00:00",
            }
        ],
    )

    worker._reclaim_all_processing_on_startup(root, "worker-new")

    row = _queue_row(db, "cancelled-orphan")
    assert row["status"] == "cancelled"
    assert row["claimed_by"] is None
    assert row["heartbeat_ts"] is None


def test_library_lock_is_single_owner(tmp_path: Path) -> None:
    """Only one holder acquires ``.mbforge/queue.lock`` at a time."""
    root = _library(tmp_path)
    lock_path = queue_lock_path(root)
    first = try_lock_file(
        lock_path, LockMeta(pid=1, host="test", role="test", started_at=0.0)
    )
    try:
        assert first is not None
        second = try_lock_file(
            lock_path, LockMeta(pid=2, host="test", role="test", started_at=0.0)
        )
        assert second is None
    finally:
        if first is not None:
            unlock_file(first)
    # After release a new holder can acquire it again.
    third = try_lock_file(
        lock_path, LockMeta(pid=3, host="test", role="test", started_at=0.0)
    )
    assert third is not None
    unlock_file(third)


def test_ensure_worker_registers_and_stops(tmp_path: Path, monkeypatch) -> None:
    """ensure_queue_worker registers one task per root and stop removes it."""
    root = _library(tmp_path)

    async def _noop_drain(library_root: str, worker: str) -> None:
        del library_root, worker
        await asyncio.sleep(30)

    async def _scenario() -> None:
        monkeypatch.setattr(worker, "_drain_loop", _noop_drain)
        assert worker.ensure_queue_worker(root) is True
        assert worker.has_worker(root) is True
        # Idempotent: calling again does not spawn a second worker.
        assert worker.ensure_queue_worker(root) is True
        worker.stop_queue_worker(root)
        await asyncio.sleep(0.05)
        assert not worker.has_worker(root)

    try:
        asyncio.run(_scenario())
    finally:
        worker.stop_queue_workers()


def test_worker_claims_and_executes_pending_row(tmp_path: Path, monkeypatch) -> None:
    """End-to-end: a pending row is claimed and executed through the worker."""
    root = _library(tmp_path)
    db = DatabaseManager.get(root)
    db.initialize()
    _seed(db, [{"id": "t1", "file_path": str(Path(root) / "doc.pdf")}])

    executed: list[str] = []

    def _fake_run(
        file_path: str,
        library_root: str,
        doc_id: str,
        task_id: str,
        stage: str | None = None,
        run_id: str | None = None,
    ) -> None:
        del file_path, library_root, doc_id, stage, run_id
        executed.append(task_id)

    monkeypatch.setattr(worker, "_run_pipeline_sync", _fake_run)

    async def _scenario() -> None:
        worker.ensure_queue_worker(root)
        for _ in range(200):
            if executed:
                break
            await asyncio.sleep(0.02)

    try:
        asyncio.run(_scenario())
    finally:
        worker.stop_queue_workers()

    assert executed == ["t1"]
    assert _queue_row(db, "t1")["status"] == "pending"


def test_active_task_ids_tracking(tmp_path: Path, monkeypatch) -> None:
    """``_execute_claimed`` registers and then clears the active id."""
    root = _library(tmp_path)
    db = DatabaseManager.get(root)
    db.initialize()
    _seed(db, [{"id": "t1", "file_path": str(Path(root) / "doc.pdf")}])
    monkeypatch.setattr(worker, "_run_pipeline_sync", lambda *_a: None)

    async def _scenario() -> None:
        row = worker._claim_rows(root, "w", 8)[0]
        worker._active_for(root).add(row["id"])
        assert worker.is_task_active(row["id"])
        await worker._execute_claimed(root, row, "w")
        assert not worker.is_task_active(row["id"])

    try:
        asyncio.run(_scenario())
    finally:
        worker._active_for(root).clear()
        worker.stop_queue_workers()
