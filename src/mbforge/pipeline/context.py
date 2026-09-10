"""Pipeline context — shared state across all stages.

Replaces function-local variables in the monolithic run_pipeline().
Each stage reads from and writes to this context.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from ..core.evidence import SourceEvidence
    from .extract_text import ExtractedDocument


@dataclass
class PipelineContext:
    """Shared state container for pipeline execution.

    Attributes:
        pdf_path: Input PDF file path
        library_root: Library data directory (per-project root)
        doc_id: Document identifier
        task_id: Optional queue task ID for event and cancellation tracking
        ocr_config: OCR configuration dict
        staging_dir: Staging dir for images/crops evidence
            (``storage/{doc_id}/.staging/``); None writes directly
            to the canonical evidence dirs

        document_evidence: SQL-loaded source evidence; secondary stages
            reference it by ``evidence_id``
        extracted: ExtractedDocument reconstructed from the evidence branch
        rough_md_path: Temporary rough markdown path (Markdown stage)
        document_md_path: Canonical final Markdown artifact (Markdown stage)
        molecule_stats: Molecule extraction statistics
        candidates: List of NormalizedMolecule
        duration_ms: Total pipeline execution time
    """

    # ---- Inputs ----
    pdf_path: Path
    library_root: Path
    doc_id: str
    task_id: str | None = None
    ocr_config: dict = field(default_factory=dict)

    # ---- Run-scoped artifact staging (PIPE-13) ----
    # ``run_id`` identifies this single pipeline run; ``staging_dir`` is
    # ``storage/{doc_id}/.staging/`` where new images/crops evidence
    # is written until the runner promotes it on success. ``None`` means
    # stages write directly to the canonical evidence dirs (legacy path).
    staging_dir: Path | None = None
    # Generated once per run_pipeline invocation; Patent facts retain it as
    # run metadata even though the artifact has a document-level path.
    run_id: str | None = None
    # Set only for the fixed initial Extract/Detection fork.
    branch: str | None = None
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
