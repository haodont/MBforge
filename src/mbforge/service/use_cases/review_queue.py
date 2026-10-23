"""Unified review queue service across native and Markush review records.

Sits above ``ReviewLifecycle`` and ``MarkushReview`` to present a single
queue surface for the HTTP router and review UI. The persistence layer owns
the SQL (``review_items`` view, the decision audit trail, and the queue
clearing); this module dispatches decisions and shapes responses.
"""

from __future__ import annotations

from typing import Any

from mbforge.contracts.patent import PATENT_FACT_REVIEW_KIND
from mbforge.domain.patent_analysis import candidate_set_signature
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
from mbforge.service.pipeline.patent.decisions import (
    DECISION_NEITHER,
    PATENT_FACT_CHOICES,
    apply_decisions,
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
    if kind == PATENT_FACT_REVIEW_KIND:
        return _decide_patent_fact(
            review,
            library_root=library_root,
            item_id=item_id,
            action=action,
            reason=reason,
            choice=choice,
            expected_revision=expected_revision,
        )
    if kind == "markush_link":
        version = review.markush_candidate_version(item_id)
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
            review,
            candidate_id=item_id,
            expected_version=int(version),
            action=mapped_action,
            reason=reason,
        )

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
    review.record_review_decision(
        entity_type="review_item",
        entity_id=item_id,
        action=action,
        previous_state=current,
        new_state=new_status,
        reason=reason,
        snapshot=payload,
    )
    return {"id": item_id, "kind": kind, "status": new_status}


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


def _decide_patent_fact(
    review: ReviewRepository,
    *,
    library_root: str | None,
    item_id: str,
    action: str,
    reason: str,
    choice: str | None,
    expected_revision: int | None,
) -> dict[str, Any]:
    """Resolve a contested fact slot by republishing the document's facts.

    Confirming adopts one reading; rejecting or reopening withdraws the decision
    and leaves the slot contested. The republication goes through the same
    publication use case the Patent stage uses, so the snapshot, the derived rows
    and the file projection stay consistent.
    """
    from datetime import UTC, datetime

    from mbforge.contracts.patent import PatentConflict
    from mbforge.foundation.layout import resolve_library_root
    from mbforge.service.use_cases.documents.patent_facts import (
        publish_document_facts,
    )

    row = review.review_item_status_payload(item_id, PATENT_FACT_REVIEW_KIND)
    if row is None:
        raise ReviewNotFoundError(item_id)
    current = row["status"]
    payload = row["payload"] if isinstance(row["payload"], dict) else {}
    slot_id = str(payload.get("slot_id") or "")
    doc_id = str(payload.get("doc_id") or "")
    conflict_payload = payload.get("conflict")
    if not slot_id or not doc_id or not isinstance(conflict_payload, dict):
        raise ReviewConflictError("the review item carries no comparable fact slot")
    if action == "confirm" and choice not in PATENT_FACT_CHOICES:
        raise ReviewTransitionError(
            "a confirmed patent fact decision must choose "
            + ", ".join(PATENT_FACT_CHOICES)
        )

    new_status = resolve_status_transition(
        current,
        action,
        action_targets={"confirm": "confirmed", "reject": "rejected"},
    )
    root = str(resolve_library_root(library_root))
    state = _get_repositories(library_root).patent_analysis.load(doc_id)
    if state is None:
        raise ReviewConflictError("the document has no committed analysis to update")
    revision = int(state["revision"])
    if expected_revision is not None and expected_revision != revision:
        raise ReviewConflictError(
            f"stale patent fact decision for {doc_id}: "
            f"expected revision {expected_revision}, found {revision}"
        )

    conflict = PatentConflict.model_validate(conflict_payload)
    decisions = dict(state.get("decisions") or {})
    artifact = _committed_artifact(state)
    if new_status == "confirmed" and not any(
        item.get("slot_id") == slot_id
        and candidate_set_signature(
            [candidate["signature"] for candidate in item["candidates"]]
        )
        == candidate_set_signature(
            [candidate.signature for candidate in conflict.candidates]
        )
        for item in artifact.conflicts
    ):
        raise ReviewConflictError("the candidate is no longer pending in this result")
    if new_status != "confirmed" and not any(
        item.get("slot_id") == slot_id for item in artifact.conflicts
    ):
        previous = decisions.get(slot_id)
        if previous is None:
            raise ReviewConflictError(
                "the decided slot is no longer part of this result"
            )
        restored = apply_decisions(
            doc_id=doc_id,
            measurements=[],
            candidates=[],
            conflicts=[conflict],
            decisions={slot_id: previous},
            evidence_signature=str(state["evidence_signature"]),
        )
        if slot_id not in restored.applied:
            raise ReviewConflictError("the decided slot no longer matches its evidence")
        adopted_ids = {item["measurement_id"] for item in restored.measurements}
        artifact = artifact.model_copy(
            update={
                "measurements": [
                    item
                    for item in artifact.measurements
                    if item.get("measurement_id") not in adopted_ids
                ],
                "conflicts": [*artifact.conflicts, conflict.model_dump()],
                "review_candidates": [
                    *artifact.review_candidates,
                    {
                        "review_item_id": item_id,
                        "slot_id": slot_id,
                        "kind": conflict.kind,
                        "reason": "conflict",
                        "page": conflict.page,
                        "evidence_ids": conflict.evidence_ids,
                        "deterministic": payload.get("deterministic"),
                        "llm": payload.get("llm"),
                        "conflict": conflict.model_dump(),
                    },
                ],
            }
        )
    forget: list[str] = []
    if new_status == "confirmed":
        decisions[slot_id] = {
            "slot_id": slot_id,
            "choice": choice or DECISION_NEITHER,
            "candidate_set_signature": candidate_set_signature(
                [item.signature for item in conflict.candidates]
            ),
            "evidence_signature": str(state["evidence_signature"]),
            "reason": reason,
            "decided_at": datetime.now(UTC).strftime("%Y-%m-%d %H:%M:%S"),
        }
    else:
        decisions.pop(slot_id, None)
        forget.append(slot_id)

    publication = publish_document_facts(
        root,
        doc_id=doc_id,
        artifact=artifact,
        evidence_signature=str(state["evidence_signature"]),
        candidates=_document_candidates(root, doc_id),
        decisions={slot_id: decisions[slot_id]} if slot_id in decisions else None,
        forget_decisions=forget,
        expected_revision=revision,
    )
    review.set_review_item_status(item_id, PATENT_FACT_REVIEW_KIND, new_status)
    review.record_review_decision(
        entity_type="review_item",
        entity_id=item_id,
        action=action,
        previous_state=current,
        new_state=new_status,
        reason=reason,
        snapshot=payload,
    )
    logger.info(
        "Patent fact decision for %s: %s (%s) → revision %d",
        doc_id,
        slot_id,
        choice or new_status,
        publication.revision,
    )
    return {
        "id": item_id,
        "kind": PATENT_FACT_REVIEW_KIND,
        "status": new_status,
        "revision": publication.revision,
    }


