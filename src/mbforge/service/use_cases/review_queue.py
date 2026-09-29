"""Unified review queue service across native and Markush review records.

Sits above ``ReviewLifecycle`` and ``MarkushReview`` to present a single
queue surface for the HTTP router and review UI. The persistence layer owns
the SQL (``review_items`` view, the decision audit trail, and the queue
clearing); this module dispatches decisions and shapes responses.
"""

from __future__ import annotations

from typing import Any

from mbforge.domain.review import (
    ReviewConflictError,
    ReviewNotFoundError,
    ReviewTransitionError,
    resolve_status_transition,
)
from mbforge.foundation.logger import get_logger
from mbforge.service.dto.review import (
    ReviewDecisionResponse,
    ReviewQueueItem,
    ReviewQueueResponse,
)
from mbforge.service.ports.repositories import LibraryRepositories, ReviewRepository
from mbforge.service.use_cases.markush.review import apply_decision

logger = get_logger(__name__)


def _get_repositories(library_root: str | None) -> LibraryRepositories:
    from mbforge.foundation.layout import resolve_library_root
    from mbforge.service.ports import get_repositories

    return get_repositories(str(resolve_library_root(library_root)))


def decide(
    review: ReviewRepository,
    conn: Any,
    *,
    kind: str,
    item_id: str,
    action: str,
    reason: str = "",
    choice: str | None = None,
) -> dict[str, Any]:
    """Route one decision to its native persistence target."""
    if kind == "markush_link":
        version = review.markush_candidate_version(conn, item_id)
        if version is None:
            raise ReviewNotFoundError(item_id)
        mapped_action = {
            "confirm": "confirm_complete",
            "reject": "reject",
            "reopen": "reopen",
        }.get(action)
        if mapped_action is None:
            raise ReviewTransitionError(f"unsupported action: {action}")
        return apply_decision(
            conn,
            candidate_id=item_id,
            expected_version=int(version),
            action=mapped_action,
            reason=reason,
            review_repository=review,
        )

    row = review.review_item_status_payload(conn, item_id, kind)
    if row is None:
        raise ReviewNotFoundError(item_id)
    current = row["status"]
    new_status = resolve_status_transition(
        current,
        action,
        action_targets={"confirm": "confirmed", "reject": "rejected"},
    )
    review.set_review_item_status(conn, item_id, kind, new_status)
    payload = row["payload"]
    mol_id = payload.get("mol_id") if isinstance(payload, dict) else None
    if mol_id and kind == "low_conf_molecule":
        review.set_molecule_review_status(conn, mol_id, new_status)
    if kind == "ambiguous_coref" and new_status == "confirmed":
        # Adopt the reviewer-chosen compound identifier as the molecule name
        # (falls back to the OCR suggestion, then the first label).
        labels = payload.get("ocr_labels") if isinstance(payload, dict) else None
        chosen = (
            choice
            or (payload.get("coref_primary") if isinstance(payload, dict) else None)
            or (labels[0] if isinstance(labels, list) and labels else None)
        )
        if mol_id and chosen:
            review.set_molecule_name(conn, mol_id, str(chosen))
    review.record_review_decision(
        conn,
        entity_type="review_item",
        entity_id=item_id,
        action=action,
        previous_state=current,
        new_state=new_status,
        reason=reason,
        snapshot=payload,
    )
    return {"id": item_id, "kind": kind, "status": new_status}


def queue_page(
    library_root: str | None,
    kind: str | None,
    item_status: str | None,
    doc_id: str | None,
    page: int,
    page_size: int,
) -> ReviewQueueResponse:
    repositories = _get_repositories(library_root)
    with repositories.database.mol_conn() as conn:
        items, total = repositories.review.list_queue(
            conn,
            kind=kind,
            status=item_status,
            doc_id=doc_id,
            page=page,
            page_size=page_size,
        )
    return ReviewQueueResponse(
        items=[ReviewQueueItem(**item) for item in items],
        total=total,
        page=page,
        page_size=page_size,
    )


def stats_summary(library_root: str | None) -> dict[str, Any]:
    repositories = _get_repositories(library_root)
    with repositories.database.mol_conn() as conn:
        return repositories.review.stats(conn)


def item_detail(library_root: str | None, kind: str, item_id: str) -> dict[str, Any]:
    repositories = _get_repositories(library_root)
    with repositories.database.mol_conn() as conn:
        return repositories.review.get_item(conn, kind, item_id)


def decide_items(
    library_root: str | None,
    action: str,
    reason: str | None,
    items: list[Any],
) -> ReviewDecisionResponse:
    """Apply one action to a batch of review items.

    *items* are request-shaped objects exposing ``kind``, ``id`` and an
    optional ``choice`` attribute.
    """
    repositories = _get_repositories(library_root)
    updated = 0
    skipped = 0
    results: list[dict] = []
    with repositories.database.mol_conn() as conn:
        for item in items:
            try:
                result = decide(
                    repositories.review,
                    conn,
                    kind=item.kind,
                    item_id=item.id,
                    action=action,
                    reason=reason or "",
                    choice=item.choice,
                )
            except (
                ReviewConflictError,
                ReviewNotFoundError,
                ReviewTransitionError,
            ) as exc:
                skipped += 1
                results.append({"kind": item.kind, "id": item.id, "error": str(exc)})
            else:
                updated += 1
                results.append(result)
    return ReviewDecisionResponse(updated=updated, skipped=skipped, results=results)


def clear_all_review_queue(library_root: str | None) -> dict[str, int]:
    """Empty the entire review center.

    Deletes every row from ``review_items`` and ``markush_review_candidates``
    (including superseded history rows) regardless of status, plus the
    ``markush_decisions`` audit rows keyed on those entities so no orphaned
    audit trail survives.

    Confirmed/promoted artifacts are intentionally kept: ``molecules``,
    ``markush_scaffolds``/``markush_fragments`` and ``markush_evidence`` are
    ingested knowledge, not queue entries, and are re-derived or referenced
    independently of the queue.
    """
    repositories = _get_repositories(library_root)
    with repositories.database.mol_conn() as conn:
        return repositories.review.clear_all(conn)


def entity_history(
    library_root: str | None, entity_id: str
) -> tuple[Any, list[dict[str, Any]]]:
    repositories = _get_repositories(library_root)
    with repositories.database.mol_conn() as conn:
        return repositories.review.history(conn, entity_id)
