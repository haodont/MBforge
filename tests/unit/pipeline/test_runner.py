"""Unit tests for pipeline runner stage handling and error codes."""

from __future__ import annotations

import json
import threading
from pathlib import Path
from typing import Any
from unittest.mock import patch

import pytest

from mbforge.pipeline.detection.types import ExtractionResult
from mbforge.pipeline.evidence_artifacts import (
    DetectionArtifact,
    DetectionPage,
    ExtractArtifact,
    ExtractPage,
    PageFrame,
)
from mbforge.pipeline.extract_text import ExtractedDocument, PageContent, TextSpan
from mbforge.pipeline.runner import PipelineResult, run_pipeline
from mbforge.pipeline.stage_result import PipelineErrorCode, StageResult


def _run_all_stages(
    pdf_path: str,
    library_root: str,
    *,
    doc_id: str,
    on_progress: Any = None,
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


def _run_all_stages_bounded(
    pdf_path: str,
    library_root: str,
    *,
    doc_id: str,
    on_progress: Any = None,
    max_invocations: int = 50,
) -> PipelineResult:
    """Drive every stage like the worker, failing on an unresolvable loop.

    A faithful re-queue driver: each invocation runs one stage and resumes
    from its ``current_stage``. If the runner ever fails to advance past a
    stage, the re-queue spins forever; this bound turns that hang into a
    test failure instead of blocking the suite.
    """
    resume: str | None = None
    for _ in range(max_invocations):
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
    raise TimeoutError(
        f"pipeline did not reach a terminal state in {max_invocations} invocations; "
        f"last current_stage={resume!r}"
    )


def test_initial_extract_detection_branches_overlap(tmp_path: Path) -> None:
    """The initial branches run concurrently and publish one joined artifact."""
    from mbforge.core.evidence import SourceEvidence
    from mbforge.pipeline.stage_artifacts import (
        save_detection_branch,
        save_extract_branch,
    )
    from mbforge.pipeline.stages.detection_stage import DetectionStage
    from mbforge.pipeline.stages.extract_stage import ExtractStage

    library_root = tmp_path / "library"
    page = PageFrame(page=1, width=100, height=100)
    source = SourceEvidence.create(
        doc_id="fork-doc", page=1, bbox=(10, 20, 30, 30), raw_text="source"
    )
    extracted = ExtractedDocument(
        raw_text="source",
        page_count=1,
        pages=[
            PageContent(
                page_num=1,
                text="source",
                text_spans=[TextSpan(text="source", bbox=(10, 20, 30, 30))],
            )
        ],
    )
    barrier = threading.Barrier(2, timeout=2)
    thread_names: list[str] = []

    def extract(_stage, ctx) -> StageResult:  # noqa: ANN001 - test stage patch
        thread_names.append(threading.current_thread().name)
        barrier.wait()
        ctx.extracted = extracted
        save_extract_branch(
            ctx.library_root,
            ExtractArtifact(
                doc_id=ctx.doc_id,
                run_id=ctx.run_id or "",
                pages=[
                    ExtractPage(
                        page_num=1,
                        width=page.width,
                        height=page.height,
                        rotation=page.rotation,
                        text="source",
                        text_spans=[
                            {
                                "text": "source",
                                "bbox": [10, 20, 30, 30],
                                "block_type": 0,
                            }
                        ],
                    )
                ],
            ),
        )
        return StageResult(stage="extract", status="success", message="extract")

    def detection(_stage, ctx) -> StageResult:  # noqa: ANN001 - test stage patch
        thread_names.append(threading.current_thread().name)
        barrier.wait()
        save_detection_branch(
            ctx.library_root,
            DetectionArtifact(
                doc_id=ctx.doc_id,
                run_id=ctx.run_id or "",
                pages=[
                    DetectionPage(
                        page_num=page.page,
                        width=page.width,
                        height=page.height,
                        rotation=page.rotation,
                    )
                ],
            ),
        )
        return StageResult(stage="detection", status="success", message="detection")

    with (
        patch.object(ExtractStage, "execute", extract),
        patch.object(DetectionStage, "execute", detection),
    ):
        result = run_pipeline(
            str(tmp_path / "document.pdf"),
            str(library_root),
            doc_id="fork-doc",
        )

    assert result.current_stage == "detection"
    assert result.next_stage == "markdown"
    assert len(thread_names) == 2
    assert len(set(thread_names)) == 2
    checkpoint = json.loads(
        (library_root / "storage" / "fork-doc" / ".staging" / "_run.json").read_text(
            encoding="utf-8"
        )
    )
    assert {
        stage: checkpoint["stages"][stage]["status"]
        for stage in ("extract", "detection")
    } == {"extract": "success", "detection": "success"}
    from mbforge.services.documents.source_evidence import list_evidence

    assert [item.evidence_id for item in list_evidence(library_root, "fork-doc")] == [
        source.evidence_id
    ]


def test_initial_branch_retry_runs_only_failed_branch(tmp_path: Path) -> None:
    """A failed initial branch is retried without rerunning the other branch."""
    from mbforge.pipeline.stage_artifacts import (
        save_detection_branch,
        save_extract_branch,
    )
    from mbforge.pipeline.stages.detection_stage import DetectionStage
    from mbforge.pipeline.stages.extract_stage import ExtractStage

    library_root = tmp_path / "library"
    page = PageFrame(page=1, width=100, height=100)
    extracted = ExtractedDocument(raw_text="source", page_count=1, pages=[])
    calls = {"extract": 0, "detection": 0}

    def extract(_stage, ctx) -> StageResult:  # noqa: ANN001 - test stage patch
        calls["extract"] += 1
        ctx.extracted = extracted
        save_extract_branch(
            ctx.library_root,
            ExtractArtifact(
                doc_id=ctx.doc_id,
                run_id=ctx.run_id or "",
                pages=[
                    ExtractPage(
                        page_num=1,
                        width=page.width,
                        height=page.height,
                        rotation=page.rotation,
                        text="source",
                        text_spans=[
                            {
                                "text": "source",
                                "bbox": [10, 20, 30, 30],
                                "block_type": 0,
                            }
                        ],
                    )
                ],
            ),
        )
        return StageResult(stage="extract", status="success", message="extract")

    def detection(_stage, ctx) -> StageResult:  # noqa: ANN001 - test stage patch
        calls["detection"] += 1
        if calls["detection"] == 1:
            raise RuntimeError("detector down")
        save_detection_branch(
            ctx.library_root,
            DetectionArtifact(
                doc_id=ctx.doc_id,
                run_id=ctx.run_id or "",
                pages=[
                    DetectionPage(
                        page_num=page.page,
                        width=page.width,
                        height=page.height,
                        rotation=page.rotation,
                    )
                ],
            ),
        )
        return StageResult(stage="detection", status="success", message="detection")

    with (
        patch.object(ExtractStage, "execute", extract),
        patch.object(DetectionStage, "execute", detection),
        pytest.raises(RuntimeError, match="detector down"),
    ):
        run_pipeline(
            str(tmp_path / "document.pdf"),
            str(library_root),
            doc_id="retry-doc",
        )

    checkpoint = json.loads(
        (library_root / "storage" / "retry-doc" / ".staging" / "_run.json").read_text(
            encoding="utf-8"
        )
    )
    first_run_id = checkpoint["run_id"]
    with (
        patch.object(ExtractStage, "execute", extract),
        patch.object(DetectionStage, "execute", detection),
    ):
        result = run_pipeline(
            str(tmp_path / "document.pdf"),
            str(library_root),
            doc_id="retry-doc",
            resume_from_stage="extract",
        )

    assert calls == {"extract": 1, "detection": 2}
    assert result.run_id != first_run_id
    assert result.next_stage == "markdown"


def test_detection_retry_does_not_rerun_extract(tmp_path: Path) -> None:
    """An explicit Detection retry must not trigger the OCR-backed Extract branch."""
    from mbforge.pipeline import stage_checkpoint
    from mbforge.pipeline.stage_artifacts import (
        save_detection_branch,
        save_extract_branch,
    )
    from mbforge.pipeline.stages.detection_stage import DetectionStage
    from mbforge.pipeline.stages.extract_stage import ExtractStage

    library_root = tmp_path / "library"
    page = PageFrame(page=1, width=100, height=100)
    calls = {"extract": 0, "detection": 0}

    def extract(_stage, ctx) -> StageResult:  # noqa: ANN001 - test stage patch
        calls["extract"] += 1
        save_extract_branch(
            ctx.library_root,
            ExtractArtifact(
                doc_id=ctx.doc_id,
                run_id=ctx.run_id or "",
                pages=[
                    ExtractPage(
                        page_num=1,
                        width=page.width,
                        height=page.height,
                        rotation=page.rotation,
                        text="source",
                    )
                ],
            ),
        )
        return StageResult(stage="extract", status="success", message="extract")

    def detection(_stage, ctx) -> StageResult:  # noqa: ANN001 - test stage patch
        calls["detection"] += 1
        save_detection_branch(
            ctx.library_root,
            DetectionArtifact(
                doc_id=ctx.doc_id,
                run_id=ctx.run_id or "",
                pages=[
                    DetectionPage(
                        page_num=page.page,
                        width=page.width,
                        height=page.height,
                        rotation=page.rotation,
                    )
                ],
            ),
        )
        return StageResult(stage="detection", status="success", message="detection")

    with (
        patch.object(ExtractStage, "execute", extract),
        patch.object(DetectionStage, "execute", detection),
    ):
        run_pipeline(
            str(tmp_path / "document.pdf"),
            str(library_root),
            doc_id="detection-retry-doc",
        )
        from mbforge.pipeline.run_artifacts import promote_staging

        promote_staging(
            library_root / "storage" / "detection-retry-doc" / ".staging",
            library_root,
            "detection-retry-doc",
        )
        stage_checkpoint.reset_stage_for_retry(
            library_root / "storage" / "detection-retry-doc" / ".staging",
            "detection",
        )
        result = run_pipeline(
            str(tmp_path / "document.pdf"),
            str(library_root),
            doc_id="detection-retry-doc",
            resume_from_stage="detection",
        )

    assert calls == {"extract": 1, "detection": 2}
    assert result.current_stage == "detection"
    assert result.next_stage == "markdown"


def test_initial_join_sql_failure_retries_same_batch_without_downstream_stage(
    tmp_path: Path,
) -> None:
    """A failed SQL join is retried without rerunning branches or Markdown."""
    from mbforge.pipeline.persist.source_evidence import (
        persist_source_evidence as persist_source_evidence_real,
    )
    from mbforge.pipeline.stage_artifacts import (
        save_detection_branch,
        save_extract_branch,
    )
    from mbforge.pipeline.stages.detection_stage import DetectionStage
    from mbforge.pipeline.stages.extract_stage import ExtractStage
    from mbforge.pipeline.stages.markdown_stage import MarkdownStage
    from mbforge.services.documents.source_evidence import list_evidence

    library_root = tmp_path / "library"
    page = PageFrame(page=1, width=100, height=100)
    calls = {"extract": 0, "detection": 0, "persist": 0}

    def extract(_stage, ctx) -> StageResult:  # noqa: ANN001 - test stage patch
        calls["extract"] += 1
        save_extract_branch(
            ctx.library_root,
            ExtractArtifact(
                doc_id=ctx.doc_id,
                run_id=ctx.run_id or "",
                pages=[
                    ExtractPage(
                        page_num=1,
                        width=page.width,
                        height=page.height,
                        rotation=page.rotation,
                        text="source",
                        text_spans=[
                            {
                                "text": "source",
                                "bbox": [10, 20, 30, 30],
                                "block_type": 0,
                            }
                        ],
                    )
                ],
            ),
        )
        return StageResult(stage="extract", status="success", message="extract")

    def detection(_stage, ctx) -> StageResult:  # noqa: ANN001 - test stage patch
        calls["detection"] += 1
        save_detection_branch(
            ctx.library_root,
            DetectionArtifact(
                doc_id=ctx.doc_id,
                run_id=ctx.run_id or "",
                pages=[
                    DetectionPage(
                        page_num=page.page,
                        width=page.width,
                        height=page.height,
                        rotation=page.rotation,
                    )
                ],
            ),
        )
        return StageResult(stage="detection", status="success", message="detection")

    def persist(_library_root, _artifact) -> int:  # noqa: ANN001 - test patch
        calls["persist"] += 1
        if calls["persist"] == 1:
            raise RuntimeError("sqlite unavailable")
        return persist_source_evidence_real(_library_root, _artifact)

    def forbidden_markdown(_stage, _ctx) -> StageResult:  # noqa: ANN001
        raise AssertionError("Markdown ran before the SQL join was repaired")

    with (
        patch.object(ExtractStage, "execute", extract),
        patch.object(DetectionStage, "execute", detection),
        patch(
            "mbforge.pipeline.persist.source_evidence.persist_source_evidence",
            side_effect=persist,
        ),
        pytest.raises(RuntimeError, match="sqlite unavailable"),
    ):
        run_pipeline(
            str(tmp_path / "document.pdf"),
            str(library_root),
            doc_id="sql-retry-doc",
        )

    first_run_id = json.loads(
        (
            library_root / "storage" / "sql-retry-doc" / ".staging" / "_run.json"
        ).read_text(encoding="utf-8")
    )["run_id"]

    with (
        patch.object(ExtractStage, "execute", extract),
        patch.object(DetectionStage, "execute", detection),
        patch.object(MarkdownStage, "execute", forbidden_markdown),
        patch(
            "mbforge.pipeline.persist.source_evidence.persist_source_evidence",
            side_effect=persist,
        ),
    ):
        result = run_pipeline(
            str(tmp_path / "document.pdf"),
            str(library_root),
            doc_id="sql-retry-doc",
        )

    assert result.run_id != first_run_id
    assert result.current_stage == "detection"
    assert result.next_stage == "markdown"
    assert calls == {"extract": 1, "detection": 1, "persist": 2}
    assert [item.raw_text for item in list_evidence(library_root, "sql-retry-doc")] == [
        "source"
    ]


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

    from mbforge.pipeline.stages.detection_stage import DetectionStage

    events: list[dict] = []

    def _capture(event) -> None:
        events.append({"stage": event.stage, "event": event.event, "data": event.data})

    with (
        patch("mbforge.pipeline.extract_text._ocr_pages", return_value=[]),
        patch(
            "mbforge.pipeline.detection.extraction.extract_molecules_from_pdf",
            return_value=[],
        ),
        patch.object(
            DetectionStage,
            "_detect_molecules",
            return_value={
                "molecule_count": 1,
                "rejected_count": 0,
                "pending_review_count": 0,
                "results": [fake_result],
            },
        ),
        patch(
            "mbforge.pipeline.run_artifacts.publish_run",
            side_effect=RuntimeError("disk full"),
        ),
        pytest.raises(RuntimeError, match="disk full"),
    ):
        _run_all_stages(
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


def test_resume_after_complete_fork_advances_past_detection(
    sample_pdf: Path, tmp_path: Path
) -> None:
    """Resuming a run whose initial fork is done must not loop on "detection".

    The worker re-queues with ``stage`` = the last completed stage after every
    invocation. Once extract+detection both succeed, that value is "detection".
    A resume that re-enters the fork block returns current_stage="detection"
    again, so the worker re-queues at "detection" forever and markdown never
    runs. This drives the whole pipeline to a terminal state — any loop on the
    initial fork turns the bounded driver into a TimeoutError.
    """
    library_root = tmp_path / "library"
    library_root.mkdir(parents=True, exist_ok=True)

    with (
        patch(
            "mbforge.pipeline.detection.extraction.extract_molecules_from_pdf",
            return_value=[],
        ),
        patch(
            "mbforge.pipeline.extract_text._ocr_pages",
            return_value=["ocr page 1", "ocr page 2"],
        ),
    ):
        result = _run_all_stages_bounded(
            str(sample_pdf),
            str(library_root),
            doc_id="sample_doc",
        )

    assert result.current_stage == "patent"
    assert result.next_stage is None
    assert (library_root / "storage" / "sample_doc" / "document.md").exists()


def test_pipeline_persists_markdown(sample_pdf: Path, tmp_path: Path) -> None:
    library_root = tmp_path / "library"
    library_root.mkdir(parents=True, exist_ok=True)

    with (
        patch(
            "mbforge.pipeline.detection.extraction.extract_molecules_from_pdf",
            return_value=[],
        ),
        patch(
            "mbforge.pipeline.extract_text._ocr_pages",
            return_value=["ocr page 1", "ocr page 2"],
        ),
    ):
        result = _run_all_stages(
            str(sample_pdf),
            str(library_root),
            doc_id="sample_doc",
        )

    assert result.doc_id == "sample_doc"
    assert (library_root / "storage" / "sample_doc" / "document.md").exists()
    # The last invocation runs the Patent stage only; earlier stages
    # completed in prior invocations (simulated by _run_all_stages).
    assert result.current_stage == "patent"
    assert result.next_stage is None
    assert "patent" in result.stage_timings


def test_progress_callback_failure_does_not_abort_pipeline(
    tmp_path: Path,
) -> None:
    """A broken progress sink must not discard completed pipeline work."""

    class _MinimalStage:
        name = "test"

        def execute(self, ctx) -> StageResult:  # noqa: ANN001 - protocol fixture
            return StageResult(stage="test", status="success", message="ok")

    def _broken_progress(_event) -> None:  # noqa: ANN001 - callback fixture
        raise OSError("stdout pipe closed")

    with patch(
        "mbforge.pipeline.runner._effective_stages", return_value=[_MinimalStage()]
    ):
        result = run_pipeline(
            str(tmp_path / "document.pdf"),
            str(tmp_path / "library"),
            doc_id="progress-callback",
            on_progress=_broken_progress,
        )

    assert result.doc_id == "progress-callback"
    assert result.stage_timings.keys() == {"test"}


def test_resume_missing_extraction_artifact_does_not_restart_from_extract(
    tmp_path: Path,
) -> None:
    """A resume does not silently downgrade to an earlier stage."""
    ran: list[str] = []

    class ExtractStage:
        name = "extract"

        def execute(self, ctx) -> StageResult:  # noqa: ANN001 - protocol fixture
            ran.append("extract")
            return StageResult(stage="extract", status="success", message="ok")

    class DetectionStage:
        name = "detection"

        def execute(self, ctx) -> StageResult:  # noqa: ANN001 - protocol fixture
            ran.append("detection")
            return StageResult(stage="detection", status="success", message="ok")

    with patch(
        "mbforge.pipeline.runner._effective_stages",
        return_value=[ExtractStage(), DetectionStage()],
    ):
        result = run_pipeline(
            str(tmp_path / "document.pdf"),
            str(tmp_path / "library"),
            doc_id="stale-doc",
            resume_from_stage="extract",
        )

    assert ran == ["detection"]
    assert result.current_stage == "detection"
    assert result.next_stage == "markdown"
