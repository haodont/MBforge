"""Unit tests for the pipeline runner's single-stage (queue node) model.

Each queue node executes exactly one stage. These tests cover stage selection,
the DAG shape, and end-to-end node driving.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any
from unittest.mock import patch

import pytest

from mbforge.application.pipeline.extract.text import ExtractedDocument, PageContent
from mbforge.application.pipeline.runner import PipelineResult, run_pipeline
from mbforge.application.pipeline.stage import PipelineErrorCode, StageResult
from mbforge.domain.types import ExtractionResult

RUN_ID = "20260909123456"


def _fake_layout_extract(*_args: Any, **_kwargs: Any) -> ExtractedDocument:
    """Stand-in for ``extract_layout_text`` over the 2-page ``sample_pdf``."""
    return ExtractedDocument(
        raw_text="page one text\n\npage two text",
        page_count=2,
        parser="layout",
        pages=[
            PageContent(page_num=1, text="page one text"),
            PageContent(page_num=2, text="page two text"),
        ],
    )


def _dag_order() -> list[str]:
    """Topological order of the stage DAG (deterministic for the fixed graph)."""
    from mbforge.application.pipeline.composition import stage_dependencies

    deps = stage_dependencies()
    order: list[str] = []
    remaining = dict(deps)
    while remaining:
        ready = sorted(s for s, d in remaining.items() if all(x in order for x in d))
        assert ready, "stage DAG has a cycle"
        for stage in ready:
            order.append(stage)
            remaining.pop(stage)
    return order


def _drive_all(
    pdf_path: str,
    library_root: str,
    *,
    doc_id: str,
    on_progress: Any = None,
    run_id: str = RUN_ID,
) -> PipelineResult:
    """Run every node in DAG order against one shared attempt run ID."""
    result: PipelineResult | None = None
    for stage in _dag_order():
        result = run_pipeline(
            pdf_path,
            library_root,
            doc_id=doc_id,
            stage=stage,
            run_id=run_id,
            on_progress=on_progress,
        )
    assert result is not None
    return result


def test_stage_dag_shape() -> None:
    """Extract is the root; the rest of the pipeline is a linear tail."""
    from mbforge.application.pipeline.composition import stage_dependencies

    deps = stage_dependencies()
    assert deps["extract"] == ()
    assert deps["join"] == ("extract",)
    assert deps["markdown"] == ("join",)
    assert deps["patent"] == ("markdown",)


def test_run_pipeline_executes_only_the_named_stage(tmp_path: Path) -> None:
    """Only the claimed node's stage runs in one invocation."""
    ran: list[str] = []

    class ExtractProbe:
        name = "extract"

        def execute(self, ctx) -> StageResult:  # noqa: ANN001 - protocol fixture
            ran.append("extract")
            return StageResult(stage="extract", status="success", message="ok")

    class MarkdownProbe:
        name = "markdown"

        def execute(self, ctx) -> StageResult:  # noqa: ANN001
            ran.append("markdown")
            return StageResult(stage="markdown", status="success", message="ok")

    with patch(
        "mbforge.application.pipeline.runner._effective_stages",
        return_value=[ExtractProbe(), MarkdownProbe()],
    ):
        result = run_pipeline(
            str(tmp_path / "document.pdf"),
            str(tmp_path / "library"),
            doc_id="only-one",
            stage="extract",
            run_id=RUN_ID,
        )

    assert ran == ["extract"]
    assert result.current_stage == "extract"


def test_run_pipeline_requires_a_registered_stage(tmp_path: Path) -> None:
    """A node with no (or an unknown) stage cannot run."""
    with pytest.raises(ValueError):
        run_pipeline(
            str(tmp_path / "document.pdf"),
            str(tmp_path / "library"),
            doc_id="no-stage",
        )
    with pytest.raises(ValueError):
        run_pipeline(
            str(tmp_path / "document.pdf"),
            str(tmp_path / "library"),
            doc_id="bad-stage",
            stage="not_a_stage",
        )


def test_drive_all_nodes_persists_markdown(sample_pdf: Path, tmp_path: Path) -> None:
    """Driving every node in DAG order completes the document."""
    library_root = tmp_path / "library"
    library_root.mkdir(parents=True, exist_ok=True)

    with (
        patch(
            "mbforge.application.pipeline.detection.extraction.extract_molecules_from_pdf",
            return_value=[],
        ),
        patch(
            "mbforge.application.pipeline.extract.text.extract_layout_text",
            side_effect=_fake_layout_extract,
        ),
    ):
        result = _drive_all(str(sample_pdf), str(library_root), doc_id="sample_doc")

    assert result.current_stage == "patent"
    assert (library_root / "storage" / "sample_doc" / "document.md").exists()


