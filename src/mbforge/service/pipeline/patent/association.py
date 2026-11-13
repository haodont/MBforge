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
from mbforge.foundation.logger import get_logger
from mbforge.service.pipeline.patent.candidate_labels import (
    candidate_designation_keys,
    candidate_owns_designation,
)
from mbforge.service.pipeline.patent.sections import (
    ParsedSection as DocumentSection,
)
from mbforge.service.pipeline.persist.molecules import filter_persistable_candidates

logger = get_logger(__name__)

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


def _ocr_confusable_forms(text: str) -> set[str]:
    """The spellings a ``1``/``I``/``l`` confusion can turn a printed token into.

    The confusion lives in the first character: a series letter (``I-256-A``)
    is read as a digit (``1-256-A``). Only that position is varied, so a digit
    inside the number is never touched.
    """
    if not text:
        return set()
    head = text[0]
    return {
        replacement + text[1:] for replacement in ("1", "i", "l") if replacement != head
    }


def _candidate_printed_names(candidate: Any) -> list[str]:
    """Every designation a candidate's drawings printed."""
    properties = getattr(candidate, "properties", {})
    properties = properties if isinstance(properties, dict) else {}
    names: list[str] = []
    name = getattr(candidate, "name", "")
    if isinstance(name, str) and name.strip():
        names.append(name)
    for key in ("detection_names", "name_candidates"):
        values = properties.get(key)
        if not isinstance(values, list):
            continue
        for value in values:
            text = value.get("name") if isinstance(value, dict) else value
            if isinstance(text, str) and text.strip():
                names.append(text)
    return list(dict.fromkeys(names))


def _rename_candidate(candidate: Any, old: str, new: str) -> None:
    """Give a candidate the spelling the document prints."""
    name = getattr(candidate, "name", "")
    if isinstance(name, str) and name.strip() == old:
        candidate.name = new
    properties = getattr(candidate, "properties", None)
    if not isinstance(properties, dict):
        return
    names = properties.get("detection_names")
    if isinstance(names, list):
        properties["detection_names"] = [
            new if isinstance(item, str) and item == old else item for item in names
        ]
    candidates = properties.get("name_candidates")
    if isinstance(candidates, list):
        for candidate in candidates:
            if isinstance(candidate, dict) and candidate.get("name") == old:
                candidate["name"] = new


