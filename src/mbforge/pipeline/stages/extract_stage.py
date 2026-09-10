"""Stage 1: Extract text from PDF via full OCR.

Renders every page and runs the cloud OCR chain (PaddleOCR) so page text,
layout spans, and coordinates are uniform for the downstream evidence model.
Producing an ExtractedDocument with per-page text, spans, and OCR metrics.
"""

from __future__ import annotations

from ...core.stage import register
from ...storage.layout import LibraryLayout
from ...utils.logger import get_logger
from ..cancellation import TaskCancelledError, default_registry, make_cancel_check
from ..context import PipelineContext
from ..stage_result import PipelineErrorCode, StageResult

logger = get_logger("mbforge.pipeline.stages.extract")


@register
class ExtractStage:
    name = "extract"
    """Stage 1: Extract text from PDF with reliable full-document OCR."""

    def execute(self, ctx: PipelineContext) -> StageResult:
        """Extract text from PDF using the OCR chain.

        Writes:
            ctx.extracted: ExtractedDocument
        """
        if not ctx.run_id:
            return StageResult(
                stage="extract",
                status="error",
                message="Missing extract branch context",
                error_code=PipelineErrorCode.MISSING_CONTEXT,
                recoverable=False,
            )
        try:
            from ...storage.document_store import load_document
            from ..extract_text import extract_document_text

            # Full-document OCR: the Document's native cache is never an
            # evidence source (see extract_document_text).
            doc = load_document(ctx.doc_id, ctx.library_root)
            save_images_dir = (
                ctx.staging_dir / "images"
                if ctx.staging_dir is not None
                else LibraryLayout(ctx.library_root).images_dir(ctx.doc_id)
            )
            ctx.extracted = extract_document_text(
                doc,
                str(ctx.pdf_path),
                ocr_config=ctx.ocr_config,
                save_images_dir=save_images_dir,
                cancel_check=make_cancel_check(default_registry, ctx.task_id),
            )

            from ..stage_artifacts import (
                build_extract_artifact,
                page_frames_from_pdf,
                save_extract_branch,
            )

            save_extract_branch(
                ctx.library_root,
                build_extract_artifact(
                    ctx.doc_id,
                    ctx.run_id,
                    ctx.extracted,
                    page_frames_from_pdf(ctx.pdf_path),
                ),
            )

            logger.info(
                "Extracted %d pages (%d chars) from %s",
                ctx.extracted.page_count,
                len(ctx.extracted.raw_text),
                ctx.doc_id,
            )

            return StageResult(
                stage="extract",
                status="success",
                message=f"Extracted {ctx.extracted.page_count} pages ({len(ctx.extracted.raw_text)} chars)",
                context={
                    "page_count": ctx.extracted.page_count,
                    "parser": ctx.extracted.parser,
                    "ocr": ctx.extracted.ocr_stats,
                },
            )

        except TaskCancelledError:
            # Cooperative cancellation aborts the pipeline with its own
            # error code; never report it as a PDF parse failure.
            raise
        except Exception as e:
            logger.error("Text extraction failed for %s: %s", ctx.doc_id, e)
            from ...backends.ocr.chain import OCRUnavailableError

            error_code = (
                PipelineErrorCode.OCR_UNAVAILABLE
                if isinstance(e, OCRUnavailableError)
                else PipelineErrorCode.PDF_PARSE_ERROR
            )
            message_prefix = (
                "OCR unavailable"
                if isinstance(e, OCRUnavailableError)
                else "Text extraction failed"
            )
            return StageResult(
                stage="extract",
                status="error",
                message=f"{message_prefix}: {e}",
                error_code=error_code,
                recoverable=False,
                context={"exception_type": type(e).__name__, "detail": str(e)},
            )
