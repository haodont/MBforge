"""Deterministic entry rules for one patent document.

An entry is a designation the document itself declares: a title names its target
compounds, a body passage names what it makes, and an example heading designates
the product its own section prepares. Only printed strings are kept; nothing here
derives a designation or a name.
"""

from __future__ import annotations

import re
from collections.abc import Mapping, Sequence
from typing import Any

from mbforge.domain.evidence import SourceEvidence
from mbforge.service.pipeline.patent.sections import (
    ParsedSection as DocumentSection,
)
from mbforge.service.pipeline.patent.sections import example_token

#: Target compounds declared in a section title, e.g. ``化合物13和14``.
_COMPOUND_LABEL = r"\d{1,4}[A-Za-z]?(?:-[A-Za-z])?"
_COMPOUND_TOKEN_RE = re.compile(
    rf"(?:化合物\s*(?P<zh>{_COMPOUND_LABEL}(?:\s*和\s*{_COMPOUND_LABEL})*)|"
    rf"compound\s+(?P<en>{_COMPOUND_LABEL}(?:\s+and\s+{_COMPOUND_LABEL})*))",
    re.IGNORECASE,
)

#: Internal compound codes in parentheses, e.g. ``(IGP-20024-01)``.
_CODE_RE = re.compile(r"[（(]([A-Za-z][A-Za-z0-9\-]{2,})[)）]")

#: A designation followed by one of these is a quantity, not a compound number.
_MASS_SUFFIX_RE = re.compile(
    r"(?i)^\s*(?:\d|\.\s*\d|mg\b|g\b|kg\b|ug\b|μg\b|ml\b|μl\b|mol\b|mmol\b|"
    r"nm\b|mm\b|μm\b|um\b|%)"
)


#: How a document prints a designation anywhere in a passage.
_DESIGNATION_MENTION_RE = re.compile(
    r"(?:化合物|实施例|実施例|制备例|compound|example)\s*[#:：]?\s*"
    # A series designation (``I-50-2``, ``I-233-A``) starts with its letter, not
    # a digit: the corpus numbers hundreds of compounds that way, and a
    # digit-only token left every one of them unreadable in prose.
    r"(\d+[A-Za-z]?(?:-[A-Za-z0-9]+)?|[A-Za-z]-\d+[A-Za-z]?(?:-[A-Za-z0-9]+)*)",
    re.IGNORECASE,
)


def _example_facts(sections: list[DocumentSection]) -> list[dict]:
    """Project example sections without copying their source text."""
    examples: list[dict] = []
    for example_idx, section in enumerate(
        (item for item in sections if item.kind == "example"), 1
    ):
        examples.append(
            {
                "example_idx": example_idx,
                "page_num": section.page_start,
                "heading": section.title,
                "labels": list(section.labels),
                "esmiles_candidate_ids": list(section.esmiles_candidate_ids),
                "evidence_ids": list(section.evidence_ids),
            }
        )
    return examples


def extract_entries_from_title(
    title: str,
    doc_id: str,
    section_id: str,
    page_num: int,
    *,
    evidence_ids: list[str] | None = None,
) -> list[dict]:
    """Extract title-declared compound entries.

    Returns ``CompoundEntry.to_dict()``-shaped dicts.
    """
    from mbforge.domain.patent import (
        ROLE_EXAMPLE,
        ROLE_PREPARATION,
        CompoundEntry,
        entry_id,
        label_key_for,
    )

    role = (
        ROLE_PREPARATION
        if "制备" in title or re.search(r"\b(?:prepare|synthes)\w*\b", title, re.I)
        else ROLE_EXAMPLE
    )
    codes = _CODE_RE.findall(title)
    entries: list[dict] = []
    for label in _mentioned_labels(title):
        label_raw = f"化合物{label}"
        entry = CompoundEntry(
            entry_id=entry_id(doc_id, section_id, label_key_for(label_raw)),
            doc_id=doc_id,
            label_raw=label_raw,
            label_key=label_key_for(label_raw),
            entry_role=role,
            name_raw=" / ".join(codes),
            section_id=section_id,
            evidence_ids=list(evidence_ids or []),
        )
        entries.append(entry.to_dict())
    return entries


