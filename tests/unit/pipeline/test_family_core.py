"""Tests for the family-core activity gate.

A row-label activity match asserts "this structure is final compound N".
Scanned patents occasionally pin a label on a neighbouring reagent or
intermediate figure; the family-core gate withholds activity matching from
any candidate that does not contain the document's own Markush core.

SMILES fixtures are taken from the WO2026037254A1 case that motivated the
gate: the reagent labelled '17', the des-CF3 enone labelled '4', and the
Boc-protected intermediate labelled '21' are all real misassignments.
"""

from __future__ import annotations

from unittest.mock import MagicMock

from mbforge.pipeline.activity.extraction import ActivityRecord
from mbforge.pipeline.activity.family_gate import (
    FAMILY_CORE_MISMATCH,
    derive_family_core,
    make_family_core_guard,
)
from mbforge.pipeline.activity.matching import match_activities

# Real Markush scaffolds recognised from the document (pages 5/9/10).
SCAFFOLD_1 = (
    "*CC1(C*)CC(NC(=O)c2c([8*])nn([9*])c2[7*])CC(Nc2cc(C(F)(F)F)nc3ccc(Cl)cc23)C1"
)
SCAFFOLD_2 = "*/C=C1\\C=C(Nc2cc(C(F)(F)F)nc3ccc(Cl)cc23)CC(NC(=O)c2cnn(C)c2)C1"
SCAFFOLD_3 = "*c1ccc2nc(C(F)(F)F)cc(N[C@H]3C/C(=C/COC)C[C@@H](NC(=O)c4cnn(C)c4)C3)c2c1"

# A genuine family member (compound 10's recognised structure).
FAMILY_MEMBER = "Cn1cc(C(=O)N[C@@H]2CC(=O)C[C@H](Nc3cc(C(F)(F)F)nc4ccc(Cl)cc34)C2)cn1"
# Misassigned structures: a sulfonyl-tetrazole reagent, a des-CF3 enone
# intermediate, and a Boc-protected amino-cyclohexanol intermediate.
REAGENT = "CCS(=O)(=O)c1nnnn1-c1ccccc1"
ENONE_NO_CF3 = "Cn1cc(C(=O)NC2CC(=O)C=C(Nc3ccnc4ccc(Cl)cc34)C2)cn1"
BOC_INTERMEDIATE = (
    "CC.CC(C)(C)OC(=O)N[C@@H]1C[C@@H](O)C[C@H](Nc2cc(C(F)(F)F)nc3ccc(Cl)cc23)C1.P"
)


def _candidate(smiles: str, role: str = "complete", name: str = "") -> MagicMock:
    cand = MagicMock()
    cand.status = "pending"
    cand.canonical_smiles = smiles
    cand.esmiles = smiles
    cand.name = name
    cand.properties = {"structure_role": role}
    cand.detections = [
        MagicMock(
            bbox=(0, 0, 1, 1),
            page=0,
            image_path="/tmp/c.png",
            confidence=0.9,
            conf_moldet=0.9,
        )
    ]
    return cand


def _record(row_label: str, row_idx: int = 1) -> ActivityRecord:
    return ActivityRecord(
        activity_type="IC50",
        value=12.5,
        value_original=12.5,
        unit="nM",
        operator="<",
        target="MRGPRX2",
        assay_type="cellular",
        raw_text=f"| {row_label} | <12.5 |",
        confidence=0.9,
        page_num=1,
        evidence_kind="table",
        evidence_bbox=None,
        table_idx=0,
        row_idx=row_idx,
        col_idx=1,
        row_label=row_label,
        row_smiles=None,
    )


def _scaffold_candidates() -> list[MagicMock]:
    return [
        _candidate(smiles, role="scaffold")
        for smiles in (SCAFFOLD_1, SCAFFOLD_2, SCAFFOLD_3)
    ]


def test_derive_family_core_from_scaffolds() -> None:
    core = derive_family_core(_scaffold_candidates())
    assert core is not None
    from rdkit import Chem

    core_mol = Chem.MolFromSmarts(core)
    assert core_mol is not None
    # The shared pharmacophore (quinoline + aminocyclohexyl + carboxamide)
    # is far above the minimum-size floor.
    assert core_mol.GetNumHeavyAtoms() >= 20


def test_derive_family_core_disabled_without_scaffolds() -> None:
    assert derive_family_core([_candidate("CCO")]) is None
    assert derive_family_core([]) is None
    assert make_family_core_guard(None) is None


def test_guard_passes_family_member() -> None:
    guard = make_family_core_guard(derive_family_core(_scaffold_candidates()))
    assert guard is not None
    assert guard(_candidate(FAMILY_MEMBER, name="10")) is None


def test_guard_vetoes_reagent_enone_and_intermediate() -> None:
    guard = make_family_core_guard(derive_family_core(_scaffold_candidates()))
    assert guard is not None
    assert guard(_candidate(REAGENT, name="17")) == FAMILY_CORE_MISMATCH
    assert guard(_candidate(ENONE_NO_CF3, name="4")) == FAMILY_CORE_MISMATCH
    assert guard(_candidate(BOC_INTERMEDIATE, name="21")) == FAMILY_CORE_MISMATCH


def test_guard_never_vetoes_unparseable_smiles() -> None:
    guard = make_family_core_guard(derive_family_core(_scaffold_candidates()))
    assert guard is not None
    assert guard(_candidate("not-a-smiles", name="1")) is None
    assert guard(_candidate("", name="1")) is None


def test_match_activities_guard_vetoes_label_match() -> None:
    """A vetoed candidate neither matches its row label nor the fallback."""
    guard = make_family_core_guard(derive_family_core(_scaffold_candidates()))
    reagent = _candidate(REAGENT, name="17")
    record = _record("17")

    vetoes: list = []
    matches = match_activities(
        [reagent], [record], candidate_guard=guard, vetoes=vetoes
    )
    assert matches == []
    assert len(vetoes) == 1
    assert vetoes[0].name == "17"
    assert vetoes[0].reason == FAMILY_CORE_MISMATCH


def test_match_activities_guard_keeps_clean_candidate() -> None:
    guard = make_family_core_guard(derive_family_core(_scaffold_candidates()))
    member = _candidate(FAMILY_MEMBER, name="10")
    record = _record("10")

    vetoes: list = []
    matches = match_activities([member], [record], candidate_guard=guard, vetoes=vetoes)
    assert len(matches) == 1
    assert matches[0].kind == "table_row"
    assert vetoes == []


def test_match_activities_uses_explicit_coref_label_metadata() -> None:
    """An image placeholder must not hide a label preserved by coreference."""
    guard = make_family_core_guard(derive_family_core(_scaffold_candidates()))
    member = _candidate(FAMILY_MEMBER, name="![](images/structure.jpg)")
    member.properties["normalized_label"] = "10"

    matches = match_activities([member], [_record("10")], candidate_guard=guard)

    assert len(matches) == 1
    assert matches[0].kind == "table_row"


def test_match_activities_uses_unique_context_label() -> None:
    member = _candidate(FAMILY_MEMBER, name="![](images/structure.jpg)")
    member.properties["explicit_context_labels"] = ["10"]

    matches = match_activities([member], [_record("10")])

    assert len(matches) == 1
    assert matches[0].kind == "table_row"


def test_match_activities_without_guard_unchanged() -> None:
    """Back-compat: with no guard the reagent still matches its label."""
    reagent = _candidate(REAGENT, name="17")
    matches = match_activities([reagent], [_record("17")])
    assert len(matches) == 1
    assert matches[0].kind == "table_row"
