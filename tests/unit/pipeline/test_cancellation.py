"""Unit tests for cooperative pipeline cancellation (PIPE-11 / PIPE-12).

Covers the encapsulated cancellation registry, terminal-state cleanup in
``run_pipeline`` (success / failure / cancelled), the dedicated
``PIPELINE_CANCELLED`` error code, cooperative checkpoints in long stages,
and the queue router releasing unclaimed tasks cancelled before the runner
starts.
"""

from __future__ import annotations

import asyncio
from pathlib import Path
from unittest.mock import patch

import pytest

from mbforge.pipeline.cancellation import (
    PIPELINE_CANCELLED,
    CancellationRegistry,
    TaskCancelledError,
    default_registry,
)
from mbforge.pipeline.run.context import PipelineContext
from mbforge.pipeline.runner import (
    cancel_task,
    is_task_cancelled,
    release_task,
    run_pipeline,
)
from mbforge.storage.sqlite.database import DatabaseManager


@pytest.fixture(autouse=True)
def _clean_registry():
    yield
    # Tests must not leak cancellation marks into each other.
    default_registry.unregister("__never__")
    for leftover in ("cancel-me", "mid-run", "success-task", "fail-task"):
        default_registry.unregister(leftover)


def _seed_queue_task(
    library_root: Path, task_id: str, run_id: str | None = None
) -> None:
    db = DatabaseManager.get(str(library_root))
    db.initialize()
    with db.kb_conn() as conn:
        conn.execute(
            "INSERT INTO ingest_queue "
            "(id, file_path, doc_id, run_id, status, created_at) "
            "VALUES (?, ?, ?, ?, 'pending', datetime('now'))",
            (task_id, "fake.pdf", "sample_doc", run_id or task_id),
        )


def _queue_status(library_root: Path, task_id: str) -> str:
    db = DatabaseManager.get(str(library_root))
    with db.kb_conn() as conn:
        row = conn.execute(
            "SELECT status FROM ingest_queue WHERE id = ?", (task_id,)
        ).fetchone()
    return row[0]


# ---------------------------------------------------------------------------
# Registry encapsulation (PIPE-11)
# ---------------------------------------------------------------------------


def test_registry_cancel_unregister_is_idempotent() -> None:
    registry = CancellationRegistry()
    registry.cancel("a")
    registry.cancel("a")
    assert registry.is_cancelled("a")
    assert len(registry) == 1
    registry.unregister("a")
    registry.unregister("a")
    assert not registry.is_cancelled("a")
    assert len(registry) == 0
    assert not registry.is_cancelled(None)
    registry.unregister(None)  # must not raise


def test_thousand_dummy_cancellations_drain_to_zero() -> None:
    """Cancelling 1,000 dummy tasks then hitting terminal cleanup empties the registry."""
    task_ids = [f"dummy-{i}" for i in range(1000)]
    for task_id in task_ids:
        cancel_task(task_id)
    assert len(default_registry) == 1000
    # Simulate run_pipeline's finally executing for every terminal state.
    for task_id in task_ids:
        release_task(task_id)
    assert len(default_registry) == 0


# ---------------------------------------------------------------------------
# run_pipeline terminal-state cleanup + PIPELINE_CANCELLED code (PIPE-11)
# ---------------------------------------------------------------------------


def test_cancel_before_start_raises_with_distinct_code(
    sample_pdf: Path, tmp_path: Path
) -> None:
    library_root = tmp_path / "library"
    library_root.mkdir(parents=True, exist_ok=True)
    _seed_queue_task(library_root, "cancel-me")

    events: list[dict] = []

    def _capture(event) -> None:
        events.append({"stage": event.stage, "event": event.event, "data": event.data})

    cancel_task("cancel-me")
    with pytest.raises(TaskCancelledError):
        run_pipeline(
            str(sample_pdf),
            str(library_root),
            doc_id="sample_doc",
            stage="extract",
            task_id="cancel-me",
            on_progress=_capture,
        )

    cancel_events = [
        e
        for e in events
        if e["event"] == "cancelled"
        and e["data"].get("error_code") == PIPELINE_CANCELLED
    ]
    assert cancel_events, f"no PIPELINE_CANCELLED event in {events}"
    # Ordinary failure events must not be emitted for a cancellation.
    assert not [e for e in events if e["event"] == "error"]
    # Terminal-state cleanup released the registry entry.
    assert not is_task_cancelled("cancel-me")
    assert len(default_registry) == 0
    # Queue terminal state stays 'cancelled', not 'failed'.
    assert _queue_status(library_root, "cancel-me") == "cancelled"


def test_registry_cleared_on_success(sample_pdf: Path, tmp_path: Path) -> None:
    library_root = tmp_path / "library"
    library_root.mkdir(parents=True, exist_ok=True)

    with (
        patch(
            "mbforge.pipeline.detection.extraction.extract_molecules_from_pdf",
            return_value=[],
        ),
        patch(
            "mbforge.pipeline.extract.text._ocr_pages",
            return_value=["ocr page 1", "ocr page 2"],
        ),
        patch("mbforge.pipeline.markdown.esmiles_insert.insert_esmiles_blocks"),
    ):
        run_pipeline(
            str(sample_pdf),
            str(library_root),
            doc_id="sample_doc",
            stage="extract",
            task_id="success-task",
        )

    assert not is_task_cancelled("success-task")
    assert len(default_registry) == 0


