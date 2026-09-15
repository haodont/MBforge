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

from mbforge.pipeline.run.checkpoint import collect_all_summaries
from mbforge.pipeline.run.context import RunContext
from mbforge.utils.logger import get_logger

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
    ) -> None:
        """Close out one node invocation: clear temp, set duration, emit event.

        Completion of the *document* is not decided here — the worker marks
        the node done and publishes only once every node of the run is done.
        """
        ctx = self.ctx
        # ``rough_md_path`` is a staging temp for the Markdown stage; drop it
        # once the stage returns (the canonical artifact is already written).
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
            "info",
            f"Stage {completed_stage} done in {ctx.duration_ms}ms"
            + (f" [{timing_summary}]" if timing_summary else ""),
            stage="pipeline",
        )

    def cleanup_on_failure(self) -> None:
        """Remove this run's uncommitted artifacts only when nothing succeeded."""
        summaries = collect_all_summaries(self.run.staging_dir)
        if not any(item.get("status") == "success" for item in summaries.values()):
            from mbforge.pipeline.artifacts.staging import cleanup_staging

            cleanup_staging(
                self.run.staging_dir, self.run.library_root, self.ctx.doc_id
            )


__all__ = ["Finalizer"]
