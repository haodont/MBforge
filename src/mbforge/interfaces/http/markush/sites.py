"""Markush attachment-site endpoints (list / create / update)."""

from __future__ import annotations

from fastapi import APIRouter

from mbforge.application.dto.markush_sites import (
    MarkushSiteCreate,
    MarkushSiteListRequest,
    MarkushSiteListResponse,
    MarkushSiteUpdate,
)
from mbforge.application.use_cases.markush._db import resolve_db, run_db_sync
from mbforge.application.use_cases.markush.sites import (
    create_site,
    list_sites,
    update_site,
)
from mbforge.foundation.errors import ValidationError

router = APIRouter()


@router.post("/sites/list", response_model=MarkushSiteListResponse)
async def sites_list_endpoint(body: MarkushSiteListRequest) -> MarkushSiteListResponse:
    db = resolve_db(body.library_root)
    if not body.scaffold_id:
        raise ValidationError("scaffold_id is required")
    items = await run_db_sync(db, lambda conn: list_sites(conn, body.scaffold_id))
    return MarkushSiteListResponse(items=items)


@router.post("/sites/create")
async def sites_create_endpoint(body: MarkushSiteCreate) -> dict:
    db = resolve_db(body.library_root)
    site = await run_db_sync(
        db,
        lambda conn: create_site(
            conn,
            scaffold_id=body.scaffold_id,
            site_label=body.site_label,
            atom_map_num=body.atom_map_num,
            attachment_count=body.attachment_count,
            bond_type=body.bond_type,
            source_text=body.source_text,
        ),
    )
    return site.model_dump(mode="json")


@router.post("/sites/update")
async def sites_update_endpoint(body: MarkushSiteUpdate) -> dict:
    db = resolve_db(body.library_root)
    site = await run_db_sync(
        db,
        lambda conn: update_site(
            conn,
            site_id=body.site_id,
            site_label=body.site_label,
            atom_map_num=body.atom_map_num,
            attachment_count=body.attachment_count,
            bond_type=body.bond_type,
            source_text=body.source_text,
        ),
    )
    return site.model_dump(mode="json")
