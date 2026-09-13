"""Finalizer — run completion and failure/cancellation cleanup.

- On success: clear the transient rough-markdown temp and emit the terminal
  ``complete`` (or intermediate ``info``) event for the worker's re-queue
  decision.
- On failure/cancellation: clean ONLY this run's uncommitted artifacts when no
  intermediate stage has succeeded yet; leave the staging dir intact for retry
  otherwise. Mirrors the old ``except``/``finally`` cleanup in ``run_pipeline``.
"""

from __future__ import annotations

import contextlib
from typing import TYPE_CHECKING

from ...utils.logger import get_logger
from ..stage_checkpoint import collect_all_summaries
from .state import RunContext

if TYPE_CHECKING:
    from .events import PipelineEventSink

logger = get_logger("mbforge.pipeline.runner")


class Finalizer:
    """Run-end handlers for the pipeline runner."""

    def __init__(self, run: RunContext) -> None:
        self.run = run
        self.ctx = run.ctx
        assert self.ctx is not None

    def complete(
        self,
        sink: PipelineEventSink,
        completed_stage: str | None,
        next_stage: str | None,
    ) -> None:
        """Close out one invocation: clear temp, set duration, emit result event."""
        ctx = self.ctx
        if next_stage is None:
            # All stages complete across one or more invocations. NOTE: promotion
            # is NOT done here — the worker writes the merged report first
            # (reading checkpoint files from the staging dir), then promotes.
            for temp_path in (ctx.rough_md_path,):
                if temp_path is None:
                    continue
                with contextlib.suppress(Exception):
                    temp_path.unlink(missing_ok=True)

        ctx.duration_ms = self.run.elapsed_ms()
        timing_summary = " | ".join(
            f"{k}={v}ms" for k, v in self.run.stage_timings.items()
        )
        sink.emit(
            "complete" if next_stage is None else "info",
            f"Stage {completed_stage} done in {ctx.duration_ms}ms"
            + (f" [{timing_summary}]" if timing_summary else "")
            + (f" — next: {next_stage}" if next_stage else " — pipeline complete"),
            stage="pipeline",
        )

    def cleanup_on_failure(self) -> None:
        """Remove this run's uncommitted artifacts only when nothing succeeded."""
        summaries = collect_all_summaries(self.run.staging_dir)
        if not any(item.get("status") == "success" for item in summaries.values()):
            from ..run_artifacts import cleanup_staging

            cleanup_staging(
                self.run.staging_dir, self.run.library_root, self.ctx.doc_id
            )


__all__ = ["Finalizer"]
