"""Tests for molecule_corrector context-based validation rules."""

from __future__ import annotations

from mbforge.domain.molecule import Molecule
from mbforge.service.pipeline.detection.correction import (
    check_markush_consistency,
    correct_molecules_with_context,
    correct_rgroup_misread,
    verify_element_consistency,
    verify_name_substructure,
)


def _make_molecule(
    smiles: str,
    name: str = "",
    status: str = "pending",
    properties: dict | None = None,
) -> Molecule:
    """Build a minimal shared Molecule for testing."""
    return Molecule(
        canonical_smiles=smiles,
        esmiles=smiles,
        name=name,
        status=status,
        properties=properties or {},
    )


def test_rgroup_misread_flags_closed_smiles_and_ignores_valid_contexts() -> None:
    """A closed structure in an R-group/formula context is flagged for review."""
    mol = _make_molecule(
        "c1ccccc1",
        name="Compound 1",
        properties={"role_contexts": ["wherein R1 is methyl"]},
    )
    assert correct_rgroup_misread(mol) is True
    assert mol.status == "pending_review"
    assert mol.properties["correction_reason"] == "rgroup_context_mismatch"
    assert len(mol.properties["corrections"]) == 1
    assert mol.properties["corrections"][0]["rule"] == "correct_rgroup_misread"

    labelled = _make_molecule(
        "c1ccccc1",
        name="Formula I",
        properties={"label_kind": "formula"},
    )
    assert correct_rgroup_misread(labelled) is True
    assert labelled.status == "pending_review"

    # A dummy atom means the structure may legitimately be a formula.
    dummy = _make_molecule(
        "c1ccccc1*",
        name="Formula I",
        properties={"label_kind": "formula", "role_contexts": ["R1 is methyl"]},
    )
    assert correct_rgroup_misread(dummy) is False
    assert dummy.status == "pending"

    # No R-group/formula context, and rejected molecules, are left alone.
    plain = _make_molecule("c1ccccc1", name="Benzene")
    assert correct_rgroup_misread(plain) is False
    assert plain.status == "pending"

    rejected = _make_molecule(
        "c1ccccc1",
        status="rejected",
        properties={"role_contexts": ["R1 is methyl"]},
    )
    assert correct_rgroup_misread(rejected) is False
    assert rejected.status == "rejected"


def test_element_consistency_flags_elements_missing_from_the_structure() -> None:
    """An element the surrounding prose names but the structure lacks is flagged."""
    fluorine = _make_molecule(
        "c1ccccc1",
        name="Compound 1",
        properties={"context_texts": ["含氟化合物具有活性"]},
    )
    assert verify_element_consistency(fluorine) is True
    assert "suspicious_elements" in fluorine.properties
    assert "F" in fluorine.properties["suspicious_elements"]
    assert len(fluorine.properties["review_flags"]) >= 1

    chlorine = _make_molecule(
        "c1ccccc1",
        name="Compound 1",
        properties={"context_texts": ["chloro derivative"]},
    )
    assert verify_element_consistency(chlorine) is True
    assert "Cl" in chlorine.properties["suspicious_elements"]

    # Element present, no context at all, or an unparsable SMILES: no flag.
    present = _make_molecule(
        "Fc1ccccc1",
        name="Fluorobenzene",
        properties={"context_texts": ["含氟化合物"]},
    )
    assert verify_element_consistency(present) is False
    assert "suspicious_elements" not in present.properties

    assert (
        verify_element_consistency(_make_molecule("c1ccccc1", name="Benzene")) is False
    )
    assert (
        verify_element_consistency(
            _make_molecule("not_a_smiles", properties={"context_texts": ["含氟化合物"]})
        )
        is False
    )


def test_markush_consistency_flags_label_dummy_mismatches() -> None:
    """A formula label without a dummy (or a dummy without the label) is flagged."""
    formula = _make_molecule("c1ccccc1", properties={"label_kind": "formula"})
    assert check_markush_consistency(formula) is True
    assert "formula_without_dummy" in [
        flag["flag"] for flag in formula.properties["review_flags"]
    ]

    dummy = _make_molecule("c1ccccc1*", properties={"label_kind": "compound"})
    assert check_markush_consistency(dummy) is True
    assert "dummy_without_formula_label" in [
        flag["flag"] for flag in dummy.properties["review_flags"]
    ]

    # Consistent combinations stay clean.
    assert (
        check_markush_consistency(
            _make_molecule("c1ccccc1*", properties={"label_kind": "formula"})
        )
        is False
    )
    assert (
        check_markush_consistency(
            _make_molecule("c1ccccc1", properties={"label_kind": "compound"})
        )
        is False
    )


def test_name_substructure_flags_mismatched_names() -> None:
    """A chemical name whose substructure is absent from the SMILES is flagged."""
    aniline = _make_molecule("c1ccccc1", name="苯胺衍生物")
    assert verify_name_substructure(aniline) is True
    assert "name_substructure_mismatch" in [
        flag["flag"] for flag in aniline.properties["review_flags"]
    ]

    pyridine = _make_molecule("c1ccccc1", name="pyridine compound")
    assert verify_name_substructure(pyridine) is True

    detection = _make_molecule(
        "c1ccccc1",
        name="",
        properties={"detection_names": ["thiophene derivative"]},
    )
    assert verify_name_substructure(detection) is True

    # Matching name, or no name to verify against.
    assert (
        verify_name_substructure(_make_molecule("Nc1ccccc1", name="aniline")) is False
    )
    assert verify_name_substructure(_make_molecule("c1ccccc1", name="")) is False


def test_correct_molecules_with_context_applies_all_rules() -> None:
    """One pass applies every rule; clean molecules are left untouched."""
    mols = [
        _make_molecule(
            "c1ccccc1",
            name="Formula I",
            properties={
                "label_kind": "formula",
                "role_contexts": ["R1 is methyl"],
                "context_texts": ["含氟化合物"],
            },
        ),
        _make_molecule("c1ccccc1", name="Benzene"),
    ]
    result = correct_molecules_with_context(mols)
    assert len(result) == 2
    # First molecule should be flagged by multiple rules
    assert result[0].status == "pending_review"
    assert "corrections" in result[0].properties
    assert "review_flags" in result[0].properties
    # Second molecule should be untouched
    assert result[1].status == "pending"
    assert "corrections" not in result[1].properties

    assert correct_molecules_with_context([]) == []
