"""Pipeline context — shared state across all stages.

Replaces function-local variables in the monolithic run_pipeline().
Each stage reads from and writes to this context.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING, Any

from mbforge.application.pipeline.run.models import PipelineResult
from mbforge.foundation.logger import reset_trace, set_trace

if TYPE_CHECKING:
    from mbforge.application.pipeline.extract.text import ExtractedDocument
    from mbforge.domain.evidence import SourceEvidence


@dataclass
class PipelineContext:
    """Shared state container for pipeline execution.

    Attributes:
        pdf_path: Input PDF file path
        library_root: Library data directory (per-project root)
        doc_id: Document identifier
        task_id: Optional queue task ID for event and cancellation tracking
        staging_dir: Staging dir for images/crops evidence
            (``storage/{doc_id}/.staging/``); None writes directly
            to the canonical evidence dirs

        document_evidence: SQL-loaded source evidence; secondary stages
            reference it by ``evidence_id``
        extracted: ExtractedDocument reconstructed from the evidence branch
        rough_md_path: Temporary rough markdown path (Markdown stage)
        document_md_path: Canonical final Markdown artifact (Markdown stage)
        molecule_stats: Molecule extraction statistics
        candidates: List of Molecule
        duration_ms: Total pipeline execution time
    """

    # ---- Inputs ----
    pdf_path: Path
    library_root: Path
    doc_id: str
    task_id: str | None = None

    # ---- Run-scoped artifact staging (PIPE-13) ----
    # ``run_id`` identifies this single pipeline run; ``staging_dir`` is
    # ``storage/{doc_id}/.staging/`` where new images/crops evidence
    # is written until the runner promotes it on success. ``None`` means
    # stages write directly to the canonical evidence dirs (legacy path).
    staging_dir: Path | None = None
    # The ingestion attempt's run ID (minted once at enqueue, shared by every
    # queue node of that attempt); Patent facts retain it as run metadata even
    # though the artifact has a document-level path.
    run_id: str | None = None
    # ---- Stage 1: Extract ----
    extracted: ExtractedDocument | None = None
    document_evidence: list[SourceEvidence] = field(default_factory=list)

    rough_md_path: Path | None = None
    document_md_path: Path | None = None
    molecule_stats: dict[str, Any] = field(default_factory=dict)
    candidates: list[Any] = field(default_factory=list)
    structure_role_counts: dict[str, int] = field(default_factory=dict)

    activity_records: list[Any] = field(default_factory=list)
    activity_stats: dict[str, Any] = field(default_factory=dict)

    # Downstream persistence fields are retained for the later Link/Persist
    # design; the current runner stops after Patent.
    examples: list[Any] = field(default_factory=list)
    """Downstream example projection, not populated by the current runner."""
    example_stats: dict[str, Any] = field(default_factory=dict)

    activity_count_written: int = 0
    source_evidence_count: int = 0

    # ---- Outputs ----
    duration_ms: int = 0


@dataclass
class RunContext:
    """One ``run_pipeline`` invocation's orchestration state."""

    pdf_path: Path
    library_root: Path
    doc_id: str
    task_id: str | None = None
    stage: str | None = None

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
        run_id: str | None = None,
        stage: str | None = None,
    ) -> RunContext:
        """Build the run, set the trace, bind the attempt run ID, stage the dir."""
        from mbforge.application.pipeline.artifacts.staging import staging_dir
        from mbforge.application.pipeline.run.checkpoint import ensure_attempt_run
        from mbforge.application.pipeline.run.ids import mint_run_id

        root = Path(library_root)
        ctx = PipelineContext(
            pdf_path=pdf_path,
            library_root=root,
            doc_id=doc_id,
            task_id=task_id,
        )
        run = cls(
            pdf_path=pdf_path,
            library_root=root,
            doc_id=doc_id,
            task_id=task_id,
            stage=stage,
            ctx=ctx,
        )
        run.trace_token = set_trace(doc_id=doc_id)
        run.staging_dir = staging_dir(root, doc_id)
        ctx.staging_dir = run.staging_dir
        # One run ID per ingestion attempt: every node of the attempt reuses
        # it, so the extract branch and its downstream stages always agree on
        # the run ID.
        run.run_id = run_id or mint_run_id(root, doc_id)
        ctx.run_id = run.run_id
        ensure_attempt_run(run.staging_dir, run.run_id)
        run.start_time = time.monotonic()
        return run

    def elapsed_ms(self) -> int:
        """Wall time for this invocation."""
        return int((time.monotonic() - self.start_time) * 1000)

    def as_public_result(self, completed_stage: str | None) -> PipelineResult:
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
        )

    def dispose(self) -> None:
        """Release cancellation mark and reset the trace."""
        from mbforge.application.pipeline.cancellation import default_registry

        default_registry.unregister(self.task_id)
        reset_trace(self.trace_token)


__all__ = ["PipelineContext", "RunContext"]
