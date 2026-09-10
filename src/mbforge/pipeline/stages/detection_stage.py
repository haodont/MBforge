"""Detection branch: molecule detection and recognition.

Separates molecule detection from Markdown generation so they can be
retried independently.

The branch reads the PDF directly and does not depend on Extract.

Writes:
    ctx.candidates: list[NormalizedMolecule]
    ctx.molecule_stats: dict
    DetectionArtifact for the initial branch
"""

from typing import NotRequired, TypedDict

from ...core.stage import register
from ...utils.logger import get_logger
from ..cancellation import TaskCancelledError, default_registry, make_cancel_check
from ..context import PipelineContext
from ..stage_result import PipelineErrorCode, StageResult

logger = get_logger("mbforge.pipeline.stages.molecule_detection")


class DetectionResult(TypedDict):
    """Shape of the dict returned by DetectionStage."""

    results: list
    molecule_count: int
    rejected_count: int
    skipped: NotRequired[bool]
    reason: NotRequired[str]
    error: NotRequired[str]
    error_code: NotRequired[str]
    sources: NotRequired[list[str]]
    pending_review_count: NotRequired[int]
    total_candidates: NotRequired[int]
    tool_stats: NotRequired[dict[str, int]]


@register(after="extract")
class DetectionStage:
    name = "detection"

    def execute(self, ctx: PipelineContext) -> StageResult:
        """Detect molecules and write only the DetectionArtifact.

        The branch archives molecule crops before publishing its artifact.
        Markdown owns the final document writer.
        """
        if not ctx.run_id:
            logger.error(
                "Molecule detection stage requires a run context for %s",
                ctx.doc_id,
            )
            return StageResult(
                stage="detection",
                status="error",
                message="Missing run context",
                error_code=PipelineErrorCode.MISSING_CONTEXT,
                recoverable=False,
            )

        logger.info("Detecting molecules for %s", ctx.doc_id)
        ctx.molecule_stats = self._detect_molecules(ctx)
        ctx.candidates = []

        molecule_count = ctx.molecule_stats.get("molecule_count", 0)

        if ctx.molecule_stats.get("skipped"):
            logger.info(
                "Molecule detection skipped for %s: %s",
                ctx.doc_id,
                ctx.molecule_stats.get("reason"),
            )

        detection_error = ctx.molecule_stats.get("error") or ctx.molecule_stats.get(
            "error_code"
        )
        detection_failed = bool(detection_error)

        if detection_failed:
            return StageResult(
                stage="detection",
                status="error",
                message=f"Molecule detection failed: {detection_error}",
                error_code=ctx.molecule_stats.get("error_code"),
                recoverable=False,
                context={
                    "molecule_count": molecule_count,
                    "detection_error": detection_error,
                },
            )

        from ..stage_artifacts import (
            build_detection_artifact,
            page_frames_from_pdf,
            save_detection_branch,
        )

        save_detection_branch(
            ctx.library_root,
            build_detection_artifact(
                ctx.doc_id,
                ctx.run_id,
                ctx.molecule_stats.get("results", []),
                ctx.molecule_stats,
                page_frames_from_pdf(ctx.pdf_path),
                library_root=ctx.library_root,
                staging_dir=ctx.staging_dir,
            ),
        )

        return StageResult(
            stage="detection",
            status="success",
            message=f"Detected {molecule_count} molecules",
            context={
                "molecule_count": molecule_count,
                "rejected_count": ctx.molecule_stats.get("rejected_count", 0),
                "skipped": ctx.molecule_stats.get("skipped", False),
                "tool_stats": ctx.molecule_stats.get("tool_stats", {}),
            },
        )

    def _detect_molecules(self, ctx: PipelineContext) -> DetectionResult:
        """Internal: molecule detection logic.

        Detection owns its PDF read and never consumes Extract output. The
        lower-level extractor therefore runs its independent full-page path.
        """
        from ..detection.extraction import extract_molecules_from_pdf
        try:
            image_results = extract_molecules_from_pdf(
                str(ctx.pdf_path),
                str(ctx.library_root),
                ctx.doc_id,
                cancel_check=make_cancel_check(default_registry, ctx.task_id),
                staging_dir=str(ctx.staging_dir)
                if ctx.staging_dir is not None
                else None,
            )
        except TaskCancelledError:
            raise
        except Exception as e:
            logger.warning("Molecule image extraction failed: %s", e)
            return {
                "molecule_count": 0,
                "rejected_count": 0,
                "skipped": True,
                "reason": f"extraction_failed: {e}",
                "error": f"extraction_failed: {e}",
                "error_code": PipelineErrorCode.MOLDET_UNAVAILABLE,
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
