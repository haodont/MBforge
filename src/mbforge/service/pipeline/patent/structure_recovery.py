"""Recover a misread structure by reprinting its own drawing at higher resolution.

The molecule pass reads each structure once, from a crop rendered at the
Extract DPI. When the document prints an ``LC-MS`` that disagrees with the
structure's own mass, the disagreement is evidence that the *recognition* is
wrong — not the reading (``find_mass_mismatches`` already detects exactly that).
Until now the only outcome was a review item, so a wrong SMILES could not bind
its readings and a human had to re-read the crop.

This pass closes the loop with the same model, better input: the drawing is
re-rendered from the PDF at a larger scale and read again, and the new structure
is kept only when it matches the mass the document printed. A reprint that still
disagrees changes nothing — the review item stands, because a second mismatch is
not a correction.

Measured motivation (CN121717757A): ``I-266-A`` exists as two drawings, one of
which the pass read with an extra ``CH2`` (572.2) while 实施例26 prints
``(M+H)+ = 558.0``; 8cb5's ``80``/``86`` are the same shape.
"""

from __future__ import annotations

import io
from collections.abc import Callable, Sequence
from pathlib import Path
from typing import Any

from mbforge.foundation.logger import get_logger

logger = get_logger(__name__)

#: A reprint is read at this multiple of the Extract DPI. MolParser's own
#: training crops are generous; doubling was enough to separate the two readings
#: of the same drawing in the corpus.
REPRINT_SCALE = 2.0


def _render_crop(
    pdf_path: str, page: int, bbox: Sequence[float], scale: float
) -> bytes:
    """Render one PDF region at *scale* times the reference DPI as PNG bytes."""
    import fitz

    document = fitz.open(pdf_path)
    try:
        pdf_page = document[page]
        clip = fitz.Rect(*(float(value) for value in bbox))
        pixmap = pdf_page.get_pixmap(
            clip=clip, matrix=fitz.Matrix(scale, scale), alpha=False
        )
        return pixmap.tobytes("png")
    finally:
        document.close()


def _recognize(image_bytes: bytes) -> str:
    """Read the structure in a crop; an unavailable model yields ``""``."""
    from PIL import Image

    from mbforge.foundation.inference import molparser

    result = molparser.predict(Image.open(io.BytesIO(image_bytes)))
    return str(getattr(result, "smiles", "") or "")


def _canonical(smiles: str) -> str:
    from rdkit import Chem

    try:
        molecule = Chem.MolFromSmiles(smiles)
    except Exception:  # noqa: BLE001 - a bad reprint is not a correction
        return ""
    if molecule is None:
        return ""
    try:
        return Chem.MolToSmiles(molecule, canonical=True, isomericSmiles=True)
    except Exception:  # noqa: BLE001
        return ""


