"""Markush pattern parsing (Phase 5 helper).

This module implements :func:`parse_markush`: parse an E-SMILES /
R-group SMILES into the core scaffold + explicit attachment sites +
free-form R-group definitions. Uses RDKit atom-map numbers as the
canonical attachment identity (implicit ``*`` order is rejected).

These helpers are pure functions: no DB I/O, no Pydantic. The HTTP
router wraps them and converts to Pydantic responses. Coverage
checking lives in :mod:`mbforge.core.markush.coverage`.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from rdkit import Chem, RDLogger

RDLogger.DisableLog("rdApp.*")


@dataclass
class MarkushSite:
    """One explicit attachment site on a Markush scaffold.

    ``site_label`` is the R-group name from the SMILES (R1, R2, ...).
    ``atom_map_num`` is the explicit ``[*:N]`` integer used as the
    canonical identity. ``attachment_count`` records how many bond
    positions the site consumes (defaults to 1).
    """

    site_label: str
    atom_map_num: int
    attachment_count: int = 1
    bond_type: str | None = None


@dataclass
class MarkushRGroupDefinition:
    """One R-group's free-text definition (optional).

    Used by the coverage check to refine the per-site judgment when the
    query substituent matches a definition range (e.g. "C1-6 alkyl").
    """

    label: str
    definition: str = ""
    allowed_smiles: list[str] = field(default_factory=list)


@dataclass
class ParsedMarkush:
    """Result of :func:`parse_markush`.

    Attributes:
        core_smiles: SMILES of the core scaffold with ``*`` replaced by
            the dummy atom ``[At]`` (RDKit's canonical attachment
            placeholder). Empty if parsing fails.
        sites: explicit attachment sites, sorted by ``atom_map_num``.
        r_groups: free-form R-group definitions supplied alongside the
            SMILES (e.g. ``{"R1": "H or C1-4 alkyl"}``).
        abstract_rings: aromatic / spiro / bridged ring descriptors that
            the user marked as ``abstract`` — currently just a placeholder
            list reserved for future ring-abstraction support.
        warnings: non-fatal parse warnings.
        raw: the original E-SMILES / Markush string.
    """

    core_smiles: str = ""
    sites: list[MarkushSite] = field(default_factory=list)
    r_groups: list[MarkushRGroupDefinition] = field(default_factory=list)
    abstract_rings: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    raw: str = ""

    @property
    def site_labels(self) -> list[str]:
        return [s.site_label for s in self.sites]


def parse_markush(
    esmiles: str,
    *,
    r_group_definitions: dict[str, str] | None = None,
) -> ParsedMarkush:
    """Parse an E-SMILES / Markush pattern into a :class:`ParsedMarkush`.

    ``r_group_definitions`` is an optional ``{label: definition_text}``
    map; the result mirrors it in ``r_groups`` so the coverage check
    can compare each query substituent against the definition text.
    """
    result = ParsedMarkush(raw=esmiles)
    if not esmiles or not esmiles.strip():
        result.warnings.append("empty SMILES input")
        return result
    mol = Chem.MolFromSmiles(esmiles)
    if mol is None:
        result.warnings.append("invalid SMILES: RDKit failed to parse")
        return result
    # Walk dummy atoms (``*`` / ``[At]``) and use their atom-map number
    # as the canonical site identity. Without an atom-map number the
    # explicit-identity invariant is violated and we surface a warning.
    for atom in mol.GetAtoms():
        if atom.GetAtomicNum() == 0:  # dummy atom
            map_num = atom.GetAtomMapNum()
            if map_num == 0:
                result.warnings.append("attachment site without explicit atom map")
                continue
            label = f"R{map_num}"
            result.sites.append(
                MarkushSite(
                    site_label=label,
                    atom_map_num=map_num,
                )
            )
    result.sites.sort(key=lambda s: s.atom_map_num)
    # ``core_smiles`` is the SMILES with all attachment points replaced
    # by ``[*:N]`` so downstream substructure matching can preserve
    # the atom-map identity for the query substitution check.
    result.core_smiles = Chem.MolToSmiles(mol, isomericSmiles=True)
    # ``Chem.MolToSmiles`` strips dummy atoms from the canonical form;
    # preserve the original Markush SMILES under ``raw`` so downstream
    # substructure matching can still recover the attachment sites.
    if result.sites:
        result.core_smiles = esmiles
    if r_group_definitions:
        for label, definition in r_group_definitions.items():
            result.r_groups.append(
                MarkushRGroupDefinition(label=label, definition=definition)
            )
    return result


def parse_response(parsed: ParsedMarkush) -> dict[str, Any]:
    """Convert a :class:`ParsedMarkush` into the dict shape expected by
    :class:`MarkushPatternResponse`."""
    return {
        "success": True,
        "core_smiles": parsed.core_smiles,
        "r_groups": [
            {"label": r.label, "definition": r.definition} for r in parsed.r_groups
        ],
        "abstract_rings": list(parsed.abstract_rings),
        "raw": parsed.raw,
        "error": None,
        "warnings": list(parsed.warnings),
    }


__all__ = [
    "MarkushRGroupDefinition",
    "MarkushSite",
    "ParsedMarkush",
    "parse_markush",
    "parse_response",
]
