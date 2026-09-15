"""Tests for deterministic complete/scaffold/fragment classification."""

from __future__ import annotations

import pytest

from mbforge.core.molecule import Molecule
from mbforge.pipeline.detection.structure_role import classify_structure_role


def _molecule(
    smiles: str,
    *,
    name: str = "",
    properties: dict[str, object] | None = None,
    status: str = "pending",
) -> Molecule:
    return Molecule(
        canonical_smiles=smiles,
        esmiles=smiles,
        name=name,
        status=status,  # type: ignore[arg-type]
        properties=properties or {},
    )


@pytest.mark.parametrize("smiles", ["CCO", "c1ccccc1OC"])
def test_classify_complete_without_dummy_atoms(smiles: str) -> None:
    molecule = _molecule(smiles)
    assert classify_structure_role(molecule) == "complete"
    assert molecule.properties["structure_role"] == "complete"


def test_classify_small_single_attachment_as_fragment() -> None:
    assert classify_structure_role(_molecule("*c1cscn1")) == "fragment"


def test_classify_extended_single_attachment_as_fragment() -> None:
    assert classify_structure_role(_molecule("*" + "C" * 23)) == "fragment"


@pytest.mark.parametrize("smiles", ["*c1ccc(*)cc1" + "C" * 13, "*" + "C" * 30 + "*"])
def test_classify_large_multi_attachment_as_scaffold(smiles: str) -> None:
    assert classify_structure_role(_molecule(smiles)) == "scaffold"


def test_classify_rejected_candidate_does_not_change_status() -> None:
    molecule = _molecule("bogus", status="rejected")
    assert classify_structure_role(molecule) == "rejected"
    assert molecule.status == "rejected"
    assert "structure_role" not in molecule.properties


@pytest.mark.parametrize("smiles", ["@@@", ""])
def test_classify_invalid_smiles_requires_review(smiles: str) -> None:
    molecule = _molecule(smiles)
    assert classify_structure_role(molecule) == "review_required"
    assert molecule.properties["structure_role_reasons"] == [
        "invalid_or_empty_structure"
    ]


@pytest.mark.parametrize(
    "context",
    [
        "Formula I compounds are optionally substituted at R1.",
        "Formula (I) 化合物在 R1 位任选取代。",
        "general structure with R2 and R3 groups",
    ],
)
def test_closed_smiles_with_markush_context_requires_review(context: str) -> None:
    molecule = _molecule("CCO")
    molecule.properties["context_texts"] = [context]

    assert classify_structure_role(molecule) == "review_required"
    assert molecule.properties["structure_role_reasons"]


def test_concrete_closed_smiles_without_markush_context_remains_complete() -> None:
    molecule = _molecule("CCO")
    molecule.properties["context_texts"] = ["Example 12 was tested by LC-MS."]

    assert classify_structure_role(molecule) == "complete"


def test_explicit_markush_without_dummy_requires_review() -> None:
    """Markush metadata must not be silently classified as a complete molecule."""
    molecule = _molecule("CCO", properties={"markush": True, "groups": "R1=alkyl"})

    assert classify_structure_role(molecule) == "review_required"
    assert molecule.properties["structure_role_reasons"] == ["markush_without_dummy"]


@pytest.mark.parametrize("label", ["1a", "21-e", "4A-1"])
def test_synthesis_step_labels_require_review(label: str) -> None:
    molecule = _molecule(
        "CCO",
        name=label,
        properties={"context_texts": [f"Intermediate {label}"]},
    )

    assert classify_structure_role(molecule) == "review_required"
    assert (
        "context_synthetic_intermediate_label"
        in molecule.properties["structure_role_reasons"]
    )


def test_synthesis_step_label_alone_is_not_review_required() -> None:
    """A bare step-like label falls through to the final-label path on a
    general corpus; corroborating intermediate context is required."""
    molecule = _molecule("CCO", name="1a")

    assert classify_structure_role(molecule) == "complete"


@pytest.mark.parametrize(
    "context",
    [
        "Intermediate 1a",
        "中间体 1a",
        "synthesis step 1a",
    ],
)
def test_synthesis_step_label_with_intermediate_context_requires_review(
    context: str,
) -> None:
    molecule = _molecule("CCO", name="1a")
    molecule.properties["context_texts"] = [context]

    assert classify_structure_role(molecule) == "review_required"
    assert (
        "context_synthetic_intermediate_label"
        in molecule.properties["structure_role_reasons"]
    )


@pytest.mark.parametrize("label", ["3A", "3B", "4A", "4B", "28"])
def test_final_compound_labels_are_not_intermediates_by_themselves(label: str) -> None:
    assert classify_structure_role(_molecule("CCO", name=label)) == "complete"


@pytest.mark.parametrize(
    "context, reason",
    [
        ("化合物3为1S,3R与1R,3S的混合物，可经SFC拆分", "context_mixture_or_isomer"),
        ("化合物28的双键构型Z/E暂不确定", "context_stereochemistry_uncertain"),
        ("化合物4A为拆分产物，构型暂定", "context_mixture_or_isomer"),
        ("compound 28 configuration is tentative", "context_stereochemistry_uncertain"),
        ("the stereochemistry is tentative", "context_stereochemistry_uncertain"),
    ],
)
def test_ambiguous_closed_structures_require_review(context: str, reason: str) -> None:
    molecule = _molecule("CCO", name="3", properties={"context_texts": [context]})

    assert classify_structure_role(molecule) == "review_required"
    assert reason in molecule.properties["structure_role_reasons"]


def test_normalized_intermediate_label_is_used_when_name_is_missing() -> None:
    molecule = _molecule(
        "CCO",
        properties={
            "normalized_label": "10-a",
            "context_texts": ["Intermediate 10-a"],
        },
    )

    assert classify_structure_role(molecule) == "review_required"
