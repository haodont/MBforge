"""Deterministic relationships between Patent facts and Detection candidates."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import TYPE_CHECKING, Any

from mbforge.domain.patent import (
    EXAMPLE_KEY_PREFIX,
    ROLE_COMPOUND,
    STATUS_PENDING,
    STRUCTURE_RESOLVED,
    CompoundEntry,
    designation_key,
    entry_id,
)
from mbforge.service.pipeline.patent.candidate_labels import candidate_label_keys
from mbforge.service.pipeline.patent.sections import (
    ParsedSection as DocumentSection,
)
from mbforge.service.pipeline.persist.molecules import filter_persistable_candidates

if TYPE_CHECKING:
    from mbforge.service.pipeline.activity.normalization import ReferenceLabel


def _string_ids(values: object) -> list[str]:
    if not isinstance(values, list):
        return []
    return list(dict.fromkeys(value for value in values if isinstance(value, str)))


#: Issue codes that report a *relation* the rules could not make. They are a
#: function of the current state, not a log: a later pass that resolves the
#: relation — an association the model supplied — must not leave the old report
#: standing, or the artifact would deny a link it just made.
RELATION_ISSUE_CODES: frozenset[str] = frozenset(
    {
        "compound_reference_unresolved",
        "compound_entry_ambiguous",
        "assay_method_unresolved",
        "molecule_label_unresolved",
        "molecule_candidate_ambiguous",
        "molecule_candidate_rejected",
        "molecule_evidence_unresolved",
    }
)


def _clear_relation_issues(issues: list[dict[str, Any]]) -> None:
    """Drop the relation reports a previous pass left behind.

    The reports below are a function of the relations *this* pass derives, so the
    pass owns that slice of the list. A later pass — after an association the model
    supplied — must not leave a failure standing that it has since resolved, or the
    artifact would deny a link it just made. No other producer emits these codes.
    """
    issues[:] = [
        issue for issue in issues if issue.get("code") not in RELATION_ISSUE_CODES
    ]


def _is_example_identity(entry: dict[str, Any]) -> bool:
    """True when the entry only stands for an example section's own label."""
    label_key = entry.get("label_key")
    return isinstance(label_key, str) and label_key.startswith(EXAMPLE_KEY_PREFIX)


def _group_by_label(
    entries: Sequence[dict[str, Any]],
) -> dict[str, list[dict[str, Any]]]:
    """Group entries by normalized designation, keeping reading order."""
    grouped: dict[str, list[dict[str, Any]]] = {}
    for entry in entries:
        label_key = entry.get("label_key")
        if isinstance(label_key, str) and label_key:
            grouped.setdefault(label_key, []).append(entry)
    return grouped


def _append_issue(
    issues: list[dict[str, Any]],
    code: str,
    message: str,
    evidence_ids: list[str],
    fact_id: str | None,
    *,
    severity: str = "warning",
    label_key: str | None = None,
) -> None:
    if any(
        issue.get("code") == code and issue.get("related_fact_id") == fact_id
        for issue in issues
    ):
        return
    issue: dict[str, Any] = {
        "code": code,
        "message": message,
        "severity": severity,
        "evidence_ids": list(dict.fromkeys(evidence_ids)),
        "related_fact_id": fact_id,
    }
    if label_key is not None:
        issue["label_key"] = label_key
    issues.append(issue)


def _candidate_evidence_ids(candidate: Any, valid_ids: set[str]) -> list[str]:
    return list(
        dict.fromkeys(
            detection.evidence_id
            for detection in getattr(candidate, "detections", [])
            if isinstance(getattr(detection, "evidence_id", None), str)
            and detection.evidence_id in valid_ids
        )
    )


