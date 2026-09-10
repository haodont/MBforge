"""Integration test for the document processing pipeline."""

from __future__ import annotations

import json
from pathlib import Path

from mbforge.pipeline.runner import PipelineResult, run_pipeline


def _run_all_stages(
    pdf_path: str,
    library_root: str,
    *,
    doc_id: str,
    on_progress=None,
) -> PipelineResult:
    """Drive the pipeline through all stages (simulates worker re-queue)."""
    resume: str | None = None
    while True:
        result = run_pipeline(
            pdf_path,
            library_root,
            doc_id=doc_id,
            on_progress=on_progress,
            resume_from_stage=resume,
        )
        if result.next_stage is None:
            return result
        resume = result.current_stage


def test_full_pipeline_text_only_document(sample_pdf: Path, tmp_path: Path) -> None:
    """Run the full pipeline on a native-text PDF and verify artifacts.

    The PDF has native text and produces the canonical Markdown artifact.
    """
    library_root = tmp_path / "library"
    library_root.mkdir(parents=True, exist_ok=True)

    result = _run_all_stages(
        str(sample_pdf),
        str(library_root),
        doc_id="sample_doc",
    )

    assert result.doc_id == "sample_doc"
    assert result.page_count == 2
    # duration_ms measures the last invocation only (Patent stage),
    # which may be sub-millisecond.
    assert result.current_stage == "patent"
    assert "patent" in result.stage_timings

    # File-system artifacts
    storage_dir = library_root / "storage" / "sample_doc"
    assert (storage_dir / "document_report.json").exists()
    assert (storage_dir / "patent_facts.json").exists()
    assert not (library_root / ".mbforge" / "wiki").exists()

    # Report contents
    report = json.loads(
        (storage_dir / "document_report.json").read_text(encoding="utf-8")
    )
    assert report["doc_id"] == "sample_doc"
    assert report["page_count"] == 2
    assert report["molecule_count"] == 0

    assert (storage_dir / "document.md").exists()

    # SourceEvidence and other database assertions live in focused tests.

