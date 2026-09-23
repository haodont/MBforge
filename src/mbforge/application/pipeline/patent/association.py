"""Deterministic relationships between Patent facts and Detection candidates."""

from __future__ import annotations

from typing import Any

from mbforge.application.pipeline.patent.sections import (
    ParsedSection as DocumentSection,
)


def _string_ids(values: object) -> list[str]:
    if not isinstance(values, list):
        return []
    return list(dict.fromkeys(value for value in values if isinstance(value, str)))


def _append_issue(
    issues: list[dict[str, Any]],
    code: str,
    message: str,
    evidence_ids: list[str],
    fact_id: str | None,
) -> None:
    if any(
        issue.get("code") == code and issue.get("related_fact_id") == fact_id
        for issue in issues
    ):
        return
    issues.append(
        {
            "code": code,
            "message": message,
            "severity": "warning",
            "evidence_ids": list(dict.fromkeys(evidence_ids)),
            "related_fact_id": fact_id,
        }
    )


def _candidate_label_keys(candidate: Any) -> set[str]:
    from mbforge.application.pipeline.detection.label_normalization import (
        LabelKind,
        normalize_coref_label,
    )

    properties = getattr(candidate, "properties", {})
    properties = properties if isinstance(properties, dict) else {}
    values: list[str] = []
    for key in (
        "ocr_labels_primary",
        "ocr_labels",
        "raw_coref_label",
        "normalized_label",
        "label",
        "formula_label",
    ):
        value = properties.get(key)
        if isinstance(value, str):
            values.append(value)
        elif isinstance(value, list):
            values.extend(item for item in value if isinstance(item, str))

    keys: set[str] = set()
    for value in values:
        normalized = normalize_coref_label(value)
        if normalized is not None and normalized.kind is LabelKind.COMPOUND:
            keys.add(normalized.normalized)
    return keys


def _candidate_evidence_ids(candidate: Any, valid_ids: set[str]) -> list[str]:
    return list(
        dict.fromkeys(
            detection.evidence_id
            for detection in getattr(candidate, "detections", [])
            if isinstance(getattr(detection, "evidence_id", None), str)
            and detection.evidence_id in valid_ids
        )
    )


def associate_facts(
    sections: list[DocumentSection],
    entries: list[dict[str, Any]],
    assay_methods: list[dict[str, Any]],
    measurements: list[dict[str, Any]],
    candidates: list[Any],
    valid_evidence_ids: set[str],
    issues: list[dict[str, Any]],
) -> None:
    """Attach only deterministic, evidence-backed relationships in Patent."""
    from mbforge.application.pipeline.activity.normalization import (
        normalize_reference_label,
    )

    sections_by_id = {section.section_id: section for section in sections}
    entries_by_label: dict[str, list[dict[str, Any]]] = {}
    for entry in entries:
        label_key = entry.get("label_key")
        if isinstance(label_key, str) and label_key:
            entries_by_label.setdefault(label_key, []).append(entry)

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
        if (
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
                _append_issue(
                    issues,
                    "dangling_fact_reference",
                    f"compound reference {reference.key} has no matching entry",
                    evidence_ids,
                    fact_id,
                )
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
        if len(matching_sections) == 1 and len(matching_methods) == 1:
            measurement["assay_method_id"] = matching_methods[0]["assay_method_id"]
        else:
            _append_issue(
                issues,
                "assay_method_unresolved",
                "measurement cannot be assigned to one assay method",
                evidence_ids,
                fact_id,
            )

        relation_issue = any(
            issue.get("related_fact_id") == fact_id
            and issue.get("code")
            in {
                "compound_reference_unresolved",
                "compound_entry_ambiguous",
                "dangling_fact_reference",
                "assay_method_unresolved",
            }
            for issue in issues
        )
        measurement["linking_status"] = "failed" if relation_issue else "linked"

    candidate_matches: dict[str, list[tuple[Any, set[str], list[str]]]] = {}
    for candidate in candidates:
        keys = _candidate_label_keys(candidate)
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
        entry_id = entry.get("entry_id")
        label_key = entry.get("label_key")
        if not isinstance(entry_id, str) or not isinstance(label_key, str):
            continue
        matches = candidate_matches.get(label_key, [])
        if not matches:
            continue
        if len(matches) > 1 or any(len(keys) != 1 for _, keys, _ in matches):
            _append_issue(
                issues,
                "molecule_candidate_ambiguous",
                f"compound label {label_key} matches multiple Detection candidates",
                list(dict.fromkeys(eid for _, _, ids in matches for eid in ids)),
                entry_id,
            )
            continue
        candidate, _, candidate_evidence_ids = matches[0]
        properties = getattr(candidate, "properties", {})
        if candidate.status == "rejected" or (
            isinstance(properties, dict) and properties.get("markush") is True
        ):
            _append_issue(
                issues,
                "molecule_candidate_rejected",
                f"Detection candidate for {label_key} is rejected or Markush",
                candidate_evidence_ids,
                entry_id,
            )
            continue
        if not candidate_evidence_ids:
            _append_issue(
                issues,
                "molecule_evidence_unresolved",
                f"Detection candidate for {label_key} has no SQL evidence",
                [],
                entry_id,
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
        entry["structure_status"] = "resolved"
        entry["linking_status"] = "linked"


__all__ = ["associate_facts"]
