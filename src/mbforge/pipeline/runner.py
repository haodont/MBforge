"""Pipeline runner — executes one stage (queue node) per invocation.

Thin facade over ``pipeline/run/*`` collaborators:

1. ``RunContext`` — per-invocation orchestration state and result assembly.
2. ``PipelineEventSink`` — event/logging/``ingest_queue`` observability.
3. ``StageRunner`` — executes the single stage named by the claimed node.
4. ``Finalizer`` — per-node completion and failure/cancellation cleanup.

Stage flow: Extract ∥ Detection → Join → Markdown → Patent. The Extract and
Detection nodes run concurrently because the queue admits both (see
``ingest_stage_deps``), not because the runner forks threads. The current
pipeline ends after Patent; downstream linking and persistence remain separate
work and are not invoked here.

Public symbols (``run_pipeline``, ``cancel_task``, ``is_task_cancelled``,
``release_task``, ``PipelineResult``, ``STAGES``, ``_effective_stages``) are
kept here unchanged for the queue worker, routers and tests.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from mbforge.core.stage import ORDER as STAGE_REGISTRY_ORDER
from mbforge.core.stage import REGISTRY as STAGE_REGISTRY
from mbforge.core.stage import StageExecutor, dependencies
from mbforge.storage.layout import canonicalize_library_root
from mbforge.utils.config import load_global_config
from mbforge.utils.logger import get_logger

from . import stages as _stage_modules  # noqa: F401  (triggers stage registration)
from .artifacts.hydration import hydrate_context_from_artifacts
from .cancellation import PIPELINE_CANCELLED, TaskCancelledError, default_registry
from .composition import effective_stage_names
from .run.context import RunContext
from .run.events import PipelineEventSink
from .run.finalize import Finalizer
from .run.models import PipelineResult, ProgressCallback
from .run.sequential import StageRunner

logger = get_logger("mbforge.pipeline.runner")

__all__ = [
    "TaskCancelledError",
    "cancel_task",
    "is_task_cancelled",
    "release_task",
    "run_pipeline",
]

# Stage registry — execution order derived from core.stage (stages self-
# register via @register; adding a stage needs only the decorator — see
# TODO/services-layer-plan.md §4.2).
#
# ``STAGES`` is the registry list kept for introspection; ``run_pipeline``
# executes the current composition-root list.
#
# Stage instances must remain stateless: all state lives in PipelineContext,
# not on the stage object. Any future instance attribute added here will be
# shared across concurrent pipeline invocations, so prefer constructor-time
# configuration or context fields over per-instance state.
STAGES: list[StageExecutor] = [STAGE_REGISTRY[name] for name in STAGE_REGISTRY_ORDER]


def _effective_stages() -> list[StageExecutor]:
    """Per-invocation effective stage list (composition root).

    Module-level indirection so tests can substitute the executed stage
    list without touching the global registry.
    """
    return [STAGE_REGISTRY[name] for name in effective_stage_names()]


def cancel_task(task_id: str) -> None:
    """Mark a task as cancelled so the runner aborts at the next checkpoint."""
    default_registry.cancel(task_id)


def is_task_cancelled(task_id: str | None) -> bool:
    return default_registry.is_cancelled(task_id)


def release_task(task_id: str | None) -> None:
    """Clear any cancellation mark for ``task_id`` (idempotent).

    Called by :func:`run_pipeline` on every terminal state (success, failure,
    cancelled) and by the queue router when a pending future is cancelled
    before the runner ever starts, so the registry always returns to empty.
    """
    default_registry.unregister(task_id)


def _current_ocr_config() -> dict:
    """Read current ocr config from AppConfig.ocr (settings.json)."""
    try:
        cfg = load_global_config()
        return cfg.ocr.model_dump()
    except Exception as exc:  # noqa: BLE001
        logger.warning("Could not read OCR config: %s", exc)
        return {}


def run_pipeline(
    pdf_path: str,
    library_root: str,
    doc_id: str = "",
    *,
    stage: str | None = None,
    run_id: str | None = None,
    task_id: str | None = None,
    on_progress: ProgressCallback | None = None,
) -> PipelineResult:
    """Execute exactly one stage — the queue node the worker just claimed.

    Args:
        pdf_path: Path to the PDF file
        library_root: Library data directory
        doc_id: Document ID (auto-generated from filename if empty)
        stage: Registered stage name of the claimed node. Required.
        run_id: The ingestion attempt's run ID, shared by every node of that
            attempt (minted once at enqueue). When omitted a fresh one is
            minted — intended only for direct/test callers.
        task_id: Optional queue task ID for event and cancellation tracking
        on_progress: Optional pipeline event callback

    Returns:
        PipelineResult with ``current_stage`` naming the executed node.

    Raises:
        ValueError: If ``library_root`` is empty, or ``stage`` is missing or
            not a registered stage.
    """
    if not library_root:
        raise ValueError("run_pipeline requires a non-empty `library_root`")
    if stage is None or stage not in STAGE_REGISTRY:
        raise ValueError(f"run_pipeline requires a registered stage, got {stage!r}")
    root = canonicalize_library_root(library_root)
    if not doc_id:
        doc_id = Path(pdf_path).stem

    run = RunContext.start(
        Path(pdf_path),
        root,
        doc_id,
        task_id=task_id,
        ocr_config=_current_ocr_config(),
        run_id=run_id,
        stage=stage,
    )
    sink = PipelineEventSink(on_progress, task_id, root, doc_id, run_id=run_id)

    try:
        # Per-invocation effective stage list from the composition root.
        active_stages: list[Any] = _effective_stages()
        # Validate all effective stages satisfy the StageExecutor protocol.
        for candidate in active_stages:
            if not isinstance(candidate, StageExecutor):
                raise TypeError(
                    f"{type(candidate).__name__} does not satisfy StageExecutor protocol"
                )

        sink.emit("start", f"Running {stage} for {Path(pdf_path).name}")

        # Cancellation is checked for every invocation before the stage runs.
        if is_task_cancelled(task_id):
            sink.emit(
                "cancelled",
                "Pipeline cancelled by user",
                stage="pipeline",
                error_code=PIPELINE_CANCELLED,
            )
            raise TaskCancelledError(task_id)

        # Non-root stages read the artifacts/evidence produced upstream; this
        # also makes a missing source-evidence row a hard pipeline error.
        if dependencies(stage):
            hydrate_context_from_artifacts(run.ctx)

        completed_stage = StageRunner(run, sink, active_stages).run_stage(stage)

        Finalizer(run).complete(sink, completed_stage)
        return run.as_public_result(completed_stage=completed_stage)
    except BaseException:
        # Failure or cancellation: clean ONLY this run's uncommitted artifacts
        # when no intermediate stage has succeeded yet. When a previous stage
        # already succeeded (checkpoint exists), leave the staging dir intact
        # for the retry to pick up from.
        Finalizer(run).cleanup_on_failure()
        raise
    finally:
        # Clear cancellation marks and reset the trace on every terminal state.
        run.dispose()
