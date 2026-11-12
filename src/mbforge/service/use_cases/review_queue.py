"""Unified review queue service.

Sits above the review persistence layer to present a single queue surface for
the HTTP router and review UI. The persistence layer owns the SQL
(``review_items``, the decision audit trail, and the queue clearing); this
module dispatches decisions and shapes responses.
"""

from __future__ import annotations

from typing import Any

from mbforge.contracts.measurement import DESIGNATION_UNBOUND_KIND
from mbforge.contracts.review_proposal import AI_REVIEW_KIND
from mbforge.domain.review import (
    ReviewConflictError,
    ReviewNotFoundError,
    ReviewTransitionError,
    resolve_status_transition,
)
from mbforge.ports.repositories import LibraryRepositories, ReviewRepository
from mbforge.service.dto.review import (
    ReviewDecisionResponse,
    ReviewQueueItem,
    ReviewQueueResponse,
)
from mbforge.service.use_cases.review_proposals import apply_proposal_payload


def _get_repositories(library_root: str | None) -> LibraryRepositories:
    from mbforge.foundation.layout import resolve_library_root
    from mbforge.service.ports import get_repositories

    return get_repositories(str(resolve_library_root(library_root)))


def decide(
    review: ReviewRepository,
    *,
    kind: str,
    item_id: str,
    action: str,
    reason: str = "",
    choice: str | None = None,
    expected_revision: int | None = None,
    library_root: str | None = None,
) -> dict[str, Any]:
    """Route one decision to its native persistence target."""
    row = review.review_item_status_payload(item_id, kind)
    if row is None:
        raise ReviewNotFoundError(item_id)
    current = row["status"]
    new_status = resolve_status_transition(
        current,
        action,
        action_targets={"confirm": "confirmed", "reject": "rejected"},
    )
    review.set_review_item_status(item_id, kind, new_status)
    payload = row["payload"]
    mol_id = payload.get("mol_id") if isinstance(payload, dict) else None
    if mol_id and kind == "low_conf_molecule":
        review.set_molecule_review_status(mol_id, new_status)
    if mol_id and kind == "smiles_correction" and new_status == "confirmed":
        # A structure correction is applied only once a human confirms it, and the
        # mol_id is deliberately kept: the corrected molecule keeps its activity,
        # evidence chain and review history.
        _apply_smiles_correction(review, mol_id, payload, choice)
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
            review.set_molecule_name(mol_id, str(chosen))
    applied = False
    if kind == AI_REVIEW_KIND and new_status == "confirmed":
        # A confirmed proposal is applied only now, by the human decision.
        applied = apply_proposal_payload(review, payload, choice)
    if kind == DESIGNATION_UNBOUND_KIND and new_status == "confirmed":
        applied = _bind_unbound_reading(payload, choice, library_root)
    review.record_review_decision(
        entity_type="review_item",
        entity_id=item_id,
        action=action,
        previous_state=current,
        new_state=new_status,
        reason=reason,
        snapshot=payload,
    )
    return {"id": item_id, "kind": kind, "status": new_status, "applied": applied}


def _apply_smiles_correction(
    review: ReviewRepository,
    mol_id: str,
    payload: dict[str, Any],
    choice: str | None,
) -> None:
    """Write a confirmed structure correction into the molecule row.

    The mol_id never changes, so the corrected molecule keeps every link it had;
    the store recomputes the canonical SMILES the rest of the app keys on. A
    reviewer's own input (``choice``) wins over the proposed structure.
    """
    new_smiles = str(choice or payload.get("suggested_smiles") or "").strip()
    if not new_smiles:
        return
    review.set_molecule_smiles(mol_id, new_smiles)


