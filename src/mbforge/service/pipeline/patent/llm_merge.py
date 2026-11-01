"""Align one submitted draft with the rule draft and decide what may be adopted.

Alignment uses the stable slot identity from :mod:`mbforge.domain.patent_analysis`
(document, anchor evidence, compound, assay, metric, conditions) — never the
value — and comparison reuses the existing activity normalization, so the same
``< 100 nM`` reading on both sides cannot be mistaken for a conflict while
``< 100 nM`` versus ``100 nM`` cannot be mistaken for agreement.

Per slot:

* **agreed** — the same semantic reading; nothing is adopted (the rule fact
  already stands) and nothing is queued for review;
* **llm-only** — no rule counterpart: unproven, so it becomes a review candidate
  instead of entering the valid set;
* **conflict** — incompatible readings in one slot: both are preserved, neither
  enters the valid set, and one review candidate offers the human the choice;
* **ambiguous** — the key matches several rule facts (or no anchor at all):
  reported, never merged.

A fact is never preferred merely because it cites valid evidence, and a rule fact
questioned by a conflict is held back until a human decides.
"""

from __future__ import annotations

from collections.abc import Collection, Mapping, Sequence
from dataclasses import dataclass, field
from typing import Any

from mbforge.contracts.patent import (
    ConflictCandidate,
    PatentConflict,
    PatentDraft,
)
from mbforge.domain.patent_analysis import (
    assay_method_slot_id,
    candidate_set_signature,
    candidate_signature,
    conditions_key,
    conflict_id,
    measurement_slot_id,
)
from mbforge.service.pipeline.activity.normalization import (
    NormalizedActivity,
    normalize_activity_measurement,
    normalize_reference_label,
    normalize_stored_measurement,
)

REASON_LLM_ONLY = "llm_only"
REASON_CONFLICT = "conflict"
REASON_AMBIGUOUS = "ambiguous"
REASON_PROSE_ASSAY = "prose_assay_method"

#: Bounds on what one candidate carries out of the merge.
MAX_EVIDENCE_REFS = 50


@dataclass(frozen=True)
class MergeResult:
    """What may be adopted, what is contested, and what needs a human."""

    measurements: list[dict[str, Any]]
    conflicts: list[PatentConflict] = field(default_factory=list)
    candidates: list[dict[str, Any]] = field(default_factory=list)
    stats: dict[str, int] = field(default_factory=dict)


