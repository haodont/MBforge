"""Molecule detection and SMILES prediction evaluator (golden-agnostic)."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any

from rdkit import Chem

from .activity import by_label


@dataclass(frozen=True)
class MoleculeMetrics:
    """Numeric metrics emitted by the molecule evaluator."""

    presence_recall: float
    label_recall: float
    role_accuracy: float
    smiles_match_rate: float
    smiles_predicted: int
    smiles_annotated: int
    matched: int
    unmatched_golden: int
    unmatched_candidate: int

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


def _canonical(smiles: str) -> str | None:
    """Return RDKit canonical SMILES, or ``None`` if unparseable."""
    if not smiles:
        return None
    mol = Chem.MolFromSmiles(smiles)
    if mol is None:
        return None
    return Chem.MolToSmiles(mol)


def _role_matches(golden: dict[str, Any], candidate_role: Any) -> bool:
    """Map runtime roles to the supervised concrete/review contract."""
    if golden.get("expected_review_required") is True:
        return candidate_role == "review_required"

    expected = golden.get("molecule_role") or golden.get("role")
    if expected == "concrete":
        return candidate_role in {"concrete", "concrete_structure_image", "complete"}
    return expected == candidate_role


def score_molecules(
    golden_rows: list[dict[str, Any]],
    candidate: dict[str, Any],
) -> MoleculeMetrics:
    """Score molecule detection / SMILES predictions against the golden."""
    gold_by_label = by_label(golden_rows)
    cand_by_label = by_label(candidate.get("molecules", []))

    common = sorted(set(gold_by_label) & set(cand_by_label))
    gold_only = sorted(set(gold_by_label) - set(cand_by_label))
    cand_only = sorted(set(cand_by_label) - set(gold_by_label))

    label_recall = len(common) / max(len(gold_by_label), 1)

    if not common:
        return MoleculeMetrics(
            presence_recall=0.0,
            label_recall=label_recall,
            role_accuracy=0.0,
            smiles_match_rate=0.0,
            smiles_predicted=0,
            smiles_annotated=0,
            matched=0,
            unmatched_golden=len(gold_only),
            unmatched_candidate=len(cand_only),
        )

    presence_hits = role_hits = smile_matches = 0
    smiles_predicted = smiles_annotated = 0
    for label in common:
        gold = gold_by_label[label]
        cand = cand_by_label[label]
        if cand.get("structure_image_present") is True:
            presence_hits += 1
        if _role_matches(gold, cand.get("molecule_role")):
            role_hits += 1

        gold_smiles = gold.get("smiles_canonical")
        cand_smiles = cand.get("smiles_canonical")
        if gold_smiles:
            smiles_annotated += 1
            if cand_smiles:
                smiles_predicted += 1
                if _canonical(gold_smiles) == _canonical(cand_smiles):
                    smile_matches += 1

    n = len(common)
    smiles_match_rate = smile_matches / smiles_annotated if smiles_annotated else 0.0
    return MoleculeMetrics(
        presence_recall=presence_hits / n,
        label_recall=label_recall,
        role_accuracy=role_hits / n,
        smiles_match_rate=smiles_match_rate,
        smiles_predicted=smiles_predicted,
        smiles_annotated=smiles_annotated,
        matched=n,
        unmatched_golden=len(gold_only),
        unmatched_candidate=len(cand_only),
    )
