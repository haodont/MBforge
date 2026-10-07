"""Decision application for Markush review candidates.

Service side of the review flow split out of the former
``core.chem.markush_review`` module before the P2 naming migration.
Owns ``apply_decision`` for the
confirm/reject/reopen actions and the role-transition helpers
(``_confirm_complete`` / ``_confirm_scaffold`` / ``_confirm_fragment``)
that write the destination table, copy the evidence chain, and update
the audit log; uses an optimistic lock
(``expected_version``) so two reviewers cannot clobber each other.

The raw SQL lives behind :class:`~mbforge.ports.repositories.ReviewRepository`
(which owns its connection). Queue reads/updates live in
:mod:`mbforge.db.markush_transitions`; the shared state machine in
:mod:`mbforge.domain.review`; the initial queue persistence in
:mod:`mbforge.db.markush_candidates`.
"""

from __future__ import annotations

import json
from typing import Any

from mbforge.domain.molecule import molecule_id
from mbforge.domain.review import (
    ReviewConflictError,
    ReviewNotFoundError,
    ReviewTransitionError,
    resolve_status_transition,
)
from mbforge.foundation.files import safe_json_loads
from mbforge.foundation.ids import short_id
from mbforge.foundation.logger import get_logger
from mbforge.ports.repositories import ReviewRepository

logger = get_logger("mbforge.service.use_cases.markush.review")


# Allowed transitions in the review state machine. ``confirm_*`` is
# only legal from ``pending``; ``reject`` is legal from ``pending``;
# ``reopen`` is legal from ``confirmed`` / ``rejected`` and resets back
# to ``pending``.
_VALID_ACTIONS: frozenset[str] = frozenset(
    {"confirm_complete", "confirm_scaffold", "confirm_fragment", "reject", "reopen"}
)


def apply_decision(
    repository: ReviewRepository,
    *,
    candidate_id: str,
    expected_version: int,
    action: str,
    reason: str = "",
) -> dict[str, str | int | None]:
    """Apply a review action.

    Returns the new state plus any id minted by the role transition
    (e.g. a fresh ``mol_id`` when ``action == 'confirm_complete'``).
    """
    if action not in _VALID_ACTIONS:
        raise ReviewTransitionError(f"unknown action: {action}")
    row = repository.get_review_candidate(candidate_id)
    if row is None:
        raise ReviewNotFoundError(candidate_id)
    if row["review_version"] != expected_version:
        raise ReviewConflictError(
            f"expected_version={expected_version} but stored={row['review_version']}"
        )
    previous_state = row["review_status"]
    new_state, payload = _transition(repository, row, action)
    repository.set_candidate_status(candidate_id, new_state)
    repository.record_review_decision(
        entity_type="review_candidate",
        entity_id=candidate_id,
        action=action,
        previous_state=previous_state,
        new_state=new_state,
        reason=reason,
        snapshot=payload,
    )
    payload.update(
        {
            "candidate_id": candidate_id,
            "new_state": new_state,
            "new_version": int(row["review_version"]) + 1,
        }
    )
    return payload


def _transition(
    repository: ReviewRepository,
    row: Any,
    action: str,
) -> tuple[str, dict[str, str | int | None]]:
    """Resolve (new_state, payload) for a review action.

    The payload carries the ids minted by the destination table
    insertion (mol_id / scaffold_id / fragment_id). The payload is also
    snapshotted into ``markush_decisions.snapshot`` for audit.
    """
    if action in {"reject", "reopen"}:
        return (
            resolve_status_transition(
                row["review_status"],
                action,
                action_targets={"reject": "rejected"},
            ),
            {},
        )
    if action == "confirm_complete":
        if row["review_status"] != "pending":
            raise ReviewTransitionError(
                f"cannot confirm_complete from {row['review_status']}"
            )
        if row["smiles"] is None or not row["smiles"]:
            raise ReviewTransitionError("cannot confirm_complete: SMILES is empty")
        mol_id = _confirm_complete_to_molecules(repository, row)
        return "confirmed", {"molecule_id": mol_id}
    if action == "confirm_scaffold":
        if row["review_status"] != "pending":
            raise ReviewTransitionError(
                f"cannot confirm_scaffold from {row['review_status']}"
            )
        scaffold_id = _confirm_scaffold_to_markush_scaffolds(repository, row)
        return "confirmed", {"scaffold_id": scaffold_id}
    if action == "confirm_fragment":
        if row["review_status"] != "pending":
            raise ReviewTransitionError(
                f"cannot confirm_fragment from {row['review_status']}"
            )
        fragment_id = _confirm_fragment_to_markush_fragments(repository, row)
        return "confirmed", {"fragment_id": fragment_id}
    raise ReviewTransitionError(f"unhandled action: {action}")


