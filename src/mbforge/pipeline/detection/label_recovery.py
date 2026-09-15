"""MS-guided recovery of compound labels for unlabeled structures.

Scanned patents frequently leave a final compound's figure without an
OCR-readable label, so the molecule is persisted with a placeholder name
and its activity row never matches. The preparation text nearby states
the product's identity unambiguously — "得白色固体化合物11（7 mg，收率33%）
… MS m/z 492.0 [M+H]+" — and the exact mass is a strong, independent
structure fingerprint.

This module re-attaches a label to a placeholder-named candidate only
when four independent signals agree and the assignment is globally
conflict-free:

1. the candidate is classified ``complete`` and contains the document's
   family core (so it is a final-family structure, not a reagent);
2. the exact mass of its largest fragment matches the label's
   ``MS m/z`` entry (monoisotopic, ±0.6 Da);
3. the candidate's page is within ±1 of the MS paragraph's page;
4. after preferring exact-page pairings, the label claims exactly one
   candidate and the candidate claims exactly one label.

Rejected candidates (never persisted) and duplicate entries for one
structure are excluded from the pairing pool so they cannot poison the
uniqueness check.

Labels already carried by a persisted final-compound (``complete``
role) candidate are never reassigned — those conflicts stay in the
review queue where a human can see both sides. A label carried only by
a rejected recognition, or pinned on a Markush scaffold/fragment, counts
as unclaimed: neither can carry the compound's activity downstream.
"""

from __future__ import annotations

import re
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Any

from mbforge.pipeline.markdown.markers import _PAGE_MARKER_RE
from mbforge.utils.logger import get_logger

logger = get_logger(__name__)

_PROTON = 1.0073
_MS_WINDOW = 1500
_MASS_TOL = 0.6
_PAGE_WINDOW = 1

_COMPOUND_RE = re.compile(r"化合物(\d{1,2})[：:（(]")
_MZ_RE = re.compile(r"MS m/z[^0-9]*([\d.]+)")


@dataclass(frozen=True)
class LabelRecovery:
    """One MS-guided label assignment applied to a candidate."""

    candidate_key: str
    label: str
    mz: float
    page: int | None


def _page_positions(md_text: str) -> list[tuple[int, int]]:
    return [(m.start(), int(m.group(1))) for m in _PAGE_MARKER_RE.finditer(md_text)]


def _page_at(positions: list[tuple[int, int]], pos: int) -> int | None:
    page = None
    for start, number in positions:
        if start <= pos:
            page = number
        else:
            break
    return page


def _parse_ms_entries(md_text: str) -> dict[str, list[tuple[float, int | None]]]:
    """Map compound label → [(m/z, page)] from preparation paragraphs."""
    positions = _page_positions(md_text)
    entries: dict[str, list[tuple[float, int | None]]] = {}
    for match in _COMPOUND_RE.finditer(md_text):
        segment = md_text[match.start() : match.start() + _MS_WINDOW]
        mz_match = _MZ_RE.search(segment)
        if mz_match is None:
            continue
        entries.setdefault(match.group(1), []).append(
            (float(mz_match.group(1)), _page_at(positions, match.start()))
        )
    return entries


def _is_placeholder_name(name: str) -> bool:
    normalized = (name or "").strip().lower()
    return (
        not normalized
        or normalized.startswith("mol_")
        or normalized.startswith("![](")
        or normalized.startswith("<div")
        or "<img" in normalized
    )


def _largest_fragment_mol(smiles: str) -> Any | None:
    from rdkit import Chem

    try:
        mol = Chem.MolFromSmiles(smiles)
    except Exception:  # noqa: BLE001 — RDKit raises bare exceptions
        return None
    if mol is None:
        return None
    frags = Chem.GetMolFrags(mol, asMols=True)
    if not frags:
        return None
    return max(frags, key=lambda frag: frag.GetNumHeavyAtoms())


