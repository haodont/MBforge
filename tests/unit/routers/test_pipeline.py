"""Unit tests for the pipeline router's SSE endpoint."""

from __future__ import annotations

import asyncio
import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from mbforge.db.sqlite.database import DatabaseManager


@pytest.fixture
def client(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    patch_config_root,
) -> TestClient:
    """Create a TestClient for the FastAPI app.

    Models are loaded lazily; no startup pre-warming to patch.
    Global config is pointed at a temp library so path validation succeeds.
    The durable queue worker is stubbed so enqueueing never runs a real
    pipeline during router tests.
    """
    from mbforge.server.ingest import worker

    monkeypatch.setattr(worker, "ensure_queue_worker", lambda _root: True)

    lib = tmp_path / "library"
    lib.mkdir(parents=True, exist_ok=True)
    patch_config_root(lib)

    try:
        from mbforge.server.app import create_app

        app = create_app()
        c = TestClient(app)
        yield c
    finally:
        if "c" in locals():
            c.close()


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
                ("patent", "success", "Patent facts published"),
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
    assert [row["stage"] for row in logs] == ["pipeline", "extract", "patent"]
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


def test_pipeline_worker_status_reports_why_claiming_is_paused(
    client: TestClient, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """`GET /worker/status` carries the model gate so the UI can explain the pause."""
    from mbforge.service.use_cases.pipeline import model_gate as gate_module

    root = tmp_path / "library"
    root.mkdir(parents=True, exist_ok=True)
    DatabaseManager.get(str(root)).initialize()

    monkeypatch.setattr(
        gate_module,
        "evaluate_model_gate",
        lambda: gate_module.ModelGateResult(
            ready=False,
            required=("moldet",),
            missing=(
                gate_module.BlockingModel(
                    id="moldet", name="MolDetv2-FT", status="not_found"
                ),
            ),
        ),
    )

    resp = client.get(
        "/api/v1/pipeline/worker/status", params={"library_root": str(root)}
    )

    assert resp.status_code == 200
    assert resp.json()["model_gate"] == {
        "ready": False,
        "required": ["moldet"],
        "missing": [
            {
                "id": "moldet",
                "name": "MolDetv2-FT",
                "status": "not_found",
                "error": None,
            }
        ],
        "reason": "missing models: moldet (not_found)",
    }


def test_pipeline_worker_status_survives_a_failing_gate_probe(
    client: TestClient, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A broken gate probe degrades to null instead of failing the status call."""
    from mbforge.service.use_cases.pipeline import model_gate as gate_module

    root = tmp_path / "library"
    root.mkdir(parents=True, exist_ok=True)
    DatabaseManager.get(str(root)).initialize()

    def _boom() -> None:
        raise RuntimeError("probe exploded")

    monkeypatch.setattr(gate_module, "evaluate_model_gate", _boom)

    resp = client.get(
        "/api/v1/pipeline/worker/status", params={"library_root": str(root)}
    )

    assert resp.status_code == 200
    assert resp.json()["model_gate"] is None


def test_pipeline_queue_includes_checkpoint_stage_statuses(
    client: TestClient, tmp_path: Path
) -> None:
    """Queue consumers receive the real fork statuses from the run checkpoint."""
    from mbforge.service.pipeline.artifacts.staging import staging_dir
    from mbforge.service.pipeline.run.checkpoint import (
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
    save_stage_summary(staging, "markdown", status="running")
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
        "markdown": "running",
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


def test_pipeline_delete_task_resets_document_and_keeps_source(
    client: TestClient, tmp_path: Path
) -> None:
    """Deleting a queue task discards its outputs but keeps the source PDF."""
    from mbforge.db.sqlite.database import DatabaseManager
    from mbforge.foundation.layout import LibraryLayout
    from mbforge.service.use_cases.documents.library import LibraryStore

    root = tmp_path / "library"
    store = LibraryStore.get(str(root))
    src = tmp_path / "source.pdf"
    src.write_bytes(b"%PDF-1.4 fake pdf")
    doc = store.add_document(src)
    layout = LibraryLayout(str(root))
    store.update_document_status(doc.doc_id, "ready")
    layout.document_md(doc.doc_id).write_text("# processed")

    # Seed a finished run for the document, independent of auto-enqueue.
    db = DatabaseManager.get(str(root))
    with db.kb_conn() as conn:
        conn.execute(
            "INSERT INTO ingest_queue (id, file_path, doc_id, stage, run_id, status) "
            "VALUES ('node-1', ?, ?, 'extract', 'run-delete', 'done')",
            (str(src), doc.doc_id),
        )

    resp = client.post(
        "/api/v1/pipeline/queue/run-delete/delete",
        json={"library_root": str(root)},
    )
    assert resp.status_code == 200
    assert resp.json()["updated"] == 1

    reloaded = store.get_document(doc.doc_id)
    assert reloaded is not None
    assert reloaded.status == "pending"
    assert not layout.document_md(doc.doc_id).exists()
    assert (layout.storage_dir(doc.doc_id) / doc.file_name).is_file()


def test_pipeline_enqueue_reuses_inflight_run_and_force_supersedes(
    client: TestClient, tmp_path: Path
) -> None:
    """Re-enqueueing an in-flight document reuses its run; force starts fresh."""
    from mbforge.db.sqlite.database import DatabaseManager
    from mbforge.service.use_cases.documents.library import LibraryStore

    root = tmp_path / "library"
    store = LibraryStore.get(str(root))
    src = tmp_path / "doc.pdf"
    src.write_bytes(b"%PDF-1.4 fake pdf")
    doc = store.add_document(src)

    def _enqueue(force: bool) -> str:
        resp = client.post(
            "/api/v1/pipeline/enqueue",
            json={"library_root": str(root), "doc_id": doc.doc_id, "force": force},
        )
        assert resp.status_code == 200
        return resp.json()["run_id"]

    first = _enqueue(False)
    # Idempotent while the run is in flight: the same run id is returned.
    assert _enqueue(False) == first

    # Forced re-enqueue supersedes it with a brand-new run.
    forced = _enqueue(True)
    assert forced and forced != first

    db = DatabaseManager.get(str(root))
    with db.kb_conn() as conn:
        runs = [
            row["run_id"]
            for row in conn.execute(
                "SELECT DISTINCT run_id FROM ingest_queue WHERE doc_id = ?",
                (doc.doc_id,),
            ).fetchall()
        ]
    # Only the new run survives; the superseded one was cleaned up.
    assert forced in runs
    assert first not in runs


def _capture_to_thread(monkeypatch: pytest.MonkeyPatch):
    """Patch asyncio.to_thread so callers can inspect what was offloaded."""
    calls: list[tuple[object, tuple, dict]] = []

    async def _fake_to_thread(func, *args, **kwargs):
        calls.append((func, args, kwargs))
        return []

    monkeypatch.setattr(asyncio, "to_thread", _fake_to_thread)
    return calls


def test_pipeline_queue_offloads_sqlite_to_thread(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, patch_config_root
) -> None:
    """The /queue route must not run SQLite queries on the event loop."""
    import asyncio

    from mbforge.api.http.pipeline.pipeline import pipeline_queue
    from mbforge.service.dto.pipeline import PipelineQueueRequest

    calls = _capture_to_thread(monkeypatch)

    root = str(tmp_path / "library")
    Path(root).mkdir(parents=True, exist_ok=True)
    patch_config_root(root)
    db = DatabaseManager.get(root)
    db.initialize()

    result = asyncio.run(pipeline_queue(PipelineQueueRequest(library_root=root)))

    assert result.success is True
    assert result.tasks == []
    assert len(calls) == 1


def test_pipeline_queue_stats_offloads_sqlite_to_thread(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, patch_config_root
) -> None:
    """The /queue/stats route must not run SQLite queries on the event loop."""
    import asyncio

    from mbforge.api.http.pipeline.pipeline import pipeline_queue_stats
    from mbforge.service.dto.pipeline import PipelineQueueRequest

    calls = _capture_to_thread(monkeypatch)

    root = str(tmp_path / "library")
    Path(root).mkdir(parents=True, exist_ok=True)
    patch_config_root(root)
    db = DatabaseManager.get(root)
    db.initialize()

    result = asyncio.run(pipeline_queue_stats(PipelineQueueRequest(library_root=root)))

    assert result.success is True
    assert result.stats == {}
    assert len(calls) == 1


def test_pipeline_enqueue_unresolved_offloads_scan_and_sqlite(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, patch_config_root
) -> None:
    """The enqueue_unresolved action offloads file scanning and DB work."""
    import asyncio
    from unittest.mock import patch

    from mbforge.api.http.pipeline.pipeline import pipeline_enqueue
    from mbforge.service.dto.pipeline import PipelineEnqueueRequest

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
    patch_config_root(root)
    db = DatabaseManager.get(root)
    db.initialize()

    with patch("mbforge.server.ingest.worker.ensure_queue_worker", return_value=True):
        result = asyncio.run(
            pipeline_enqueue(
                PipelineEnqueueRequest(library_root=root, action="enqueue_unresolved")
            )
        )

    assert result.success is True
    assert result.enqueued == 0
    # First to_thread call is scan_library_files, second is the DB enqueue batch.
    assert len(calls) == 2
