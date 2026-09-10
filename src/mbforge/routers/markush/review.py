"""Markush review queue endpoints (list / get / decide / update)."""

from __future__ import annotations

from fastapi import APIRouter

from ...models.markush import (
    MarkushDecisionRequest,
    MarkushDecisionResponse,
    MarkushGetRequest,
    MarkushListRequest,
    MarkushListResponse,
    MarkushUpdateRequest,
)
from ...services.markush._db import resolve_db, run_db_sync
from ...services.markush.review import apply_decision
from ...storage.markush_transitions import (
    get_candidate_detail,
    list_candidates,
    update_candidate,
)

router = APIRouter()


@router.post("/list", response_model=MarkushListResponse)
async def list_endpoint(body: MarkushListRequest) -> MarkushListResponse:
    db = resolve_db(body.library_root)
    items, total = await run_db_sync(
        db,
        lambda conn: list_candidates(
            conn,
            doc_id=body.doc_id,
            review_status=body.review_status,
            predicted_role=body.predicted_role,
            reason=body.reason,
            page=body.page,
            page_size=body.page_size,
        ),
    )
    return MarkushListResponse(
        items=items, total=total, page=body.page, page_size=body.page_size
    )


@router.post("/get")
async def get_endpoint(body: MarkushGetRequest) -> dict:
    """Return the candidate plus evidence and decisions."""
    db = resolve_db(body.library_root)
    detail = await run_db_sync(
        db, lambda conn: get_candidate_detail(conn, body.candidate_id)
    )
    return detail.model_dump(mode="json")


@router.post("/decide", response_model=MarkushDecisionResponse)
async def decide_endpoint(body: MarkushDecisionRequest) -> MarkushDecisionResponse:
    db = resolve_db(body.library_root)
    payload = await run_db_sync(
        db,
        lambda conn: apply_decision(
            conn,
            candidate_id=body.entity_id,
            expected_version=body.expected_version,
            action=body.action,
            reason=body.reason,
        ),
    )
    return MarkushDecisionResponse(
        candidate_id=str(payload.get("candidate_id", body.entity_id)),
        new_state=payload["new_state"],  # type: ignore[arg-type]
        new_version=int(payload["new_version"]),  # type: ignore[arg-type]
        molecule_id=payload.get("molecule_id"),  # type: ignore[arg-type]
        scaffold_id=payload.get("scaffold_id"),  # type: ignore[arg-type]
        fragment_id=payload.get("fragment_id"),  # type: ignore[arg-type]
    )


@router.post("/update")
async def update_endpoint(body: MarkushUpdateRequest) -> dict:
    db = resolve_db(body.library_root)
    detail = await run_db_sync(
        db,
        lambda conn: update_candidate(
            conn,
            candidate_id=body.entity_id,
            expected_version=body.expected_version,
            smiles=body.smiles,
            esmiles=body.esmiles,
            normalized_label=body.normalized_label,
            raw_label=body.raw_label,
            predicted_role=body.predicted_role,
            note=body.note,
        ),
    )
    return detail.model_dump(mode="json")
