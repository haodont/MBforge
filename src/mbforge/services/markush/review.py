"""Decision application for Markush review candidates.

Service side of the review flow split out of the former
``core.chem.markush_review`` module before the P2 naming migration.
Owns ``apply_decision`` for the
confirm/reject/reopen actions and the role-transition helpers
(``_confirm_complete`` / ``_confirm_scaffold`` / ``_confirm_fragment``)
that write the destination table, copy the evidence chain, and update
the audit log in one transaction; uses an optimistic lock
(``expected_version``) so two reviewers cannot clobber each other.

Queue reads/updates live in :mod:`mbforge.storage.markush_transitions`;
the shared state machine in :mod:`mbforge.core.review`; the initial
queue persistence in :mod:`mbforge.storage.markush_candidates`.

All writes target the caller-owned connection so the persist stage's
existing transaction is reused; no implicit commits.
"""

from __future__ import annotations

import json
import sqlite3

from ...core.molecule import molecule_id
from ...core.review import (
    ReviewConflictError,
    ReviewNotFoundError,
    ReviewTransitionError,
    resolve_status_transition,
)
from ...storage.markush_transitions import _copy_evidence, _fetch_one
from ...storage.review_audit import record_review_decision
from ...utils.files import safe_json_loads
from ...utils.ids import short_id
from ...utils.logger import get_logger

logger = get_logger("mbforge.services.markush.review")


# Allowed transitions in the review state machine. ``confirm_*`` is
# only legal from ``pending``; ``reject`` is legal from ``pending``;
# ``reopen`` is legal from ``confirmed`` / ``rejected`` and resets back
# to ``pending``.
_VALID_ACTIONS: frozenset[str] = frozenset(
    {"confirm_complete", "confirm_scaffold", "confirm_fragment", "reject", "reopen"}
)


def apply_decision(
    conn: sqlite3.Connection,
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
    row = _fetch_one(
        conn,
        "SELECT * FROM markush_review_candidates WHERE candidate_id = ?",
        (candidate_id,),
    )
    if row is None:
        raise ReviewNotFoundError(candidate_id)
    if row["review_version"] != expected_version:
        raise ReviewConflictError(
            f"expected_version={expected_version} but stored={row['review_version']}"
        )
    previous_state = row["review_status"]
    new_state, payload = _transition(conn, row, action)
    conn.execute(
        """
        UPDATE markush_review_candidates
        SET review_status = ?, review_version = review_version + 1,
            updated_at = datetime('now')
        WHERE candidate_id = ?
        """,
        (new_state, candidate_id),
    )
    record_review_decision(
        conn,
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
    conn: sqlite3.Connection,
    row: sqlite3.Row,
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
        mol_id = _confirm_complete_to_molecules(conn, row)
        return "confirmed", {"molecule_id": mol_id}
    if action == "confirm_scaffold":
        if row["review_status"] != "pending":
            raise ReviewTransitionError(
                f"cannot confirm_scaffold from {row['review_status']}"
            )
        scaffold_id = _confirm_scaffold_to_markush_scaffolds(conn, row)
        return "confirmed", {"scaffold_id": scaffold_id}
    if action == "confirm_fragment":
        if row["review_status"] != "pending":
            raise ReviewTransitionError(
                f"cannot confirm_fragment from {row['review_status']}"
            )
        fragment_id = _confirm_fragment_to_markush_fragments(conn, row)
        return "confirmed", {"fragment_id": fragment_id}
    raise ReviewTransitionError(f"unhandled action: {action}")


def _confirm_complete_to_molecules(conn: sqlite3.Connection, row: sqlite3.Row) -> str:
    """Write the destination ``molecules`` row and copy evidence chain."""
    mol_id = molecule_id(row["smiles"] or "") or short_id()
    conn.execute(
        """
        INSERT INTO molecules
            (mol_id, smiles, esmiles, name, source_doc,
             status, properties, canonical_smiles, review_status)
        VALUES (?, ?, ?, ?, ?, 'active', ?, ?, 'confirmed')
        """,
        (
            mol_id,
            row["smiles"] or "",
            row["esmiles"] or "",
            row["name"] or "",
            row["doc_id"],
            json.dumps(
                {
                    "raw_coref_label": row["raw_label"],
                    "normalized_label": row["normalized_label"],
                    "label_kind": row["label_kind"],
                    "review_candidate_id": row["candidate_id"],
                },
                ensure_ascii=False,
            ),
            row["smiles"] or "",
        ),
    )
    _copy_evidence(conn, row, "molecule", mol_id, row["doc_id"])
    return mol_id


def _confirm_scaffold_to_markush_scaffolds(
    conn: sqlite3.Connection, row: sqlite3.Row
) -> str:
    """Write the destination ``markush_scaffolds`` row."""
    scaffold_id = short_id()
    conn.execute(
        """
        INSERT INTO markush_scaffolds
            (scaffold_id, doc_id, formula_label, smiles, esmiles, page,
             bbox_x0, bbox_y0, bbox_x1, bbox_y1, crop_relpath, confidence,
             status, properties)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            scaffold_id,
            row["doc_id"],
            row["normalized_label"] or row["raw_label"] or "",
            row["smiles"] or "",
            row["esmiles"] or "",
            row["page"],
            row["bbox_x0"],
            row["bbox_y0"],
            row["bbox_x1"],
            row["bbox_y1"],
            row["crop_relpath"],
            row["composite_confidence"],
            "confirmed",
            json.dumps(
                {
                    "review_candidate_id": row["candidate_id"],
                    "label_kind": row["label_kind"],
                },
                ensure_ascii=False,
            ),
        ),
    )
    # Echo the new scaffold_id back to the candidate's properties so the
    # review UI can drive the SiteEditor without an extra round
    # trip. The JSON merge is small and idempotent.
    existing = safe_json_loads(row["properties"], {})
    if not isinstance(existing, dict):
        existing = {}
    existing["scaffold_id"] = scaffold_id
    conn.execute(
        "UPDATE markush_review_candidates SET properties = ? WHERE candidate_id = ?",
        (json.dumps(existing, ensure_ascii=False), row["candidate_id"]),
    )
    _copy_evidence(conn, row, "scaffold", scaffold_id, row["doc_id"])
    return scaffold_id


def _confirm_fragment_to_markush_fragments(
    conn: sqlite3.Connection, row: sqlite3.Row
) -> str:
    """Write the destination ``markush_fragments`` row."""
    fragment_id = short_id()
    conn.execute(
        """
        INSERT INTO markush_fragments
            (fragment_id, doc_id, label, smiles, esmiles, page,
             bbox_x0, bbox_y0, bbox_x1, bbox_y1, crop_relpath, confidence,
             status, properties)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            fragment_id,
            row["doc_id"],
            row["normalized_label"] or row["raw_label"] or "",
            row["smiles"] or "",
            row["esmiles"] or "",
            row["page"],
            row["bbox_x0"],
            row["bbox_y0"],
            row["bbox_x1"],
            row["bbox_y1"],
            row["crop_relpath"],
            row["composite_confidence"],
            "confirmed",
            json.dumps(
                {
                    "review_candidate_id": row["candidate_id"],
                    "label_kind": row["label_kind"],
                },
                ensure_ascii=False,
            ),
        ),
    )
    _copy_evidence(conn, row, "fragment", fragment_id, row["doc_id"])
    return fragment_id


__all__ = [
    "apply_decision",
]
