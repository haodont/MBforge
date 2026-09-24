"""Stage 1: Extract page layout, text and molecules with the local producers.

Two producers read the PDF from their own handles and run concurrently:

- the **layout producer** renders every page once at the layout zoom and runs
  Hiro-Layout plus layout-guided text and table recognition
  (:mod:`mbforge.application.pipeline.layout.parse`);
- the **molecule pass** renders every page at ``moldet.detection_dpi``, runs
  MolDet and reads each box into SMILES / E-SMILES with MolParser, archiving
  its crops under the staging directory
  (:mod:`mbforge.application.pipeline.detection.extraction`).

Both feed the single piece of work this stage owns: minting the canonical
``SourceEvidence`` rows and persisting them.  There is no intermediate branch
artifact — SQL is the only evidence store.
"""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from typing import Any

from mbforge.application.pipeline.cancellation import (
    TaskCancelledError,
    default_registry,
    make_cancel_check,
)
from mbforge.application.pipeline.run.context import PipelineContext
from mbforge.application.pipeline.stage import PipelineErrorCode, StageResult, register
from mbforge.foundation.logger import get_logger

logger = get_logger("mbforge.application.pipeline.stages.extract")


def _detect_molecules(ctx: PipelineContext) -> dict[str, Any]:
    """Run the molecule pass and return its raw results plus stats.

    Never fatal: a failure records the reason in the returned stats and leaves
    the document with page text and layout only, which is strictly better than
    publishing nothing at all. Crops are archived into the staging directory so
    the artifact can reference them by library-relative path.
    """
    from mbforge.application.pipeline.detection.extraction import (
        extract_molecules_from_pdf,
    )

    try:
        image_results = extract_molecules_from_pdf(
            str(ctx.pdf_path),
            str(ctx.library_root),
            ctx.doc_id,
            cancel_check=make_cancel_check(default_registry, ctx.task_id),
            staging_dir=str(ctx.staging_dir) if ctx.staging_dir is not None else None,
        )
    except TaskCancelledError:
        raise
    except Exception as exc:
        logger.warning("Molecule extraction failed for %s: %s", ctx.doc_id, exc)
        return {
            "molecule_count": 0,
            "rejected_count": 0,
            "skipped": True,
            "reason": f"extraction_failed: {exc}",
            "error": f"extraction_failed: {exc}",
            "results": [],
        }

    if not image_results:
        return {
            "molecule_count": 0,
            "rejected_count": 0,
            "skipped": True,
            "reason": "no molecule images detected",
            "results": [],
        }

    return {
        "molecule_count": len(image_results),
        "rejected_count": 0,
        "total_candidates": len(image_results),
        "results": image_results,
    }


@register
class ExtractStage:
    name = "extract"
    """Stage 1: Extract page layout, text and molecules."""

    def execute(self, ctx: PipelineContext) -> StageResult:
        """Extract layout regions, text and molecules from the PDF.

        Writes:
            ctx.extracted: ExtractedDocument
            ctx.molecule_stats: dict
            ctx.source_evidence_count: number of persisted evidence rows
            ctx.candidates: list[Molecule] — always empty; candidates are
                rebuilt from SQL at Markdown/Patent.
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
            from mbforge.application.pipeline.artifacts.evidence_join import (
                mint_evidence,
                page_frames_from_pdf,
            )
            from mbforge.application.pipeline.extract.text import extract_layout_text
            from mbforge.application.ports import get_repositories
            from mbforge.foundation.config import load_global_config

            layout_config = load_global_config().layout

            with ThreadPoolExecutor(max_workers=2) as pool:
                layout_future = pool.submit(
                    extract_layout_text,
                    str(ctx.pdf_path),
                    doc_id=ctx.doc_id,
                    layout_config=layout_config.model_dump(),
                    cancel_check=make_cancel_check(default_registry, ctx.task_id),
                )
                molecules_future = pool.submit(_detect_molecules, ctx)
                # The layout producer owns the document: without page text there
                # is no evidence at all, so its failure is fatal.
                ctx.extracted = layout_future.result()
                molecule_stats = molecules_future.result()

            ctx.molecule_stats = molecule_stats
            ctx.candidates = []

            evidence = mint_evidence(
                ctx.extracted,
                page_frames_from_pdf(ctx.pdf_path),
                list(molecule_stats.get("results", [])),
                library_root=ctx.library_root,
                staging_dir=ctx.staging_dir,
            )
            ctx.source_evidence_count = get_repositories(
                ctx.library_root
            ).evidence.persist(evidence)

            molecule_count = molecule_stats.get("molecule_count", 0)
            logger.info(
                "Extracted %d pages (%d chars, %d molecules, %d evidence rows) from %s",
                ctx.extracted.page_count,
                len(ctx.extracted.raw_text),
                molecule_count,
                ctx.source_evidence_count,
                ctx.doc_id,
            )

            warning = ""
            if molecule_stats.get("skipped"):
                warning = (
                    "molecule extraction skipped: "
                    f"{molecule_stats.get('reason', 'unknown reason')}"
                )

            return StageResult(
                stage="extract",
                status="success",
                message=(
                    f"Extracted {ctx.extracted.page_count} pages "
                    f"({len(ctx.extracted.raw_text)} chars, "
                    f"{molecule_count} molecules, "
                    f"{ctx.source_evidence_count} evidence rows)"
                ),
                warnings=[warning] if warning else [],
                context={
                    "page_count": ctx.extracted.page_count,
                    "parser": ctx.extracted.parser,
                    "title": ctx.extracted.title,
                    "ocr": ctx.extracted.ocr_stats,
                    "molecule_count": molecule_count,
                    "rejected_count": molecule_stats.get("rejected_count", 0),
                    "skipped": molecule_stats.get("skipped", False),
                    "source_evidence_count": ctx.source_evidence_count,
                    "tool_stats": molecule_stats.get("tool_stats", {}),
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


__all__ = ["ExtractStage"]
