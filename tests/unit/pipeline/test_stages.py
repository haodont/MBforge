"""Unit tests for pipeline stages."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

import pytest

from mbforge.core.evidence import SourceEvidence
from mbforge.pipeline.context import PipelineContext
from mbforge.pipeline.evidence_artifacts import DocumentEvidenceArtifact, PageFrame
from mbforge.pipeline.persist.source_evidence import persist_source_evidence
from mbforge.pipeline.runner import STAGES, run_pipeline
from mbforge.pipeline.stage_result import PipelineErrorCode, StageResult
from mbforge.pipeline.stages import (
    DetectionStage,
    ExtractStage,
    MarkdownStage,
)
from mbforge.pipeline.stages.base import StageExecutor


class TestStageExecutors:
    """Test stage executor protocols."""

    def test_all_stages_satisfy_runtime_checkable_protocol(self):
        """Step 5: @runtime_checkable Protocol must accept every stage."""
        for stage in STAGES:
            assert isinstance(stage, StageExecutor), (
                f"{type(stage).__name__} should satisfy StageExecutor"
            )

    def test_stage_registry_runs_in_document_order(self):
        assert [type(stage).__name__ for stage in STAGES] == [
            "ExtractStage",
            "DetectionStage",
            "MarkdownStage",
            "PatentStage",
        ]

    def test_nonconforming_stage_rejected_by_protocol(self):
        """Step 5: a class missing execute() must fail isinstance()."""

        class BadStage:
            pass

        assert not isinstance(BadStage(), StageExecutor)


class TestRunPipelineMissingRoot:
    """Step 3: run_pipeline must reject empty library_root."""

    def test_none_library_root_raises_value_error(self, tmp_path):
        with pytest.raises(ValueError) as exc_info:
            run_pipeline("dummy.pdf", library_root=None)
        msg = str(exc_info.value)
        assert "library_root" in msg, msg

    def test_empty_library_root_raises_value_error(self, tmp_path):
        with pytest.raises(ValueError):
            run_pipeline("dummy.pdf", library_root="")

    def test_library_root_accepted(self, tmp_path):
        """When a valid library_root is given, run_pipeline must not raise ValueError."""
        # We expect it to fail later (PDF doesn't exist) but the root resolution
        # must succeed.
        lib = tmp_path / "library"
        lib.mkdir()
        with pytest.raises(Exception) as exc_info:
            run_pipeline(str(tmp_path / "nope.pdf"), library_root=str(lib))
        # Must NOT be the root-rejection ValueError
        assert not isinstance(exc_info.value, ValueError) or (
            "library_root" not in str(exc_info.value)
        )


class TestStageNullChecks:
    """Stage executors must guard against missing upstream context."""

    def test_markdown_stage_requires_joined_evidence(self, tmp_path):
        ctx = PipelineContext(
            pdf_path=tmp_path / "x.pdf",
            library_root=tmp_path,
            doc_id="t-missing",
        )
        result = MarkdownStage().execute(ctx)
        assert result.status == "error"
        assert result.error_code == PipelineErrorCode.MISSING_CONTEXT

    def test_markdown_stage_persists_canonical_markdown(self, tmp_path):
        from mbforge.pipeline.extract_text import ExtractedDocument, PageContent

        source = SourceEvidence.create(
            doc_id="t-markdown-persist",
            page=1,
            bbox=(10.0, 70.0, 50.0, 80.0),
            raw_text="Source text",
        )
        evidence = DocumentEvidenceArtifact(
            doc_id="t-markdown-persist",
            run_id="run-1",
            conventions={"origin": "bottom-left"},
            pages=[PageFrame(page=1, width=100.0, height=100.0)],
            evidence=[source],
        )
        persist_source_evidence(tmp_path, evidence)
        ctx = PipelineContext(
            pdf_path=tmp_path / "x.pdf",
            library_root=tmp_path,
            doc_id="t-markdown-persist",
            run_id="run-1",
            extracted=ExtractedDocument(
                raw_text="Source text",
                page_count=1,
                parser="test",
                pages=[PageContent(page_num=1, text="Source text")],
            ),
        )
        result = MarkdownStage().execute(ctx)

        assert result.status == "success"
        assert ctx.rough_md_path is not None
        assert ctx.rough_md_path.exists()
        assert "Source text" in ctx.rough_md_path.read_text(encoding="utf-8")
        assert ctx.document_md_path is not None
        assert ctx.document_md_path.exists()
        assert "Source text" in ctx.document_md_path.read_text(encoding="utf-8")

    def test_detection_stage_does_not_read_extract_context(self, tmp_path):
        """Detection's independent branch must not consume Extract output."""

        class ForbiddenExtract:
            @property
            def pages(self):
                raise AssertionError("Detection read Extract output")

        ctx = PipelineContext(
            pdf_path=tmp_path / "x.pdf",
            library_root=tmp_path,
            doc_id="t-detection-independent",
            run_id="run-1",
            extracted=ForbiddenExtract(),
        )
        with (
            patch(
                "mbforge.pipeline.detection.extraction.extract_molecules_from_pdf",
                return_value=[],
            ),
            patch(
                "mbforge.pipeline.stage_artifacts.page_frames_from_pdf",
                return_value=[],
            ),
            patch("mbforge.pipeline.stage_artifacts.save_detection_branch"),
        ):
            result = DetectionStage().execute(ctx)

        assert result.status == "success"

    def test_detection_stage_keeps_extraction_error_detail(self, tmp_path):
        """A MolDet-side failure must expose its cause for a targeted retry."""
        ctx = PipelineContext(
            pdf_path=tmp_path / "x.pdf",
            library_root=tmp_path,
            doc_id="t-detection-error",
            run_id="run-1",
        )
        with patch(
            "mbforge.pipeline.detection.extraction.extract_molecules_from_pdf",
            side_effect=RuntimeError("crop archive missing"),
        ):
            result = DetectionStage().execute(ctx)

        assert result.status == "error"
        assert result.error_code == PipelineErrorCode.MOLDET_UNAVAILABLE
        assert "crop archive missing" in result.message


