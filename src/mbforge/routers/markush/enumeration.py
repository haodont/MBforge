"""Markush enumeration endpoints (preview / run / results / generated-decide)."""

from __future__ import annotations

from fastapi import APIRouter

from ...core.markush.enumeration import (
    SiteSelection,
)
from ...core.markush.enumeration import (
    preview as core_preview,
)
from ...models.markush_enumeration import (
    EnumerationPreviewRequest,
    EnumerationPreviewResponse,
    EnumerationResultItem,
    EnumerationResultsRequest,
    EnumerationResultsResponse,
    EnumerationRunRequest,
    EnumerationRunResponse,
    GeneratedDecisionRequest,
)
from ...services.markush._db import resolve_db, run_db_sync
from ...services.markush.enumeration import (
    apply_generated_decision,
    list_run_results,
    resolve_authorized_selection,
    run_enumeration,
)
from ...utils.errors import ValidationError
from ._shared import to_selections

router = APIRouter()


@router.post(
    "/enumeration/preview",
    response_model=EnumerationPreviewResponse,
)
async def enumeration_preview_endpoint(
    body: EnumerationPreviewRequest,
) -> EnumerationPreviewResponse:
    """Count theoretical combinations; no rows written."""
    db = resolve_db(body.library_root)
    selections = to_selections(body.selection)

    def _preview_op(conn):
        _, resolved = resolve_authorized_selection(
            conn,
            scaffold_id=body.scaffold_id,
            selection=selections,
        )
        sel = [
            SiteSelection(
                site_label=r.site_label,
                atom_map_num=r.atom_map_num,
                fragments=[f.fragment_id for f in r.fragments],
            )
            for r in resolved
        ]
        return core_preview(sel, requested_limit=body.requested_limit)

    info = await run_db_sync(db, _preview_op)
    return EnumerationPreviewResponse(
        theoretical_count=info["theoretical_count"],
        requested_limit=info["requested_limit"],
        truncated=info["truncated"],
    )


@router.post(
    "/enumeration/run",
    response_model=EnumerationRunResponse,
)
async def enumeration_run_endpoint(
    body: EnumerationRunRequest,
) -> EnumerationRunResponse:
    """Run bounded enumeration; persists run + generated candidates."""
    db = resolve_db(body.library_root)
    selections = to_selections(body.selection)
    result = await run_db_sync(
        db,
        lambda conn: run_enumeration(
            conn,
            scaffold_id=body.scaffold_id,
            selection=selections,
            requested_limit=body.requested_limit,
        ),
    )
    return EnumerationRunResponse(
        run_id=result.run_id,
        theoretical_count=result.theoretical_count,
        written_count=result.written_count,
        truncated=result.truncated,
        status=result.status,
        error=result.error,
    )


@router.post(
    "/enumeration/results",
    response_model=EnumerationResultsResponse,
)
async def enumeration_results_endpoint(
    body: EnumerationResultsRequest,
) -> EnumerationResultsResponse:
    """List every generated candidate for a given ``run_id``."""
    db = resolve_db(body.library_root)
    if not body.run_id:
        raise ValidationError("run_id is required")
    items = await run_db_sync(db, lambda conn: list_run_results(conn, body.run_id))
    return EnumerationResultsResponse(
        items=[EnumerationResultItem(**item) for item in items],
    )


@router.post("/generated/decide")
async def generated_decide_endpoint(body: GeneratedDecisionRequest) -> dict:
    """Confirm or reject a generated candidate.

    ``confirm`` promotes the candidate into the ``molecules`` table and
    flips ``review_status='confirmed'``; ``reject`` flips it to
    ``rejected`` without writing to ``molecules``.
    """
    db = resolve_db(body.library_root)
    return await run_db_sync(
        db,
        lambda conn: apply_generated_decision(
            conn,
            entity_id=body.entity_id,
            action=body.action,
            reason=body.reason,
        ),
    )
