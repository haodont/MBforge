"""Markush mount endpoints (list / create / decide)."""

from __future__ import annotations

from fastapi import APIRouter

from ...models.markush_sites import (
    MarkushMountCreate,
    MarkushMountDecision,
    MarkushMountListRequest,
    MarkushMountListResponse,
)
from ...services.markush._db import resolve_db, run_db_sync
from ...services.markush.sites import create_mount, decide_mount, list_mounts

router = APIRouter()


@router.post("/mounts/list", response_model=MarkushMountListResponse)
async def mounts_list_endpoint(
    body: MarkushMountListRequest,
) -> MarkushMountListResponse:
    db = resolve_db(body.library_root)
    items = await run_db_sync(
        db,
        lambda conn: list_mounts(
            conn,
            site_id=body.site_id,
            scaffold_id=body.scaffold_id,
            fragment_id=body.fragment_id,
        ),
    )
    return MarkushMountListResponse(items=items)


@router.post("/mounts/create")
async def mounts_create_endpoint(body: MarkushMountCreate) -> dict:
    db = resolve_db(body.library_root)
    mount = await run_db_sync(
        db,
        lambda conn: create_mount(
            conn,
            site_id=body.site_id,
            fragment_id=body.fragment_id,
            origin=body.origin,
            confidence=body.confidence,
            reasons=body.reasons,
        ),
    )
    return mount.model_dump(mode="json")


@router.post("/mounts/decide")
async def mounts_decide_endpoint(body: MarkushMountDecision) -> dict:
    db = resolve_db(body.library_root)
    mount = await run_db_sync(
        db,
        lambda conn: decide_mount(
            conn, mount_id=body.mount_id, action=body.action, reason=body.reason
        ),
    )
    return mount.model_dump(mode="json")