def _reconcile_ocr_designations(
    candidates: Sequence[Any],
    entries: Sequence[Mapping[str, Any]],
    measurements: Sequence[Mapping[str, Any]],
    issues: list[dict[str, Any]],
) -> int:
    """Rewrite a misread designation to the spelling the document prints.

    A capital ``I`` is read as a digit ``1`` often enough that a whole series
    of compounds (``I-32``…``I-66``) reaches the library as ``1-32``…``1-66``
    and no longer matches the activity table that prints ``I-…``. The
    document's own designations settle it: when exactly one spelling of the
    read token is printed by this document, that spelling is the compound's.
    """

    printed: dict[str, str] = {}
    for entry in entries:
        raw = str(entry.get("label_raw") or "").strip()
        if raw:
            printed.setdefault(raw.lower(), raw)
    for measurement in measurements:
        if not isinstance(measurement, Mapping):
            continue
        provenance = measurement.get("provenance")
        provenance = provenance if isinstance(provenance, Mapping) else {}
        raw = str(provenance.get("reference_raw") or "").strip()
        if raw:
            printed.setdefault(raw.lower(), raw)
    if not printed:
        return 0

    reconciled = 0
    for candidate in candidates:
        for name in _candidate_printed_names(candidate):
            normalized = name.strip().lower()
            if not normalized or normalized in printed:
                continue
            hits = [
                variant
                for variant in _ocr_confusable_forms(normalized)
                if variant in printed
            ]
            if len(hits) != 1:
                # The document prints more than one spelling of this token, or
                # none: the read stays as it is.
                continue
            corrected = printed[hits[0]]
            _rename_candidate(candidate, name, corrected)
            _append_issue(
                issues,
                "designation_ocr_reconciled",
                f"designation {name} read as {corrected}",
                [],
                None,
            )
            reconciled += 1
    return reconciled


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
    still has to find a candidate.
    """
    doc_id = str(measurement.get("doc_id") or "")
    printed = str(provenance.get("reference_raw") or reference.raw or "")
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


#: The next example heading inside a section's text. Sections overlap by a page,
#: so one example's raw text runs into the next one's product statement.
_NEXT_EXAMPLE_HEADING_RE = None


def _own_example_text(text: str, heading: str = "") -> str:
    """The part of an example section's text that belongs to its own preparation.

    Sections are page-ranged, so 实施例44's text (pages 90–91) also holds the start
    of 实施例45 and 实施例46 and their product statements. Reading all of it makes
    "which compound does this example prepare" ambiguous and the identity stays
    unresolved; cutting at the next heading leaves the example's own statement.
    """
    global _NEXT_EXAMPLE_HEADING_RE
    if _NEXT_EXAMPLE_HEADING_RE is None:
        import re

        # A heading follows the end of a sentence (a newline, ``。`` or ``.``),
        # optionally behind a ``[0625]`` marker; a mention inside a sentence
        # ("合成方法参考实施例43，得到…") is part of the same statement.
        _NEXT_EXAMPLE_HEADING_RE = re.compile(
            r"(?<=[\n\u3002.])\s*(?:\[\d{4}\]\s*)?(?:实施例|実施例)[ \t]*\d"
        )
    body = str(text or "")
    # Start after this section's own heading: sections overlap by a page, so the
    # text can open with the tail of the previous example.
    anchor = body.find(heading.strip()) if heading else -1
    start = anchor + len(heading.strip()) if anchor >= 0 else 0
    match = _NEXT_EXAMPLE_HEADING_RE.search(body, start)
    cut = match.start() if match else len(body)
    # Start at this section's own heading: the tail of the previous example is not
    # this example's product statement, and reading it makes the answer ambiguous.
    return body[anchor:cut] if anchor >= 0 else body[:cut]


def _example_product_entry(
    token: str,
    example_sections: Mapping[str, Sequence[DocumentSection]],
    entries_by_label: Mapping[str, list[dict[str, Any]]],
) -> dict[str, Any] | None:
    """The compound entry an example section's printed product statement names.

    ``实施例29`` whose body prints ``得到 55 mg 化合物29`` states the product
    itself, so the reading belongs to compound 29 — not to the example identity,
    which no structure answers to. The statement must name exactly one compound:
    a route that prints several products names no single owner, and the reading
    then keeps the example identity it printed.
    """
    from mbforge.domain.patent import label_key_for
    from mbforge.service.pipeline.patent.rules.characterization import (
        declared_product_labels,
    )

    for section in example_sections.get(token, []):
        labels = declared_product_labels(section.raw_text)
        if len(labels) != 1:
            continue
        key = label_key_for(labels[0])
        matches = [
            entry
            for entry in entries_by_label.get(key, [])
            if entry.get("section_id") == section.section_id
        ]
        if len(matches) == 1:
            return matches[0]
        if not matches and len(entries_by_label.get(key, [])) == 1:
            return entries_by_label[key][0]
    return None



def _entry_scope_sections(
    entry: Mapping[str, Any],
    label_key: str,
    example_sections: Mapping[str, Sequence[DocumentSection]],
) -> tuple[str, ...]:
    """The sections whose printed MS may decide this entry's structure.

    An entry declared from a table row has no section of its own, so the example
    that bears its number supplies the scope: ``化合物44`` is prepared, and its
    mass printed, in 实施例44.
    """
    scopes: list[str] = []
    own = entry.get("section_id")
    if isinstance(own, str) and own:
        scopes.append(own)
    for section in example_sections.get(label_key, []):
        if section.section_id not in scopes:
            scopes.append(section.section_id)
    return tuple(scopes)


def associate_facts(
    sections: list[DocumentSection],
    entries: list[dict[str, Any]],
    assay_methods: list[dict[str, Any]],
    measurements: list[dict[str, Any]],
    candidates: list[Any],
    valid_evidence_ids: set[str],
    issues: list[dict[str, Any]],
    characterizations: Sequence[Mapping[str, Any]] = (),
) -> None:
    """Attach only deterministic, evidence-backed relationships in Patent.

    The relation reports are recomputed here, not appended to: this function runs
    once for the rule draft and again after the model's associations are applied,
    and the second pass must report the state it now finds.
    """
    from mbforge.domain.patent import label_key_for
    from mbforge.service.pipeline.activity.normalization import (
        normalize_reference_label,
    )
    from mbforge.service.pipeline.patent.rules.characterization import (
        declared_product_labels,
    )
    from mbforge.service.pipeline.patent.sections import example_token

    _clear_relation_issues(issues)
    sections_by_id = {section.section_id: section for section in sections}
    entries_by_label = _group_by_label(entries)
    _reconcile_ocr_designations(candidates, entries, measurements, issues)

    entries_by_section: dict[str, list[dict[str, Any]]] = {}
    for entry in entries:
        section_ref = entry.get("section_id")
        if isinstance(section_ref, str) and section_ref:
            entries_by_section.setdefault(section_ref, []).append(entry)

    # ``实施例9`` names the compound its own section prepares; a bare number is
    # never a document-wide alias for every compound that shares it.
    entries_by_example: dict[str, list[dict[str, Any]]] = {}
    example_sections: dict[str, list[DocumentSection]] = {}
    for section in sections:
        token = example_token(section)
        if token is None:
            continue
        entries_by_example.setdefault(token, []).extend(
            entries_by_section.get(section.section_id, [])
        )
        example_sections.setdefault(token, []).append(section)

    methods_by_section: dict[str, list[dict[str, Any]]] = {}
    for method in assay_methods:
        section_id = method.get("section_id")
        if isinstance(section_id, str):
            methods_by_section.setdefault(section_id, []).append(method)

    # Which designations a recognized drawing actually answers to. A reading may
    # only fall back from an example label to the compound space when the
    # document drew that compound: a bare section number never borrows a
    # compound another section declares.
    drawn_before: set[str] = set()
    for candidate in filter_persistable_candidates("", list(candidates), warn=False):
        for key in candidate_designation_keys(candidate):
            if candidate_owns_designation(candidate, key):
                drawn_before.add(key)

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
        declared = [group[0] for group in _group_by_label(compound_entries).values()]
        identity = [
            group[0]
            for group in _group_by_label(
                [entry for entry in example_entries if _is_example_identity(entry)]
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
            # No title-backed compound exists. The section identity is the
            # fallback, but a section that prints its own product
            # (``实施例29 … 得到55mg化合物29``) names compound 29, and that entry
            # is the one a recognized structure can answer to.
            product = _example_product_entry(
                reference.key, example_sections, entries_by_label
            )
            if (
                product is None
                and reference.key not in example_sections
                and reference.key in drawn_before
            ):
                # The activity table labels the row ``Example 27A`` while the
                # section that prepares it is numbered elsewhere (``实施例6``),
                # and the drawing it names is printed ``27A`` — the compound
                # designation. When no example section claims the token and the
                # document drew that compound, the compound key space is what
                # the reading cites.
                # Several sections name the same compound (its preparation and
                # its synthesis route), so one designation can own several
                # entries. They all carry the same label key, so the first is
                # the compound the reading cites; a disputed designation is
                # reported by the entry pass on its own.
                matches = entries_by_label.get(reference.key, [])
                if matches:
                    product = matches[0]
            if product is not None:
                measurement["compound_entry_id"] = product["entry_id"]
            elif identity:
                # Retain the example designation without borrowing a body compound
                # or an equal number from another section.
                measurement["compound_entry_id"] = identity[0]["entry_id"]
            else:
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
        keys = candidate_designation_keys(candidate)
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
        # A patent prints a compound more than once, and the printings are not
        # always recognized the same way. A candidate answers only to the
        # designation its drawings agree on most; the minority designation of a
        # structure belongs to the compound its other drawings name. So the
        # candidates that do not own the designation are not in the running.
        owned = [
            (candidate, keys, evidence_ids)
            for candidate, keys, evidence_ids in matches
            if candidate_owns_designation(candidate, label_key)
        ]
        if not owned:
            # The structure whose own drawings disagree with each other owns none
            # of the names by the majority rule — but the molecule pass already
            # gave one of them the designation when it named the drawing. That name
            # is the pipeline's own identification, so it decides the entry:
            # CN120943813A's compound 44 is drawn twice and printed under two
            # numbers, which stranded every reading that cited it.
            named = [
                match
                for match in matches
                if designation_key(str(getattr(match[0], "name", "") or ""))
                == label_key
            ]
            if len(named) == 1:
                owned = named
        if len(owned) > 1:
            # One compound is often drawn (and recognized) more than once. Two
            # candidates with the same SMILES are one structure, so they cannot
            # make a designation ambiguous — CN120943813A's compound 44 is two
            # detections of one drawing, and treating them as rivals left the
            # entry unresolved and every reading that cited it unowned.
            unique: list[Any] = []
            seen_smiles: set[str] = set()
            for match in owned:
                smiles = str(getattr(match[0], "canonical_smiles", "") or "")
                if smiles in seen_smiles:
                    continue
                seen_smiles.add(smiles)
                unique.append(match)
            owned = unique
        if len(owned) != 1 and characterizations:
            # Two drawings claim one designation. The filing usually settles it:
            # the section that prepares the compound prints its LC-MS, and only
            # one structure is consistent with it (CN121717757A: I-266-A's
            # claims drawing is 572.2 while 实施例26 prints 558.0).
            from mbforge.service.pipeline.patent.rules.characterization import (
                mass_consistent_structures,
            )

            consistent = mass_consistent_structures(
                list(characterizations),
                [candidate for candidate, _, _ in matches],
                label_key,
                section_ids=_entry_scope_sections(
                    entry, label_key, example_sections
                ),
            )
            if len(consistent) == 1:
                owned = [
                    (candidate, keys, evidence_ids)
                    for candidate, keys, evidence_ids in owned
                    if candidate is consistent[0]
                ] or [
                    next(
                        (match for match in matches if match[0] is consistent[0]),
                        (consistent[0], set(), []),
                    )
                ]
                _append_issue(
                    issues,
                    "designation_settled_by_printed_mass",
                    f"compound label {label_key} resolved by the printed MS",
                    _string_ids(owned[0][2]),
                    fact_entry_id,
                    severity="info",
                    label_key=label_key,
                )
        if len(owned) != 1:
            _append_issue(
                issues,
                "molecule_candidate_ambiguous",
                f"compound label {label_key} matches multiple Detection candidates",
                list(dict.fromkeys(eid for _, _, ids in matches for eid in ids)),
                fact_entry_id,
                label_key=label_key,
            )
            continue
        candidate, _, candidate_evidence_ids = owned[0]
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

    # An example identity has no drawing of its own: the page captions the product
    # with its compound number (``44``), never with the heading (``实施例44``), so
    # ``@example:44`` matched no candidate and stayed unresolved — CN120943813A
    # reported that for forty-five examples, and every reading citing ``实施例44``
    # therefore had nothing to bind to. The document does say what the example
    # makes, in its product statement (``得到33.75mg化合物44``): the identity takes
    # the structure that statement named, once the product entry is resolved.
    for entry in entries:
        label_key = entry.get("label_key")
        if not isinstance(label_key, str) or not label_key.startswith("@example:"):
            continue
        if entry.get("entity_id"):
            continue
        token = label_key.split(":", 1)[1]
        product = None
        for section in example_sections.get(token, []):
            labels = declared_product_labels(
                _own_example_text(section.raw_text, section.heading_line)
            )
            if len(labels) != 1:
                continue
            key = label_key_for(labels[0])
            same = [
                candidate
                for candidate in entries_by_label.get(key, [])
                if candidate.get("section_id") == section.section_id
            ]
            product = (same or entries_by_label.get(key) or [None])[0]
            if product is not None:
                break
        product_entity = (product or {}).get("entity_id")
        if not product or not product_entity:
            continue
        entry["entity_id"] = product_entity
        entry["structure_status"] = STRUCTURE_RESOLVED
        entry["linking_status"] = "linked"
        entry["evidence_ids"] = list(
            dict.fromkeys(
                _string_ids(entry.get("evidence_ids"))
                + _string_ids(product.get("evidence_ids"))
            )
        )

    # An example reference whose section declares its product still had no owner
    # when no entry row exists for the designation at all. explain_reading on
    # CN120943813A's 实施例43 showed exactly that: the drawing named 43 owns it, the
    # section prepares compound 43, and `entry_side` was empty — nothing to bind to.
    # The product the section states is the structure, so bind it directly.
    for measurement in measurements:
        if measurement.get("mol_id"):
            continue
        provenance = measurement.get("provenance")
        provenance = provenance if isinstance(provenance, dict) else {}
        reference = normalize_reference_label(
            provenance.get("reference_raw") or provenance.get("reference_key") or ""
        )
        if reference.reference_type != "example" or not reference.key:
            continue
        product = _example_product_entry(
            reference.key, example_sections, entries_by_label
        )
        if product is None:
            continue
        product_key = str(product.get("label_key") or "")
        owners = {
            str(getattr(candidate, "canonical_smiles", "") or ""): candidate
            for candidate, keys, _ids in candidate_matches.get(product_key, [])
            if candidate_owns_designation(candidate, product_key)
        }
        owners.pop("", None)
        if len(owners) == 1:
            measurement["mol_id"] = next(iter(owners))

    # A reading can be owned by a drawing even when no entry declares its
    # designation. CN120943813A's page-94 table cites 44, 48, 43, 19 …: the
    # example section draws each compound and captions it, so exactly one
    # structure owns the designation, while the entry side left them unresolved
    # and the readings stayed unowned ("designation_without_structure" in the
    # queue, "structure_detected_unmatched" in the dataset — the same fact read
    # twice). Binding by the drawing is deterministic: one owning structure or
    # nothing.
    owning: dict[str, dict[str, Any]] = {}
    for candidate in filter_persistable_candidates("", list(candidates), warn=False):
        # The name the molecule pass gave the drawing is the pipeline's own
        # identification of it, and unlike the majority vote below it survives a
        # second drawing of the same structure that read a different number.
        keys = set()
        named = designation_key(str(getattr(candidate, "name", "") or ""))
        if named:
            keys.add(named)
        keys |= {
            key
            for key in candidate_designation_keys(candidate)
            if candidate_owns_designation(candidate, key)
        }
        smiles = str(getattr(candidate, "canonical_smiles", "") or "").strip()
        if not smiles:
            continue
        for key in keys:
            owning.setdefault(key, {}).setdefault(smiles, candidate)
    for measurement in measurements:
        if measurement.get("mol_id"):
            continue
        provenance = measurement.get("provenance")
        provenance = provenance if isinstance(provenance, dict) else {}
        reference = normalize_reference_label(
            provenance.get("reference_raw") or provenance.get("reference_key") or ""
        )
        if reference.reference_type != "compound" or not reference.key:
            continue
        matches = owning.get(reference.key, {})
        if len(matches) != 1:
            continue
        measurement["mol_id"] = next(iter(matches))


__all__ = ["associate_facts"]
