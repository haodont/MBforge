"""Apply human decisions to one document's pending Patent facts.

A decision is reusable only while it still describes the same thing: the slot
must hold the same candidate set and the document must still cite the same
evidence set. A decision that no longer matches is reported as stale instead of
being applied to different facts.

The chosen reading is materialised back into the rule measurement shape so the
adopted fact flows through the ordinary publication path — an adopted LLM
reading keeps the entry and assay links the rule fact already had, because the
slot identity says they describe the same measurement.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from typing import Any

from mbforge.contracts.patent import PatentConflict
from mbforge.domain.patent_analysis import candidate_set_signature
from mbforge.foundation.ids import stable_id

#: The choices a reviewer may make for one contested fact slot.
DECISION_DETERMINISTIC = "deterministic"
DECISION_LLM = "llm"
DECISION_NEITHER = "neither"
PATENT_FACT_CHOICES = (DECISION_DETERMINISTIC, DECISION_LLM, DECISION_NEITHER)


@dataclass(frozen=True)
class DecisionApplication:
    """The pending facts after the reusable decisions have been applied."""

    measurements: list[dict[str, Any]] = field(default_factory=list)
    candidates: list[dict[str, Any]] = field(default_factory=list)
    conflicts: list[PatentConflict] = field(default_factory=list)
    applied: list[str] = field(default_factory=list)
    stale: list[str] = field(default_factory=list)


def apply_decisions(
    *,
    doc_id: str,
    measurements: Sequence[Mapping[str, Any]],
    candidates: Sequence[Mapping[str, Any]],
    conflicts: Sequence[PatentConflict],
    decisions: Mapping[str, Mapping[str, Any]],
    evidence_signature: str,
) -> DecisionApplication:
    """Fold the still-valid decisions into the pending facts."""
    valid = [dict(item) for item in measurements]
    pending = [dict(item) for item in candidates]
    unresolved: list[PatentConflict] = []
    applied: list[str] = []
    stale: list[str] = []

    for conflict in conflicts:
        decision = decisions.get(conflict.slot_id)
        if not decision:
            unresolved.append(conflict)
            continue
        if not _decision_matches(conflict, decision, evidence_signature):
            stale.append(conflict.slot_id)
            unresolved.append(conflict)
            continue
        chosen = _chosen_measurement(
            doc_id, conflict, str(decision.get("choice") or "")
        )
        if chosen is not None:
            valid.append(chosen)
        applied.append(conflict.slot_id)
        pending = [item for item in pending if item.get("slot_id") != conflict.slot_id]

    return DecisionApplication(
        measurements=valid,
        candidates=pending,
        conflicts=unresolved,
        applied=applied,
        stale=stale,
    )


def _decision_matches(
    conflict: PatentConflict,
    decision: Mapping[str, Any],
    evidence_signature: str,
) -> bool:
    """A decision applies only to the candidate set and evidence it was made on."""
    if str(decision.get("evidence_signature") or "") != evidence_signature:
        return False
    current_set = candidate_set_signature(
        [candidate.signature for candidate in conflict.candidates]
    )
    return str(decision.get("candidate_set_signature") or "") == current_set


def _chosen_measurement(
    doc_id: str, conflict: PatentConflict, choice: str
) -> dict[str, Any] | None:
    """The measurement a decision adopts, or ``None`` for ``neither``."""
    if choice not in (DECISION_DETERMINISTIC, DECISION_LLM):
        return None
    candidate = next(
        (item for item in conflict.candidates if item.source == choice), None
    )
    if candidate is None:
        return None
    raw = candidate.fields.get("measurement")
    if not isinstance(raw, Mapping):
        return None
    if choice == DECISION_DETERMINISTIC:
        return dict(raw)
    return _from_draft(doc_id, conflict, raw)


def _from_draft(
    doc_id: str, conflict: PatentConflict, raw: Mapping[str, Any]
) -> dict[str, Any] | None:
    """Materialise an adopted LLM reading as a rule-shaped measurement."""
    value = raw.get("value")
    if not isinstance(value, Mapping):
        return None
    rule = next(
        (
            item.fields.get("measurement")
            for item in conflict.candidates
            if item.source == DECISION_DETERMINISTIC
        ),
        None,
    )
    rule = rule if isinstance(rule, Mapping) else {}
    return {
        "measurement_id": stable_id("measurement-llm-v1", doc_id, conflict.slot_id),
        "doc_id": doc_id,
        # The slot identity says both readings describe one fact, so the entry
        # and assay links the rule side resolved still hold.
        "compound_entry_id": rule.get("compound_entry_id"),
        "assay_method_id": rule.get("assay_method_id"),
        # A reading the model bound to a recognized structure keeps that structure:
        # the adopted fact must land on the molecule the candidate showed, not on
        # "no molecule at all".
        "mol_id": raw.get("molecule_ref") or None,
        "metric": raw.get("metric"),
        "linking_status": "linked",
        "value": {
            "raw_text": value.get("raw_text", ""),
            "operator": value.get("operator", "") or "=",
            "original_value": value.get("value"),
            "original_unit": value.get("unit", ""),
            "canonical_value": None,
            "canonical_unit": "",
            "qualitative_value": value.get("qualitative", ""),
        },
        "evidence_ids": list(raw.get("evidence_ids") or [])[:50],
        "provenance": {
            "reference_raw": raw.get("compound_label_raw", ""),
            "reference_key": raw.get("compound_label_key", ""),
            "reference_type": "compound",
            "source": DECISION_LLM,
        },
    }


__all__ = [
    "DECISION_DETERMINISTIC",
    "DECISION_LLM",
    "DECISION_NEITHER",
    "PATENT_FACT_CHOICES",
    "DecisionApplication",
    "apply_decisions",
]