def recover_structures_by_printed_mass(
    *,
    pdf_path: str | Path,
    library_root: str | Path,
    doc_id: str,
    candidates: Sequence[Any],
    characterizations: Sequence[dict],
    issues: list[dict[str, Any]],
    render: Callable[[str, int, Sequence[float], float], bytes] | None = None,
    recognize: Callable[[bytes], str] | None = None,
) -> list[Any]:
    """Re-read every mismatching drawing at higher resolution; return the fixes.

    The corrected structures are returned **and** persisted, so the entry that
    names the compound can bind to them. A correction that does not match the
    printed mass is not applied: the mismatch stays a review item.
    """
    from mbforge.foundation.ids import stable_id
    from mbforge.service.pipeline.detection.label_recovery import exact_mass
    from mbforge.service.pipeline.patent.rules.characterization import (
        MASS_TOLERANCE_DA,
        adduct_mass_delta,
        find_mass_mismatches,
    )
    from mbforge.service.pipeline.persist.molecules import (
        persist_molecule_candidates,
    )

    render = render or _render_crop
    recognize = recognize or _recognize
    by_smiles = {
        str(getattr(candidate, "canonical_smiles", "") or ""): candidate
        for candidate in candidates
    }

    recovered: list[Any] = []
    handled: set[tuple[str, str]] = set()
    for mismatch in find_mass_mismatches(characterizations, list(candidates)):
        key = (str(mismatch["mol_id"]), str(mismatch["label_key"]))
        if key in handled:
            continue
        handled.add(key)
        candidate = by_smiles.get(str(mismatch["structure_smiles"]))
        if candidate is None:
            continue
        detections = list(getattr(candidate, "detections", []) or [])
        if not detections:
            continue
        detection = detections[0]
        if detection.page is None or detection.bbox is None:
            continue
        try:
            image = render(
                str(pdf_path), int(detection.page), detection.bbox, REPRINT_SCALE
            )
            smiles = recognize(image)
        except Exception as exc:  # noqa: BLE001 - a failed reprint is not fatal
            logger.warning("Reprint failed for %s: %s", mismatch["label_key"], exc)
            continue
        canonical = _canonical(smiles)
        if not canonical or canonical == str(mismatch["structure_smiles"]):
            continue
        delta_mass = adduct_mass_delta(str(mismatch.get("adduct") or ""))
        structure_mass = exact_mass(canonical)
        if delta_mass is None or structure_mass is None:
            continue
        printed = float(mismatch["printed_mz"])
        if abs(printed - (structure_mass + delta_mass)) > MASS_TOLERANCE_DA:
            # A reprint that still disagrees is not a correction.
            continue

        corrected = _corrected_molecule(candidate, canonical)
        if corrected is None:
            continue
        persist_molecule_candidates(str(library_root), doc_id, [corrected])
        recovered.append(corrected)
        _append_issue(
            issues,
            {
                "code": "structure_recovered_from_reprint",
                "message": (
                    f"{mismatch['label_key']}: reprinted drawing at "
                    f"{REPRINT_SCALE:g}x reads {canonical}, matching the printed "
                    f"m/z {printed:g}"
                ),
                "severity": "warning",
                "evidence_ids": [detection.evidence_id]
                if detection.evidence_id
                else [],
                "related_fact_id": stable_id(
                    "reprint", doc_id, str(mismatch["label_key"]), canonical
                ),
                "label_key": mismatch["label_key"],
                "replaced_smiles": mismatch["structure_smiles"],
                "smiles": canonical,
                "printed_mz": printed,
            },
        )
    return recovered


def _corrected_molecule(candidate: Any, canonical: str) -> Any | None:
    """Copy *candidate* with the corrected structure, ready to persist."""
    from mbforge.domain.molecule import Molecule

    source = candidate if isinstance(candidate, Molecule) else None
    if source is None:
        return None
    properties = dict(source.properties or {})
    properties["structure_role"] = "complete"
    properties["corrected_structure"] = {
        "from": source.canonical_smiles,
        "to": canonical,
        "reason": "reprint_matches_printed_ms",
    }
    return Molecule(
        canonical_smiles=canonical,
        esmiles=source.esmiles,
        name=source.name,
        sources=list(source.sources),
        detections=list(source.detections),
        status="pending",
        properties=properties,
        labels=list(source.labels),
    )


def _append_issue(issues: list[dict[str, Any]], issue: dict[str, Any]) -> None:
    if any(
        existing.get("code") == issue["code"]
        and existing.get("related_fact_id") == issue["related_fact_id"]
        for existing in issues
    ):
        return
    issues.append(issue)


__all__ = ["REPRINT_SCALE", "recover_structures_by_printed_mass"]


