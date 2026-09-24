"""Unit tests for pipeline stages."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

import pytest

from mbforge.adapters.persistence.source_evidence import persist_source_evidence
from mbforge.application.pipeline.artifacts.evidence_models import (
    DocumentEvidenceArtifact,
    PageFrame,
)
from mbforge.application.pipeline.run.context import PipelineContext
from mbforge.application.pipeline.runner import STAGES, run_pipeline
from mbforge.application.pipeline.stage import (
    PipelineErrorCode,
    StageExecutor,
    StageResult,
)
from mbforge.application.pipeline.stages import ExtractStage, MarkdownStage
from mbforge.domain.evidence import SourceEvidence
from mbforge.domain.types import ExtractionResult

#: The molecule pass lives inside ExtractStage; every ExtractStage test must
#: stub it so the suite never loads real detector/recognizer weights.
_MOLECULE_PASS = (
    "mbforge.application.pipeline.detection.extraction.extract_molecules_from_pdf"
)


def _molecule_result() -> ExtractionResult:
    """A text-sourced molecule observation (no archived crop to resolve)."""
    return ExtractionResult(
        esmiles="CCO<sep>",
        smiles="CCO",
        name="EtOH",
        source="text",
        moldet_conf=0.9,
        bbox_pdf=(10.0, 20.0, 30.0, 40.0),
        page_idx=0,
        status="pending",
    )


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
            "JoinStage",
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
        from mbforge.application.pipeline.extract.text import (
            ExtractedDocument,
            PageContent,
        )

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

    def test_extract_stage_produces_and_reports_molecules(self, tmp_path):
        """Extract owns the molecule pass, so its results land in the context."""
        from mbforge.application.pipeline.extract.text import (
            ExtractedDocument,
            PageContent,
        )

        fake_doc = ExtractedDocument(
            raw_text="hello",
            page_count=1,
            parser="layout",
            pages=[PageContent(page_num=1, text="hello")],
        )
        ctx = PipelineContext(
            pdf_path=tmp_path / "x.pdf",
            library_root=tmp_path,
            doc_id="t-molecules",
            run_id="run-1",
        )
        molecules = [_molecule_result()]

        with (
            patch(
                "mbforge.application.pipeline.extract.text.extract_layout_text",
                return_value=fake_doc,
            ),
            patch(_MOLECULE_PASS, return_value=molecules),
            patch(
                "mbforge.application.pipeline.artifacts.branch_io.page_frames_from_pdf",
                return_value=[PageFrame(page=1, width=100.0, height=100.0)],
            ),
        ):
            result = ExtractStage().execute(ctx)

        assert result.status == "success"
        assert result.warnings == []
        assert result.context["molecule_count"] == 1
        assert ctx.molecule_stats["results"] == molecules
        # Candidates are always rebuilt from the artifact at Join/Patent.
        assert ctx.candidates == []

    def test_molecule_pass_failure_does_not_fail_the_document(self, tmp_path):
        """A molecule-side failure keeps the page text evidence alive."""
        from mbforge.application.pipeline.extract.text import (
            ExtractedDocument,
            PageContent,
        )

        fake_doc = ExtractedDocument(
            raw_text="hello",
            page_count=1,
            parser="layout",
            pages=[PageContent(page_num=1, text="hello")],
        )
        ctx = PipelineContext(
            pdf_path=tmp_path / "x.pdf",
            library_root=tmp_path,
            doc_id="t-molecule-error",
            run_id="run-1",
        )

        with (
            patch(
                "mbforge.application.pipeline.extract.text.extract_layout_text",
                return_value=fake_doc,
            ),
            patch(_MOLECULE_PASS, side_effect=RuntimeError("crop archive missing")),
            patch(
                "mbforge.application.pipeline.artifacts.branch_io.page_frames_from_pdf",
                return_value=[PageFrame(page=1, width=100.0, height=100.0)],
            ),
        ):
            result = ExtractStage().execute(ctx)

        assert result.status == "success"
        assert ctx.extracted is fake_doc
        assert ctx.molecule_stats["molecule_count"] == 0
        assert "crop archive missing" in ctx.molecule_stats["error"]
        assert any("crop archive missing" in w for w in result.warnings)


class TestExtractStage:
    """Step 11: cover ExtractStage happy path and PDF failure path."""

    def test_execute_success(self, tmp_path):
        """Mock extract_layout_text to return a fake ExtractedDocument."""
        from mbforge.application.pipeline.extract.text import (
            ExtractedDocument,
            PageContent,
        )

        fake_doc = ExtractedDocument(
            raw_text="hello",
            page_count=1,
            parser="layout",
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
                "mbforge.application.pipeline.extract.text.extract_layout_text",
                return_value=fake_doc,
            ),
            patch(_MOLECULE_PASS, return_value=[]),
            patch(
                "mbforge.application.pipeline.artifacts.branch_io.page_frames_from_pdf",
                return_value=[PageFrame(page=1, width=100.0, height=100.0)],
            ),
        ):
            result = ExtractStage().execute(ctx)

        assert isinstance(result, StageResult)
        assert result.status == "success"
        assert ctx.extracted is fake_doc
        assert result.context["page_count"] == 1
        assert result.context["parser"] == "layout"

    def test_execute_failure_returns_error_result(self, tmp_path):
        """When the layout producer raises, stage returns an error result."""
        ctx = PipelineContext(
            pdf_path=tmp_path / "bad.pdf",
            library_root=tmp_path,
            doc_id="t2",
            run_id="run-1",
        )

        with (
            patch(
                "mbforge.application.pipeline.extract.text.extract_layout_text",
                side_effect=ValueError("corrupt pdf"),
            ),
            patch(_MOLECULE_PASS, return_value=[]),
        ):
            result = ExtractStage().execute(ctx)

        assert result.status == "error"
        assert result.recoverable is False
        assert "Text extraction failed" in result.message
        assert ctx.extracted is None

    def test_execute_reports_layout_unavailable_separately(self, tmp_path):
        """A missing local layout model is actionable, not PDF corruption."""
        from mbforge.application.pipeline.layout.parse import LayoutUnavailableError

        ctx = PipelineContext(
            pdf_path=tmp_path / "scan.pdf",
            library_root=tmp_path,
            doc_id="t-scan",
            run_id="run-1",
        )

        with (
            patch(
                "mbforge.application.pipeline.extract.text.extract_layout_text",
                side_effect=LayoutUnavailableError(
                    "Hiro-Layout model is not available; cannot produce a local layout"
                ),
            ),
            patch(_MOLECULE_PASS, return_value=[]),
        ):
            result = ExtractStage().execute(ctx)

        assert result.status == "error"
        assert result.error_code == PipelineErrorCode.LAYOUT_UNAVAILABLE
        assert result.recoverable is False
        assert "Layout detection unavailable" in result.message


def test_write_rough_markdown_keeps_page_text_verbatim(tmp_path: Path) -> None:
    """The rough markdown copies page text as-is and marks each page boundary."""
    from mbforge.application.pipeline.stages.markdown_stage import write_rough_markdown

    class FakePage:
        def __init__(self, num: int, text: str) -> None:
            self.page_num = num
            self.text = text

    pages = [
        FakePage(1, "Some intro text\nMore text here"),
        FakePage(2, "Plain text only"),
    ]

    output_md = tmp_path / "output.md"
    write_rough_markdown(pages, str(output_md))

    content = output_md.read_text(encoding="utf-8")
    assert "<!-- PAGE 1 -->" in content
    assert "<!-- PAGE 2 -->" in content
    assert "Some intro text" in content
    assert "Plain text only" in content
