"""SequentialStageRunner — resume/skip-aware one-stage execution loop.

The runner executes **one** stage per invocation; the queue worker reads
``PipelineResult.next_stage`` to decide whether to re-queue. This module
encapsulates the old ``for stage_executor in active_stages: ... break`` loop:
skip stages already completed (``resume_from_stage``), journalize the running /
success / error stage summaries, and return the completed stage name.
"""

from __future__ import annotations

import time
from typing import TYPE_CHECKING, Any

from ...utils.logger import get_logger
from ..cancellation import PIPELINE_CANCELLED, TaskCancelledError, default_registry
from ..stage_checkpoint import STAGE_ORDER, save_stage_summary
from .state import RunContext

if TYPE_CHECKING:
    from .events import PipelineEventSink

logger = get_logger("mbforge.pipeline.runner")


class SequentialStageRunner:
    """Drives one sequential stage for the current invocation."""

    def __init__(
        self,
        run: RunContext,
        sink: PipelineEventSink,
        active_stages: list[Any],
    ) -> None:
        self.run = run
        self.ctx = run.ctx
        assert self.ctx is not None
        self.sink = sink
        self.active_stages = active_stages
        self.resume_from_stage = run.resume_from_stage

    def run_one(self) -> str | None:
        """Run exactly one pending stage; return the completed stage name."""
        ctx = self.ctx
        # A resumed invocation skips stages up to and including the last
        # completed one recorded on the queue row.
        skip_until = self.resume_from_stage
        if skip_until is not None and skip_until not in STAGE_ORDER:
            logger.warning(
                "Invalid resume_from_stage=%r (not in %s), starting from beginning",
                skip_until,
                STAGE_ORDER,
            )
            skip_until = None

        completed_stage: str | None = self.resume_from_stage
        for stage_executor in self.active_stages:
            # Stable stage name: must match STAGE_ORDER entries and the stage
            # reported in the StageResult (checkpoint consistency).
            stage_name = stage_executor.name

            if skip_until is not None:
                if stage_name == skip_until or (
                    stage_name in STAGE_ORDER[: STAGE_ORDER.index(skip_until) + 1]
                ):
                    logger.debug("Skipping completed stage: %s", stage_name)
                    continue
                skip_until = None  # past the skip zone, run from here

            if default_registry.is_cancelled(self.run.task_id):
                self.sink.emit(
                    "cancelled",
                    "Pipeline cancelled by user",
                    stage="pipeline",
                    error_code=PIPELINE_CANCELLED,
                )
                raise TaskCancelledError(self.run.task_id)

            try:
                save_stage_summary(self.run.staging_dir, stage_name, status="running")
                started = time.perf_counter()
                result = stage_executor.execute(ctx)
                result.elapsed_ms = round((time.perf_counter() - started) * 1000)
                checkpoint_name = result.stage
                self.run.stage_timings[checkpoint_name] = result.elapsed_ms

                self.sink.emit_stage_result(result)

                if result.status == "error" and not result.recoverable:
                    save_stage_summary(
                        self.run.staging_dir,
                        checkpoint_name,
                        status="error",
                        elapsed_ms=result.elapsed_ms,
                        message=result.message,
                        context=result.context,
                        error_code=result.error_code,
                        run_id=self.run.run_id,
                    )
                    raise RuntimeError(f"{stage_name} failed: {result.message}")

                save_stage_summary(
                    self.run.staging_dir,
                    checkpoint_name,
                    status="success",
                    elapsed_ms=result.elapsed_ms,
                    message=result.message,
                    context=result.context,
                    run_id=self.run.run_id,
                )
                completed_stage = stage_name
            except TaskCancelledError:
                self.sink.emit(
                    "cancelled",
                    "Pipeline cancelled by user",
                    stage=stage_name,
                    error_code=PIPELINE_CANCELLED,
                )
                raise
            except Exception as exc:
                save_stage_summary(
                    self.run.staging_dir,
                    stage_name,
                    status="error",
                    message=str(exc),
                    run_id=self.run.run_id,
                )
                self.sink.emit(stage_name, f"Exception: {exc}", error=str(exc))
                raise

            # One stage per invocation — stop here and let the worker decide
            # whether to re-queue or finalize.
            break

        return completed_stage


__all__ = ["SequentialStageRunner"]