def apply_gap_links(
    entries: list[dict],
    links: Sequence[Mapping[str, Any]],
    *,
    doc_id: str = "",
    sections: Sequence[DocumentSection] = (),
    candidates: Sequence[Any] = (),
    measurements: Sequence[dict[str, Any]] = (),
    attributions: Sequence[dict[str, Any]] = (),
) -> int:
    """Attach the structures the model linked to the designations they name.

    The model names a structure for a designation it read; Python derives the key
    space (``designation_key``), so a link can only ever meet a designation in the
    space Python owns. It never rewrites a rule fact and never states a reading —
    association is the model's whole job here, and this is where that job is
    consumed.

    A designation is met in one of two ways, and the second one is the point of the
    gap path: the designations the rules dropped are exactly the ones the model was
    asked about.

    * an entry that already prints the designation is resolved in place — unless the
      rules already resolved it, because a deterministic match is not silently
      overwritten by a suggestion;
    * a designation no section declared (a table row label, a prose mention, an
      example nothing prepares) is already declared by the rule pass from the print
      itself, and the link resolves that entry. Minting stays for the case where
      even the print is ambiguous, and the record is the existing
      :class:`CompoundEntry`, marked as still awaiting review, so a declared
      designation is visible as one instead of a silent alias.

    ``measurements`` are then stamped with the structure their own provenance
    cites: that field, not the entry, is what the persisted activity reads.

    ``attributions`` are the printed passages that name their owner in words the
    rules did not read — a spectrum, a printed name, a preparation route. The same
    link answers them: the model read those evidence rows and named the designation
    they print. One link settles exactly one unattributed passage whose own evidence
    is the one the link cites, and only when nothing else claims that row; anything
    else stays unattributed rather than being paired by guesswork.
    """
    by_key = {
        str(entry.get("label_key") or ""): entry
        for entry in entries
        if entry.get("label_key")
    }
    # Both identity spaces: the document names a candidate by ``mol_id`` in a gap
    # payload and by canonical SMILES everywhere persistence looks, so a link's
    # reference is translated when the pair is known, never copied blind.
    by_ref: dict[str, str] = {}
    for candidate in candidates:
        smiles = getattr(candidate, "canonical_smiles", "")
        smiles = smiles.strip() if isinstance(smiles, str) else ""
        if not smiles:
            continue
        by_ref[smiles] = smiles
        mol_ref = str(getattr(candidate, "mol_id", "") or "").strip()
        if mol_ref:
            by_ref.setdefault(mol_ref, smiles)
    section_by_evidence = {
        evidence_id: section.section_id
        for section in sections
        for evidence_id in section.evidence_ids
    }

    applied = 0
    resolved: dict[str, str] = {}
    for link in links:
        key = designation_key(str(link.get("label_raw") or ""))
        mol_id = str(link.get("mol_id") or "")
        if not key or not mol_id:
            continue
        entity = by_ref.get(mol_id, mol_id)
        evidence_ids = [
            evidence_id
            for evidence_id in (link.get("evidence_ids") or [])
            if isinstance(evidence_id, str)
        ]
        entry = by_key.get(key)
        if entry is not None:
            if entry.get("structure_status") == STRUCTURE_RESOLVED:
                continue
            entry["entity_id"] = entity
            entry["structure_status"] = STRUCTURE_RESOLVED
            entry["linking_status"] = "linked"
            entry["evidence_ids"] = list(
                dict.fromkeys(list(entry.get("evidence_ids") or []) + evidence_ids)
            )[:50]
        elif doc_id:
            section_id = next(
                (
                    section_by_evidence[evidence_id]
                    for evidence_id in evidence_ids
                    if evidence_id in section_by_evidence
                ),
                "",
            )
            entry = CompoundEntry(
                entry_id=entry_id(doc_id, section_id, key),
                doc_id=doc_id,
                label_raw=str(link.get("label_raw") or ""),
                label_key=key,
                entry_role=ROLE_COMPOUND,
                section_id=section_id,
                entity_id=entity,
                structure_status=STRUCTURE_RESOLVED,
                linking_status="linked",
                review_status=STATUS_PENDING,
                evidence_ids=list(dict.fromkeys(evidence_ids))[:50],
            ).to_dict()
            entries.append(entry)
            by_key[key] = entry
        else:
            continue
        resolved[key] = entity
        applied += 1

    for measurement in measurements:
        if not isinstance(measurement, dict) or measurement.get("mol_id"):
            continue
        provenance = measurement.get("provenance")
        provenance = provenance if isinstance(provenance, dict) else {}
        key = designation_key(
            provenance.get("reference_raw") or provenance.get("reference_key") or ""
        )
        entity = resolved.get(key)
        if not entity:
            continue
        measurement["mol_id"] = entity
        measurement["linking_status"] = "linked"

    if attributions and links:
        # A passage names its owner in words the rules did not read. The link that
        # answers it carries the evidence the model read, so the passage on that row
        # is the one it spoke about — but only when exactly one unattributed passage
        # sits there and exactly one link cites that row. A row printing two spectra,
        # or two links over the same row, is a pairing nobody decided.
        unattributed: dict[str, list[dict[str, Any]]] = {}
        for item in attributions:
            if not isinstance(item, dict) or item.get("label_key"):
                continue
            for evidence_id in item.get("evidence_ids") or []:
                if isinstance(evidence_id, str):
                    unattributed.setdefault(evidence_id, []).append(item)
        claimed: dict[str, int] = {}
        for link in links:
            for evidence_id in link.get("evidence_ids") or []:
                if isinstance(evidence_id, str):
                    claimed[evidence_id] = claimed.get(evidence_id, 0) + 1
        for link in links:
            key = designation_key(str(link.get("label_raw") or ""))
            cited = [
                evidence_id
                for evidence_id in (link.get("evidence_ids") or [])
                if isinstance(evidence_id, str)
            ]
            if not key or len(cited) != 1 or claimed.get(cited[0], 0) != 1:
                continue
            pending = unattributed.get(cited[0], [])
            if len(pending) != 1:
                continue
            pending[0]["label_key"] = key
            pending[0]["attribution"] = "resolved"

    return applied


