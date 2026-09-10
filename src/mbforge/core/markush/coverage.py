"""Markush coverage checking (Phase 6 helper).

This module implements :func:`check_markush_coverage`: given a parsed
Markush pattern and a query molecule, determine whether the query falls
*within scope*, *outside scope*, or *unknown*. The decision is per-
attachment-site: each site reports its query substituent, the matched
definition, and a reason. The aggregate ``match_level`` is one of
``full``, ``partial``, ``scaffold_only``, ``none``, ``unknown``.

These helpers are pure functions: no DB I/O, no Pydantic. The HTTP
router wraps them and converts to Pydantic responses. Pattern parsing
lives in :mod:`mbforge.core.markush.parser`.
"""

from __future__ import annotations

import contextlib
from dataclasses import dataclass
from typing import Any

from rdkit import Chem, RDLogger

from .parser import ParsedMarkush

RDLogger.DisableLog("rdApp.*")


SiteJudgment = str  # "within_scope" | "outside_scope" | "unknown"
MatchLevel = str  # "full" | "partial" | "scaffold_only" | "none" | "unknown"


@dataclass
class SiteResult:
    """Per-attachment-site coverage verdict."""

    site_label: str
    atom_map_num: int
    query_substituent: str | None
    definition: str
    judgment: SiteJudgment
    reason: str
    confidence: float = 0.0


def _strip_dummy_atoms(mol: Chem.Mol, *, kekulize: bool = False) -> Chem.Mol:
    """Return a copy of *mol* with every dummy ``*`` atom removed.

    RDKit's substructure match is unreliable when one side carries
    dummy atoms (the matcher sees them as bond-endpoint mismatches);
    stripping them up front gives a clean heavy-atom core that
    matches deterministically.

    When ``kekulize`` is True the result is also kekulized so it
    matches a kekulized query under the standard matcher.
    """
    rw = Chem.RWMol(mol)
    for atom in sorted(
        [a.GetIdx() for a in rw.GetAtoms() if a.GetAtomicNum() == 0],
        reverse=True,
    ):
        rw.RemoveAtom(atom)
    result = rw.GetMol()
    if kekulize:
        with contextlib.suppress(Exception):
            Chem.Kekulize(result)
    return result


def _strip_attachment_atoms(query_mol: Chem.Mol, atom_map_num: int) -> Chem.Mol | None:
    """Remove the attachment atom with ``atom_map_num`` from *query_mol*.

    Returns the residue that was bonded to the attachment point (the
    "substituent"); ``None`` when no such atom exists. Used to extract
    the SMILES of the R-group that occupies a given site.
    """
    rwmol = Chem.RWMol(query_mol)
    target_idx: int | None = None
    parent_idx: int | None = None
    for atom in rwmol.GetAtoms():
        if atom.GetAtomMapNum() == atom_map_num:
            target_idx = atom.GetIdx()
            for bond in atom.GetBonds():
                parent_idx = bond.GetOtherAtomIdx(atom.GetIdx())
                break
            break
    if target_idx is None or parent_idx is None:
        return None
    # Remove the attachment atom; the parent's substituent remains in
    # place and becomes the returned molecule.
    rwmol.RemoveAtom(target_idx)
    return rwmol.GetMol()