class TestExtractStage:
    """Step 11: cover ExtractStage happy path and PDF failure path."""

    def test_execute_success(self, tmp_path):
        """Mock extract_pdf_text to return a fake ExtractedDocument."""
        from mbforge.pipeline.extract_text import ExtractedDocument, PageContent

        fake_doc = ExtractedDocument(
            raw_text="hello",
            page_count=1,
            parser="pymupdf",
            pages=[PageContent(page_num=1, text="hello")],
        )
        ctx = PipelineContext(
            pdf_path=tmp_path / "fake.pdf",
            library_root=tmp_path,
            doc_id="t1",
            run_id="run-1",
        )

        with (
            patch(
                "mbforge.pipeline.extract_text.extract_document_text",
                return_value=fake_doc,
            ),
            patch(
                "mbforge.pipeline.stage_artifacts.page_frames_from_pdf",
                return_value=[PageFrame(page=1, width=100.0, height=100.0)],
            ),
        ):
            result = ExtractStage().execute(ctx)

        assert isinstance(result, StageResult)
        assert result.status == "success"
        assert ctx.extracted is fake_doc
        assert result.context["page_count"] == 1
        assert result.context["parser"] == "pymupdf"

    def test_execute_failure_returns_error_result(self, tmp_path):
        """When extract_pdf_text raises, stage returns error result (does NOT raise)."""
        ctx = PipelineContext(
            pdf_path=tmp_path / "bad.pdf",
            library_root=tmp_path,
            doc_id="t2",
            run_id="run-1",
        )

        with patch(
            "mbforge.pipeline.extract_text.extract_document_text",
            side_effect=ValueError("corrupt pdf"),
        ):
            result = ExtractStage().execute(ctx)

        assert result.status == "error"
        assert result.recoverable is False
        assert "Text extraction failed" in result.message
        assert ctx.extracted is None

    def test_execute_reports_ocr_unavailable_separately(self, tmp_path):
        """Missing cloud OCR is actionable and must not look like PDF corruption."""
        from mbforge.backends.ocr.chain import OCRUnavailableError

        ctx = PipelineContext(
            pdf_path=tmp_path / "scan.pdf",
            library_root=tmp_path,
            doc_id="t-scan",
            run_id="run-1",
        )

        with patch(
            "mbforge.pipeline.extract_text.extract_document_text",
            side_effect=OCRUnavailableError(
                "no configured cloud OCR backend available"
            ),
        ):
            result = ExtractStage().execute(ctx)

        assert result.status == "error"
        assert result.error_code == PipelineErrorCode.OCR_UNAVAILABLE
        assert result.recoverable is False
        assert "OCR unavailable" in result.message


def test_write_rough_markdown_replaces_ocr_image_paths(tmp_path: Path) -> None:
    """OCR-backend relative image references must be rewritten to absolute paths."""
    from mbforge.pipeline.stages.markdown_stage import write_rough_markdown

    # Simulate a page whose OCR text contains OCR-backend image refs.
    images_dir = tmp_path / "images"
    images_dir.mkdir()
    (images_dir / "figure_001.jpg").write_bytes(b"\xff\xd8")
    (images_dir / "figure_002.png").write_bytes(b"\x89PNG")

    class FakePage:
        def __init__(self, num: int, text: str, ocr_images: list[str]) -> None:
            self.page_num = num
            self.text = text
            self.ocr_images = ocr_images

    pages = [
        FakePage(
            1,
            "Some intro text\n![](images/figure_001.jpg)\nMore text here",
            ["images/figure_001.jpg"],
        ),
        FakePage(2, "Plain text only", []),
        FakePage(
            3,
            "![](images/figure_002.png)\nConclusion",
            ["images/figure_002.png"],
        ),
    ]

    output_md = tmp_path / "output.md"
    write_rough_markdown(pages, str(output_md), images_dir=images_dir)

    content = output_md.read_text(encoding="utf-8")
    expected_abs_1 = f"![]({(images_dir / 'figure_001.jpg').as_posix()})"
    expected_abs_2 = f"![]({(images_dir / 'figure_002.png').as_posix()})"

    assert expected_abs_1 in content
    assert expected_abs_2 in content
    assert "![](images/figure_001.jpg)" not in content
    assert "![](images/figure_002.png)" not in content
