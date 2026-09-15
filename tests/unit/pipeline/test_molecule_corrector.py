"""Tests for molecule_corrector context-based validation rules."""

from __future__ import annotations

from mbforge.core.molecule import Molecule
from mbforge.pipeline.detection.correction import (
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


class TestCorrectRgroupMisread:
    """Tests for the R-group misread correction rule."""

    def test_flags_closed_smiles_with_rgroup_context(self):
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

    def test_flags_closed_smiles_with_formula_label(self):
        mol = _make_molecule(
            "c1ccccc1",
            name="Formula I",
            properties={"label_kind": "formula"},
        )
        assert correct_rgroup_misread(mol) is True
        assert mol.status == "pending_review"

    def test_ignores_smiles_with_dummy_atoms(self):
        mol = _make_molecule(
            "c1ccccc1*",
            name="Formula I",
            properties={"label_kind": "formula", "role_contexts": ["R1 is methyl"]},
        )
        assert correct_rgroup_misread(mol) is False
        assert mol.status == "pending"

    def test_ignores_no_context(self):
        mol = _make_molecule("c1ccccc1", name="Benzene")
        assert correct_rgroup_misread(mol) is False
        assert mol.status == "pending"

    def test_ignores_rejected_molecules(self):
        mol = _make_molecule(
            "c1ccccc1",
            status="rejected",
            properties={"role_contexts": ["R1 is methyl"]},
        )
        assert correct_rgroup_misread(mol) is False
        assert mol.status == "rejected"


class TestVerifyElementConsistency:
    """Tests for element consistency verification."""

    def test_flags_missing_fluorine(self):
        mol = _make_molecule(
            "c1ccccc1",
            name="Compound 1",
            properties={"context_texts": ["含氟化合物具有活性"]},
        )
        assert verify_element_consistency(mol) is True
        assert "suspicious_elements" in mol.properties
        assert "F" in mol.properties["suspicious_elements"]
        assert len(mol.properties["review_flags"]) >= 1

    def test_flags_missing_chlorine(self):
        mol = _make_molecule(
            "c1ccccc1",
            name="Compound 1",
            properties={"context_texts": ["chloro derivative"]},
        )
        assert verify_element_consistency(mol) is True
        assert "Cl" in mol.properties["suspicious_elements"]

    def test_ignores_present_element(self):
        mol = _make_molecule(
            "Fc1ccccc1",
            name="Fluorobenzene",
            properties={"context_texts": ["含氟化合物"]},
        )
        assert verify_element_consistency(mol) is False
        assert "suspicious_elements" not in mol.properties

    def test_ignores_no_context(self):
        mol = _make_molecule("c1ccccc1", name="Benzene")
        assert verify_element_consistency(mol) is False

    def test_ignores_invalid_smiles(self):
        mol = _make_molecule(
            "not_a_smiles",
            properties={"context_texts": ["含氟化合物"]},
        )
        assert verify_element_consistency(mol) is False


class TestCheckMarkushConsistency:
    """Tests for Markush consistency checking."""

    def test_flags_formula_without_dummy(self):
        mol = _make_molecule(
            "c1ccccc1",
            properties={"label_kind": "formula"},
        )
        assert check_markush_consistency(mol) is True
        flags = [f["flag"] for f in mol.properties["review_flags"]]
        assert "formula_without_dummy" in flags

    def test_flags_dummy_without_formula_label(self):
        mol = _make_molecule(
            "c1ccccc1*",
            properties={"label_kind": "compound"},
        )
        assert check_markush_consistency(mol) is True
        flags = [f["flag"] for f in mol.properties["review_flags"]]
        assert "dummy_without_formula_label" in flags

    def test_ignores_consistent_formula(self):
        mol = _make_molecule(
            "c1ccccc1*",
            properties={"label_kind": "formula"},
        )
        assert check_markush_consistency(mol) is False

    def test_ignores_consistent_compound(self):
        mol = _make_molecule(
            "c1ccccc1",
            properties={"label_kind": "compound"},
        )
        assert check_markush_consistency(mol) is False


class TestVerifyNameSubstructure:
    """Tests for chemical name substructure verification."""

    def test_flags_aniline_mismatch(self):
        mol = _make_molecule(
            "c1ccccc1",
            name="苯胺衍生物",
        )
        assert verify_name_substructure(mol) is True
        flags = [f["flag"] for f in mol.properties["review_flags"]]
        assert "name_substructure_mismatch" in flags

    def test_flags_pyridine_mismatch(self):
        mol = _make_molecule(
            "c1ccccc1",
            name="pyridine compound",
        )
        assert verify_name_substructure(mol) is True

    def test_ignores_matching_aniline(self):
        mol = _make_molecule(
            "Nc1ccccc1",
            name="aniline",
        )
        assert verify_name_substructure(mol) is False

    def test_ignores_no_name(self):
        mol = _make_molecule("c1ccccc1", name="")
        assert verify_name_substructure(mol) is False

    def test_checks_detection_names(self):
        mol = _make_molecule(
            "c1ccccc1",
            name="",
            properties={"detection_names": ["thiophene derivative"]},
        )
        assert verify_name_substructure(mol) is True


class TestCorrectMoleculesWithContext:
    """Tests for the main correction entry point."""

    def test_applies_all_rules(self):
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

    def test_empty_list(self):
        assert correct_molecules_with_context([]) == []
