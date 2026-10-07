"""Markush attachment-option endpoints (list / create)."""

from __future__ import annotations

import asyncio

from fastapi import APIRouter

from mbforge.api.http.markush._shared import resolve_repositories
from mbforge.foundation.errors import ValidationError
from mbforge.service.dto.markush_sites import (
    MarkushOptionCreate,
    MarkushOptionListRequest,
    MarkushOptionListResponse,
)
from mbforge.service.use_cases.markush.sites import create_option, list_options

router = APIRouter()


@router.post("/options/list", response_model=MarkushOptionListResponse)
async def options_list_endpoint(
    body: MarkushOptionListRequest,
) -> MarkushOptionListResponse:
    if not body.site_id:
        raise ValidationError("site_id is required")
    repository = resolve_repositories(body.library_root).markush
    items = await asyncio.to_thread(list_options, repository, body.site_id)
    return MarkushOptionListResponse(items=items)


@router.post("/options/create")
async def options_create_endpoint(body: MarkushOptionCreate) -> dict:
    repository = resolve_repositories(body.library_root).markush
    option = await asyncio.to_thread(
        create_option,
        repository,
        site_id=body.site_id,
        fragment_id=body.fragment_id,
        normalized_smiles=body.normalized_smiles,
        definition_text=body.definition_text,
        constraints=body.constraints,
    )
    return option.model_dump(mode="json")