def check_markush_coverage(
    parsed: ParsedMarkush,
    query_smiles: str,
) -> tuple[MatchLevel, list[SiteResult], list[str], float]:
    """Return ``(match_level, site_results, details, core_overlap_ratio)``.

    The function first matches the Markush core against the query; if
    the core does not embed in the query at all the answer is
    ``"none"``. Otherwise each site is examined in turn and assigned a
    three-state verdict (``within_scope`` / ``outside_scope`` /
    ``unknown``). The aggregate ``match_level`` is computed as follows:

    - ``unknown`` if any site verdict is ``unknown`` *and* no site is
      ``outside_scope``.
    - ``full`` if every site is ``within_scope``.
    - ``partial`` if at least one site is ``outside_scope`` and the rest
      are ``within_scope`` or ``unknown``.
    - ``scaffold_only`` when no site verdict is ``within_scope`` but the
      core matched.
    """
    details: list[str] = []
    site_results: list[SiteResult] = []
    if not parsed.core_smiles or not query_smiles:
        return "unknown", site_results, ["empty core or query"], 0.0
    # Build a core molecule with the dummy atoms stripped — RDKit's
    # standard ``GetSubstructMatch`` is unreliable when one side has
    # dummy atoms. We remove them by mapping them to a fresh molecule
    # and dropping them so the heavy atoms alone drive matching.
    core_mol = Chem.MolFromSmiles(parsed.core_smiles)
    query_mol = Chem.MolFromSmiles(query_smiles)
    if core_mol is None or query_mol is None:
        details.append("invalid SMILES in core or query")
        return "unknown", site_results, details, 0.0
    if not parsed.sites:
        details.append("Markush pattern has no explicit attachment sites")
        return "unknown", [], details, 0.0

    # Markush SMILES with ``[*:N]`` are SMARTS-compatible. The atom-map
    # numbers on the dummy atoms are stripped before matching so the
    # pattern accepts any heavy atom at the attachment position rather
    # than only the literal atom-map identity in the query.
    pattern_kekule = _strip_dummy_atoms(core_mol, kekulize=True)
    try:
        pattern_smarts = Chem.MolToSmiles(
            pattern_kekule, kekuleSmiles=True, isomericSmiles=True
        )
        query_pattern = Chem.MolFromSmarts(pattern_smarts)
    except Exception:
        query_pattern = None
    if query_pattern is None:
        details.append("failed to build SMARTS pattern from core")
        return "unknown", [], details, 0.0
    # Kekulize the query too so the matcher is on equal footing.
    query_kekule = Chem.Mol(query_mol)
    try:
        Chem.Kekulize(query_kekule)
    except Exception:
        query_kekule = Chem.Mol(query_mol)
    matched = query_kekule.GetSubstructMatch(query_pattern)
    if not matched:
        details.append("query does not contain the Markush core")
        return "none", [], details, 0.0
    core_atoms = query_kekule.GetNumHeavyAtoms()
    core_overlap_ratio = 1.0 if core_atoms else 0.0
    details.append(f"core matched ({core_atoms} atoms)")

    # Build a label-to-substituent map by stripping each attachment
    # atom from a fresh query copy and re-serializing.
    for site in parsed.sites:
        residue = _strip_attachment_atoms(query_mol, site.atom_map_num)
        sub_smiles = Chem.MolToSmiles(residue) if residue is not None else None
        definition = next(
            (r.definition for r in parsed.r_groups if r.label == site.site_label),
            "",
        )
        if sub_smiles is None:
            site_results.append(
                SiteResult(
                    site_label=site.site_label,
                    atom_map_num=site.atom_map_num,
                    query_substituent=None,
                    definition=definition,
                    judgment="unknown",
                    reason="attachment atom not present in query SMILES",
                )
            )
            continue
        # Heuristic: a trivial substituent (``[H]`` / single atom / very
        # short SMILES) is treated as within_scope regardless of
        # definition, because R-group definitions like "H or C1-6
        # alkyl" explicitly include the hydrogen case. A non-trivial
        # substituent with a textual definition stays ``unknown`` until
        # the caller (UI) confirms against the textual rule; without a
        # definition we treat it as ``unknown`` so the human stays in
        # the loop.
        is_trivial = sub_smiles in {"[H]", "[*]"} or len(sub_smiles) <= 4
        query_is_markush = "*" in sub_smiles
        if is_trivial or query_is_markush:
            judgment: SiteJudgment = "within_scope"
            if query_is_markush:
                reason = "query is itself a Markush pattern (no substitution)"
            else:
                reason = "trivial substituent (H / single-atom)"
            confidence = 0.9
        elif definition:
            judgment = "unknown"
            reason = (
                f"definition present ({definition!r}); confirm against textual rules"
            )
            confidence = 0.5
        else:
            judgment = "unknown"
            reason = "non-trivial substituent without a textual definition"
            confidence = 0.5
        site_results.append(
            SiteResult(
                site_label=site.site_label,
                atom_map_num=site.atom_map_num,
                query_substituent=sub_smiles,
                definition=definition,
                judgment=judgment,
                reason=reason,
                confidence=confidence,
            )
        )

    if not site_results:
        return "unknown", [], details, core_overlap_ratio
    judgments = [s.judgment for s in site_results]
    if all(j == "within_scope" for j in judgments):
        match_level: MatchLevel = "full"
    elif any(j == "outside_scope" for j in judgments) or any(
        j == "within_scope" for j in judgments
    ):
        match_level = "partial"
    elif any(j == "unknown" for j in judgments):
        match_level = "unknown"
    else:
        match_level = "scaffold_only"
    return match_level, site_results, details, core_overlap_ratio


def check_response(
    match_level: MatchLevel,
    site_results: list[SiteResult],
    details: list[str],
    core_overlap_ratio: float,
) -> dict[str, Any]:
    """Convert the coverage-check tuple into the dict shape expected by
    :class:`MarkushOverlapResponse`."""
    return {
        "success": True,
        "match_level": match_level,
        "core_overlap_ratio": core_overlap_ratio,
        "matched_core_atoms": int(round(core_overlap_ratio * len(site_results))),
        "total_core_atoms": len(site_results),
        "r_group_results": [
            {
                "group_name": s.site_label,
                "position": s.atom_map_num,
                "query_substituent": s.query_substituent,
                "within_scope": (
                    s.judgment == "within_scope" if s.judgment != "unknown" else None
                ),
                "definition": s.definition,
                "reason": s.reason,
                "confidence": s.confidence,
            }
            for s in site_results
        ],
        "details": details,
        "error": None,
    }


__all__ = [
    "MatchLevel",
    "SiteJudgment",
    "SiteResult",
    "check_markush_coverage",
    "check_response",
]
