"""Markush attachment-option endpoints (list / create)."""

from __future__ import annotations

from fastapi import APIRouter

from mbforge.application.dto.markush_sites import (
    MarkushOptionCreate,
    MarkushOptionListRequest,
    MarkushOptionListResponse,
)
from mbforge.application.use_cases.markush._db import resolve_db, run_db_sync
from mbforge.application.use_cases.markush.sites import create_option, list_options
from mbforge.foundation.errors import ValidationError

router = APIRouter()


@router.post("/options/list", response_model=MarkushOptionListResponse)
async def options_list_endpoint(
    body: MarkushOptionListRequest,
) -> MarkushOptionListResponse:
    db = resolve_db(body.library_root)
    if not body.site_id:
        raise ValidationError("site_id is required")
    items = await run_db_sync(db, lambda conn: list_options(conn, body.site_id))
    return MarkushOptionListResponse(items=items)


@router.post("/options/create")
async def options_create_endpoint(body: MarkushOptionCreate) -> dict:
    db = resolve_db(body.library_root)
    option = await run_db_sync(
        db,
        lambda conn: create_option(
            conn,
            site_id=body.site_id,
            fragment_id=body.fragment_id,
            normalized_smiles=body.normalized_smiles,
            definition_text=body.definition_text,
            constraints=body.constraints,
        ),
    )
    return option.model_dump(mode="json")
