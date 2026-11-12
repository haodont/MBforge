"""Structure verification rows for one document.

The automatable half of "is this structure right?": for every structure the
document drew, this reports what a reader needs to check it — the formula and
masses, the printed designation the structure carries, the compound entry that
owns that designation, and the printed MS line the designation owns together
with the mass delta the patent's own tolerance allows.

Everything is read from the canonical SQL evidence and the committed Patent
snapshot. Nothing is written, no structure is corrected, and a delta is
evidence for a human — never a verdict.

The chemistry rules are the pipeline's own: the same mass parsing, the same
adduct table and the same tolerance the Patent stage applies, so this surface
and the published facts cannot disagree about one printed line.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from mbforge.service.use_cases.documents import source_evidence
from mbforge.service.use_cases.documents.patent_facts import load_patent_facts

#: The tolerance the Patent stage applies to a printed mass.
DEFAULT_TOLERANCE_DA = 0.6

#: Property keys a producer may have written a printed designation into.
_LABEL_PROPERTY_KEYS: tuple[str, ...] = (
    "ocr_labels_primary",
    "ocr_labels",
    "raw_coref_label",
    "normalized_label",
    "label",
    "formula_label",
)


def _printed_labels(candidate: Any) -> list[str]:
    """Every printed designation string the candidate carries."""
    properties = getattr(candidate, "properties", None)
    properties = properties if isinstance(properties, dict) else {}
    values: list[str] = []
    for key in _LABEL_PROPERTY_KEYS:
        value = properties.get(key)
        if isinstance(value, str):
            values.append(value)
        elif isinstance(value, list):
            values.extend(item for item in value if isinstance(item, str))
    name = getattr(candidate, "name", "")
    if isinstance(name, str):
        values.append(name)

    labels: list[str] = []
    for value in values:
        text = value.strip()
        if text and text not in labels:
            labels.append(text)
    return labels


def _label_sources(candidate: Any) -> list[str]:
    """Where the candidate's designations came from (page text vs crop).

    ``name_candidates`` records the source of every name the drawings
    supplied; ``label_source`` is the merged source. Both are read because a
    candidate can carry a name from each channel.
    """
    properties = getattr(candidate, "properties", None)
    properties = properties if isinstance(properties, dict) else {}
    sources: list[str] = []
    candidates = properties.get("name_candidates")
    if isinstance(candidates, list):
        for item in candidates:
            if isinstance(item, dict):
                source = item.get("source")
                if isinstance(source, str) and source and source not in sources:
                    sources.append(source)
    source = properties.get("label_source")
    if isinstance(source, str) and source and source not in sources:
        sources.append(source)
    return sources


def _chemistry(smiles: str) -> dict[str, Any]:
    """Formula and masses of a structure.

    ``formula``/``molar_mass`` describe the stored SMILES as written, while
    ``exact_mass``/``main_formula`` describe its salt-stripped parent — the
    fragment a printed ``[M+H]+`` ion actually weighs. A hydrochloride stored as
    ``Cl.`` therefore reports both, and the mass check compares the parent.
    """
    from mbforge.service.pipeline.detection.label_recovery import (
        exact_mass,
        largest_fragment_mol,
    )

    result: dict[str, Any] = {
        "formula": "",
        "main_formula": "",
        "molar_mass": None,
        "exact_mass": None,
    }
    if not smiles:
        return result
    try:
        from rdkit import Chem, RDLogger
        from rdkit.Chem import Descriptors, rdMolDescriptors

        RDLogger.DisableLog("rdApp.*")
        mol = Chem.MolFromSmiles(smiles)
    except Exception:  # noqa: BLE001 - a read surface never fails on bad input
        return result
    if mol is None:
        return result

    result["formula"] = rdMolDescriptors.CalcMolFormula(mol)
    result["molar_mass"] = round(float(Descriptors.MolWt(mol)), 4)
    main = largest_fragment_mol(smiles)
    if main is not None:
        result["main_formula"] = rdMolDescriptors.CalcMolFormula(main)
    mass = exact_mass(smiles)
    if mass is not None:
        result["exact_mass"] = round(float(mass), 4)
    return result


def _load_candidates(library_root: str | Path, doc_id: str) -> list[Any]:
    """Restore the document's structures from SQL evidence.

    The Patent stage rebuilds its structures from the same rows, so both see
    one set of candidates.
    """
    from mbforge.service.pipeline.artifacts.hydration import load_detections

    restored = load_detections(library_root, doc_id)
    if not restored:
        return []
    return list(restored[0])


def _load_printed_ms(
    library_root: str | Path,
    doc_id: str,
    evidence: list[Any],
    molecule_evidence_ids: set[str],
) -> tuple[list[dict[str, Any]], str, int]:
    """The printed MS lines of a document, where they came from, and what was dropped.

    The committed Patent snapshot is preferred — it is the published view of
    the same lines. A document whose Patent stage has not run yet has no
    snapshot, so the lines are read from SQL evidence with the same rule.

    A line that was scraped out of a *structure* row is not a printed mass: the
    crop's OCR context quotes the neighbouring prose, whose mass belongs to
    whichever compound that paragraph describes. Those lines are excluded here
    and counted, never silently compared against a structure.
    """
    facts = load_patent_facts(library_root, doc_id)
    if facts is not None:
        lines = [
            dict(item)
            for item in facts.characterizations
            if str(item.get("technique") or "") == "ms"
        ]
        if lines:
            kept, dropped = _split_structure_rows(lines, molecule_evidence_ids)
            return kept, "snapshot", dropped

    from mbforge.service.pipeline.patent.rules.characterization import (
        extract_characterization,
    )

    if not evidence:
        return [], "none", 0
    lines = [
        dict(item)
        for item in extract_characterization(evidence, doc_id)
        if str(item.get("technique") or "") == "ms"
    ]
    kept, dropped = _split_structure_rows(lines, molecule_evidence_ids)
    return kept, "evidence", dropped


def _split_structure_rows(
    lines: list[dict[str, Any]], molecule_evidence_ids: set[str]
) -> tuple[list[dict[str, Any]], int]:
    """Separate printed masses from masses quoted inside a structure row."""
    if not molecule_evidence_ids:
        return lines, 0
    kept: list[dict[str, Any]] = []
    dropped = 0
    for line in lines:
        ids = {str(item) for item in line.get("evidence_ids") or []}
        if ids & molecule_evidence_ids:
            dropped += 1
            continue
        kept.append(line)
    return kept, dropped


def _molecule_evidence_ids(evidence: list[Any]) -> set[str]:
    """The evidence ids that carry a structure rather than printed text."""
    from mbforge.domain.evidence_kind import MOLECULE, category_of
    from mbforge.service.pipeline.artifacts.hydration import register_evidence_kinds

    register_evidence_kinds()
    return {row.evidence_id for row in evidence if category_of(row.kind) == MOLECULE}


def _load_entries(library_root: str | Path, doc_id: str) -> dict[str, dict[str, Any]]:
    """The compound entries of a document, keyed by their designation."""
    facts = load_patent_facts(library_root, doc_id)
    if facts is None:
        return {}
    entries: dict[str, dict[str, Any]] = {}
    for entry in facts.entries:
        key = str(entry.get("label_key") or "")
        if key and key not in entries:
            entries[key] = entry
    return entries


def _structure_row(
    candidate: Any,
    printed_by_label: dict[str, list[dict[str, Any]]],
    entries: dict[str, dict[str, Any]],
    tolerance: float,
) -> dict[str, Any]:
    """One structure's verification row."""
    from mbforge.service.pipeline.patent.candidate_labels import (
        candidate_designation_counts,
        candidate_label_keys,
    )
    from mbforge.service.pipeline.patent.rules.characterization import (
        adduct_mass_delta,
        printed_ms_mz,
    )

    label_keys = candidate_label_keys(candidate)
    canonical = str(
        getattr(candidate, "canonical_smiles", "")
        or getattr(candidate, "smiles", "")
        or ""
    )
    chemistry = _chemistry(canonical or str(getattr(candidate, "esmiles", "") or ""))

    detection = None
    detections = getattr(candidate, "detections", None) or []
    if detections:
        detection = detections[0]
    page = getattr(detection, "page", None)
    page_number = (
        page + 1 if isinstance(page, int) and not isinstance(page, bool) else None
    )
    bbox = getattr(detection, "bbox", None)
    score = float(getattr(detection, "conf_moldet", 0.0) or 0.0)

    checks: list[dict[str, Any]] = []
    markush = "*" in canonical
    for key in sorted(label_keys):
        for line in printed_by_label.get(key, []):
            parsed = printed_ms_mz(str(line.get("raw_text") or ""))
            if parsed is None:
                continue
            printed, adduct = parsed
            delta_mass = adduct_mass_delta(adduct)
            exact_mass = chemistry["exact_mass"]
            if delta_mass is None or exact_mass is None:
                continue
            expected = round(exact_mass + delta_mass, 4)
            delta = round(printed - expected, 4)
            if markush:
                # A Markush scaffold has no compound mass: its dummy atoms carry
                # no weight, so a delta against a printed m/z says nothing.
                verdict = "not_comparable"
            elif abs(delta) <= tolerance:
                verdict = "match"
            else:
                verdict = "mismatch"
            checks.append(
                {
                    "printed_mz": printed,
                    "adduct": adduct,
                    "expected_mz": expected,
                    "delta": delta,
                    "tolerance": tolerance,
                    "verdict": verdict,
                    "label_key": key,
                    "page": line.get("page"),
                    "evidence_ids": list(line.get("evidence_ids") or []),
                    "raw_text": str(line.get("raw_text") or "")[:400],
                }
            )

    if any(check["verdict"] == "mismatch" for check in checks):
        mass_check = "mismatch"
    elif any(check["verdict"] == "match" for check in checks):
        mass_check = "match"
    elif checks:
        mass_check = "not_comparable"
    else:
        mass_check = "no_printed_mass"

    entry = None
    for key in sorted(label_keys):
        if key in entries:
            entry = entries[key]
            break

    return {
        "page": page_number,
        "evidence_id": getattr(detection, "evidence_id", None),
        "mol_id": str(getattr(candidate, "mol_id", "") or ""),
        "smiles": str(getattr(candidate, "smiles", "") or ""),
        "esmiles": str(getattr(candidate, "esmiles", "") or ""),
        "canonical_smiles": canonical,
        "name": str(getattr(candidate, "name", "") or ""),
        "labels": [
            item
            for item in (getattr(candidate, "labels", None) or [])
            if isinstance(item, str)
        ],
        "formula": chemistry["formula"],
        "main_formula": chemistry["main_formula"],
        "molar_mass": chemistry["molar_mass"],
        "exact_mass": chemistry["exact_mass"],
        "mass_basis": "largest_fragment",
        "detection_score": round(score, 4),
        "structure_kind": "markush" if markush else "concrete",
        "bbox": list(bbox) if bbox else None,
        "printed_labels": _printed_labels(candidate),
        "label_keys": sorted(label_keys),
        "label_sources": _label_sources(candidate),
        "designation_counts": candidate_designation_counts(candidate),
        "entry": entry,
        "printed_ms": checks,
        "mass_check": mass_check,
    }


