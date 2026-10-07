"""Markush attachment-site endpoints (list / create / update)."""

from __future__ import annotations

import asyncio

from fastapi import APIRouter

from mbforge.api.http.markush._shared import resolve_repositories
from mbforge.foundation.errors import ValidationError
from mbforge.service.dto.markush_sites import (
    MarkushSiteCreate,
    MarkushSiteListRequest,
    MarkushSiteListResponse,
    MarkushSiteUpdate,
)
from mbforge.service.use_cases.markush.sites import (
    create_site,
    list_sites,
    update_site,
)

router = APIRouter()


@router.post("/sites/list", response_model=MarkushSiteListResponse)
async def sites_list_endpoint(body: MarkushSiteListRequest) -> MarkushSiteListResponse:
    if not body.scaffold_id:
        raise ValidationError("scaffold_id is required")
    repository = resolve_repositories(body.library_root).markush
    items = await asyncio.to_thread(list_sites, repository, body.scaffold_id)
    return MarkushSiteListResponse(items=items)


@router.post("/sites/create")
async def sites_create_endpoint(body: MarkushSiteCreate) -> dict:
    repository = resolve_repositories(body.library_root).markush
    site = await asyncio.to_thread(
        create_site,
        repository,
        scaffold_id=body.scaffold_id,
        site_label=body.site_label,
        atom_map_num=body.atom_map_num,
        attachment_count=body.attachment_count,
        bond_type=body.bond_type,
        source_text=body.source_text,
    )
    return site.model_dump(mode="json")


@router.post("/sites/update")
async def sites_update_endpoint(body: MarkushSiteUpdate) -> dict:
    repository = resolve_repositories(body.library_root).markush
    site = await asyncio.to_thread(
        update_site,
        repository,
        site_id=body.site_id,
        site_label=body.site_label,
        atom_map_num=body.atom_map_num,
        attachment_count=body.attachment_count,
        bond_type=body.bond_type,
        source_text=body.source_text,
    )
    return site.model_dump(mode="json")