def _exact_mass(smiles: str) -> float | None:
    """Monoisotopic mass of the largest fragment (salt-stripped)."""
    from rdkit.Chem import rdMolDescriptors

    main = _largest_fragment_mol(smiles)
    if main is None:
        return None
    try:
        return float(rdMolDescriptors.CalcExactMolWt(main))
    except Exception:  # noqa: BLE001
        return None


def _candidate_page_number(candidate: Any) -> int | None:
    detections = getattr(candidate, "detections", None)
    if not detections:
        return None
    page = getattr(detections[0], "page", None)
    if not isinstance(page, int) or isinstance(page, bool):
        return None
    return page + 1


def recover_labels_from_ms(
    md_text: str,
    candidates: Sequence[Any],
    core_smarts: str | None,
) -> list[LabelRecovery]:
    """Assign missing compound labels from MS evidence, in place.

    Mutates ``candidate.name`` and records provenance in
    ``candidate.properties['label_source'] = 'ms_context'`` for each
    assignment. Returns the applied assignments (empty when the family
    core is unavailable — mass and page alone are too weak a signal).
    """
    if not core_smarts:
        return []
    from rdkit import Chem

    core = Chem.MolFromSmarts(core_smarts)
    if core is None:
        return []

    ms_entries = _parse_ms_entries(md_text)
    if not ms_entries:
        return []

    claimed_labels: set[str] = set()
    eligible: list[tuple[Any, str, float, int | None]] = []
    seen_keys: set[str] = set()
    claimants: dict[str, str] = {}
    for candidate in candidates:
        name = (getattr(candidate, "name", "") or "").strip()
        if not _is_placeholder_name(name):
            # Only a persisted (non-rejected) final-compound candidate's
            # name claim counts: a rejected recognition never reaches the
            # database, and a numeric label pinned on a Markush scaffold
            # or fragment is an OCR misassignment — Markush structures
            # live in their own formula-label namespace and can never
            # pass the MS mass check themselves.
            if getattr(candidate, "status", None) != "rejected":
                c_props = getattr(candidate, "properties", None)
                c_role = (
                    c_props.get("structure_role") if isinstance(c_props, dict) else None
                )
                if c_role == "complete":
                    claimed_labels.add(name)
                    if name not in claimants:
                        c_smiles = (
                            getattr(candidate, "canonical_smiles", "")
                            or getattr(candidate, "esmiles", "")
                            or ""
                        )
                        claimants[name] = (
                            f"status={getattr(candidate, 'status', None)} "
                            f"role={c_role} smiles={c_smiles[:60]}"
                        )
            continue
        # Rejected candidates are never persisted; they must neither
        # receive a label nor poison the uniqueness check. Duplicate
        # entries for one structure (same canonical SMILES) count once.
        if getattr(candidate, "status", None) == "rejected":
            continue
        properties = getattr(candidate, "properties", None)
        if not isinstance(properties, dict):
            continue
        if properties.get("structure_role") != "complete":
            continue
        smiles = (
            getattr(candidate, "canonical_smiles", "")
            or getattr(candidate, "esmiles", "")
            or ""
        )
        if smiles in seen_keys:
            continue
        seen_keys.add(smiles)
        main = _largest_fragment_mol(smiles)
        if main is None or not main.HasSubstructMatch(core):
            continue
        mass = _exact_mass(smiles)
        if mass is None:
            continue
        candidate_key = smiles
        eligible.append(
            (candidate, candidate_key, mass, _candidate_page_number(candidate))
        )

    # Score every (label, candidate) pair: 0 for an exact page match,
    # 1 for a neighbouring page. Pairs with no page affinity are dropped.
    pairs: list[tuple[int, int, str, Any, str, float, int | None]] = []
    for label, entries in ms_entries.items():
        if label in claimed_labels:
            logger.info(
                "MS recovery: label %r skipped — already carried by a named "
                "candidate (%s)",
                label,
                claimants.get(label, "?"),
            )
            continue
        for candidate, candidate_key, mass, page in eligible:
            best_score: int | None = None
            best_mz = 0.0
            best_page: int | None = None
            for mz, ms_page in entries:
                if abs(mass + _PROTON - mz) > _MASS_TOL:
                    continue
                if page is not None and ms_page is not None:
                    distance = abs(page - ms_page)
                    if distance > _PAGE_WINDOW:
                        continue
                    score = distance
                else:
                    score = _PAGE_WINDOW  # unknown page: weakest claim
                if best_score is None or score < best_score:
                    best_score = score
                    best_mz = mz
                    best_page = page
            if best_score is not None:
                pairs.append(
                    (
                        best_score,
                        int(label),
                        label,
                        candidate,
                        candidate_key,
                        best_mz,
                        best_page,
                    )
                )

    # Keep only each label's and each candidate's best-scoring pairings.
    # Ties — two candidates equally good for one label, or two labels
    # equally good for one candidate — are ambiguous and drop the whole
    # label/candidate rather than guessing.
    best_by_label: dict[str, int] = {}
    best_by_candidate: dict[int, int] = {}
    for score, _label_int, label, candidate, _key, _mz, _page in pairs:
        best_by_label[label] = min(score, best_by_label.get(label, 99))
        best_by_candidate[id(candidate)] = min(
            score, best_by_candidate.get(id(candidate), 99)
        )
    label_best_cands: dict[str, set[int]] = {}
    cand_best_labels: dict[int, set[str]] = {}
    for score, _label_int, label, candidate, _key, _mz, _page in pairs:
        if score == best_by_label[label]:
            label_best_cands.setdefault(label, set()).add(id(candidate))
        if score == best_by_candidate[id(candidate)]:
            cand_best_labels.setdefault(id(candidate), set()).add(label)
    key_by_id = {id(pair[3]): pair[4] for pair in pairs}
    pairs = [
        pair
        for pair in pairs
        if pair[0] == best_by_label[pair[2]] == best_by_candidate[id(pair[3])]
        and len(label_best_cands[pair[2]]) == 1
        and len(cand_best_labels[id(pair[3])]) == 1
    ]
    surviving_labels = {pair[2] for pair in pairs}
    for label, entries in ms_entries.items():
        if label in claimed_labels or label in surviving_labels:
            continue
        tied = label_best_cands.get(label, set())
        if len(tied) > 1:
            logger.info(
                "MS recovery: label %r dropped — %d equally good candidates: %s",
                label,
                len(tied),
                sorted(key_by_id.get(cid, "?")[:60] for cid in tied),
            )
        elif len(tied) == 1:
            contest = cand_best_labels.get(next(iter(tied)), set())
            logger.info(
                "MS recovery: label %r dropped — its only candidate is contested "
                "by labels %s",
                label,
                sorted(contest),
            )
        else:
            logger.info(
                "MS recovery: label %r found no mass/page-matching candidate "
                "(mz entries: %s)",
                label,
                entries,
            )

    # Greedy conflict-free assignment: exact-page pairings first, then
    # by label; a taken label or candidate blocks all later pairings.
    pairs.sort(key=lambda pair: (pair[0], pair[1]))
    used_labels: set[str] = set()
    used_candidates: set[int] = set()
    recoveries: list[LabelRecovery] = []
    for _score, _label_int, label, candidate, candidate_key, mz, page in pairs:
        if label in used_labels or id(candidate) in used_candidates:
            continue
        used_labels.add(label)
        used_candidates.add(id(candidate))
        candidate.name = label
        properties = getattr(candidate, "properties", None)
        if isinstance(properties, dict):
            properties["label_source"] = "ms_context"
            properties["ms_mz"] = mz
        recoveries.append(
            LabelRecovery(candidate_key=candidate_key, label=label, mz=mz, page=page)
        )
        logger.info(
            "Recovered label %r for placeholder molecule via MS m/z %.1f on page %s",
            label,
            mz,
            page,
        )
    return recoveries