def _entry_role(section_kind: str) -> str:
    """Map a section kind to the entry role the title path assigns."""
    from mbforge.domain.patent import ROLE_EXAMPLE, ROLE_PREPARATION

    return ROLE_PREPARATION if section_kind == "preparation" else ROLE_EXAMPLE


def _example_identity_entry(section: DocumentSection, doc_id: str) -> dict | None:
    """Return the entry standing for an example section's own product.

    Activity tables index their rows by example label, so ``实施例7`` designates
    the compound that section prepares even when its body never prints a
    ``化合物7`` designation.
    """
    from mbforge.domain.patent import CompoundEntry, entry_id, example_label_key

    token = example_token(section)
    if token is None:
        return None
    label_raw = section.title.split("：", 1)[0].split(":", 1)[0].strip()
    label_key = example_label_key(token)
    return CompoundEntry(
        entry_id=entry_id(doc_id, section.section_id, label_key),
        doc_id=doc_id,
        label_raw=label_raw or token,
        label_key=label_key,
        entry_role=_entry_role(section.kind),
        section_id=section.section_id,
        evidence_ids=list(section.title_evidence_ids),
    ).to_dict()


def _mentioned_labels(text: str) -> list[str]:
    """Return the compound designations named by ``text`` (title vocabulary).

    A designation followed by a quantity is a mass reading, not a number
    (``制得化合物36.8mg`` names no compound 36).
    """
    labels: list[str] = []
    for match in _COMPOUND_TOKEN_RE.finditer(text):
        if _MASS_SUFFIX_RE.match(text[match.end() :]):
            continue
        group = match.group("zh") or match.group("en") or ""
        for label in re.split(r"\s*(?:和|and)\s*", group, flags=re.I):
            label = label.strip()
            if label and label not in labels:
                labels.append(label)
    return labels


def extract_entries_from_body(
    blocks: list[tuple[str, str]],
    doc_id: str,
    section_id: str,
    role: str,
) -> list[dict]:
    """Mint entries for compounds the section body declares.

    Titles often name only the prepared example (``实施例3：化合物12的合成``)
    while most patents name the compound in the body prose. Both are read so a
    measurement can link to the section that really declares it.

    Args:
        blocks: ``(evidence_id, raw_text)`` pairs in reading order. An entry
            keeps only the blocks that actually name it.
        role: ``ROLE_*`` value derived from the section kind.
    """
    from mbforge.domain.patent import CompoundEntry, entry_id, label_key_for

    entries: dict[str, dict] = {}
    for evidence_id, text in blocks:
        for label in _mentioned_labels(text):
            label_raw = f"化合物{label}"
            label_key = label_key_for(label_raw)
            entry = entries.get(label_key)
            if entry is None:
                entry = CompoundEntry(
                    entry_id=entry_id(doc_id, section_id, label_key),
                    doc_id=doc_id,
                    label_raw=label_raw,
                    label_key=label_key,
                    entry_role=role,
                    section_id=section_id,
                    evidence_ids=[],
                ).to_dict()
                entries[label_key] = entry
            if evidence_id not in entry["evidence_ids"]:
                entry["evidence_ids"].append(evidence_id)
    return list(entries.values())


def _backfill_entry_names(entries: list[dict], names: Sequence[dict]) -> int:
    """Fill an entry's empty ``name_raw`` from the name its section printed.

    A printed name never overwrites one already recorded, and an entry the
    document never named stays unnamed.
    """
    by_key = {
        str(name.get("label_key") or ""): str(name.get("name_raw") or "")
        for name in names
        if name.get("label_key")
    }
    filled = 0
    for entry in entries:
        if entry.get("name_raw"):
            continue
        value = by_key.get(str(entry.get("label_key") or ""))
        if value:
            entry["name_raw"] = value
            filled += 1
    return filled