def promote_structures_by_printed_mass(
    *,
    library_root: str | Path,
    doc_id: str,
    candidates: Sequence[Any],
    characterizations: Sequence[dict],
    issues: list[dict[str, Any]],
) -> list[Any]:
    """Name an unlabelled drawing after the designation whose printed mass it matches.

    A designation can be cited by a reading and printed with its own ``LC-MS``
    while no drawing carries the number: CN121717757A prints ``I-2`` in its
    activity table and ``(M+H)+ = 504.1`` in 实施例3, and the claims drawing whose
    mass is 503.16 was read but captioned by neither. The document has said
    which structure it means; only the label never reached the drawing.

    The promotion is deliberately narrow: the designation must have no structure
    answering it already, the printed mass must match **exactly one** unlabelled
    concrete drawing, and a scaffold is never a candidate. The molecule is stored
    under the designation so the association can then bind the readings by rule.
    """
    from mbforge.foundation.ids import stable_id
    from mbforge.service.pipeline.detection.label_recovery import exact_mass
    from mbforge.service.pipeline.detection.structure_role import (
        PROPERTY_KEY,
        classify_structure_role,
    )
    from mbforge.service.pipeline.patent.candidate_labels import candidate_label_keys
    from mbforge.service.pipeline.patent.rules.characterization import (
        MASS_TOLERANCE_DA,
        adduct_mass_delta,
        printed_ms_mz,
    )
    from mbforge.service.pipeline.persist.molecules import (
        persist_molecule_candidates,
    )

    named: set[str] = set()
    for candidate in candidates:
        named |= candidate_label_keys(candidate)

    unlabelled = []
    for candidate in candidates:
        smiles = str(getattr(candidate, "canonical_smiles", "") or "")
        if not smiles or "*" in smiles or candidate_label_keys(candidate):
            continue
        properties = getattr(candidate, "properties", {})
        properties = properties if isinstance(properties, dict) else {}
        role = properties.get(PROPERTY_KEY)
        if role is None:
            role = classify_structure_role(candidate)
        if role in ("fragment", "scaffold", "rejected"):
            continue
        unlabelled.append(candidate)

    promoted: list[Any] = []
    for item in characterizations:
        label_key = str(item.get("label_key") or "")
        if item.get("technique") != "ms" or not label_key or label_key in named:
            continue
        parsed = printed_ms_mz(str(item.get("raw_text") or ""))
        if parsed is None:
            continue
        printed, adduct = parsed
        delta_mass = adduct_mass_delta(adduct)
        if delta_mass is None:
            continue
        matches = []
        for candidate in unlabelled:
            structure_mass = exact_mass(
                str(getattr(candidate, "canonical_smiles", "") or "")
            )
            if structure_mass is None:
                continue
            if abs(printed - (structure_mass + delta_mass)) <= MASS_TOLERANCE_DA:
                matches.append(candidate)
        if len(matches) != 1:
            continue
        target = matches[0]
        target.name = label_key
        target.properties[PROPERTY_KEY] = "complete"
        target.properties["designation_promotion"] = {
            "label_key": label_key,
            "printed_mz": printed,
            "adduct": adduct,
            "reason": "printed_mass_names_this_drawing",
        }
        persist_molecule_candidates(str(library_root), doc_id, [target])
        unlabelled.remove(target)
        named.add(label_key)
        promoted.append(target)
        _append_issue(
            issues,
            {
                "code": "designation_promoted_by_printed_mass",
                "message": (
                    f"{label_key}: the unlabelled drawing whose mass is {printed:g} "
                    f"was named after the designation its LC-MS prints"
                ),
                "severity": "info",
                "evidence_ids": [
                    detection.evidence_id
                    for detection in getattr(target, "detections", [])
                    if getattr(detection, "evidence_id", None)
                ],
                "related_fact_id": stable_id("promoted-by-mass", doc_id, label_key),
                "label_key": label_key,
                "smiles": str(getattr(target, "canonical_smiles", "") or ""),
                "printed_mz": printed,
            },
        )
    return promoted


__all__ = [
    "REPRINT_SCALE",
    "promote_structures_by_printed_mass",
    "recover_structures_by_printed_mass",
]