def merge_submission(
    *,
    doc_id: str,
    rule_measurements: Sequence[Mapping[str, Any]],
    rule_assay_methods: Sequence[Mapping[str, Any]],
    submission: PatentDraft,
    evidence_pages: Mapping[str, int] | None = None,
    scope_evidence_ids: Collection[str] | None = None,
    scope_fact_ids: Collection[str] | None = None,
    scope_work_evidence_ids: Collection[str] | None = None,
) -> MergeResult:
    """Align and merge one validated submission against the rule draft.

    ``scope_evidence_ids`` and ``scope_fact_ids`` are the gap this submission
    answers: only rule facts anchored on that evidence, or named by that gap, are
    compared with it. Everything else stays out of scope, so an answer for one
    table can never be read as a conflict with a fact somewhere else, and a gap
    that names one measurement is not answered against a neighbour sharing its
    slot — which is where the ``ambiguous`` bucket came from.
    """
    pages = dict(evidence_pages or {})
    assays_by_id = {
        str(item.get("assay_method_id")): item for item in rule_assay_methods
    }
    draft_assays = {method.local_key: method for method in submission.assay_methods}
    scope_evidence = set(scope_evidence_ids) if scope_evidence_ids else None
    scope_facts = set(scope_fact_ids) if scope_fact_ids else None

    slots: dict[str, list[dict[str, Any]]] = {}
    loose: dict[str, list[dict[str, Any]]] = {}
    for measurement in rule_measurements:
        if not _in_scope(measurement, scope_evidence, scope_facts):
            continue
        slot = _rule_slot(doc_id, measurement, assays_by_id)
        if slot:
            slots.setdefault(slot, []).append(dict(measurement))
            loose.setdefault(
                _rule_slot(doc_id, measurement, assays_by_id, with_assay=False), []
            ).append(dict(measurement))

    contested: set[str] = set()
    conflicts: list[PatentConflict] = []
    candidates: list[dict[str, Any]] = []
    stats = {
        "deterministic": len(rule_measurements),
        "agreed": 0,
        "llm_only": 0,
        "conflict": 0,
        "ambiguous": 0,
        "unattributed": 0,
        "prose_assay_methods": 0,
        "held_back": 0,
    }

    for measurement in submission.measurements:
        # A reading with no designation and no structure reference cannot be
        # attached to anything: it is dropped and counted, never queued as a
        # fact that a reviewer has to guess an owner for.
        if not _is_attributed(measurement):
            stats["unattributed"] += 1
            continue
        # A submission that states no assay context can still align, but only
        # when the loose key resolves to exactly one slot — otherwise the
        # reference is ambiguous and must be reported, not guessed.
        states_assay = bool(measurement.assay_local_key) or any(
            (measurement.target, measurement.system, measurement.endpoint)
        )
        work_anchor = _anchor(
            [
                eid
                for eid in measurement.evidence_ids
                if scope_work_evidence_ids and eid in scope_work_evidence_ids
            ]
        )
        key = _llm_slot(
            doc_id,
            measurement,
            draft_assays,
            with_assay=states_assay,
            anchor_evidence_id=work_anchor,
        )
        peers = slots.get(key, []) if states_assay else loose.get(key, [])
        if (
            not states_assay
            and len({_rule_slot(doc_id, peer, assays_by_id) for peer in peers}) > 1
        ):
            candidates.append(
                _candidate(REASON_AMBIGUOUS, key, measurement, pages, peers=peers)
            )
            stats["ambiguous"] += 1
            continue
        if not peers:
            candidates.append(_candidate(REASON_LLM_ONLY, key, measurement, pages))
            stats["llm_only"] += 1
            continue
        if len(peers) > 1:
            candidates.append(
                _candidate(REASON_AMBIGUOUS, key, measurement, pages, peers=peers)
            )
            stats["ambiguous"] += 1
            continue

        rule = peers[0]
        # A conflict belongs to the rule fact's slot, so a reviewer's decision is
        # reusable across re-runs even when the submission stated less.
        slot = _rule_slot(doc_id, rule, assays_by_id) or key
        rule_fields = _reading_fields(_rule_reading(rule))
        llm_fields = _reading_fields(_llm_reading(measurement))
        if rule_fields == llm_fields:
            stats["agreed"] += 1
            continue
        conflict = _conflict(
            doc_id, slot, rule, measurement, rule_fields, llm_fields, pages
        )
        conflicts.append(conflict)
        candidates.append(_conflict_candidate(conflict, rule, measurement, pages))
        contested.add(slot)
        stats["conflict"] += 1

    valid = [
        dict(measurement)
        for measurement in rule_measurements
        if _rule_slot(doc_id, measurement, assays_by_id) not in contested
    ]
    stats["held_back"] = len(rule_measurements) - len(valid)

    for method in submission.assay_methods:
        candidates.append(_assay_candidate(doc_id, method))
        stats["prose_assay_methods"] += 1

    return MergeResult(
        measurements=valid, conflicts=conflicts, candidates=candidates, stats=stats
    )


# -- slots -------------------------------------------------------------------


def _anchor(evidence_ids: Sequence[str] | None) -> str | None:
    """The slot anchor: the smallest evidence id (stable, order-independent)."""
    ids = sorted(item for item in (evidence_ids or []) if item)
    return ids[0] if ids else None


def _is_attributed(measurement: Any) -> bool:
    """Whether a reading names an owner: a printed designation or a structure.

    ``molecule_ref`` counts because the service layer only accepts a label key or
    mol_id that this document's own structures returned.
    """
    return bool(
        str(getattr(measurement, "row_label_raw", "") or "").strip()
        or str(getattr(measurement, "compound_label_raw", "") or "").strip()
        or str(getattr(measurement, "compound_label_key", "") or "").strip()
        or str(getattr(measurement, "molecule_ref", "") or "").strip()
    )


def _in_scope(
    measurement: Mapping[str, Any],
    scope_evidence: set[str] | None,
    scope_facts: set[str] | None,
) -> bool:
    """Whether a rule fact lies inside the gap an answer is scoped to.

    A fact is in scope when the gap named it, or when it is anchored on the
    gap's own evidence. Without a scope every fact is in scope, which is the
    whole-document behaviour the scoped merge replaces.
    """
    if scope_evidence is None and scope_facts is None:
        return True
    fact_id = str(measurement.get("measurement_id") or "")
    if scope_facts is not None and fact_id and fact_id in scope_facts:
        return True
    if scope_evidence is None:
        return False
    return _anchor(measurement.get("evidence_ids")) in scope_evidence


