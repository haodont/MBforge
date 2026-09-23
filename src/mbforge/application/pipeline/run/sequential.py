"""StageRunner — executes exactly one stage (one queue node).

The execution DAG lives in the queue (``ingest_stage_deps``): each node is
admitted independently by :mod:`mbforge.adapters.runtime.ingest.worker` and calls the
runner with a single stage name. This module runs that stage, journals its
running/success/error summary, and returns the completed stage name.
"""

from __future__ import annotations

import time
from typing import TYPE_CHECKING, Any

from mbforge.application.pipeline.cancellation import (
    PIPELINE_CANCELLED,
    TaskCancelledError,
    default_registry,
)
from mbforge.application.pipeline.run.checkpoint import save_stage_summary
from mbforge.application.pipeline.run.context import RunContext
from mbforge.foundation.logger import get_logger

if TYPE_CHECKING:
    from mbforge.application.pipeline.run.events import PipelineEventSink

logger = get_logger("mbforge.application.pipeline.runner")


class StageRunner:
    """Drives the single stage named by the claimed queue node."""

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

    def _stage(self, name: str) -> Any:
        for stage_executor in self.active_stages:
            if stage_executor.name == name:
                return stage_executor
        raise ValueError(f"stage {name!r} is not in the effective composition")

    def run_stage(self, stage_name: str) -> str:
        """Execute one stage; return the completed stage name.

        Named ``run_stage`` (not ``run``) because ``self.run`` holds the
        RunContext and would shadow the method.
        """
        stage_executor = self._stage(stage_name)
        ctx = self.ctx

        if default_registry.is_cancelled(self.run.task_id):
            self.sink.emit(
                "cancelled",
                "Pipeline cancelled by user",
                stage="pipeline",
                error_code=PIPELINE_CANCELLED,
            )
            raise TaskCancelledError(self.run.task_id)

        recorded = False
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
                # The stage's own error summary (with its error_code) is the
                # authoritative record; the handler below must not clobber it.
                recorded = True
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
            return stage_name
        except TaskCancelledError:
            self.sink.emit(
                "cancelled",
                "Pipeline cancelled by user",
                stage=stage_name,
                error_code=PIPELINE_CANCELLED,
            )
            raise
        except Exception as exc:
            if not recorded:
                save_stage_summary(
                    self.run.staging_dir,
                    stage_name,
                    status="error",
                    message=str(exc),
                    run_id=self.run.run_id,
                )
            self.sink.emit(stage_name, f"Exception: {exc}", error=str(exc))
            raise


__all__ = ["StageRunner"]
