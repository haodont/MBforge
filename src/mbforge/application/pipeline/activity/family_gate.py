"""Family-core consistency gate for activity assignment.

A numeric row-label match (``row_label == mol.name``) asserts "this
structure is the document's final compound N". In scanned patents the
coref layer occasionally pins a label on the wrong figure — a reagent or
an intermediate next to the product — and the activity then attaches to
the wrong molecule. When the document's own Markush scaffolds define a
common core, a candidate that does not contain that core cannot be a
final family member. Such candidates are vetoed from activity matching
(row-label and same-page fallback alike); their records fall through to
the review queue instead of producing a confidently wrong assignment.

The gate is intentionally conservative:

- It activates only when at least two scaffold candidates share a
  maximum common substructure of >= ``_MIN_CORE_HEAVY`` heavy atoms.
- Unparseable candidate SMILES are never vetoed (other stages own
  rejection).
- With no reliable core the guard is ``None`` and matching is unchanged.
"""

from __future__ import annotations

from collections.abc import Callable, Sequence
from typing import Any

from mbforge.foundation.logger import get_logger

logger = get_logger(__name__)

# Structured reason code logged with each veto (repair plan section 11).
FAMILY_CORE_MISMATCH = "FAMILY_CORE_MISMATCH"

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


def make_family_core_guard(
    core_smarts: str | None,
) -> Callable[[Any], str | None] | None:
    """Build the activity-match guard for *core_smarts*.

    The returned callable yields :data:`FAMILY_CORE_MISMATCH` for
    candidates whose structure does not contain the family core, and
    ``None`` otherwise. Returns ``None`` when no usable core exists so
    callers can skip guarding entirely.
    """
    if not core_smarts:
        return None
    from rdkit import Chem

    core = Chem.MolFromSmarts(core_smarts)
    if core is None:
        return None

    def _guard(candidate: Any) -> str | None:
        mol = _mol_from_smiles(_candidate_smiles(candidate))
        if mol is None:
            # Unparseable structures are owned by the rejection path;
            # the core gate must not veto what it cannot judge.
            return None
        if mol.HasSubstructMatch(core):
            return None
        return FAMILY_CORE_MISMATCH

    return _guard