def _field(source: Any, name: str) -> Any:
    if isinstance(source, Mapping):
        return source.get(name)
    return getattr(source, name, None)


def _text(value: Any) -> str:
    return " ".join(str(value or "").split()).casefold()


def _assay_signature(source: Any) -> str:
    """Comparable assay identity: target, species system and endpoint."""
    if source is None:
        return ""
    return conditions_key(
        {
            "target": _text(_field(source, "target")),
            "system": _text(_field(source, "system")),
            "endpoint": _text(_field(source, "endpoint")),
        }
    )


def _rule_slot(
    doc_id: str,
    measurement: Mapping[str, Any],
    assays_by_id: Mapping[str, Mapping[str, Any]],
    *,
    with_assay: bool = True,
) -> str | None:
    anchor = _anchor(measurement.get("evidence_ids"))
    if anchor is None:
        return None
    assay_key = ""
    if with_assay:
        assay = assays_by_id.get(str(measurement.get("assay_method_id") or ""))
        assay_key = _assay_signature(assay) if assay else ""
    provenance = measurement.get("provenance") or {}
    return measurement_slot_id(
        doc_id,
        anchor_evidence_id=anchor,
        compound_key=_text(provenance.get("reference_key")),
        assay_key=assay_key,
        metric=_text(measurement.get("metric")),
    )


def _llm_slot(
    doc_id: str,
    measurement: Any,
    draft_assays: Mapping[str, Any],
    *,
    with_assay: bool = True,
    anchor_evidence_id: str | None = None,
) -> str:
    # The draft contract requires at least one evidence reference, so the anchor
    # is always available for a validated submission.
    anchor = anchor_evidence_id or _anchor(measurement.evidence_ids) or ""
    assay_key = ""
    if with_assay:
        assay_key = _assay_signature(
            draft_assays.get(measurement.assay_local_key) or measurement
        )
    reference = normalize_reference_label(
        measurement.compound_label_raw or measurement.compound_label_key
    )
    return measurement_slot_id(
        doc_id,
        anchor_evidence_id=anchor,
        compound_key=_text(
            measurement.compound_label_key
            if measurement.compound_label_key.startswith("@example:")
            else reference.key or measurement.compound_label_key
        ),
        assay_key=assay_key,
        metric=_text(measurement.metric),
        # Rule measurements carry no conditions today, so a submission that
        # states any stays a separate slot (and thus a review candidate) rather
        # than being folded into a rule fact.
        conditions=measurement.conditions,
    )


# -- readings ----------------------------------------------------------------


def _rule_reading(measurement: Mapping[str, Any]) -> NormalizedActivity:
    value = measurement.get("value") or {}
    return normalize_stored_measurement(measurement.get("metric"), value)


def _llm_reading(measurement: Any) -> NormalizedActivity:
    value = measurement.value
    number = (
        value.value
        if value.value is not None
        else (value.qualitative or value.raw_text)
    )
    return normalize_activity_measurement(
        measurement.metric,
        number,
        value.unit,
        value.operator or "=",
        value_text=value.raw_text,
    )


def _reading_fields(reading: NormalizedActivity) -> dict[str, Any]:
    """The compared fields; the raw text is display-only and never signed."""
    fields = {
        "metric": reading.metric,
        "operator": reading.operator,
        "value_canonical": reading.value_canonical,
        "unit_canonical": reading.unit_canonical,
        "qualitative": reading.qualitative_label,
    }
    if reading.value_canonical is None and reading.value_original is not None:
        fields["value_unconverted"] = reading.value_original
        fields["unit_unconverted"] = reading.unit_original
    return fields


def _display_fields(source: Any, fields: Mapping[str, Any]) -> dict[str, Any]:
    """The compared fields plus the raw reading a decision can be applied from."""
    if isinstance(source, Mapping):
        raw: Any = source
        value = source.get("value") or {}
        raw_text = value.get("raw_text", "")
    else:
        raw = source.model_dump(mode="json")
        raw_text = source.value.raw_text
    return {**fields, "value_text": raw_text, "measurement": raw}


# -- conflicts and candidates ------------------------------------------------


def _page_of(evidence_ids: Sequence[str], pages: Mapping[str, int]) -> int | None:
    known = [pages[item] for item in evidence_ids if item in pages]
    return min(known) if known else None


