"""Stage 1: Extract page layout and text with the local layout producer.

Renders every page once and runs the local Hiro-Layout detector plus its
layout-guided text recognition, so page text, layout spans, regions and
coordinates are uniform for the downstream evidence model.
"""

from __future__ import annotations

from mbforge.application.pipeline.cancellation import (
    TaskCancelledError,
    default_registry,
    make_cancel_check,
)
from mbforge.application.pipeline.run.context import PipelineContext
from mbforge.application.pipeline.stage import PipelineErrorCode, StageResult, register
from mbforge.foundation.logger import get_logger

logger = get_logger("mbforge.application.pipeline.stages.extract")


@register
class ExtractStage:
    name = "extract"
    """Stage 1: Extract page layout and text with the local layout producer."""

    def execute(self, ctx: PipelineContext) -> StageResult:
        """Extract layout regions and text from the PDF.

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
            from mbforge.application.pipeline.extract.text import extract_layout_text
            from mbforge.foundation.config import load_global_config

            cancel_check = make_cancel_check(default_registry, ctx.task_id)
            layout_config = load_global_config().layout

            # The layout producer owns the whole branch: page text comes from
            # layout-guided recognition and each page carries typed regions for
            # the join. There is no OCR provider fallback.
            ctx.extracted = extract_layout_text(
                str(ctx.pdf_path),
                doc_id=ctx.doc_id,
                layout_config=layout_config.model_dump(),
                cancel_check=cancel_check,
            )

            from mbforge.application.pipeline.artifacts.branch_io import (
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
            from mbforge.application.pipeline.layout.parse import LayoutUnavailableError

            if isinstance(e, LayoutUnavailableError):
                error_code = PipelineErrorCode.LAYOUT_UNAVAILABLE
                message_prefix = "Layout detection unavailable"
            else:
                error_code = PipelineErrorCode.PDF_PARSE_ERROR
                message_prefix = "Text extraction failed"
            return StageResult(
                stage="extract",
                status="error",
                message=f"{message_prefix}: {e}",
                error_code=error_code,
                recoverable=False,
                context={"exception_type": type(e).__name__, "detail": str(e)},
            )
