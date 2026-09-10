"""Pipeline runner — orchestrates document processing via modular stages.

Refactored from monolithic 747-line function to stage-based architecture.
Each stage is a self-contained executor in pipeline/stages/*.py.

Stages:
1. Extract || Detection: independent PDF evidence producers
2. Markdown: join evidence and write the final document artifact
3. Patent: SQL-backed document fact extraction and publication

The current pipeline ends after Patent. Downstream linking and persistence
remain separate work and are not invoked here.
"""

from __future__ import annotations

import contextlib
import time
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from ..core.stage import ORDER as STAGE_REGISTRY_ORDER
from ..core.stage import REGISTRY as STAGE_REGISTRY
from ..storage.layout import canonicalize_library_root
from ..storage.sqlite.database import DatabaseManager
from ..utils.config import load_global_config
from ..utils.logger import get_logger, reset_trace, set_trace
from . import stage_checkpoint
from . import stages as _stage_modules  # noqa: F401  (triggers stage registration)
from .cancellation import (
    PIPELINE_CANCELLED,
    TaskCancelledError,
    default_registry,
)
from .composition import effective_stage_names
from .context import PipelineContext
from .run_artifacts import cleanup_staging, staging_dir
from .stage_artifacts import hydrate_context_from_artifacts
from .stage_result import StageResult
from .stages.base import StageExecutor

logger = get_logger("mbforge.pipeline.runner")

__all__ = [
    "TaskCancelledError",
    "cancel_task",
    "is_task_cancelled",
    "release_task",
    "run_pipeline",
]


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


def _reap_branch_run(
    staging_dir: Path,
    library_root: str | Path,
    doc_id: str,
    stage: str,
    previous_run_id: str,
) -> None:
    """Remove a superseded fork-branch run's artifacts (best-effort).

    A re-run of a crashed extract/detection branch publishes under a fresh
    run ID; the previous attempt's branch file is only removed once the new
    attempt succeeded, and a reap failure never masks the branch success.
    """
    from .run_artifacts import reap_stage_run

    try:
        reap_stage_run(library_root, doc_id, stage, previous_run_id)
    except Exception as exc:  # noqa: BLE001
        logger.error(
            "Failed to reap superseded branch run: stage=%s run_id=%s error=%s",
            stage,
            previous_run_id,
            exc,
        )


@dataclass
class PipelineEvent:
    stage: str
    event: str | None = None
    message: str = ""
    data: dict = field(default_factory=dict)


@dataclass
class PipelineResult:
    doc_id: str
    page_count: int = 0
    parser: str = ""
    title: str = ""
    duration_ms: int = 0
    stage_timings: dict[str, int] = field(default_factory=dict)
    current_stage: str | None = None
    """The stage that just completed in this invocation."""
    next_stage: str | None = None
    """The stage the worker should re-queue for, or None when all done."""
    run_id: str | None = None
    """Durable run identity reused across stage invocations and retries."""