def test_registry_cleared_on_failure(sample_pdf: Path, tmp_path: Path) -> None:
    library_root = tmp_path / "library"
    library_root.mkdir(parents=True, exist_ok=True)

    # With stage-by-stage execution only the first stage (extract) runs,
    # so the failure must happen during extract.
    with (
        patch(
            "mbforge.pipeline.extract.text.extract_pdf_text",
            side_effect=RuntimeError("disk full"),
        ),
        pytest.raises(RuntimeError, match="disk full"),
    ):
        run_pipeline(
            str(sample_pdf),
            str(library_root),
            doc_id="sample_doc",
            stage="extract",
            task_id="fail-task",
        )

    assert not is_task_cancelled("fail-task")
    assert len(default_registry) == 0


# ---------------------------------------------------------------------------
# Cooperative checkpoints in long stages (PIPE-12)
# ---------------------------------------------------------------------------


def test_extract_text_checkpoint_aborts_native_loop(sample_pdf: Path) -> None:
    from mbforge.pipeline.extract.text import extract_pdf_text

    def _raise() -> None:
        raise TaskCancelledError("t")

    with pytest.raises(TaskCancelledError):
        extract_pdf_text(str(sample_pdf), cancel_check=_raise)


def test_ocr_checkpoint_not_swallowed_by_fallback(tmp_path: Path) -> None:
    """A cancel raised inside the OCR retry path must propagate, not degrade."""
    import pymupdf

    from mbforge.pipeline.extract.text import extract_pdf_text

    blank_pdf = tmp_path / "blank.pdf"
    doc = pymupdf.open()
    doc.new_page(width=612, height=792)  # no text -> OCR fallback path
    doc.save(str(blank_pdf))
    doc.close()

    calls = {"n": 0}

    def _raise_in_ocr() -> None:
        calls["n"] += 1
        if calls["n"] >= 2:  # first OCR checkpoint (native loop passes)
            raise TaskCancelledError("t")

    with pytest.raises(TaskCancelledError):
        extract_pdf_text(str(blank_pdf), ocr_config={}, cancel_check=_raise_in_ocr)


def test_extract_stage_reraises_cancellation(tmp_path: Path, sample_pdf: Path) -> None:
    from mbforge.pipeline.stages.extract_stage import ExtractStage

    ctx = PipelineContext(
        pdf_path=sample_pdf,
        library_root=tmp_path,
        doc_id="doc",
        task_id="t",
        run_id="run-1",
    )
    with (
        patch(
            "mbforge.pipeline.extract.text.extract_pdf_text",
            side_effect=TaskCancelledError("t"),
        ),
        pytest.raises(TaskCancelledError),
    ):
        ExtractStage().execute(ctx)


# ---------------------------------------------------------------------------
# Router: pending (unclaimed) task cancelled before the runner starts releases
# the registry entry
# ---------------------------------------------------------------------------


def test_router_cancel_pending_future_unregisters(tmp_path: Path) -> None:
    from mbforge.models.pipeline import PipelineTaskBatchRequest
    from mbforge.routers.pipeline import pipeline as pipeline_router

    library_root = tmp_path / "library"
    library_root.mkdir(parents=True, exist_ok=True)
    _seed_queue_task(library_root, "pending-task")

    body = PipelineTaskBatchRequest(
        library_root=str(library_root), run_ids=["pending-task"]
    )
    # The task is not executing inside this process: no worker has claimed it.
    from mbforge.infra.ingest import worker

    assert not worker.is_task_active("pending-task")
    with patch(
        "mbforge.routers.pipeline.pipeline.resolve_library_root",
        return_value=library_root,
    ):
        result = asyncio.run(pipeline_router.pipeline_cancel_batch(body))
    assert result.updated == 1
    # Router released the entry because the runner will never start.
    assert not is_task_cancelled("pending-task")
    assert len(default_registry) == 0
    assert _queue_status(library_root, "pending-task") == "cancelled"
    release_task("pending-task")


def test_router_cancel_running_future_leaves_release_to_runner(
    tmp_path: Path,
) -> None:
    from mbforge.models.pipeline import PipelineTaskBatchRequest
    from mbforge.routers.pipeline import pipeline as pipeline_router

    library_root = tmp_path / "library"
    library_root.mkdir(parents=True, exist_ok=True)
    _seed_queue_task(library_root, "running-task")

    # Simulate a task currently executing in this process (claimed by the
    # queue worker); the runner owns the registry cleanup, not the router.
    with (
        patch(
            "mbforge.routers.pipeline.pipeline.resolve_library_root",
            return_value=library_root,
        ),
        patch("mbforge.infra.ingest.worker.is_task_active", return_value=True),
    ):
        body = PipelineTaskBatchRequest(
            library_root=str(library_root), run_ids=["running-task"]
        )
        asyncio.run(pipeline_router.pipeline_cancel_batch(body))
    # Marked cancelled, still registered until the runner's finally runs.
    assert is_task_cancelled("running-task")
    # Simulate the runner reaching a checkpoint and terminating.
    release_task("running-task")
    assert len(default_registry) == 0
    release_task("running-task")


def test_retry_skips_task_until_active_runner_wrapper_exits(tmp_path: Path) -> None:
    """Retry must not revive a terminal row still owned by its runner task."""
    from mbforge.services.pipeline import ingest

    library_root = tmp_path / "library"
    library_root.mkdir(parents=True, exist_ok=True)
    _seed_queue_task(library_root, "retry-race")
    db = DatabaseManager.get(str(library_root))
    with db.kb_conn() as conn:
        conn.execute(
            "UPDATE ingest_queue SET status = 'cancelled' WHERE id = ?",
            ("retry-race",),
        )

    with patch("mbforge.infra.ingest.worker.is_task_active", return_value=True):
        result = asyncio.run(ingest.retry_batch(str(library_root), ["retry-race"]))

    assert result.updated == 0
    assert result.skipped == 1
    assert _queue_status(library_root, "retry-race") == "cancelled"
