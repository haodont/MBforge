"""Context-based molecule correction and validation.

Applies deterministic rules to flag or correct likely MolParser misreads
using contextual signals (nearby text, chemical names).
All corrections are audit-logged to ``properties["corrections"]`` and
never silently discard the original SMILES.

The rules are business operations on a :class:`NormalizedMolecule` record,
so the module lives alongside the record type in :mod:`mbforge.pipeline`.
"""

from __future__ import annotations

import re
from datetime import UTC, datetime
from typing import Any

from rdkit import Chem

from ...utils.logger import get_logger
from .label_normalization import LabelKind
from .types import NormalizedMolecule

logger = get_logger(__name__)

# Common chemical name → required substructure (SMARTS or SMILES fragment)
# Used to validate that a molecule's structure matches its detected name.
_CHEM_NAME_SUBSTRUCTURES: dict[str, str] = {
    "苯胺": "c1ccccc1N",
    "aniline": "c1ccccc1N",
    "吡啶": "c1ccncc1",
    "pyridine": "c1ccncc1",
    "噻吩": "c1ccsc1",
    "thiophene": "c1ccsc1",
    "呋喃": "c1ccoc1",
    "furan": "c1ccoc1",
    "吲哚": "c1ccc2[nH]ccc2c1",
    "indole": "c1ccc2[nH]ccc2c1",
    "喹啉": "c1ccc2ncccc2c1",
    "quinoline": "c1ccc2ncccc2c1",
    "苯甲酸": "c1ccccc1C(=O)O",
    "benzoic acid": "c1ccccc1C(=O)O",
    "苯酚": "c1ccccc1O",
    "phenol": "c1ccccc1O",
}

# Element keywords in context → expected element symbols
_ELEMENT_KEYWORDS: dict[str, str] = {
    "含氟": "F",
    "氟代": "F",
    "fluoro": "F",
    "fluorine": "F",
    "含氯": "Cl",
    "氯代": "Cl",
    "chloro": "Cl",
    "chlorine": "Cl",
    "含溴": "Br",
    "溴代": "Br",
    "bromo": "Br",
    "bromine": "Br",
    "含碘": "I",
    "碘代": "I",
    "iodo": "I",
    "iodine": "I",
    "含硫": "S",
    "thio": "S",
    "sulfur": "S",
    "含氮": "N",
    "amino": "N",
    "nitro": "N",
    "nitrogen": "N",
    "含磷": "P",
    "phospho": "P",
    "phosphorus": "P",
}

_RGROUP_LABEL_RE = re.compile(r"\bR\s*[0-9₀-₉]+\b", re.IGNORECASE)


def _add_correction(
    molecule: NormalizedMolecule,
    rule: str,
    original: str,
    corrected: str,
    detail: str,
) -> None:
    """Record a correction in the molecule's audit log."""
    corrections: list[dict[str, Any]] = molecule.properties.setdefault(
        "corrections", []
    )
    corrections.append(
        {
            "rule": rule,
            "original": original,
            "corrected": corrected,
            "detail": detail,
            "timestamp": datetime.now(UTC).isoformat(),
        }
    )


def _add_review_flag(molecule: NormalizedMolecule, flag: str, detail: str) -> None:
    """Add a review flag without changing status."""
    flags: list[dict[str, str]] = molecule.properties.setdefault("review_flags", [])
    flags.append({"flag": flag, "detail": detail})


def _context_values(molecule: NormalizedMolecule) -> list[str]:
    """Collect all human-readable context for a molecule."""
    values: list[str] = []
    if molecule.name:
        values.append(molecule.name)
    properties = molecule.properties
    for key in ("context_texts", "detection_names", "role_contexts"):
        value = properties.get(key)
        if isinstance(value, str):
            values.append(value)
        elif isinstance(value, list):
            values.extend(item for item in value if isinstance(item, str))
    return [value[:2000] for value in values if value.strip()]


def correct_rgroup_misread(molecule: NormalizedMolecule) -> bool:
    """Flag molecules whose context suggests R-groups but SMILES is closed.

    MolParser can turn a Markush structure with R-group labels into a
    syntactically valid closed SMILES. If the context explicitly mentions
    R1/R2/etc. or Formula labels, the molecule should be reviewed rather
    than imported as a concrete compound.

    Returns True if the molecule was flagged.
    """
    if molecule.status != "pending":
        return False

    context = " ".join(_context_values(molecule))
    has_rgroup_context = bool(_RGROUP_LABEL_RE.search(context))
    label_kind = molecule.properties.get("label_kind")
    is_formula_label = label_kind == LabelKind.FORMULA.value

    if not (has_rgroup_context or is_formula_label):
        return False

    # Check if SMILES already contains dummy atoms (expected for Markush)
    smiles = molecule.canonical_smiles
    try:
        mol = Chem.MolFromSmiles(smiles)
    except Exception:
        mol = None
    if mol is None:
        return False

    has_dummy = any(
        atom.GetSymbol() == "*" or atom.GetAtomicNum() == 0 for atom in mol.GetAtoms()
    )
    if has_dummy:
        # Already correctly recognized as Markush — no correction needed.
        return False

    # Closed SMILES + R-group context → likely misread, flag for review.
    original_status = molecule.status
    molecule.status = "pending_review"
    molecule.properties["correction_reason"] = "rgroup_context_mismatch"
    _add_correction(
        molecule,
        rule="correct_rgroup_misread",
        original=original_status,
        corrected="pending_review",
        detail=(
            f"Context contains R-group/Formula markers "
            f"(label_kind={label_kind}, rgroup={has_rgroup_context}) "
            f"but SMILES is closed: {smiles}"
        ),
    )
    logger.debug(
        "Flagged molecule %s for review: R-group context but closed SMILES %s",
        molecule.name or molecule.esmiles[:20],
        smiles,
    )
    return True