def _committed_artifact(state: dict[str, Any]) -> Any:
    """The artifact exactly as committed; the publication re-applies decisions."""
    from mbforge.service.pipeline.patent.artifact import PatentFactsArtifact

    return PatentFactsArtifact.model_validate(
        {**state["payload"], "revision": int(state["revision"])}
    )


def _document_candidates(library_root: str, doc_id: str) -> list[Any]:
    """The document's recognized structures, for re-deriving molecule rows."""
    from mbforge.service.pipeline.artifacts.hydration import load_detections

    loaded = load_detections(library_root, doc_id)
    return list(loaded[0]) if loaded else []


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
    states: dict[str, dict[str, Any] | None] = {}
    for item in items:
        if item["kind"] != PATENT_FACT_REVIEW_KIND or item["status"] == "pending":
            continue
        doc_id = item["doc_id"]
        if doc_id not in states:
            states[doc_id] = repositories.patent_analysis.load(doc_id)
        state = states[doc_id]
        if state is None:
            continue
        payload = item["payload"]
        decision = (state.get("decisions") or {}).get(payload.get("slot_id"))
        conflict = payload.get("conflict") or {}
        if decision and (
            decision.get("evidence_signature") == state["evidence_signature"]
            and decision.get("candidate_set_signature")
            == candidate_set_signature(
                [candidate["signature"] for candidate in conflict.get("candidates", [])]
            )
        ):
            item["payload"] = {**payload, "revision": state["revision"]}
    return ReviewQueueResponse(
        items=[ReviewQueueItem(**item) for item in items],
        total=total,
        page=page,
        page_size=page_size,
    )


def stats_summary(library_root: str | None) -> dict[str, Any]:
    return _get_repositories(library_root).review.stats()


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
        if (
            item.kind == PATENT_FACT_REVIEW_KIND
            and action == "confirm"
            and not getattr(item, "choice", None)
        ):
            # A patent fact decision must state which reading wins.
            skipped += 1
            results.append(
                {
                    "kind": item.kind,
                    "id": item.id,
                    "error": (
                        "a patent fact decision requires "
                        "choice=deterministic|llm|neither"
                    ),
                }
            )
            continue
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
    return repositories.review.clear_all()


def entity_history(
    library_root: str | None, entity_id: str
) -> tuple[Any, list[dict[str, Any]]]:
    return _get_repositories(library_root).review.history(entity_id)
