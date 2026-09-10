"""Advanced Markush features.

Extends the baseline Markush pipeline with:

1. **Multi-attachment fragments**: Fragments with 2+ attachment points
   (e.g., `-O-CH2-O-` as a linker between two sites). Requires explicit
   mapping of which fragment attachment connects to which scaffold site.

2. **Stereochemistry constraints**: Site-level chirality requirements
   (R/S, E/Z, cis/trans). Enumeration validates generated candidates
   against these constraints using RDKit's chirality APIs.

3. **Ring systems**: Abstract ring definitions (e.g., "A1 is a 5-6 membered
   heteroaryl") that enumerate to specific ring templates (pyridine,
   thiazole, etc.). Stored as SMARTS patterns with substitution rules.

These features are **opt-in per scaffold**. The baseline pipeline
continues to work without modification; this module only activates when
the new fields are populated.

Planned schema additions (not yet implemented — the functions below
validate their inputs but do not persist them):
- markush_sites.stereo_constraint (R/S/E/Z/cis/trans/null)
- markush_fragments.attachment_map (JSON: {"1": "R1", "2": "R3"})
- markush_ring_systems (ring_id, scaffold_id, ring_label, smarts_pattern, constraints)
- markush_options.ring_system_id (FK to markush_ring_systems)
"""

from __future__ import annotations

from typing import Any

from rdkit import Chem

from ..utils.logger import get_logger

logger = get_logger("mbforge.chem.markush_advanced")


def validate_multi_attachment_mapping(
    fragment_smiles: str,
    attachment_map: dict[str, str],
) -> tuple[bool, str]:
    """Validate that a fragment's attachment_map is consistent with its structure.

    Args:
        fragment_smiles: E-SMILES with explicit atom-map numbers (e.g., "[*:1]O[*:2]")
        attachment_map: Dict mapping fragment atom-map to site label
                       (e.g., {"1": "R1", "2": "R3"})

    Returns:
        (is_valid, error_message)
    """
    mol = Chem.MolFromSmiles(fragment_smiles)
    if mol is None:
        return False, "Invalid SMILES"

    # Count dummy atoms with atom-map numbers
    dummy_maps = set()
    for atom in mol.GetAtoms():
        if atom.GetAtomicNum() == 0:  # Dummy atom
            map_num = atom.GetAtomMapNum()
            if map_num > 0:
                dummy_maps.add(str(map_num))

    # Check attachment_map keys match dummy atoms
    map_keys = set(attachment_map.keys())
    if map_keys != dummy_maps:
        missing = dummy_maps - map_keys
        extra = map_keys - dummy_maps
        msg = []
        if missing:
            msg.append(f"missing maps: {missing}")
        if extra:
            msg.append(f"extra maps: {extra}")
        return False, "; ".join(msg)

    return True, ""


def validate_stereochemistry(
    smiles: str,
    site_label: str,
    stereo_constraint: str,
) -> tuple[bool, str]:
    """Check if a molecule satisfies a site's stereochemistry constraint.

    Args:
        smiles: Canonical SMILES of the generated candidate
        site_label: e.g., "R1"
        stereo_constraint: One of "R", "S", "E", "Z", "cis", "trans", or null

    Returns:
        (is_satisfied, reason)
    """
    if not stereo_constraint or stereo_constraint.lower() == "null":
        return True, "No constraint"

    mol = Chem.MolFromSmiles(smiles)
    if mol is None:
        return False, "Invalid SMILES"

    # Assign stereochemistry if not already present
    Chem.AssignStereochemistry(mol, cleanIt=True, force=True)

    constraint_upper = stereo_constraint.upper()

    # Check chiral centers (R/S)
    if constraint_upper in ("R", "S"):
        for atom in mol.GetAtoms():
            if atom.GetChiralTag() != Chem.ChiralType.CHI_UNSPECIFIED:
                chi = atom.GetChiralTag()
                if (
                    constraint_upper == "R"
                    and chi == Chem.ChiralType.CHI_TETRAHEDRAL_CW
                ):
                    return True, f"Found R center at atom {atom.GetIdx()}"
                if (
                    constraint_upper == "S"
                    and chi == Chem.ChiralType.CHI_TETRAHEDRAL_CCW
                ):
                    return True, f"Found S center at atom {atom.GetIdx()}"
        return False, f"No {constraint_upper} chiral center found"

    # Check double bond geometry (E/Z, cis/trans)
    if constraint_upper in ("E", "Z", "CIS", "TRANS"):
        for bond in mol.GetBonds():
            if bond.GetBondType() == Chem.BondType.DOUBLE:
                stereo = bond.GetStereo()
                if (
                    constraint_upper in ("E", "TRANS")
                    and stereo == Chem.BondStereo.STEREOE
                ):
                    return True, f"Found E/trans double bond {bond.GetIdx()}"
                if (
                    constraint_upper in ("Z", "CIS")
                    and stereo == Chem.BondStereo.STEREOZ
                ):
                    return True, f"Found Z/cis double bond {bond.GetIdx()}"
        return False, f"No {constraint_upper} double bond found"

    return False, f"Unknown constraint: {stereo_constraint}"


