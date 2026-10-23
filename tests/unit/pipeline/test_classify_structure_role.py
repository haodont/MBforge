"""Tests for deterministic complete/scaffold/fragment classification.

Covers ``mbforge.service.pipeline.detection.structure_role.classify_structure_role``:
dummy-atom shape drives complete/fragment/scaffold, and every *contextual*
Markush or ambiguity signal conservatively routes a closed SMILES to
``review_required`` with a stable reason code.
"""

from __future__ import annotations

from mbforge.domain.molecule import Molecule
from mbforge.service.pipeline.detection.structure_role import (
    classify_structure_role,
)

# (smiles, expected role, case) — dummy-atom shape decides the role.
_DUMMY_ROLE_CASES: list[tuple[str, str, str]] = [
    ("CCO", "complete", "acyclic molecule without dummies"),
    ("c1ccccc1OC", "complete", "aromatic molecule without dummies"),
    ("*c1cscn1", "fragment", "small single attachment"),
    ("*" + "C" * 23, "fragment", "extended single attachment"),
    ("*c1ccc(*)cc1" + "C" * 13, "scaffold", "large multi-attachment ring"),
    ("*" + "C" * 30 + "*", "scaffold", "large multi-attachment chain"),
]

# Markush wording in the surrounding evidence must not be read as a real
# structure: the SMILES is closed but the context says it is generic.
_MARKUSH_CONTEXT_CASES: list[tuple[str, str]] = [
    (
        "Formula I compounds are optionally substituted at R1.",
        "English formula designation",
    ),
    ("Formula (I) 化合物在 R1 位任选取代。", "Chinese formula designation"),
    ("general structure with R2 and R3 groups", "generic structure wording"),
]

# (context, expected reason) — mixture/stereochemistry statements.
_AMBIGUITY_CASES: list[tuple[str, str]] = [
    ("化合物3为1S,3R与1R,3S的混合物，可经SFC拆分", "context_mixture_or_isomer"),
    ("化合物28的双键构型Z/E暂不确定", "context_stereochemistry_uncertain"),
    ("化合物4A为拆分产物，构型暂定", "context_mixture_or_isomer"),
    ("compound 28 configuration is tentative", "context_stereochemistry_uncertain"),
    ("the stereochemistry is tentative", "context_stereochemistry_uncertain"),
]


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


def test_dummy_atom_shape_decides_the_structure_role() -> None:
    """No dummies → complete; one attachment → fragment; many → scaffold."""
    for smiles, expected, case in _DUMMY_ROLE_CASES:
        molecule = _molecule(smiles)

        assert classify_structure_role(molecule) == expected, case
        assert molecule.properties["structure_role"] == expected, case


def test_invalid_or_empty_smiles_require_review() -> None:
    """Malformed recognition output never falls through to the complete library."""
    for smiles in ("@@@", ""):
        molecule = _molecule(smiles)

        assert classify_structure_role(molecule) == "review_required", smiles
        assert molecule.properties["structure_role_reasons"] == [
            "invalid_or_empty_structure"
        ], smiles


def test_markush_context_or_metadata_requires_review() -> None:
    """A closed SMILES with generic context or markush metadata is not concrete."""
    for context, case in _MARKUSH_CONTEXT_CASES:
        molecule = _molecule("CCO")
        molecule.properties["context_texts"] = [context]

        assert classify_structure_role(molecule) == "review_required", case
        assert molecule.properties["structure_role_reasons"], case

    # Control: concrete context keeps the candidate complete.
    concrete = _molecule("CCO")
    concrete.properties["context_texts"] = ["Example 12 was tested by LC-MS."]
    assert classify_structure_role(concrete) == "complete"

    # Markush metadata must not be silently classified as a complete molecule.
    flagged = _molecule("CCO", properties={"markush": True, "groups": "R1=alkyl"})
    assert classify_structure_role(flagged) == "review_required"
    assert flagged.properties["structure_role_reasons"] == ["markush_without_dummy"]


def test_contextual_intermediate_labels_require_review() -> None:
    """Step-like labels need corroborating intermediate context; final labels
    never become intermediates on their own."""
    for label in ["1a", "21-e", "4A-1"]:
        molecule = _molecule(
            "CCO",
            name=label,
            properties={"context_texts": [f"Intermediate {label}"]},
        )

        assert classify_structure_role(molecule) == "review_required", label
        assert (
            "context_synthetic_intermediate_label"
            in molecule.properties["structure_role_reasons"]
        ), label

    for context in ["Intermediate 1a", "中间体 1a", "synthesis step 1a"]:
        molecule = _molecule("CCO", name="1a")
        molecule.properties["context_texts"] = [context]

        assert classify_structure_role(molecule) == "review_required", context
        assert (
            "context_synthetic_intermediate_label"
            in molecule.properties["structure_role_reasons"]
        ), context

    # A bare step-like label falls through to the final-label path.
    assert classify_structure_role(_molecule("CCO", name="1a")) == "complete"

    for label in ["3A", "3B", "4A", "4B", "28"]:
        assert classify_structure_role(_molecule("CCO", name=label)) == "complete", (
            label
        )


def test_ambiguous_closed_structures_require_review() -> None:
    """Mixture and tentative-stereochemistry wording is preserved for review."""
    for context, reason in _AMBIGUITY_CASES:
        molecule = _molecule("CCO", name="3", properties={"context_texts": [context]})

        assert classify_structure_role(molecule) == "review_required", context
        assert reason in molecule.properties["structure_role_reasons"], context


def test_rejected_candidate_keeps_status_and_gets_no_role() -> None:
    """Rejected recognitions stay rejected and are not classified."""
    molecule = _molecule("bogus", status="rejected")

    assert classify_structure_role(molecule) == "rejected"
    assert molecule.status == "rejected"
    assert "structure_role" not in molecule.properties


def test_normalized_intermediate_label_is_used_when_name_is_missing() -> None:
    """Coreference-preserved labels feed the intermediate-context guard."""
    molecule = _molecule(
        "CCO",
        properties={
            "normalized_label": "10-a",
            "context_texts": ["Intermediate 10-a"],
        },
    )

    assert classify_structure_role(molecule) == "review_required"
