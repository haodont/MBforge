"""Join stage: the Extract ∥ Detection fan-in.

Extract and Detection run as two independent queue nodes (concurrently, up to
``ingest.max_concurrency``); this stage is the barrier that merges their raw
branch artifacts into the SQL ``source_evidence`` facts every downstream stage
reads. The queue DAG runs it only after both branches are ``done``, so it is a
pure merge with no waiting logic of its own.

Writes:
    ctx.source_evidence_count: number of published evidence facts
"""

from __future__ import annotations

from mbforge.application.pipeline.run.context import PipelineContext
from mbforge.application.pipeline.stage import PipelineErrorCode, StageResult, register
from mbforge.application.ports import get_repositories
from mbforge.foundation.logger import get_logger

logger = get_logger("mbforge.application.pipeline.stages.join")


@register(after="detection", depends_on=("extract", "detection"))
class JoinStage:
    name = "join"

    def execute(self, ctx: PipelineContext) -> StageResult:
        if not ctx.run_id:
            return StageResult(
                stage="join",
                status="error",
                message="Missing run context",
                error_code=PipelineErrorCode.MISSING_CONTEXT,
                recoverable=False,
            )

        from mbforge.application.pipeline.artifacts.branch_io import (
            load_detection_branch,
            load_extract_branch,
        )
        from mbforge.application.pipeline.artifacts.evidence_join import (
            join_evidence_artifacts,
        )

        extract_artifact = load_extract_branch(ctx.library_root, ctx.doc_id, ctx.run_id)
        detection_artifact = load_detection_branch(
            ctx.library_root, ctx.doc_id, ctx.run_id
        )
        if extract_artifact is None or detection_artifact is None:
            return StageResult(
                stage="join",
                status="error",
                message="initial branches are not ready to join",
                error_code=PipelineErrorCode.EVIDENCE_JOIN_FAILED,
                recoverable=False,
            )

        try:
            joined = join_evidence_artifacts(extract_artifact, detection_artifact)
            count = get_repositories(ctx.library_root).evidence.persist(joined)
        except Exception as exc:  # noqa: BLE001 — surfaced as a stage error
            logger.error("Evidence join failed for %s: %s", ctx.doc_id, exc)
            return StageResult(
                stage="join",
                status="error",
                message=f"Evidence join failed: {exc}",
                error_code=PipelineErrorCode.EVIDENCE_JOIN_FAILED,
                recoverable=False,
                context={"exception_type": type(exc).__name__, "detail": str(exc)},
            )

        ctx.source_evidence_count = count
        logger.info("Joined %d evidence facts for %s", count, ctx.doc_id)
        return StageResult(
            stage="join",
            status="success",
            message=f"Joined {count} evidence facts",
            context={"source_evidence_count": count},
        )


__all__ = ["JoinStage"]