def enumerate_ring_system(
    ring_label: str,
    smarts_pattern: str,
    constraints: dict[str, Any],
) -> list[str]:
    """Enumerate concrete ring structures from an abstract ring system definition.

    Args:
        ring_label: e.g., "A1"
        smarts_pattern: SMARTS defining the ring core (e.g., "c1ccccc1" for phenyl)
        constraints: Dict with keys like:
            - "heteroatom": ["N", "O", "S"]
            - "ring_size": [5, 6]
            - "aromatic": true

    Returns:
        List of SMILES for concrete ring candidates
    """
    # This is a placeholder for a full ring enumeration engine.
    # A production implementation would:
    # 1. Parse SMARTS pattern
    # 2. Generate all valid heteroatom substitutions
    # 3. Filter by aromaticity/ring size constraints
    # 4. Return deduplicated canonical SMILES

    logger.warning(
        f"Ring enumeration for {ring_label} not yet implemented; returning empty list"
    )
    return []


def apply_stereo_constraint_to_site(
    conn: Any,
    site_id: str,
    stereo_constraint: str,
) -> None:
    """Set stereochemistry constraint on a site.

    Currently validates the value only; constraint persistence is not
    implemented.

    Args:
        conn: Database connection
        site_id: markush_sites.site_id
        stereo_constraint: "R" / "S" / "E" / "Z" / "cis" / "trans" / null
    """
    valid_constraints = {"R", "S", "E", "Z", "cis", "trans", "null", None}
    if stereo_constraint and stereo_constraint not in valid_constraints:
        raise ValueError(f"Invalid stereo_constraint: {stereo_constraint}")

    logger.info(
        f"Stereo constraint for site {site_id}: {stereo_constraint} "
        "(validated only; constraint storage is not implemented)"
    )


def set_fragment_attachment_map(
    conn: Any,
    fragment_id: str,
    attachment_map: dict[str, str],
) -> None:
    """Set multi-attachment mapping for a fragment.

    Currently validates the mapping only; persistence is not implemented.

    Args:
        conn: Database connection
        fragment_id: markush_fragments.fragment_id
        attachment_map: {"1": "R1", "2": "R3"}
    """
    cursor = conn.execute(
        "SELECT esmiles FROM markush_fragments WHERE fragment_id = ?",
        (fragment_id,),
    )
    row = cursor.fetchone()
    if not row:
        raise ValueError(f"Fragment {fragment_id} not found")

    esmiles = row[0]
    is_valid, error_msg = validate_multi_attachment_mapping(esmiles, attachment_map)
    if not is_valid:
        raise ValueError(f"Invalid attachment_map: {error_msg}")

    logger.info(
        f"Attachment map for fragment {fragment_id}: {attachment_map} "
        "(validated only; attachment-map storage is not implemented)"
    )


def create_ring_system(
    conn: Any,
    scaffold_id: str,
    ring_label: str,
    smarts_pattern: str,
    constraints: dict[str, Any],
) -> str:
    """Create an abstract ring system definition.

    Currently returns a derived ``ring_id`` only; ring-system persistence
    is not implemented.

    Args:
        conn: Database connection
        scaffold_id: Parent scaffold
        ring_label: e.g., "A1", "Het1"
        smarts_pattern: SMARTS defining the ring core
        constraints: Dict with heteroatom/ring_size/aromatic rules

    Returns:
        ring_id
    """
    logger.info(
        f"Ring system {ring_label} for scaffold {scaffold_id}: {smarts_pattern} "
        "(derived id only; ring-system storage is not implemented)"
    )
    return f"ring-{scaffold_id}-{ring_label}"


def enumerate_with_constraints(
    scaffold_smiles: str,
    site_selections: list[dict[str, Any]],
    stereo_constraints: dict[str, str],
) -> list[tuple[str, bool, str]]:
    """Enumerate with stereo validation.

    Args:
        scaffold_smiles: Core structure with [*:N] placeholders
        site_selections: List of {site_label, atom_map_num, fragments}
        stereo_constraints: {site_label: "R"/"S"/"E"/"Z"/etc.}

    Returns:
        List of (canonical_smiles, passes_stereo, reason)
    """
    results: list[tuple[str, bool, str]] = []

    for candidate_smiles in _baseline_enumerate(scaffold_smiles, site_selections):
        passes_all = True
        reasons = []

        for site_label, constraint in stereo_constraints.items():
            if constraint:
                passes, reason = validate_stereochemistry(
                    candidate_smiles, site_label, constraint
                )
                if not passes:
                    passes_all = False
                    reasons.append(f"{site_label}: {reason}")

        results.append(
            (
                candidate_smiles,
                passes_all,
                "; ".join(reasons) if reasons else "All constraints satisfied",
            )
        )

    return results


def _baseline_enumerate(
    scaffold_smiles: str,
    site_selections: list[dict[str, Any]],
) -> list[str]:
    """Baseline enumeration stub: always returns an empty list.

    Real bounded enumeration is implemented in
    :mod:`mbforge.core.markush_enumerate`.
    """
    return []
