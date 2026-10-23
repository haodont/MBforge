"""Unit tests for pipeline stages.

Covers the stage registry/protocol, ``run_pipeline`` root validation, the
``MarkdownStage``/``ExtractStage`` executor contracts (including the molecule
pass and its degradation paths) and the rough-Markdown writer.
"""

from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

import pytest

from mbforge.db.source_evidence import persist_source_evidence
from mbforge.domain.evidence import SourceEvidence
from mbforge.domain.types import ExtractionResult
from mbforge.service.pipeline.artifacts.evidence_models import PageFrame
from mbforge.service.pipeline.extract.text import ExtractedDocument, PageContent
from mbforge.service.pipeline.run.context import PipelineContext
from mbforge.service.pipeline.runner import STAGES, run_pipeline
from mbforge.service.pipeline.stage import (
    PipelineErrorCode,
    StageExecutor,
    StageResult,
)
from mbforge.service.pipeline.stages import ExtractStage, MarkdownStage

#: The molecule pass lives inside ExtractStage; every ExtractStage test must
#: stub it so the suite never loads real detector/recognizer weights.
_MOLECULE_PASS = (
    "mbforge.service.pipeline.detection.extraction.extract_molecules_from_pdf"
)

#: The layout producer is the page-text source; stub it in every stage test.
_LAYOUT_TEXT = "mbforge.service.pipeline.extract.text.extract_layout_text"

_LAYOUT_FRAMES = "mbforge.service.pipeline.artifacts.evidence_join.page_frames_from_pdf"


def _molecule_result() -> ExtractionResult:
    """A text-sourced molecule observation (no archived crop to resolve).

    ``bbox_pdf`` is a list on purpose: that is the shape the JSON payload and the
    producer hand over, and Extract matches it against the evidence location
    index, so the value must be normalised to a hashable tuple on the way in.
    """
    return ExtractionResult(
        esmiles="CCO<sep>",
        smiles="CCO",
        name="EtOH",
        moldet_conf=0.9,
        bbox_pdf=[10.0, 20.0, 30.0, 40.0],  # type: ignore[arg-type]
        page_idx=0,
    )


def _layout_doc(raw_text: str = "hello") -> ExtractedDocument:
    """One single-page document as the layout producer emits it."""
    return ExtractedDocument(
        raw_text=raw_text,
        page_count=1,
        parser="layout",
        pages=[PageContent(page_num=1, text=raw_text)],
    )


def _context(
    tmp_path: Path,
    doc_id: str,
    pdf_name: str = "x.pdf",
    *,
    run_id: str | None = "run-1",
) -> PipelineContext:
    return PipelineContext(
        pdf_path=tmp_path / pdf_name,
        library_root=tmp_path,
        doc_id=doc_id,
        run_id=run_id,
    )


class TestStageExecutors:
    """Test stage executor protocols."""

    def test_registry_satisfies_protocol_and_runs_in_document_order(self):
        """Step 5: every registered stage is a StageExecutor, in document order."""
        for stage in STAGES:
            assert isinstance(stage, StageExecutor), (
                f"{type(stage).__name__} should satisfy StageExecutor"
            )

        assert [type(stage).__name__ for stage in STAGES] == [
            "ExtractStage",
            "MarkdownStage",
            "PatentStage",
        ]

        class BadStage:
            pass

        assert not isinstance(BadStage(), StageExecutor)


class TestRunPipelineMissingRoot:
    """Step 3: run_pipeline must reject empty library_root."""

    def test_run_pipeline_rejects_missing_library_root(self, tmp_path):
        with pytest.raises(ValueError) as exc_info:
            run_pipeline("dummy.pdf", library_root=None)
        msg = str(exc_info.value)
        assert "library_root" in msg, msg

        with pytest.raises(ValueError):
            run_pipeline("dummy.pdf", library_root="")

        # A valid library_root is accepted (the run then fails on the missing
        # PDF, but never with the root-rejection ValueError).
        lib = tmp_path / "library"
        lib.mkdir()
        with pytest.raises(Exception) as exc_info:
            run_pipeline(str(tmp_path / "nope.pdf"), library_root=str(lib))
        assert not isinstance(exc_info.value, ValueError) or (
            "library_root" not in str(exc_info.value)
        )


class TestStageNullChecks:
    """Stage executors must guard against missing upstream context."""

    def test_markdown_stage_requires_evidence_and_persists_canonical_markdown(
        self, tmp_path
    ):
        missing = _context(tmp_path, "t-missing", run_id=None)
        result = MarkdownStage().execute(missing)
        assert result.status == "error"
        assert result.error_code == PipelineErrorCode.MISSING_CONTEXT

        source = SourceEvidence.create(
            doc_id="t-markdown-persist",
            page=1,
            bbox=(10.0, 70.0, 50.0, 80.0),
            raw_text="Source text",
        )
        persist_source_evidence(tmp_path, [source])
        ctx = _context(tmp_path, "t-markdown-persist")
        ctx.extracted = ExtractedDocument(
            raw_text="Source text",
            page_count=1,
            parser="test",
            pages=[PageContent(page_num=1, text="Source text")],
        )

        result = MarkdownStage().execute(ctx)

        assert result.status == "success"
        assert ctx.rough_md_path is not None
        assert ctx.rough_md_path.exists()
        assert "Source text" in ctx.rough_md_path.read_text(encoding="utf-8")
        assert ctx.document_md_path is not None
        assert ctx.document_md_path.exists()
        assert "Source text" in ctx.document_md_path.read_text(encoding="utf-8")


