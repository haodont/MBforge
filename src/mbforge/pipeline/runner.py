"""Pipeline runner — orchestrates document processing via modular stages.

Refactored from a monolithic ``run_pipeline`` into a thin facade over
``pipeline/run/*`` collaborators (see docs/plan-runner-split.md):

1. ``RunContext`` — per-invocation orchestration state and result assembly.
2. ``PipelineEventSink`` — event/logging/``ingest_queue`` observability.
3. ``InitialForkRunner`` — the fixed parallel Extract ∥ Detection fork + join.
4. ``SequentialStageRunner`` — resume/skip-aware one-stage execution loop.
5. ``Finalizer`` — run completion and failure/cancellation cleanup.

Stage flow: Extract ∥ Detection → Markdown → Patent. The current pipeline ends
after Patent; downstream linking and persistence remain separate work and are
not invoked here.

Public symbols (``run_pipeline``, ``cancel_task``, ``is_task_cancelled``,
``release_task``, ``PipelineResult``, ``STAGES``, ``_effective_stages``) are
kept here unchanged for the queue worker, routers and tests.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from ..core.stage import ORDER as STAGE_REGISTRY_ORDER
from ..core.stage import REGISTRY as STAGE_REGISTRY
from ..storage.layout import canonicalize_library_root
from ..utils.config import load_global_config
from ..utils.logger import get_logger
from . import stage_checkpoint
from . import stages as _stage_modules  # noqa: F401  (triggers stage registration)
from .cancellation import PIPELINE_CANCELLED, TaskCancelledError, default_registry
from .composition import effective_stage_names
from .run.events import PipelineEventSink
from .run.finalize import Finalizer
from .run.initial_fork import InitialForkRunner
from .run.models import PipelineResult, ProgressCallback
from .run.sequential import SequentialStageRunner
from .run.state import RunContext
from .stage_artifacts import hydrate_context_from_artifacts
from .stages.base import StageExecutor

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
    task_id: str | None = None,
    on_progress: ProgressCallback | None = None,
    resume_from_stage: str | None = None,
) -> PipelineResult:
    """Run the next pending stage of the document processing pipeline.

    Extract and Detection run as one fixed initial fork. Each later invocation
    executes one sequential stage, writes a checkpoint summary, and returns.
    The worker reads :attr:`PipelineResult.next_stage` to decide whether to
    re-queue the task for the next stage or mark it done.

    Args:
        pdf_path: Path to the PDF file
        library_root: Library data directory
        doc_id: Document ID (auto-generated from filename if empty)
        task_id: Optional queue task ID for event and cancellation tracking
        on_progress: Optional pipeline event callback
        resume_from_stage: The last *completed* stage name (from the queue
            row's ``stage`` column).  When set, earlier stages are skipped
            and only the next pending stage runs.  ``None`` starts from
            the beginning.

    Returns:
        PipelineResult with processing statistics plus ``current_stage``
        and ``next_stage`` for the worker's re-queue decision.

    Raises:
        ValueError: If ``library_root`` is empty or missing.
    """
    if not library_root:
        raise ValueError("run_pipeline requires a non-empty `library_root`")
    root = canonicalize_library_root(library_root)
    if not doc_id:
        doc_id = Path(pdf_path).stem

    run = RunContext.start(
        Path(pdf_path),
        root,
        doc_id,
        task_id=task_id,
        ocr_config=_current_ocr_config(),
        resume_from_stage=resume_from_stage,
    )
    sink = PipelineEventSink(on_progress, task_id, root, doc_id)

    try:
        # Per-invocation effective stage list from the composition root.
        active_stages: list[Any] = _effective_stages()
        # Validate all effective stages satisfy the StageExecutor protocol.
        for stage in active_stages:
            if not isinstance(stage, StageExecutor):
                raise TypeError(
                    f"{type(stage).__name__} does not satisfy StageExecutor protocol"
                )

        sink.emit(
            "start",
            f"Processing {Path(pdf_path).name}"
            + (f" (resuming after {resume_from_stage})" if resume_from_stage else ""),
        )

        # Cancellation is checked for every invocation before any stage runs.
        if is_task_cancelled(task_id):
            sink.emit(
                "cancelled",
                "Pipeline cancelled by user",
                stage="pipeline",
                error_code=PIPELINE_CANCELLED,
            )
            raise TaskCancelledError(task_id)

        initial_fork = InitialForkRunner(run, sink, active_stages)
        if initial_fork.should_run():
            # The only parallel section is the fixed initial fork. Keeping this
            # explicit avoids turning the runner into a generic workflow engine.
            return initial_fork.run_fork()

        # Later invocations hydrate from the SQL-backed joined artifact; this
        # also makes a missing source-evidence row a hard pipeline error.
        hydrate_context_from_artifacts(run.ctx)

        completed_stage = SequentialStageRunner(run, sink, active_stages).run_one()
        next_stage = stage_checkpoint.next_stage(completed_stage)

        Finalizer(run).complete(sink, completed_stage, next_stage)
        return run.as_public_result(
            completed_stage=completed_stage, next_stage=next_stage
        )
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
