"""Family-core derivation for a document's compound series.

Scanned patents sometimes pin a label on the wrong figure, so a candidate that
does not contain the document's own common core cannot be a final family member.
:func:`derive_family_core` extracts that shared core as a SMARTS pattern from the
document's Markush scaffold candidates; it returns ``None`` when no reliable core
exists, and callers must then make no claim about family membership.

Extraction stays conservative: a core needs at least ``_MIN_CORE_HEAVY`` heavy
atoms and at least two candidate structures to be considered real.
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import Any

from mbforge.foundation.logger import get_logger

logger = get_logger(__name__)

_MIN_SCAFFOLD_HEAVY = 12
_MIN_CORE_HEAVY = 14
_MCS_TOP_N = 25
_MCS_TIMEOUT_S = 15
_MCS_THRESHOLD = 0.75


def _mol_from_smiles(smiles: str) -> Any | None:
    from rdkit import Chem

    if not smiles:
        return None
    try:
        return Chem.MolFromSmiles(smiles)
    except Exception:  # noqa: BLE001 — RDKit raises bare exceptions on bad input
        return None


def _candidate_smiles(candidate: Any) -> str:
    return (
        getattr(candidate, "canonical_smiles", "")
        or getattr(candidate, "esmiles", "")
        or ""
    )


def derive_family_core(candidates: Sequence[Any]) -> str | None:
    """Return the shared-core SMARTS from scaffold-role candidates, or None.

    The maximum common substructure is computed over the largest scaffold
    SMILES (capped at ``_MCS_TOP_N``) with a 75% presence threshold so a
    few junk recognitions cannot shrink the core. Returns ``None`` when
    fewer than two usable scaffolds exist or the common core is too small
    to discriminate family members from reagents.
    """
    mols: list[Any] = []
    for candidate in candidates:
        properties = getattr(candidate, "properties", None)
        if not isinstance(properties, dict):
            continue
        if properties.get("structure_role") != "scaffold":
            continue
        mol = _mol_from_smiles(_candidate_smiles(candidate))
        if mol is not None and mol.GetNumHeavyAtoms() >= _MIN_SCAFFOLD_HEAVY:
            mols.append(mol)
    if len(mols) < 2:
        return None
    mols.sort(key=lambda mol: mol.GetNumHeavyAtoms(), reverse=True)
    mols = mols[:_MCS_TOP_N]

    from rdkit import Chem
    from rdkit.Chem import rdFMCS

    try:
        result = rdFMCS.FindMCS(
            mols,
            timeout=_MCS_TIMEOUT_S,
            threshold=_MCS_THRESHOLD,
            ringMatchesRingOnly=True,
        )
    except Exception as exc:  # noqa: BLE001 — MCS failure must not break persist
        logger.warning("Family core MCS computation failed: %s", exc)
        return None
    smarts = getattr(result, "smartsString", None) or getattr(result, "smarts", None)
    if getattr(result, "canceled", False) or not smarts:
        logger.info("Family core MCS canceled or empty; guard disabled")
        return None
    core = Chem.MolFromSmarts(smarts)
    if core is None or core.GetNumHeavyAtoms() < _MIN_CORE_HEAVY:
        logger.info(
            "Family core too small (%s atoms); guard disabled",
            core.GetNumHeavyAtoms() if core is not None else 0,
        )
        return None
    return smarts