def _designation_keys(text: str) -> list[str]:
    """Document-local identity keys for the designations a passage prints.

    ``化合物77`` → ``77``, ``实施例1`` → ``@example:1``: an example designates the
    compound its own section prepares, so the two never share a key.
    """
    keys: list[str] = []
    from mbforge.domain.patent import example_label_key
    from mbforge.service.pipeline.activity.normalization import (
        normalize_reference_label,
    )

    for match in _DESIGNATION_MENTION_RE.finditer(text or ""):
        # ``参考实施例1方法，制得化合物36.8mg`` prints a mass, not compound 36.
        if _MASS_SUFFIX_RE.match((text or "")[match.end(1) :]):
            continue
        reference = normalize_reference_label(match.group(0))
        if reference.reference_type == "example" and reference.key:
            key = example_label_key(reference.key)
        elif reference.key and reference.reference_type in ("compound", "e_series"):
            key = reference.key
        else:
            continue
        if key not in keys:
            keys.append(key)
    return keys


def _disputed_designations(issues: Sequence[Mapping[str, Any]]) -> set[str]:
    """Designations the association refused to bind to one structure.

    Two candidates printing the same designation, or one candidate printing two,
    leave the entry unresolved. The ``molecules.name`` a structure offers for
    such a designation is whichever label read arrived first, so joining it
    publishes a pair the reading's own attribution row refuses. Measured on
    CN119504738A: one OCR misread (``21`` read as ``1``) put Table 1's
    compound-1 reading beside the wrong structure.
    """
    return {
        str(issue.get("label_key"))
        for issue in issues
        if issue.get("code") == "molecule_candidate_ambiguous"
        and issue.get("label_key")
    }


def _declared_structure_activity(
    evidence: Sequence[SourceEvidence],
    measurements: Sequence[dict],
    doc_id: str,
    library_root: str,
    issues: Sequence[Mapping[str, Any]] = (),
) -> list[dict]:
    """Pair each reading with the structure its example heading declares.

    Returns artifact-shaped dicts. A reading with no declared structure is simply
    absent: the document named the compound but drew nothing, and reporting a
    pair there would mean inventing a structure.

    The structures are read from the library's ``molecules`` table: the
    candidates this stage receives are the raw recognition
    results (Markush scaffolds included, labelled ``I-A``/``II-A``), while the
    concrete compound the pipeline stored — ``name='8'`` with a plain SMILES — is
    the one an example heading's designation points at.

    A designation two candidates dispute names no structure this join can
    vouch for, so it is withheld exactly as the association withholds it
    (``issues`` carries that refusal). Publishing it from ``molecules.name``
    is what let a reading leave with the wrong structure attached.
    """
    from mbforge.service.pipeline.patent.declared_pairs import (
        extract_declared_examples,
        pair_structure_activity,
    )

    disputed = _disputed_designations(issues)
    structures = {
        key: smiles
        for key, smiles in _stored_structures_by_designation(
            library_root, doc_id
        ).items()
        if key not in disputed
    }
    examples = extract_declared_examples(evidence, doc_id)
    # A document without example headings still declares its compounds: the
    # activity table prints the compound number beside the reading. The
    # declaration is needed only to map an *example* reference and to check a
    # printed product mass; a reading that names a compound is joined by that
    # name, so a document that declares nothing by heading still pairs.
    pairs = (
        pair_structure_activity(examples, measurements, structures)
        if structures
        else []
    )
    return [
        {
            "declared_key": pair.declared_key,
            "measurement_id": pair.measurement_id,
            "smiles": pair.smiles,
            "metric": pair.metric,
            "value": pair.value,
            "unit": pair.unit,
            "verified_by_mass": pair.verified_by_mass,
            "printed_mz": pair.printed_mz,
            "calculated_mz": pair.calculated_mz,
        }
        for pair in pairs
    ]


def _stored_structures_by_designation(library_root: str, doc_id: str) -> dict[str, str]:
    """``{printed designation: canonical SMILES}`` for this document's structures.

    Only concrete compounds are included: a Markush scaffold's ``name`` is a
    scheme label (``I-A``), never the designation an activity table prints for a
    finished compound.
    """
    from mbforge.service.ports import get_repositories

    rows = get_repositories(library_root).molecules.designated_structures(doc_id)
    structures: dict[str, str] = {}
    for row in rows:
        key = str(row.get("name") or "").strip()
        smiles = str(row.get("canonical_smiles") or "").strip()
        if key and smiles and "*" not in smiles:
            structures.setdefault(key, smiles)
    return structures