def verify_structures(
    library_root: str | Path,
    doc_id: str,
    *,
    page: int | None = None,
    label: str | None = None,
    offset: int = 0,
    limit: int = 25,
    tolerance: float = DEFAULT_TOLERANCE_DA,
) -> dict[str, Any]:
    """Verify one document's structures against the masses it printed.

    ``page`` and ``label`` narrow the structures; the counts in ``summary``
    describe the narrowed set, while the printed-mass counts describe the whole
    document.
    """
    empty = {
        "doc_id": doc_id,
        "summary": {
            "structures": 0,
            "structures_with_printed_ms": 0,
            "mass_matches": 0,
            "mass_mismatches": 0,
            "mass_not_comparable": 0,
            "structures_without_printed_ms": 0,
            "printed_ms_lines": 0,
            "printed_ms_unowned": 0,
            "printed_ms_from_structure_rows": 0,
            "printed_ms_source": "none",
        },
        "items": [],
        "total": 0,
    }
    if not doc_id:
        return empty

    candidates = _load_candidates(library_root, doc_id)
    evidence = source_evidence.list_evidence(library_root, doc_id)
    molecule_evidence_ids = _molecule_evidence_ids(evidence)
    printed_lines, printed_source, printed_dropped = _load_printed_ms(
        library_root, doc_id, evidence, molecule_evidence_ids
    )
    entries = _load_entries(library_root, doc_id)

    printed_by_label: dict[str, list[dict[str, Any]]] = {}
    for line in printed_lines:
        key = str(line.get("label_key") or "")
        if not key:
            continue
        printed_by_label.setdefault(key, []).append(line)

    rows = [
        _structure_row(candidate, printed_by_label, entries, tolerance)
        for candidate in candidates
    ]

    # Ownership is a document-level fact: a printed mass is unowned when no
    # structure of the document carries its designation.
    claimed_keys: set[str] = set()
    for row in rows:
        claimed_keys.update(row["label_keys"])
    unowned = [
        line
        for line in printed_lines
        if not str(line.get("label_key") or "")
        or str(line.get("label_key") or "") not in claimed_keys
    ]

    scoped = rows
    if page is not None:
        scoped = [row for row in scoped if row["page"] == page]
    if label:
        wanted = label.strip()
        scoped = [
            row
            for row in scoped
            if wanted in row["label_keys"]
            or any(
                printed.strip().lower() == wanted.lower()
                for printed in row["printed_labels"]
            )
        ]

    matches = sum(1 for row in scoped if row["mass_check"] == "match")
    mismatches = sum(1 for row in scoped if row["mass_check"] == "mismatch")
    incomparable = sum(1 for row in scoped if row["mass_check"] == "not_comparable")
    without = sum(1 for row in scoped if row["mass_check"] == "no_printed_mass")

    page_items = scoped[offset : offset + limit] if limit > 0 else []
    return {
        "doc_id": doc_id,
        "summary": {
            "structures": len(scoped),
            "structures_with_printed_ms": matches + mismatches + incomparable,
            "mass_matches": matches,
            "mass_mismatches": mismatches,
            "mass_not_comparable": incomparable,
            "structures_without_printed_ms": without,
            "printed_ms_lines": len(printed_lines),
            "printed_ms_unowned": len(unowned),
            "printed_ms_from_structure_rows": printed_dropped,
            "printed_ms_source": printed_source,
        },
        "items": page_items,
        "total": len(scoped),
    }


__all__ = ["DEFAULT_TOLERANCE_DA", "verify_structures"]