def test_join_failure_does_not_run_downstream_stages(
    sample_pdf: Path, tmp_path: Path
) -> None:
    """A failed Join stage aborts before Markdown/Patent run."""
    from mbforge.application.pipeline.stages.markdown_stage import MarkdownStage

    library_root = tmp_path / "library"
    library_root.mkdir(parents=True, exist_ok=True)

    def forbidden_markdown(_stage, _ctx) -> StageResult:  # noqa: ANN001
        raise AssertionError("Markdown ran after a failed Join")

    with (
        patch(
            "mbforge.application.pipeline.detection.extraction.extract_molecules_from_pdf",
            return_value=[],
        ),
        patch(
            "mbforge.application.pipeline.extract.text.extract_layout_text",
            side_effect=_fake_layout_extract,
        ),
        patch(
            "mbforge.adapters.persistence.source_evidence.persist_source_evidence",
            side_effect=RuntimeError("sqlite unavailable"),
        ),
        patch.object(MarkdownStage, "execute", forbidden_markdown),
        pytest.raises(RuntimeError, match="sqlite unavailable"),
    ):
        _drive_all(str(sample_pdf), str(library_root), doc_id="join-fail")

    # The join stage recorded a hard error for the queue node.
    from mbforge.application.pipeline.run.checkpoint import load_stage_summary

    staging = library_root / "storage" / "join-fail" / ".staging"
    summary = load_stage_summary(staging, "join")
    assert summary is not None
    assert summary["status"] == "error"
    assert summary["error_code"] == PipelineErrorCode.EVIDENCE_JOIN_FAILED


def test_pipeline_aborts_on_fatal_patent_publish_error(
    sample_pdf: Path, tmp_path: Path
) -> None:
    """A failure publishing Patent facts is fatal and aborts the pipeline."""
    library_root = tmp_path / "library"
    library_root.mkdir(parents=True, exist_ok=True)
    crop_path = library_root / "storage" / "sample_doc" / "crops" / "c.png"
    crop_path.parent.mkdir(parents=True, exist_ok=True)
    crop_path.write_bytes(b"archived crop")

    fake_result = ExtractionResult(
        smiles="CCO",
        esmiles="CCO",
        name="",
        source="image",
        bbox_pdf=(0, 0, 1, 1),
        page_idx=0,
        mol_img_path=str(crop_path),
        moldet_conf=0.9,
    )

    events: list[dict] = []

    def _capture(event) -> None:
        events.append({"stage": event.stage, "event": event.event, "data": event.data})

    with (
        patch(
            "mbforge.application.pipeline.extract.text.extract_layout_text",
            side_effect=_fake_layout_extract,
        ),
        patch(
            "mbforge.application.pipeline.stages.extract_stage._detect_molecules",
            return_value={
                "molecule_count": 1,
                "rejected_count": 0,
                "pending_review_count": 0,
                "results": [fake_result],
            },
        ),
        patch(
            "mbforge.application.pipeline.artifacts.staging.publish_run",
            side_effect=RuntimeError("disk full"),
        ),
        pytest.raises(RuntimeError, match="disk full"),
    ):
        _drive_all(
            str(sample_pdf),
            str(library_root),
            doc_id="sample_doc",
            on_progress=_capture,
        )

    error_events = [e for e in events if e["event"] == "error"]
    assert len(error_events) >= 1
    assert error_events[0]["stage"] == "patent"
    assert (
        error_events[0]["data"].get("error_code")
        == PipelineErrorCode.PATENT_EXTRACTION_FAILED
    )


def test_progress_callback_failure_does_not_abort_stage(tmp_path: Path) -> None:
    """A broken progress sink must not discard the completed stage."""

    class ExtractProbe:
        name = "extract"

        def execute(self, ctx) -> StageResult:  # noqa: ANN001 - protocol fixture
            return StageResult(stage="extract", status="success", message="ok")

    def _broken_progress(_event) -> None:  # noqa: ANN001 - callback fixture
        raise OSError("stdout pipe closed")

    with patch(
        "mbforge.application.pipeline.runner._effective_stages",
        return_value=[ExtractProbe()],
    ):
        result = run_pipeline(
            str(tmp_path / "document.pdf"),
            str(tmp_path / "library"),
            doc_id="progress-callback",
            stage="extract",
            run_id=RUN_ID,
            on_progress=_broken_progress,
        )

    assert result.doc_id == "progress-callback"
    assert result.current_stage == "extract"
