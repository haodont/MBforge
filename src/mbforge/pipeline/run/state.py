"""RunContext — per-invocation orchestration state for the pipeline runner.

Wraps the ``PipelineContext`` shared with stages plus the runner-local
bookkeeping (orchestration state, run lifecycle, result assembly) that used to
be free variables inside ``run_pipeline``. Lifecycle side effects
(``set_trace``/``reset_trace``, cancellation-registry release) are owned here so
the runner facade stays a flat orchestration sequence.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING, Any

from ...utils.logger import get_logger, reset_trace, set_trace
from ..context import PipelineContext
from ..run_artifacts import staging_dir
from ..stage_checkpoint import begin_stage_run
from .models import PipelineResult

if TYPE_CHECKING:
    from ...core.evidence import SourceEvidence  # noqa: F401  (re-exported via ctx)

logger = get_logger("mbforge.pipeline.runner")


@dataclass
class RunContext:
    """One ``run_pipeline`` invocation's orchestration state."""

    pdf_path: Path
    library_root: Path
    doc_id: str
    task_id: str | None = None
    ocr_config: dict = field(default_factory=dict)
    resume_from_stage: str | None = None

    ctx: PipelineContext | None = field(default=None, repr=False)
    staging_dir: Path | None = None
    run_id: str | None = None
    start_time: float = 0.0
    stage_timings: dict[str, int] = field(default_factory=dict)
    trace_token: Any = field(default=None, repr=False)

    @classmethod
    def start(
        cls,
        pdf_path: Path,
        library_root: str | Path,
        doc_id: str,
        *,
        task_id: str | None = None,
        ocr_config: dict | None = None,
        resume_from_stage: str | None = None,
    ) -> RunContext:
        """Build the run, set the trace, mint the run ID, and stage the dir."""
        root = Path(library_root)
        ctx = PipelineContext(
            pdf_path=pdf_path,
            library_root=root,
            doc_id=doc_id,
            task_id=task_id,
            ocr_config=dict(ocr_config or {}),
            run_id=None,
        )
        run = cls(
            pdf_path=pdf_path,
            library_root=root,
            doc_id=doc_id,
            task_id=task_id,
            ocr_config=dict(ocr_config or {}),
            resume_from_stage=resume_from_stage,
            ctx=ctx,
        )
        run.trace_token = set_trace(doc_id=doc_id)
        run.staging_dir = staging_dir(root, doc_id)
        ctx.staging_dir = run.staging_dir
        ctx.run_id = begin_stage_run(
            run.staging_dir,
            library_root=root,
            doc_id=doc_id,
            discard_completed=resume_from_stage is None,
        )
        run.run_id = ctx.run_id
        run.start_time = time.monotonic()
        return run

    def elapsed_ms(self) -> int:
        """Wall time for this invocation."""
        return int((time.monotonic() - self.start_time) * 1000)

    def as_public_result(
        self, completed_stage: str | None, next_stage: str | None
    ) -> PipelineResult:
        """Assemble the worker-facing ``PipelineResult`` for this invocation."""
        ctx = self.ctx
        assert ctx is not None
        return PipelineResult(
            doc_id=ctx.doc_id,
            run_id=self.run_id,
            page_count=ctx.extracted.page_count if ctx.extracted else 0,
            parser=ctx.extracted.parser if ctx.extracted else "",
            title=ctx.extracted.title if ctx.extracted else "",
            duration_ms=ctx.duration_ms,
            stage_timings=dict(self.stage_timings),
            current_stage=completed_stage,
            next_stage=next_stage,
        )

    def dispose(self) -> None:
        """Release cancellation mark and reset the trace (mirrors the old finally)."""
        from ..cancellation import default_registry

        default_registry.unregister(self.task_id)
        reset_trace(self.trace_token)


__all__ = ["RunContext"]