def _conflict(
    doc_id: str,
    slot: str,
    rule: Mapping[str, Any],
    submission: Any,
    rule_fields: Mapping[str, Any],
    llm_fields: Mapping[str, Any],
    pages: Mapping[str, int],
) -> PatentConflict:
    rule_signature = candidate_signature(rule_fields)
    llm_signature = candidate_signature(llm_fields)
    rule_evidence = sorted(rule.get("evidence_ids") or [])
    llm_evidence = sorted(submission.evidence_ids)
    return PatentConflict(
        conflict_id=conflict_id(
            slot, candidate_set_signature([rule_signature, llm_signature])
        ),
        slot_id=slot,
        kind="measurement",
        doc_id=doc_id,
        page=_page_of(rule_evidence, pages)
        or submission.page
        or _page_of(llm_evidence, pages),
        evidence_ids=sorted(set(rule_evidence) | set(llm_evidence))[:MAX_EVIDENCE_REFS],
        candidates=[
            ConflictCandidate(
                source="deterministic",
                fields=_display_fields(rule, rule_fields),
                signature=rule_signature,
                evidence_ids=rule_evidence[:MAX_EVIDENCE_REFS],
            ),
            ConflictCandidate(
                source="llm",
                fields=_display_fields(submission, llm_fields),
                signature=llm_signature,
                evidence_ids=llm_evidence[:MAX_EVIDENCE_REFS],
            ),
        ],
    )


def _candidate(
    reason: str,
    slot: str,
    measurement: Any,
    pages: Mapping[str, int],
    *,
    peers: Sequence[Mapping[str, Any]] | None = None,
) -> dict[str, Any]:
    llm_fields = _reading_fields(_llm_reading(measurement))
    signatures = [candidate_signature(llm_fields)] + [
        candidate_signature(_reading_fields(_rule_reading(peer)))
        for peer in peers or []
    ]
    return {
        "reason": reason,
        "kind": "measurement",
        "slot_id": slot,
        "review_item_id": conflict_id(slot, candidate_set_signature(signatures)),
        "page": measurement.page or _page_of(measurement.evidence_ids, pages),
        "evidence_ids": sorted(measurement.evidence_ids)[:MAX_EVIDENCE_REFS],
        "deterministic": [
            _display_fields(peer, _reading_fields(_rule_reading(peer)))
            for peer in peers or []
        ]
        or None,
        "llm": {
            **_display_fields(measurement, llm_fields),
            # The structure the reading was attached to, as a recognized label
            # key or mol_id (never a SMILES); a reviewer sees the assignment.
            "molecule_ref": measurement.molecule_ref,
        },
        "conflict": None,
    }


def _conflict_candidate(
    conflict: PatentConflict,
    rule: Mapping[str, Any],
    submission: Any,
    pages: Mapping[str, int],
) -> dict[str, Any]:
    return {
        "reason": REASON_CONFLICT,
        "kind": "measurement",
        "slot_id": conflict.slot_id,
        "review_item_id": conflict.conflict_id,
        "page": conflict.page or _page_of(submission.evidence_ids, pages),
        "evidence_ids": list(conflict.evidence_ids),
        "deterministic": [_display_fields(rule, _reading_fields(_rule_reading(rule)))],
        "llm": [
            {
                **_display_fields(
                    submission, _reading_fields(_llm_reading(submission))
                ),
                "molecule_ref": submission.molecule_ref,
            }
        ],
        "conflict": conflict,
    }


def _assay_candidate(doc_id: str, method: Any) -> dict[str, Any]:
    anchor = _anchor(method.evidence_ids) or ""
    slot = assay_method_slot_id(
        doc_id,
        anchor_evidence_id=anchor,
        endpoint_key=_text(method.endpoint),
        target_key=_text(method.target),
        system_key=_text(method.system),
    )
    fields = {
        "target": method.target,
        "system": method.system,
        "endpoint": method.endpoint,
        "assay_type": method.assay_type,
    }
    signature = candidate_signature(
        {key: _text(value) for key, value in fields.items()}
    )
    return {
        "reason": REASON_PROSE_ASSAY,
        "kind": "assay_method",
        "slot_id": slot,
        "review_item_id": conflict_id(slot, candidate_set_signature([signature])),
        "page": method.page_start or _page_of(method.evidence_ids, {}),
        "evidence_ids": sorted(method.evidence_ids)[:MAX_EVIDENCE_REFS],
        "deterministic": None,
        "llm": {**fields, "raw_text": method.raw_text, "local_key": method.local_key},
        "conflict": None,
    }


__all__ = [
    "REASON_AMBIGUOUS",
    "REASON_CONFLICT",
    "REASON_LLM_ONLY",
    "REASON_PROSE_ASSAY",
    "MergeResult",
    "merge_submission",
]