def _declare_entry(
    entries: list[dict[str, Any]],
    entries_by_label: dict[str, list[dict[str, Any]]],
    measurement: Mapping[str, Any],
    reference: ReferenceLabel,
    provenance: Mapping[str, Any],
    evidence_ids: Sequence[str],
) -> dict[str, Any]:
    """Declare the designation a passage prints when no section declares it.

    A table row or a sentence printing ``化合物23`` / ``实施例23`` *is* a declaration
    of this document: the parser accepted the cell as a designation before the
    reading existed, so the entry is minted here instead of the reading being
    reported as ownerless. ``review_status`` stays pending, because only the printed
    label vouches for it. Structure resolution is unchanged — the entry pass below
    still has to find a candidate, and an accepted model link can do the same job.
    """
    doc_id = str(measurement.get("doc_id") or "")
    printed = str(provenance.get("reference_raw") or reference.raw or "")
    # The key comes from the printed designation, exactly as in ``apply_gap_links``:
    # ``实施例23`` declares ``@example:23``, never the compound ``23``.
    label_key = designation_key(printed) or reference.key
    minted = CompoundEntry(
        entry_id=entry_id(doc_id, "", label_key),
        doc_id=doc_id,
        label_raw=printed or reference.key,
        label_key=label_key,
        entry_role=ROLE_COMPOUND,
        section_id="",
        linking_status=STATUS_PENDING,
        review_status=STATUS_PENDING,
        evidence_ids=list(evidence_ids)[:50],
    ).to_dict()
    entries.append(minted)
    entries_by_label.setdefault(label_key, []).append(minted)
    return minted


