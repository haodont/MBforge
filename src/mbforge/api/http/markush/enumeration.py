"""Markush enumeration endpoints (preview / run / results / generated-decide)."""

from __future__ import annotations

import asyncio

from fastapi import APIRouter

from mbforge.api.http.markush._shared import resolve_repositories, to_selections
from mbforge.domain.enumeration import (
    SiteSelection,
)
from mbforge.domain.enumeration import (
    preview as core_preview,
)
from mbforge.foundation.errors import ValidationError
from mbforge.service.dto.markush_enumeration import (
    EnumerationPreviewRequest,
    EnumerationPreviewResponse,
    EnumerationResultItem,
    EnumerationResultsRequest,
    EnumerationResultsResponse,
    EnumerationRunRequest,
    EnumerationRunResponse,
    GeneratedDecisionRequest,
)
from mbforge.service.use_cases.markush.enumeration import (
    apply_generated_decision,
    list_run_results,
    resolve_authorized_selection,
    run_enumeration,
)

router = APIRouter()


@router.post(
    "/enumeration/preview",
    response_model=EnumerationPreviewResponse,
)
async def enumeration_preview_endpoint(
    body: EnumerationPreviewRequest,
) -> EnumerationPreviewResponse:
    """Count theoretical combinations; no rows written."""
    repository = resolve_repositories(body.library_root).markush
    selections = to_selections(body.selection)

    _, resolved = await asyncio.to_thread(
        resolve_authorized_selection,
        repository,
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
    info = core_preview(sel, requested_limit=body.requested_limit)
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
    repository = resolve_repositories(body.library_root).markush
    selections = to_selections(body.selection)
    result = await asyncio.to_thread(
        run_enumeration,
        repository,
        scaffold_id=body.scaffold_id,
        selection=selections,
        requested_limit=body.requested_limit,
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
    if not body.run_id:
        raise ValidationError("run_id is required")
    repository = resolve_repositories(body.library_root).markush
    items = await asyncio.to_thread(list_run_results, repository, body.run_id)
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
    repository = resolve_repositories(body.library_root).markush
    return await asyncio.to_thread(
        apply_generated_decision,
        repository,
        entity_id=body.entity_id,
        action=body.action,
        reason=body.reason,
    )