ProgressCallback = Callable[[PipelineEvent], None]

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

    # Initialize context
    ctx = PipelineContext(
        pdf_path=Path(pdf_path),
        library_root=root,
        doc_id=doc_id,
        task_id=task_id,
        ocr_config=_current_ocr_config(),
        run_id=None,
    )
    trace_token = set_trace(doc_id=doc_id)
    ctx.staging_dir = staging_dir(root, doc_id)

    ctx.run_id = stage_checkpoint.begin_stage_run(
        ctx.staging_dir,
        library_root=root,
        doc_id=ctx.doc_id,
        discard_completed=resume_from_stage is None,
    )

    start_time = time.monotonic()

    def _maybe_record(
        event: str,
        message: str,
        *,
        stage: str | None = None,
        **data: Any,
    ) -> None:
        """Forward an _emit call to record_ingest_event when DB writes enabled."""
        if task_id is None:
            return
        try:
            from ..storage.sqlite.database import record_ingest_event

            # Map pipeline lifecycle events to ingest_queue.status so the UI
            # reflects the actual run state instead of being stuck at
            # "processing" forever. "start" opens the task, "complete"
            # closes it as done, unrecoverable "error" aborts as failed,
            # and "cancelled" keeps the queue terminal state at cancelled
            # (distinct from ordinary failures).
            # Stage-level warning/success events are intermediate and leave
            # the status alone.
            if event == "start":
                status: str | None = "processing"
            elif event == "complete":
                status = "done"
            elif event == "error":
                status = "failed"
            elif event == "cancelled":
                status = "cancelled"
            else:
                status = None
            record_ingest_event(
                DatabaseManager.get(str(root)),
                task_id=task_id,
                doc_id=doc_id or None,
                stage=stage or "pipeline",
                level=event,
                message=message,
                data=data or None,
                status=status,
                # Only real stages overwrite the resume checkpoint; meta-stages
                # like "pipeline" are logging-only.
                update_stage=(
                    stage if stage and stage in stage_checkpoint.STAGE_ORDER else None
                ),
            )
        except Exception as exc:  # noqa: BLE001
            logger.warning("record_ingest_event failed: %s", exc)
            try:
                from ..utils.logger import push_diagnostic

                push_diagnostic(
                    {
                        "level": "WARNING",
                        "message": f"record_ingest_event failed: {exc}",
                        "category": "pipeline.runner",
                        "error_code": "ingest_log_write_failed",
                    }
                )
            except Exception:  # pragma: no cover
                pass

    def _emit(
        event: str,
        message: str = "",
        *,
        stage: str | None = None,
        **data: Any,
    ) -> None:
        """Emit a pipeline event to the callback, logger, and ingest queue."""
        if on_progress:
            try:
                on_progress(
                    PipelineEvent(
                        stage=stage or "pipeline",
                        event=event,
                        message=message,
                        data=data,
                    ),
                )
            except Exception as exc:  # noqa: BLE001 - observability must not abort work
                logger.warning("Pipeline event callback failed: %s", exc)
        if event == "error" or data.get("error"):
            logger.error("[%s] %s", event, message)
        elif stage not in {"extract", "detection"}:
            logger.info("[%s] %s", event, message)
        _maybe_record(event, message, stage=stage, **data)

    def _emit_stage_result(result: StageResult) -> None:
        """Emit a pipeline event from a StageResult."""
        data: dict[str, Any] = dict(result.context)
        if result.error_code:
            data["error_code"] = result.error_code
        data["recoverable"] = result.recoverable
        if result.warnings:
            data["warnings"] = list(result.warnings)
        event_name = "warning" if result.recoverable else result.status
        _emit(
            event_name,
            result.message,
            stage=result.stage,
            **data,
        )

    # Determine which stage to run.  When resuming, skip stages that
    # already completed in a previous invocation.
    skip_until = resume_from_stage  # skip stages up to and including this

    # Validate skip_until: it must be a valid stage name or None.
    # "pipeline" is a meta-stage used for cancellation/events, not a real stage.
    if skip_until is not None and skip_until not in stage_checkpoint.STAGE_ORDER:
        logger.warning(
            "Invalid resume_from_stage=%r (type=%s, repr=%r) (not in %s), starting from beginning",
            skip_until,
            type(skip_until).__name__,
            str(skip_until),
            stage_checkpoint.STAGE_ORDER,
        )
        skip_until = None

    _emit(
        "start",
        f"Processing {Path(pdf_path).name}"
        + (f" (resuming after {resume_from_stage})" if resume_from_stage else ""),
    )
    # Per-invocation effective stage list from the composition root.
    active_stages = _effective_stages()
    # Validate all effective stages satisfy the StageExecutor protocol
    for stage in active_stages:
        if not isinstance(stage, StageExecutor):
            raise TypeError(
                f"{type(stage).__name__} does not satisfy StageExecutor protocol"
            )
    try:
        stage_timings: dict[str, int] = {}
        completed_stage: str | None = resume_from_stage

        # The only parallel section is the fixed initial fork. Keeping this
        # explicit avoids turning the runner into a generic workflow engine.
        branch_names = [stage.name for stage in active_stages[:2]]
        real_initial_fork = (
            len(active_stages) >= 2
            and active_stages[0] is STAGE_REGISTRY.get("extract")
            and active_stages[1] is STAGE_REGISTRY.get("detection")
        )
        if is_task_cancelled(task_id):
            _emit(
                "cancelled",
                "Pipeline cancelled by user",
                stage="pipeline",
                error_code=PIPELINE_CANCELLED,
            )
            raise TaskCancelledError(task_id)
        # A completed initial fork falls through to the sequential path. A
        # manual branch retry first marks that branch pending in the checkpoint,
        # so the same status-driven fork can rerun only that branch.
        initial_branches_complete = False
        join_complete = False
        if (
            real_initial_fork
            and branch_names == ["extract", "detection"]
            and resume_from_stage is not None
        ):
            fork_checkpoint = (
                stage_checkpoint.load_run_checkpoint(ctx.staging_dir) or {}
            )
            fork_statuses = fork_checkpoint.get("stages", {})
            initial_branches_complete = all(
                fork_statuses.get(name, {}).get("status") == "success"
                for name in branch_names
            )
            join_complete = fork_statuses.get("join", {}).get("status") == "success"
        if (
            real_initial_fork
            and branch_names == ["extract", "detection"]
            and (not initial_branches_complete or not join_complete)
            and (resume_from_stage is None or resume_from_stage in branch_names)
        ):
            checkpoint = stage_checkpoint.load_run_checkpoint(ctx.staging_dir) or {}
            statuses = checkpoint.get("stages", {})
            pending_branches = [
                name
                for name in branch_names
                if statuses.get(name, {}).get("status") != "success"
            ]
            branch_stages = {stage.name: stage for stage in active_stages[:2]}
            branch_contexts: dict[str, PipelineContext] = {}

            def _new_branch_context(name: str) -> PipelineContext:
                return PipelineContext(
                    pdf_path=ctx.pdf_path,
                    library_root=ctx.library_root,
                    doc_id=ctx.doc_id,
                    task_id=ctx.task_id,
                    ocr_config=dict(ctx.ocr_config),
                    staging_dir=ctx.staging_dir,
                    run_id=ctx.run_id,
                    branch=name,
                )

            def _execute_branch(name: str) -> tuple[StageResult, PipelineContext]:
                branch_ctx = _new_branch_context(name)
                started = time.perf_counter()
                result = branch_stages[name].execute(branch_ctx)
                result.elapsed_ms = round((time.perf_counter() - started) * 1000)
                return result, branch_ctx

            from .persist.source_evidence import persist_source_evidence
            from .stage_artifacts import (
                _candidates_from_evidence,
                _extracted_from_evidence,
                detection_results,
                join_evidence_artifacts,
                load_detection_branch,
                load_document_evidence,
                load_extract_branch,
                save_detection_branch,
                save_extract_branch,
                summarize_molecules,
            )

            def _align_branch_to_current_run(stage_name: str) -> None:
                """Carry a previously successful branch into this retry claim."""
                previous_run_id = stage_checkpoint.latest_stage_run_id(
                    ctx.staging_dir, stage_name
                )
                if not previous_run_id or previous_run_id == ctx.run_id:
                    return
                if stage_name == "extract":
                    branch = load_extract_branch(root, doc_id, previous_run_id)
                    if branch is None:
                        raise RuntimeError("extract branch artifact is incomplete")
                    save_extract_branch(
                        root, branch.model_copy(update={"run_id": ctx.run_id})
                    )
                elif stage_name == "detection":
                    branch = load_detection_branch(root, doc_id, previous_run_id)
                    if branch is None:
                        raise RuntimeError("detection branch artifact is incomplete")
                    save_detection_branch(
                        root, branch.model_copy(update={"run_id": ctx.run_id})
                    )
                else:
                    return

                summary = stage_checkpoint.load_stage_summary(
                    ctx.staging_dir, stage_name
                )
                if summary is not None:
                    stage_checkpoint.save_stage_summary(
                        ctx.staging_dir,
                        stage_name,
                        status=str(summary.get("status") or "success"),
                        elapsed_ms=int(summary.get("elapsed_ms") or 0),
                        message=str(summary.get("message") or ""),
                        context=(
                            summary.get("context")
                            if isinstance(summary.get("context"), dict)
                            else None
                        ),
                        error_code=(
                            str(summary["error_code"])
                            if summary.get("error_code")
                            else None
                        ),
                        run_id=ctx.run_id,
                    )

            extract_artifact = None
            detection_artifact = None
            source_evidence_count = 0
            candidates: list[Any] = []
            join_attempted = False

            def _try_join() -> bool:
                """Join exactly once when both initial branches are successful."""
                nonlocal extract_artifact, detection_artifact, join_attempted
                nonlocal source_evidence_count, candidates
                checkpoint = stage_checkpoint.load_run_checkpoint(ctx.staging_dir) or {}
                statuses = checkpoint.get("stages", {})
                if join_attempted:
                    return False
                if not all(
                    statuses.get(name, {}).get("status") == "success"
                    for name in branch_names
                ):
                    return False
                join_attempted = True

                for branch_name in branch_names:
                    _align_branch_to_current_run(branch_name)
                extract_run_id = (
                    stage_checkpoint.latest_stage_run_id(ctx.staging_dir, "extract")
                    or ctx.run_id
                    or ""
                )
                detection_run_id = (
                    stage_checkpoint.latest_stage_run_id(ctx.staging_dir, "detection")
                    or ctx.run_id
                    or ""
                )
                extract_artifact = load_extract_branch(root, doc_id, extract_run_id)
                detection_artifact = load_detection_branch(
                    root, doc_id, detection_run_id
                )
                if extract_artifact is None or detection_artifact is None:
                    raise RuntimeError("initial fork artifacts are incomplete")
                joined = join_evidence_artifacts(extract_artifact, detection_artifact)
                source_evidence_count = persist_source_evidence(root, joined)
                candidates = _candidates_from_evidence(
                    detection_results(detection_artifact), joined.evidence
                )
                stage_checkpoint.save_stage_summary(
                    ctx.staging_dir,
                    "join",
                    status="success",
                    message="Joined extract and detection evidence",
                    run_id=ctx.run_id,
                )
                return True

            branch_results: dict[str, StageResult] = {}
            branch_errors: list[tuple[str, BaseException]] = []
            join_errors: list[BaseException] = []
            for name in pending_branches:
                stage_checkpoint.save_stage_summary(
                    ctx.staging_dir, name, status="running"
                )
                _emit("start", f"Starting {name} branch", stage=name)

            with ThreadPoolExecutor(
                max_workers=max(1, len(pending_branches)),
                thread_name_prefix="mbforge-branch",
            ) as executor:
                futures = {
                    executor.submit(_execute_branch, name): name
                    for name in pending_branches
                }
                for future in as_completed(futures):
                    name = futures[future]
                    try:
                        result, branch_ctx = future.result()
                        branch_contexts[name] = branch_ctx
                        branch_results[name] = result
                        stage_timings[name] = result.elapsed_ms
                        _emit_stage_result(result)
                        if result.status == "error" and not result.recoverable:
                            branch_errors.append(
                                (name, RuntimeError(result.message or "stage failed"))
                            )
                        # A fresh run ID is minted per claim, so a re-run of a
                        # branch supersedes the previous attempt's run. Record
                        # the new run ID, then reap the superseded branch run
                        # once the re-run succeeded (best-effort).
                        previous_run_id = stage_checkpoint.latest_stage_run_id(
                            ctx.staging_dir, name
                        )
                        stage_checkpoint.save_stage_summary(
                            ctx.staging_dir,
                            name,
                            status=("error" if result.status == "error" else "success"),
                            elapsed_ms=result.elapsed_ms,
                            message=result.message,
                            context=result.context,
                            error_code=result.error_code,
                            run_id=ctx.run_id,
                        )
                        if (
                            result.status != "error"
                            and previous_run_id
                            and previous_run_id != ctx.run_id
                        ):
                            _reap_branch_run(
                                ctx.staging_dir, root, ctx.doc_id, name, previous_run_id
                            )
                    except BaseException as exc:
                        branch_errors.append((name, exc))
                        stage_checkpoint.save_stage_summary(
                            ctx.staging_dir,
                            name,
                            status="error",
                            message=str(exc),
                            run_id=ctx.run_id,
                        )
                        if isinstance(exc, TaskCancelledError):
                            _emit(
                                "cancelled",
                                "Pipeline cancelled by user",
                                stage=name,
                                error_code=PIPELINE_CANCELLED,
                            )
                        else:
                            _emit(name, f"Exception: {exc}", error=str(exc))
                    else:
                        try:
                            _try_join()
                        except BaseException as exc:
                            join_errors.append(exc)

            if not join_attempted and not branch_errors:
                try:
                    _try_join()
                except BaseException as exc:
                    join_errors.append(exc)

            if branch_errors:
                name, error = branch_errors[0]
                if isinstance(error, TaskCancelledError):
                    raise error
                raise RuntimeError(f"{name} branch failed: {error}") from error
            if join_errors:
                raise join_errors[0]

            if extract_artifact is None or detection_artifact is None:
                raise RuntimeError("initial branches are not ready to join")

            ctx.document_evidence = load_document_evidence(root, doc_id)
            ctx.source_evidence_count = source_evidence_count
            ctx.extracted = _extracted_from_evidence(
                extract_artifact, ctx.document_evidence
            )
            ctx.candidates = candidates
            ctx.molecule_stats = summarize_molecules(
                candidates,
                dict(detection_artifact.meta.get("molecule_stats", {})),
            )

            ctx.duration_ms = int((time.monotonic() - start_time) * 1000)
            _emit(
                "info",
                f"Initial branches joined in {ctx.duration_ms}ms — next: markdown",
                stage="pipeline",
            )
            return PipelineResult(
                doc_id=ctx.doc_id,
                run_id=ctx.run_id,
                page_count=ctx.extracted.page_count if ctx.extracted else 0,
                parser=ctx.extracted.parser if ctx.extracted else "",
                title=ctx.extracted.title if ctx.extracted else "",
                duration_ms=ctx.duration_ms,
                stage_timings=stage_timings,
                current_stage="detection",
                next_stage="markdown",
            )

        # Later invocations must hydrate from the SQL-backed joined artifact;
        # this also makes a missing source-evidence row a hard pipeline error.
        hydrate_context_from_artifacts(ctx)

        for stage_executor in active_stages:
            # Stable stage name: must match STAGE_ORDER entries and the
            # stage reported in the StageResult (checkpoint consistency).
            stage_name = stage_executor.name

            # Skip stages that already completed in a prior invocation.
            if skip_until is not None:
                if stage_name == skip_until or (
                    stage_name
                    in stage_checkpoint.STAGE_ORDER[
                        : stage_checkpoint.STAGE_ORDER.index(skip_until) + 1
                    ]
                ):
                    logger.debug("Skipping completed stage: %s", stage_name)
                    continue
                skip_until = None  # past the skip zone, run from here

            if is_task_cancelled(task_id):
                _emit(
                    "cancelled",
                    "Pipeline cancelled by user",
                    stage="pipeline",
                    error_code=PIPELINE_CANCELLED,
                )
                raise TaskCancelledError(task_id)

            try:
                stage_checkpoint.save_stage_summary(
                    ctx.staging_dir,
                    stage_name,
                    status="running",
                )
                _t0 = time.perf_counter()
                result = stage_executor.execute(ctx)
                result.elapsed_ms = round((time.perf_counter() - _t0) * 1000)
                # Checkpoint files and event reporting use the same stable
                # stage name as flow control.
                checkpoint_name = result.stage
                stage_timings[checkpoint_name] = result.elapsed_ms

                _emit_stage_result(result)

                if result.status == "error" and not result.recoverable:
                    # Write a failure summary so the checkpoint records
                    # which stage failed and why.
                    stage_checkpoint.save_stage_summary(
                        ctx.staging_dir,
                        checkpoint_name,
                        status="error",
                        elapsed_ms=result.elapsed_ms,
                        message=result.message,
                        context=result.context,
                        error_code=result.error_code,
                        run_id=ctx.run_id,
                    )
                    raise RuntimeError(f"{stage_name} failed: {result.message}")

                # Stage succeeded — write checkpoint summary.
                stage_checkpoint.save_stage_summary(
                    ctx.staging_dir,
                    checkpoint_name,
                    status="success",
                    elapsed_ms=result.elapsed_ms,
                    message=result.message,
                    context=result.context,
                    run_id=ctx.run_id,
                )
                completed_stage = stage_name

            except TaskCancelledError:
                _emit(
                    "cancelled",
                    "Pipeline cancelled by user",
                    stage=stage_name,
                    error_code=PIPELINE_CANCELLED,
                )
                raise
            except Exception as e:
                stage_checkpoint.save_stage_summary(
                    ctx.staging_dir,
                    stage_name,
                    status="error",
                    message=str(e),
                    run_id=ctx.run_id,
                )
                _emit(stage_name, f"Exception: {e}", error=str(e))
                raise

            # One stage per invocation — stop here and let the worker
            # decide whether to re-queue or finalize.
            break

        nxt = stage_checkpoint.next_stage(completed_stage)

        if nxt is None:
            # All stages complete across one or more invocations.
            # NOTE: promote_staging is NOT called here — the worker writes
            # the merged report first (reading checkpoint files from the
            # staging dir), then promotes evidence into storage.
            for temp_path in (ctx.rough_md_path,):
                if temp_path is None:
                    continue
                with contextlib.suppress(Exception):
                    temp_path.unlink(missing_ok=True)

        ctx.duration_ms = int((time.monotonic() - start_time) * 1000)
        timing_summary = " | ".join(f"{k}={v}ms" for k, v in stage_timings.items())
        _emit(
            "complete" if nxt is None else "info",
            f"Stage {completed_stage} done in {ctx.duration_ms}ms"
            + (f" [{timing_summary}]" if timing_summary else "")
            + (f" — next: {nxt}" if nxt else " — pipeline complete"),
            stage="pipeline",
        )

        return PipelineResult(
            doc_id=ctx.doc_id,
            run_id=ctx.run_id,
            page_count=ctx.extracted.page_count if ctx.extracted else 0,
            parser=ctx.extracted.parser if ctx.extracted else "",
            title=ctx.extracted.title if ctx.extracted else "",
            duration_ms=ctx.duration_ms,
            stage_timings=stage_timings,
            current_stage=completed_stage,
            next_stage=nxt,
        )
    except BaseException:
        # Failure or cancellation: clean ONLY this run's uncommitted
        # artifacts when no intermediate stages have succeeded yet.
        # When a previous stage already succeeded (checkpoint exists),
        # leave the staging dir intact for the retry to pick up from.
        summaries = stage_checkpoint.collect_all_summaries(ctx.staging_dir)
        if not any(item.get("status") == "success" for item in summaries.values()):
            cleanup_staging(ctx.staging_dir, root, ctx.doc_id)
        raise
    finally:
        release_task(task_id)
        reset_trace(trace_token)