def queue_page(
    library_root: str | None,
    kind: str | None,
    item_status: str | None,
    doc_id: str | None,
    page: int,
    page_size: int,
) -> ReviewQueueResponse:
    repositories = _get_repositories(library_root)
    items, total = repositories.review.list_queue(
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


def stats_summary(
    library_root: str | None, doc_id: str | None = None
) -> dict[str, Any]:
    """Count the review queue, optionally scoped to one document."""
    return _get_repositories(library_root).review.stats(doc_id=doc_id)


def item_detail(library_root: str | None, kind: str, item_id: str) -> dict[str, Any]:
    return _get_repositories(library_root).review.get_item(kind, item_id)


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
    for item in items:
        try:
            result = decide(
                repositories.review,
                kind=item.kind,
                item_id=item.id,
                action=action,
                reason=reason or "",
                choice=item.choice,
                expected_revision=getattr(item, "expected_revision", None),
                library_root=library_root,
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


class _DecisionRow:
    """Request-shaped row for :func:`decide_items`."""

    __slots__ = ("choice", "expected_revision", "id", "kind")

    def __init__(self, kind: str, item_id: str) -> None:
        self.kind = kind
        self.id = item_id
        self.choice = None
        self.expected_revision = None


def decide_filtered(
    library_root: str | None,
    *,
    kind: str | None,
    doc_id: str | None,
    target_kind: str | None,
    action: str,
    reason: str,
    limit: int,
) -> ReviewDecisionResponse:
    """Decide every pending item matching the filter, in one batch.

    This is the "approve all text" / "approve the whole patent" path: the filter
    is resolved here, never trusted from the model, and every item still goes
    through the same per-kind decision handler as a single click.
    """
    repositories = _get_repositories(library_root)
    rows, _total = repositories.review.list_queue(
        kind=kind or None,
        status="pending",
        doc_id=doc_id or None,
        page=1,
        page_size=limit,
    )
    chosen: list[_DecisionRow] = []
    for row in rows:
        if target_kind:
            payload = row.get("payload")
            proposal = payload.get("proposal") if isinstance(payload, dict) else None
            if not isinstance(proposal, dict):
                continue
            if proposal.get("target_kind") != target_kind:
                continue
        chosen.append(_DecisionRow(str(row["kind"]), str(row["id"])))
    if not chosen:
        return ReviewDecisionResponse(updated=0, skipped=0, results=[])
    return decide_items(library_root, action, reason, chosen)


def _bind_unbound_reading(
    payload: Any, choice: str | None, library_root: str | None
) -> bool:
    """Write the attribution the reviewer picked for a printed reading.

    The chosen structure must be one of the candidates the item was built from:
    the model never supplies the target, and a value outside that list is refused
    instead of becoming an unattributable link.
    """
    if not isinstance(payload, dict):
        return False
    candidates = payload.get("candidates")
    allowed = {
        str(item.get("mol_id"))
        for item in candidates or []
        if isinstance(item, dict) and item.get("mol_id")
    }
    measurement_id = str(payload.get("measurement_id") or "")
    chosen = str(choice or "")
    if not measurement_id or chosen not in allowed:
        raise ReviewConflictError(
            "the decided structure is not one of the printed candidates"
        )
    evidence_ids = payload.get("evidence_ids")
    evidence_id = (
        str(evidence_ids[0]) if isinstance(evidence_ids, list) and evidence_ids else ""
    )
    _get_repositories(library_root).measurements.bind_attribution(
        measurement_id=measurement_id,
        mol_id=chosen,
        doc_id=str(payload.get("doc_id") or ""),
        evidence_id=evidence_id,
        method="human",
    )
    return True


def clear_all_review_queue(library_root: str | None) -> dict[str, int]:
    """Empty the entire review center.

    Deletes every ``review_items`` row regardless of status, plus the
    ``markush_decisions`` audit rows keyed on those items so no orphaned audit
    trail survives. Confirmed artifacts are intentionally kept: ``molecules``
    and the evidence rows are ingested knowledge, not queue entries.
    """
    repositories = _get_repositories(library_root)
    return repositories.review.clear_all()


def entity_history(
    library_root: str | None, entity_id: str
) -> tuple[Any, list[dict[str, Any]]]:
    return _get_repositories(library_root).review.history(entity_id)