class TestExtractStage:
    """Step 11: cover ExtractStage happy path and PDF failure path."""

    def test_execute_success_reports_molecules_and_page_stats(self, tmp_path):
        """Extract owns the molecule pass, so its results land in the context."""
        fake_doc = _layout_doc()
        ctx = _context(tmp_path, "t-molecules", "fake.pdf")
        molecules = [_molecule_result()]

        with (
            patch(_LAYOUT_TEXT, return_value=fake_doc),
            patch(_MOLECULE_PASS, return_value=molecules),
            patch(
                _LAYOUT_FRAMES,
                return_value=[PageFrame(page=1, width=100.0, height=100.0)],
            ),
        ):
            result = ExtractStage().execute(ctx)

        assert isinstance(result, StageResult)
        assert result.status == "success"
        assert result.warnings == []
        assert result.context["molecule_count"] == 1
        assert result.context["page_count"] == 1
        assert result.context["parser"] == "layout"
        assert ctx.extracted is fake_doc
        assert ctx.molecule_stats["results"] == molecules
        # Candidates are always rebuilt from the artifact at Join/Patent.
        assert ctx.candidates == []

    def test_extract_stage_queues_markush_with_canonical_evidence(self, tmp_path):
        from mbforge.db.markush_transitions import get_candidate_detail
        from mbforge.db.sqlite.database import DatabaseManager

        fake_doc = ExtractedDocument(
            raw_text="Formula I compounds",
            page_count=1,
            parser="layout",
            pages=[PageContent(page_num=1, text="Formula I compounds")],
        )
        result = _molecule_result()
        result.smiles = "*c1ccccc1"
        result.esmiles = "*c1ccccc1<sep>R"
        result.properties = {"markush": True, "groups": "R1"}
        ctx = _context(tmp_path, "t-markush-queue", "fake.pdf")

        with (
            patch(_LAYOUT_TEXT, return_value=fake_doc),
            patch(_MOLECULE_PASS, return_value=[result]),
            patch(
                _LAYOUT_FRAMES,
                return_value=[PageFrame(page=1, width=100.0, height=100.0)],
            ),
        ):
            stage_result = ExtractStage().execute(ctx)

        assert stage_result.status == "success"
        assert stage_result.context["markush_review_candidate_count"] == 1
        database = DatabaseManager.get(str(tmp_path))
        with database.mol_conn() as conn:
            candidate_id = conn.execute(
                "SELECT candidate_id FROM markush_review_candidates WHERE doc_id = ?",
                (ctx.doc_id,),
            ).fetchone()["candidate_id"]
            candidate = get_candidate_detail(conn, candidate_id)
            source_id = conn.execute(
                "SELECT evidence_id FROM source_evidence "
                "WHERE doc_id = ? AND kind = 'molecule'",
                (ctx.doc_id,),
            ).fetchone()["evidence_id"]

        assert candidate.predicted_role == "fragment"
        assert candidate.evidence[0].source_evidence_id == source_id

    def test_molecule_pass_failure_does_not_fail_the_document(self, tmp_path):
        """A molecule-side failure keeps the page text evidence alive."""
        fake_doc = _layout_doc()
        ctx = _context(tmp_path, "t-molecule-error")

        with (
            patch(_LAYOUT_TEXT, return_value=fake_doc),
            patch(_MOLECULE_PASS, side_effect=RuntimeError("crop archive missing")),
            patch(
                _LAYOUT_FRAMES,
                return_value=[PageFrame(page=1, width=100.0, height=100.0)],
            ),
        ):
            result = ExtractStage().execute(ctx)

        assert result.status == "success"
        assert ctx.extracted is fake_doc
        assert ctx.molecule_stats["molecule_count"] == 0
        assert "crop archive missing" in ctx.molecule_stats["error"]
        assert any("crop archive missing" in w for w in result.warnings)

    def test_execute_reports_extraction_and_layout_failures(self, tmp_path):
        """PDF corruption and a missing layout model are distinct, fatal errors."""
        from mbforge.service.pipeline.layout.parse import LayoutUnavailableError

        ctx = _context(tmp_path, "t2", "bad.pdf")

        with (
            patch(_LAYOUT_TEXT, side_effect=ValueError("corrupt pdf")),
            patch(_MOLECULE_PASS, return_value=[]),
        ):
            result = ExtractStage().execute(ctx)

        assert result.status == "error"
        assert result.recoverable is False
        assert "Text extraction failed" in result.message
        assert ctx.extracted is None

        # A missing local layout model is actionable, not PDF corruption.
        scan_ctx = _context(tmp_path, "t-scan", "scan.pdf")

        with (
            patch(
                _LAYOUT_TEXT,
                side_effect=LayoutUnavailableError(
                    "Hiro-Layout model is not available; cannot produce a local layout"
                ),
            ),
            patch(_MOLECULE_PASS, return_value=[]),
        ):
            result = ExtractStage().execute(scan_ctx)

        assert result.status == "error"
        assert result.error_code == PipelineErrorCode.LAYOUT_UNAVAILABLE
        assert result.recoverable is False
        assert "Layout detection unavailable" in result.message


def test_write_rough_markdown_keeps_page_text_verbatim(tmp_path: Path) -> None:
    """The rough markdown copies page text as-is and marks each page boundary."""
    from mbforge.service.pipeline.stages.markdown_stage import write_rough_markdown

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