def associate_facts(
    sections: list[DocumentSection],
    entries: list[dict[str, Any]],
    assay_methods: list[dict[str, Any]],
    measurements: list[dict[str, Any]],
    candidates: list[Any],
    valid_evidence_ids: set[str],
    issues: list[dict[str, Any]],
) -> None:
    """Attach only deterministic, evidence-backed relationships in Patent.

    The relation reports are recomputed here, not appended to: this function runs
    once for the rule draft and again after the model's associations are applied,
    and the second pass must report the state it now finds.
    """
    from mbforge.service.pipeline.activity.normalization import (
        normalize_reference_label,
    )
    from mbforge.service.pipeline.patent.sections import example_token

    _clear_relation_issues(issues)
    sections_by_id = {section.section_id: section for section in sections}
    entries_by_label = _group_by_label(entries)

    entries_by_section: dict[str, list[dict[str, Any]]] = {}
    for entry in entries:
        section_ref = entry.get("section_id")
        if isinstance(section_ref, str) and section_ref:
            entries_by_section.setdefault(section_ref, []).append(entry)

    # ``实施例9`` names the compound its own section prepares; a bare number is
    # never a document-wide alias for every compound that shares it.
    entries_by_example: dict[str, list[dict[str, Any]]] = {}
    for section in sections:
        token = example_token(section)
        if token is None:
            continue
        entries_by_example.setdefault(token, []).extend(
            entries_by_section.get(section.section_id, [])
        )

    methods_by_section: dict[str, list[dict[str, Any]]] = {}
    for method in assay_methods:
        section_id = method.get("section_id")
        if isinstance(section_id, str):
            methods_by_section.setdefault(section_id, []).append(method)

    for measurement in measurements:
        measurement_id = measurement.get("measurement_id")
        fact_id = measurement_id if isinstance(measurement_id, str) else None
        evidence_ids = _string_ids(measurement.get("evidence_ids"))
        provenance = measurement.get("provenance")
        provenance = provenance if isinstance(provenance, dict) else {}
        reference = normalize_reference_label(
            provenance.get("reference_raw") or provenance.get("reference_key") or ""
        )
        example_entries = (
            entries_by_example.get(reference.key, [])
            if reference.key and reference.reference_type == "example"
            else []
        )
        # Splitting one heading into several blocks yields several sections for
        # the same example; they declare the same compound, so the identity is
        # decided by distinct designations, not by section count. Only a title
        # declaration can replace the example identity; body mentions may be reagents.
        compound_entries = [
            entry
            for entry in example_entries
            if not _is_example_identity(entry)
            and (section := sections_by_id.get(entry.get("section_id"))) is not None
            and set(_string_ids(entry.get("evidence_ids")))
            & set(section.title_evidence_ids)
        ]
        declared = [
            group[0]
            for group in _group_by_label(
                compound_entries
                or [entry for entry in example_entries if _is_example_identity(entry)]
            ).values()
        ]
        if len(declared) == 1:
            measurement["compound_entry_id"] = declared[0]["entry_id"]
        elif declared:
            _append_issue(
                issues,
                "compound_entry_ambiguous",
                f"example reference {reference.key} is claimed by several compounds",
                evidence_ids,
                fact_id,
            )
        elif reference.key and reference.reference_type == "example":
            # No title-backed product identity exists; retain the printed example
            # designation without borrowing a body compound or an equal number.
            measurement["compound_entry_id"] = _declare_entry(
                entries,
                entries_by_label,
                measurement,
                reference,
                provenance,
                evidence_ids,
            )["entry_id"]
        elif (
            reference.key is None
            or reference.reference_type != "compound"
            or reference.ambiguous
        ):
            _append_issue(
                issues,
                "compound_reference_unresolved",
                "measurement has no unambiguous compound reference",
                evidence_ids,
                fact_id,
            )
        else:
            entry_matches = entries_by_label.get(reference.key, [])
            if not entry_matches:
                measurement["compound_entry_id"] = _declare_entry(
                    entries,
                    entries_by_label,
                    measurement,
                    reference,
                    provenance,
                    evidence_ids,
                )["entry_id"]
            elif len(entry_matches) == 1:
                measurement["compound_entry_id"] = entry_matches[0]["entry_id"]
            else:
                scoped: list[dict[str, Any]] = []
                for entry in entry_matches:
                    section = sections_by_id.get(entry.get("section_id"))
                    if section is not None and set(evidence_ids) & set(
                        section.evidence_ids
                    ):
                        scoped.append(entry)
                if len(scoped) == 1:
                    measurement["compound_entry_id"] = scoped[0]["entry_id"]
                else:
                    _append_issue(
                        issues,
                        "compound_entry_ambiguous",
                        f"compound reference {reference.key} matches multiple entries",
                        evidence_ids,
                        fact_id,
                    )

        matching_sections = [
            section
            for section in sections
            if set(evidence_ids) & set(section.evidence_ids)
        ]
        matching_methods = [
            method
            for section in matching_sections
            for method in methods_by_section.get(section.section_id, [])
        ]
        # A section can print several assays (``测试例1`` … ``测试例4``). The
        # method whose own evidence block cites this reading's row settles which
        # one; otherwise the section has to own exactly one method.
        citing = [
            method
            for method in matching_methods
            if set(evidence_ids) & set(method.get("evidence_ids") or [])
        ]
        if len(citing) == 1:
            chosen = citing[0]
        elif len(matching_sections) == 1 and len(matching_methods) == 1:
            chosen = matching_methods[0]
        else:
            chosen = None
        if chosen is not None:
            measurement["assay_method_id"] = chosen["assay_method_id"]
        else:
            _append_issue(
                issues,
                "assay_method_unresolved",
                "measurement cannot be assigned to one assay method",
                evidence_ids,
                fact_id,
            )

        # A fact whose every relation this pass resolved is bound; the reports an
        # earlier pass left for it are gone (the reset at the top of this function).
        relation_issue = any(
            issue.get("related_fact_id") == fact_id
            and issue.get("code") in RELATION_ISSUE_CODES
            for issue in issues
        )
        measurement["linking_status"] = "failed" if relation_issue else "linked"

    candidate_matches: dict[str, list[tuple[Any, set[str], list[str]]]] = {}
    for candidate in filter_persistable_candidates("", list(candidates), warn=False):
        keys = candidate_label_keys(candidate)
        evidence_ids = _candidate_evidence_ids(candidate, valid_evidence_ids)
        if not keys:
            if evidence_ids:
                _append_issue(
                    issues,
                    "molecule_label_unresolved",
                    "Detection candidate has no verifiable compound label",
                    evidence_ids,
                    None,
                )
            continue
        for key in keys:
            candidate_matches.setdefault(key, []).append(
                (candidate, keys, evidence_ids)
            )

    for entry in entries:
        fact_entry_id = entry.get("entry_id")
        label_key = entry.get("label_key")
        if not isinstance(fact_entry_id, str) or not isinstance(label_key, str):
            continue
        matches = candidate_matches.get(label_key, [])
        if not matches:
            # The candidate list carries no such label. That is not "nothing to do":
            # it is the one association only a reader can make, and every reading
            # that cites the designation stays unowned until it is made. Reporting
            # it hands the designation over (``molecule_label_unresolved`` is a gap
            # kind) instead of leaving it silently unresolved — unless the entry is
            # already resolved, which is what an accepted association looks like
            # when no candidate prints the designation as a label.
            if not entry.get("entity_id"):
                _append_issue(
                    issues,
                    "molecule_label_unresolved",
                    f"designation {label_key} has no recognized structure",
                    _string_ids(entry.get("evidence_ids")),
                    fact_entry_id,
                    severity="info",
                )
            continue
        if len(matches) > 1 or any(len(keys) != 1 for _, keys, _ in matches):
            _append_issue(
                issues,
                "molecule_candidate_ambiguous",
                f"compound label {label_key} matches multiple Detection candidates",
                list(dict.fromkeys(eid for _, _, ids in matches for eid in ids)),
                fact_entry_id,
                label_key=label_key,
            )
            continue
        candidate, _, candidate_evidence_ids = matches[0]
        if not candidate_evidence_ids:
            _append_issue(
                issues,
                "molecule_evidence_unresolved",
                f"Detection candidate for {label_key} has no SQL evidence",
                [],
                fact_entry_id,
            )
            continue
        entry["evidence_ids"] = list(
            dict.fromkeys(
                _string_ids(entry.get("evidence_ids")) + candidate_evidence_ids
            )
        )
        candidate_smiles = getattr(candidate, "canonical_smiles", "")
        entry["entity_id"] = (
            candidate_smiles.strip() if isinstance(candidate_smiles, str) else None
        )
        entry["structure_status"] = STRUCTURE_RESOLVED
        entry["linking_status"] = "linked"


__all__ = ["associate_facts"]
