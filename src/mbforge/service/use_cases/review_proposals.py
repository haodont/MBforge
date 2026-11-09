"""AI review proposals: queue the assistant finding, never apply it silently.

The assistant may propose at any time. What it may not do is decide: a proposal
becomes a pending ``ai_review`` item with its evidence and a before/after pair,
and a human confirms or rejects it. Once a human has decided the same
target+field, the item is frozen against further proposals — that is the rule
this module enforces before it writes anything.
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import Any

from mbforge.contracts.review_proposal import (
    AI_REVIEW_KIND,
    ReviewProposal,
    ReviewProposalResult,
)
from mbforge.foundation.ids import stable_id
from mbforge.foundation.logger import get_logger
from mbforge.ports.repositories import ReviewRepository
from mbforge.service.ports import get_repositories

logger = get_logger(__name__)

#: States a human produced. A proposal may not touch them again.
DECIDED_STATUSES = frozenset({"confirmed", "rejected"})
#: How many superseded proposals one item keeps for the reviewer.
HISTORY_LIMIT = 10
#: Targets whose printed text is the only thing a proposal can change.
RECORD_ONLY_TARGETS = frozenset({"evidence", "measurement", "entry", "designation"})


def proposal_item_id(
    *, doc_id: str | None, target_kind: str, target_id: str, field: str
) -> str:
    """Deterministic id: one pending proposal per target field.

    A second proposal for the same field updates that item instead of filling
    the queue with duplicates, and a decided item keeps its id so the assistant
    can see it is frozen.
    """
    return stable_id("ai-review", doc_id or "", target_kind, target_id, field or "")


def _actual_before(library_root: str, proposal: ReviewProposal) -> str:
    """The value the store actually holds, never the model declaration.

    Comparing the model declaration with this is what makes a hallucinated
    "before" visible in the review item.
    """
    repositories = get_repositories(library_root)
    try:
        if proposal.target_kind == "evidence":
            evidence = repositories.evidence.get(proposal.target_id)
            return (evidence.raw_text or "") if evidence is not None else ""
        if proposal.target_kind == "molecule":
            row = repositories.molecules.identity_fields([proposal.target_id]).get(
                proposal.target_id
            )
            if row is None:
                return ""
            field = proposal.field or "name"
            return str(row.get(field) or "")
    except Exception:  # noqa: BLE001 - an unknown target is reported, not fatal
        return ""
    return ""


def _review(review: ReviewRepository, item_id: str) -> dict[str, Any] | None:
    """Current state of the proposal item, or ``None`` when it never existed."""
    row = review.review_item_status_payload(item_id, AI_REVIEW_KIND)
    if row is None:
        return None
    payload = row.get("payload")
    return {
        "status": str(row.get("status") or ""),
        "payload": payload if isinstance(payload, dict) else {},
    }


def _target_exists(library_root: str, proposal: ReviewProposal) -> bool:
    """Verify the target the assistant names actually exists.

    A proposal against an invented id would fill the queue with nothing a human
    can act on, so evidence and molecule targets are resolved first. Measurement
    and entry ids have no by-id read here; they are accepted and shown as such.
    """
    repositories = get_repositories(library_root)
    try:
        if proposal.target_kind == "evidence":
            return repositories.evidence.get(proposal.target_id) is not None
        if proposal.target_kind == "molecule":
            return bool(repositories.molecules.identity_fields([proposal.target_id]))
    except Exception:  # noqa: BLE001 - an unreadable store is not a valid target
        return False
    return True


def propose_items(
    library_root: str, proposals: Sequence[ReviewProposal]
) -> list[ReviewProposalResult]:
    """Record proposals; a decided target is refused, never overwritten.

    The model may revise its own *pending* proposal (the human has not decided
    yet), so an update keeps status ``pending`` and appends to a bounded history.
    """
    review = get_repositories(library_root).review
    results: list[ReviewProposalResult] = []
    for proposal in proposals:
        item_id = proposal_item_id(
            doc_id=proposal.doc_id,
            target_kind=proposal.target_kind,
            target_id=proposal.target_id,
            field=proposal.field,
        )
        if not _target_exists(library_root, proposal):
            results.append(
                ReviewProposalResult(
                    item_id=item_id,
                    action="refused",
                    error=f"unknown {proposal.target_kind} target: {proposal.target_id}",
                )
            )
            continue
        state = _review(review, item_id)
        if state is not None and state["status"] in DECIDED_STATUSES:
            results.append(
                ReviewProposalResult(
                    item_id=item_id,
                    action="refused",
                    status=state["status"],
                    error=(
                        "a human already decided this target; the assistant may "
                        "not modify it again"
                    ),
                )
            )
            continue

        previous = state["payload"] if state else {}
        history = list(previous.get("history") or [])[-HISTORY_LIMIT:]
        if state is not None and previous.get("proposal"):
            history = (history + [previous["proposal"]])[-HISTORY_LIMIT:]
        payload = {
            "source": "ai",
            "proposal": proposal.model_dump(),
            "before_actual": _actual_before(library_root, proposal),
            "revision": int(previous.get("revision") or 0) + 1,
            "history": history,
        }
        review.insert_review_item(
            item_id=item_id,
            kind=AI_REVIEW_KIND,
            doc_id=proposal.doc_id,
            reasons=["ai_proposal"],
            context_text=proposal.rationale[:200] or None,
            payload=payload,
        )
        results.append(
            ReviewProposalResult(
                item_id=item_id,
                action="created" if state is None else "updated",
                status="pending",
                payload=payload,
            )
        )
    return results


def apply_proposal_payload(
    review: ReviewRepository, payload: Any, choice: str | None = None
) -> bool:
    """Apply a confirmed proposal to the store; return whether anything changed.

    Only a molecule field has a mechanical applier today. Evidence text and
    readings are deliberately record-only: rewriting the source text or a
    reading is a pipeline change, and the confirmed item is the audit of it.
    """
    if not isinstance(payload, dict):
        return False
    proposal = payload.get("proposal")
    if not isinstance(proposal, dict):
        return False
    target_kind = str(proposal.get("target_kind") or "")
    target_id = str(proposal.get("target_id") or "")
    after = choice or str(proposal.get("after") or "")
    if not target_id or not after:
        return False
    field = str(proposal.get("field") or "")
    if target_kind == "molecule" and field in {"", "name"}:
        review.set_molecule_name(target_id, after[:200])
        return True
    if target_kind in RECORD_ONLY_TARGETS:
        return False
    return False


__all__ = [
    "DECIDED_STATUSES",
    "apply_proposal_payload",
    "_target_exists",
    "propose_items",
    "proposal_item_id",
]
