"""Unit tests for the pipeline router's SSE endpoint."""

from __future__ import annotations

import asyncio
import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from mbforge.adapters.persistence.sqlite.database import DatabaseManager


@pytest.fixture
def client(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> TestClient:
    """Create a TestClient for the FastAPI app.

    Models are loaded lazily; no startup pre-warming to patch.
    Global config is pointed at a temp library so path validation succeeds.
    The durable queue worker is stubbed so enqueueing never runs a real
    pipeline during router tests.
    """
    import mbforge.adapters.runtime.environment as _environment
    from mbforge.adapters.runtime.ingest import worker
    from mbforge.foundation import config

    monkeypatch.setattr(worker, "ensure_queue_worker", lambda _root: True)

    _orig_check_environment = getattr(_environment, "check_environment", lambda: None)

    def _noop() -> None:
        return None

    _environment.check_environment = _noop

    lib = tmp_path / "library"
    lib.mkdir(parents=True, exist_ok=True)
    original_load = config.load_global_config

    class _PatchedLoad:
        def __call__(self):
            cfg = original_load()
            cfg.library_root = str(lib)
            return cfg

        def cache_clear(self):
            original_load.cache_clear()

    monkeypatch.setattr(config, "load_global_config", _PatchedLoad())

    try:
        from mbforge.app import create_app

        app = create_app()
        c = TestClient(app)
        yield c
    finally:
        if "c" in locals():
            c.close()
        _environment.check_environment = _orig_check_environment


def _parse_sse(body: bytes) -> list[dict]:
    """Parse a simple text/event-stream body into payload dicts."""
    events: list[dict] = []
    current: dict[str, str] = {}
    for line in body.decode("utf-8").splitlines():
        if line.startswith("event: "):
            current["event"] = line[len("event: ") :]
        elif line.startswith("data: "):
            current["data"] = line[len("data: ") :]
        elif line == "" and current:
            events.append(json.loads(current["data"]))
            current = {}
    if current:
        events.append(json.loads(current["data"]))
    return events


def test_pipeline_events_stream_returns_log_rows(
    client: TestClient, tmp_path: Path
) -> None:
    """The SSE endpoint yields persisted ingest_logs rows with structured data."""
    root = tmp_path / "library"
    root.mkdir(parents=True, exist_ok=True)
    db = DatabaseManager.get(str(root))
    db.initialize()

    run_id = "run-sse-1"
    with db.kb_conn() as conn:
        conn.execute(
            "INSERT INTO ingest_queue (id, file_path, doc_id, run_id, status) "
            "VALUES (?, ?, ?, ?, ?)",
            ("node-sse-1", str(root / "doc.pdf"), "doc-1", run_id, "pending"),
        )
        conn.execute(
            """
            INSERT INTO ingest_logs
                (doc_id, stage, level, message, ts_ms, run_id, data)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (
                "doc-1",
                "detect",
                "info",
                "Detected 2 molecules",
                1234567890000,
                run_id,
                json.dumps({"molecule_count": 2}),
            ),
        )

    response = client.get(
        f"/api/v1/pipeline/events/{run_id}",
        params={"library_root": str(root)},
    )
    assert response.status_code == 200
    events = _parse_sse(response.content)

    assert len(events) >= 1
    payload = events[0]
    assert payload["stage"] == "detect"
    assert payload["event"] == "info"
    assert payload["message"] == "Detected 2 molecules"
    assert payload["ts_ms"] == 1234567890000
    assert payload["data"] == {"molecule_count": 2}


def test_pipeline_queue_logs_returns_rows_for_doc(
    client: TestClient, tmp_path: Path
) -> None:
    """`POST /queue/logs` must read from ingest_logs, not return an empty stub.

    Regression test for the case where the endpoint shipped as `return []`
    and the queue page showed "暂无日志" even though the runner had
    written rows to ingest_logs.
    """
    import time

    root = tmp_path / "library"
    root.mkdir(parents=True, exist_ok=True)
    db = DatabaseManager.get(str(root))
    db.initialize()
    doc_id = "527916f6-e0d0-4f99-8a45-d9d0fa14f37f"
    task_id = "task-1"
    with db.kb_conn() as conn:
        conn.execute(
            "INSERT INTO ingest_queue (id, file_path, status) VALUES (?, ?, ?)",
            (task_id, str(root / "doc.pdf"), "done"),
        )
        for i, (stage, level, message) in enumerate(
            (
                ("pipeline", "start", "Processing doc.pdf"),
                ("extract", "success", "Extracted 39 pages"),
                ("persist", "success", "Document persisted"),
            )
        ):
            conn.execute(
                """
                INSERT INTO ingest_logs
                    (doc_id, stage, level, message, ts_ms, task_id)
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                (doc_id, stage, level, message, int(time.time() * 1000) + i, task_id),
            )
        # Add a row for a different doc that should NOT show up.
        conn.execute(
            """
            INSERT INTO ingest_logs
                (doc_id, stage, level, message, ts_ms, task_id)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            ("other-doc", "extract", "success", "x", int(time.time() * 1000), "other"),
        )

    resp = client.post(
        "/api/v1/pipeline/queue/logs",
        json={"library_root": str(root), "doc_id": doc_id, "limit": 50},
    )
    assert resp.status_code == 200
    payload = resp.json()
    assert payload["success"] is True
    logs = payload["logs"]
    assert len(logs) == 3
    assert [row["stage"] for row in logs] == ["pipeline", "extract", "persist"]
    assert all(row["doc_id"] == doc_id for row in logs)
    # chronological order
    assert [row["ts_ms"] for row in logs] == sorted(row["ts_ms"] for row in logs)

    # Empty/missing doc_id returns no rows.
    empty = client.post(
        "/api/v1/pipeline/queue/logs",
        json={"library_root": str(root), "doc_id": "", "limit": 50},
    )
    assert empty.status_code == 200
    assert empty.json()["logs"] == []


def test_pipeline_worker_status_reports_queue_snapshot(
    client: TestClient, tmp_path: Path
) -> None:
    """`GET /worker/status` reports real queue counts, not a liveness stub."""
    root = tmp_path / "library"
    root.mkdir(parents=True, exist_ok=True)
    db = DatabaseManager.get(str(root))
    db.initialize()
    with db.kb_conn() as conn:
        for task_id, status in (
            ("pending-task", "pending"),
            ("processing-task", "processing"),
            ("done-task", "done"),
        ):
            conn.execute(
                "INSERT INTO ingest_queue (id, file_path, status) VALUES (?, ?, ?)",
                (task_id, str(root / f"{task_id}.pdf"), status),
            )

    resp = client.get(
        "/api/v1/pipeline/worker/status", params={"library_root": str(root)}
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["total"] == 3
    assert body["backlog"] == 1
    assert body["active"] == 1
    assert body["by_status"] == {"pending": 1, "processing": 1, "done": 1}
    assert body["status"] in {"online", "offline"}
    assert isinstance(body["ts"], int)


def test_pipeline_queue_includes_checkpoint_stage_statuses(
    client: TestClient, tmp_path: Path
) -> None:
    """Queue consumers receive the real fork statuses from the run checkpoint."""
    from mbforge.application.pipeline.artifacts.staging import staging_dir
    from mbforge.application.pipeline.run.checkpoint import (
        ensure_run_checkpoint,
        save_stage_summary,
    )

    root = tmp_path / "library"
    root.mkdir(parents=True, exist_ok=True)
    db = DatabaseManager.get(str(root))
    db.initialize()
    doc_id = "doc-with-checkpoint"
    staging = staging_dir(root, doc_id)
    ensure_run_checkpoint(staging)
    save_stage_summary(staging, "extract", status="success")
    save_stage_summary(staging, "detection", status="running")
    with db.kb_conn() as conn:
        conn.execute(
            "INSERT INTO ingest_queue (id, file_path, doc_id, status) "
            "VALUES (?, ?, ?, ?)",
            ("task-checkpoint", str(root / "doc.pdf"), doc_id, "processing"),
        )

    response = client.post("/api/v1/pipeline/queue", json={"library_root": str(root)})

    assert response.status_code == 200
    assert response.json()["tasks"][0]["stage_statuses"] == {
        "extract": "success",
        "detection": "running",
    }


def test_pipeline_bulk_queue_actions_update_only_eligible_tasks(
    client: TestClient, tmp_path: Path
) -> None:
    root = tmp_path / "library"
    root.mkdir(parents=True, exist_ok=True)
    db = DatabaseManager.get(str(root))
    db.initialize()
    with db.kb_conn() as conn:
        for node_id, run_id, status in (
            ("pending-node", "run-pending", "pending"),
            ("failed-node", "run-failed", "failed"),
            ("done-node", "run-done", "done"),
        ):
            conn.execute(
                "INSERT INTO ingest_queue (id, file_path, doc_id, run_id, status) "
                "VALUES (?, ?, ?, ?, ?)",
                (node_id, str(root / f"{node_id}.pdf"), node_id, run_id, status),
            )

    cancel = client.post(
        "/api/v1/pipeline/queue/batch/cancel",
        json={"library_root": str(root), "run_ids": ["run-pending", "run-done"]},
    )
    assert cancel.status_code == 200
    assert cancel.json()["updated"] == 1
    assert cancel.json()["skipped"] == 1

    retry = client.post(
        "/api/v1/pipeline/queue/batch/retry",
        json={"library_root": str(root), "run_ids": ["run-failed", "run-done"]},
    )
    assert retry.status_code == 200
    assert retry.json()["updated"] == 1
    assert retry.json()["skipped"] == 1

    cleanup = client.post(
        "/api/v1/pipeline/queue/cleanup",
        json={"library_root": str(root)},
    )
    assert cleanup.status_code == 200
    assert cleanup.json()["cleaned"] == 1


def _capture_to_thread(monkeypatch: pytest.MonkeyPatch):
    """Patch asyncio.to_thread so callers can inspect what was offloaded."""
    calls: list[tuple[object, tuple, dict]] = []

    async def _fake_to_thread(func, *args, **kwargs):
        calls.append((func, args, kwargs))
        return []

    monkeypatch.setattr(asyncio, "to_thread", _fake_to_thread)
    return calls


def _patch_config_root(monkeypatch: pytest.MonkeyPatch, root: str) -> None:
    """Point load_global_config at ``root`` so path validation succeeds."""
    from mbforge.foundation import config

    original_load = config.load_global_config

    def _patched_load():
        cfg = original_load()
        cfg.library_root = root
        return cfg

    monkeypatch.setattr(config, "load_global_config", _patched_load)


def test_pipeline_queue_offloads_sqlite_to_thread(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The /queue route must not run SQLite queries on the event loop."""
    import asyncio

    from mbforge.application.dto.pipeline import PipelineQueueRequest
    from mbforge.interfaces.http.pipeline.pipeline import pipeline_queue

    calls = _capture_to_thread(monkeypatch)

    root = str(tmp_path / "library")
    Path(root).mkdir(parents=True, exist_ok=True)
    _patch_config_root(monkeypatch, root)
    db = DatabaseManager.get(root)
    db.initialize()

    result = asyncio.run(pipeline_queue(PipelineQueueRequest(library_root=root)))

    assert result.success is True
    assert result.tasks == []
    assert len(calls) == 1


def test_pipeline_queue_stats_offloads_sqlite_to_thread(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The /queue/stats route must not run SQLite queries on the event loop."""
    import asyncio

    from mbforge.application.dto.pipeline import PipelineQueueRequest
    from mbforge.interfaces.http.pipeline.pipeline import pipeline_queue_stats

    calls = _capture_to_thread(monkeypatch)

    root = str(tmp_path / "library")
    Path(root).mkdir(parents=True, exist_ok=True)
    _patch_config_root(monkeypatch, root)
    db = DatabaseManager.get(root)
    db.initialize()

    result = asyncio.run(pipeline_queue_stats(PipelineQueueRequest(library_root=root)))

    assert result.success is True
    assert result.stats == {}
    assert len(calls) == 1


def test_pipeline_enqueue_unresolved_offloads_scan_and_sqlite(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The enqueue_unresolved action offloads file scanning and DB work."""
    import asyncio
    from unittest.mock import patch

    from mbforge.application.dto.pipeline import PipelineEnqueueRequest
    from mbforge.interfaces.http.pipeline.pipeline import pipeline_enqueue

    calls: list[tuple[object, tuple, dict]] = []

    async def _fake_to_thread(func, *args, **kwargs):
        calls.append((func, args, kwargs))
        # The second to_thread call runs the DB enqueue batch and should return an int.
        if func.__name__ == "_enqueue_all":
            return 0
        return []

    monkeypatch.setattr(asyncio, "to_thread", _fake_to_thread)

    root = str(tmp_path / "library")
    Path(root).mkdir(parents=True, exist_ok=True)
    _patch_config_root(monkeypatch, root)
    db = DatabaseManager.get(root)
    db.initialize()

    with patch(
        "mbforge.adapters.runtime.ingest.worker.ensure_queue_worker", return_value=True
    ):
        result = asyncio.run(
            pipeline_enqueue(
                PipelineEnqueueRequest(library_root=root, action="enqueue_unresolved")
            )
        )

    assert result.success is True
    assert result.enqueued == 0
    # First to_thread call is scan_library_files, second is the DB enqueue batch.
    assert len(calls) == 2
