"""Fact-slot identity and content signatures for patent analysis (pure).

Two identities are deliberately separate:

* **Slot ID** — the stable position a fact occupies, derived from source
  anchors only (document, evidence location, compound reference, assay,
  metric, conditions). Values are never part of it, so the same slot can hold
  two incompatible readings and become a conflict.
* **Candidate signature** — the content of one candidate for that slot,
  computed over exactly the compared fields. Changing a value changes the
  signature, which is what retires a human decision (the decision stores the
  candidate-set and evidence signatures it was made under).

Distinct assays, species systems, repeat measurements and same-page records
stay separate: they differ in the assay key, the conditions or the anchor
evidence. Two readings of the same value at the same anchor are the same
fact, not two.
"""

from __future__ import annotations

import json
from collections.abc import Iterable, Mapping
from typing import Any

from mbforge.foundation.ids import stable_id


def _canonical_json(value: Any) -> str:
    """Deterministic JSON for hashing: sorted keys, no whitespace drift."""
    return json.dumps(
        value,
        sort_keys=True,
        ensure_ascii=False,
        separators=(",", ":"),
        default=str,
    )


def conditions_key(conditions: Mapping[str, Any] | None) -> str:
    """Alignment-stable key for measurement/assay conditions."""
    return _canonical_json(dict(conditions or {}))


def measurement_slot_id(
    doc_id: str,
    *,
    anchor_evidence_id: str,
    compound_key: str = "",
    assay_key: str = "",
    metric: str = "",
    conditions: Mapping[str, Any] | None = None,
) -> str:
    """Slot of one activity measurement; value fields are excluded on purpose."""
    return stable_id(
        "patent-slot-v1",
        "measurement",
        doc_id,
        anchor_evidence_id,
        compound_key,
        assay_key,
        metric,
        conditions_key(conditions),
    )


def assay_method_slot_id(
    doc_id: str,
    *,
    anchor_evidence_id: str,
    endpoint_key: str = "",
    target_key: str = "",
    system_key: str = "",
) -> str:
    """Slot of one assay method; different species systems never merge."""
    return stable_id(
        "patent-slot-v1",
        "assay_method",
        doc_id,
        anchor_evidence_id,
        endpoint_key,
        target_key,
        system_key,
    )


def candidate_signature(fields: Mapping[str, Any]) -> str:
    """Content signature over one conflict candidate's compared fields."""
    return stable_id("patent-candidate-v1", _canonical_json(dict(fields)))


def candidate_set_signature(signatures: Iterable[str]) -> str:
    """Signature of a whole candidate set (order-independent)."""
    return stable_id("patent-candidate-set-v1", *sorted(set(signatures)))


def conflict_id(slot_id: str, candidate_set: str) -> str:
    """Conflict / review-item ID: slot plus candidate-set signature.

    Re-running an unchanged analysis reproduces the same ID (no duplicate
    review items) and an unchanged candidate set keeps an existing decision
    applicable.
    """
    return stable_id("patent-conflict-v1", slot_id, candidate_set)


def evidence_signature(rows: Iterable[tuple[str, int, str, str]]) -> str:
    """Order-independent signature over ``(evidence_id, page, kind, text)`` rows.

    Stored on snapshots and decisions so a re-extract — which changes the
    row set or its text — makes them stale instead of silently current.
    """
    row_hashes = sorted(
        stable_id("evidence-row-v1", evidence_id, str(page), kind, text)
        for evidence_id, page, kind, text in rows
    )
    return stable_id("evidence-set-v1", *row_hashes)


__all__ = [
    "assay_method_slot_id",
    "candidate_set_signature",
    "candidate_signature",
    "conditions_key",
    "conflict_id",
    "evidence_signature",
    "measurement_slot_id",
]