def verify_element_consistency(molecule: NormalizedMolecule) -> bool:
    """Flag molecules whose context mentions elements missing from SMILES.

    Returns True if any suspicious elements were flagged.
    """
    if molecule.status not in ("pending", "pending_review"):
        return False

    context = " ".join(_context_values(molecule)).lower()
    if not context:
        return False

    smiles = molecule.canonical_smiles
    try:
        mol = Chem.MolFromSmiles(smiles)
    except Exception:
        mol = None
    if mol is None:
        return False

    present_elements = {atom.GetSymbol() for atom in mol.GetAtoms()}
    suspicious: list[str] = []

    for keyword, element in _ELEMENT_KEYWORDS.items():
        if keyword.lower() in context and element not in present_elements:
            suspicious.append(element)
            _add_review_flag(
                molecule,
                flag="missing_element",
                detail=(
                    f"Context mentions '{keyword}' ({element}) "
                    f"but SMILES lacks {element}: {smiles}"
                ),
            )

    if suspicious:
        molecule.properties["suspicious_elements"] = suspicious
        logger.debug(
            "Flagged molecule %s for missing elements %s in SMILES %s",
            molecule.name or molecule.esmiles[:20],
            suspicious,
            smiles,
        )
        return True
    return False


def check_markush_consistency(molecule: NormalizedMolecule) -> bool:
    """Flag mismatches between Markush labels and SMILES structure.

    Returns True if a mismatch was flagged.
    """
    if molecule.status not in ("pending", "pending_review"):
        return False

    label_kind = molecule.properties.get("label_kind")
    smiles = molecule.canonical_smiles
    try:
        mol = Chem.MolFromSmiles(smiles)
    except Exception:
        mol = None
    if mol is None:
        return False

    has_dummy = any(
        atom.GetSymbol() == "*" or atom.GetAtomicNum() == 0 for atom in mol.GetAtoms()
    )

    flagged = False
    if label_kind == LabelKind.FORMULA.value and not has_dummy:
        _add_review_flag(
            molecule,
            flag="formula_without_dummy",
            detail=(f"Label kind is FORMULA but SMILES has no dummy atoms: {smiles}"),
        )
        flagged = True
    elif label_kind != LabelKind.FORMULA.value and has_dummy:
        # Not necessarily wrong (fragments can have dummies), but worth review.
        _add_review_flag(
            molecule,
            flag="dummy_without_formula_label",
            detail=(f"SMILES has dummy atoms but label kind is {label_kind}: {smiles}"),
        )
        flagged = True

    if flagged:
        logger.debug(
            "Flagged molecule %s for Markush consistency: label=%s, dummy=%s",
            molecule.name or molecule.esmiles[:20],
            label_kind,
            has_dummy,
        )
    return flagged


def verify_name_substructure(molecule: NormalizedMolecule) -> bool:
    """Flag molecules whose detected name implies a substructure not in SMILES.

    Returns True if a mismatch was flagged.
    """
    if molecule.status not in ("pending", "pending_review"):
        return False

    smiles = molecule.canonical_smiles
    try:
        mol = Chem.MolFromSmiles(smiles)
    except Exception:
        mol = None
    if mol is None:
        return False

    names_to_check: list[str] = []
    if molecule.name:
        names_to_check.append(molecule.name.lower())
    detection_names = molecule.properties.get("detection_names", [])
    names_to_check.extend(str(n).lower() for n in detection_names if n)

    flagged = False
    for name in names_to_check:
        for chem_name, substructure in _CHEM_NAME_SUBSTRUCTURES.items():
            if chem_name.lower() not in name:
                continue
            try:
                pattern = Chem.MolFromSmiles(substructure)
            except Exception:
                continue
            if pattern is None:
                continue
            if not mol.HasSubstructMatch(pattern):
                _add_review_flag(
                    molecule,
                    flag="name_substructure_mismatch",
                    detail=(
                        f"Name contains '{chem_name}' but SMILES lacks "
                        f"substructure {substructure}: {smiles}"
                    ),
                )
                flagged = True
                logger.debug(
                    "Flagged molecule %s: name '%s' implies %s but SMILES %s lacks it",
                    molecule.name or molecule.esmiles[:20],
                    chem_name,
                    substructure,
                    smiles,
                )

    return flagged


def correct_molecules_with_context(
    molecules: list[NormalizedMolecule],
) -> list[NormalizedMolecule]:
    """Apply all context-based corrections to a list of normalized molecules.

    Args:
        molecules: Output of :func:`mbforge.pipeline.detection.normalization.normalize_molecules`.

    Returns:
        The same list, with corrections and review flags applied in-place.
    """
    corrected_count = 0
    for molecule in molecules:
        flagged = False
        flagged |= correct_rgroup_misread(molecule)
        flagged |= verify_element_consistency(molecule)
        flagged |= check_markush_consistency(molecule)
        flagged |= verify_name_substructure(molecule)
        if flagged:
            corrected_count += 1

    logger.debug(
        "Context correction complete: %d/%d molecules flagged or corrected",
        corrected_count,
        len(molecules),
    )
    return molecules


__all__ = [
    "check_markush_consistency",
    "correct_molecules_with_context",
    "correct_rgroup_misread",
    "verify_element_consistency",
    "verify_name_substructure",
]