def _confirm_complete_to_molecules(repository: ReviewRepository, row: Any) -> str:
    """Write the destination ``molecules`` row and copy evidence chain."""
    mol_id = molecule_id(row["smiles"] or "") or short_id()
    repository.insert_molecule_from_candidate(
        mol_id=mol_id,
        smiles=row["smiles"] or "",
        esmiles=row["esmiles"] or "",
        name=row["name"] or "",
        doc_id=row["doc_id"],
        properties_json=json.dumps(
            {
                "raw_coref_label": row["raw_label"],
                "normalized_label": row["normalized_label"],
                "label_kind": row["label_kind"],
                "review_candidate_id": row["candidate_id"],
            },
            ensure_ascii=False,
        ),
    )
    repository.copy_evidence(row, "molecule", mol_id, row["doc_id"])
    return mol_id


def _confirm_scaffold_to_markush_scaffolds(
    repository: ReviewRepository, row: Any
) -> str:
    """Write the destination ``markush_scaffolds`` row."""
    scaffold_id = short_id()
    repository.insert_scaffold_from_candidate(
        scaffold_id=scaffold_id,
        doc_id=row["doc_id"],
        formula_label=row["normalized_label"] or row["raw_label"] or "",
        smiles=row["smiles"] or "",
        esmiles=row["esmiles"] or "",
        page=row["page"],
        bbox_x0=row["bbox_x0"],
        bbox_y0=row["bbox_y0"],
        bbox_x1=row["bbox_x1"],
        bbox_y1=row["bbox_y1"],
        crop_relpath=row["crop_relpath"],
        confidence=row["composite_confidence"],
        properties_json=json.dumps(
            {
                "review_candidate_id": row["candidate_id"],
                "label_kind": row["label_kind"],
            },
            ensure_ascii=False,
        ),
    )
    # Echo the new scaffold_id back to the candidate's properties so the
    # review UI can drive the SiteEditor without an extra round
    # trip. The JSON merge is small and idempotent.
    existing = safe_json_loads(row["properties"], {})
    if not isinstance(existing, dict):
        existing = {}
    existing["scaffold_id"] = scaffold_id
    repository.set_candidate_properties(
        row["candidate_id"],
        json.dumps(existing, ensure_ascii=False),
    )
    repository.copy_evidence(row, "scaffold", scaffold_id, row["doc_id"])
    return scaffold_id


def _confirm_fragment_to_markush_fragments(
    repository: ReviewRepository, row: Any
) -> str:
    """Write the destination ``markush_fragments`` row."""
    fragment_id = short_id()
    repository.insert_fragment_from_candidate(
        fragment_id=fragment_id,
        doc_id=row["doc_id"],
        label=row["normalized_label"] or row["raw_label"] or "",
        smiles=row["smiles"] or "",
        esmiles=row["esmiles"] or "",
        page=row["page"],
        bbox_x0=row["bbox_x0"],
        bbox_y0=row["bbox_y0"],
        bbox_x1=row["bbox_x1"],
        bbox_y1=row["bbox_y1"],
        crop_relpath=row["crop_relpath"],
        confidence=row["composite_confidence"],
        properties_json=json.dumps(
            {
                "review_candidate_id": row["candidate_id"],
                "label_kind": row["label_kind"],
            },
            ensure_ascii=False,
        ),
    )
    repository.copy_evidence(row, "fragment", fragment_id, row["doc_id"])
    return fragment_id


__all__ = [
    "apply_decision",
]
