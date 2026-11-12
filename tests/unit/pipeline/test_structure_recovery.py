"""A misread drawing is re-read from a higher-resolution reprint.

``find_mass_mismatches`` says the printed mass and the recognized structure
disagree; that is evidence the recognition is wrong. The recovery pass re-renders
the drawing from the PDF at a larger scale, reads it again with the same model,
and keeps the new structure only when it matches the printed mass.

CN121717757A's ``I-266-A`` is the measured case: the claims drawing reads
``C26H30…`` (572.2) while 实施例26 prints ``(M+H)+ = 558.0`` and the example
drawing is ``C25H28…`` (558.16).
"""

from __future__ import annotations

from pathlib import Path

import pytest

from mbforge.db.sqlite.database import DatabaseManager
from mbforge.domain.molecule import Molecule
from mbforge.domain.types import DetectionSource
from mbforge.service.pipeline.patent.structure_recovery import (
    recover_structures_by_printed_mass,
)

_WRONG = (
    "CC(C)(CO)CCn1cc(C(=O)N[C@@H]2CCC[C@H](Nc3cc(C(F)(F)F)nc4ccc(Cl)cc34)C2)c(Cl)n1"
)
_RIGHT = (
    "CC(C)(O)CCn1cc(C(=O)N[C@@H]2CCC[C@H](Nc3cc(C(F)(F)F)nc4ccc(Cl)cc34)C2)c(Cl)n1"
)
_MS = [
    {
        "technique": "ms",
        "label_key": "I-266-A",
        "raw_text": "LC-MS:m/z:(M+H)+=558.0",
        "evidence_ids": ["ev-266"],
    }
]


def _candidate() -> Molecule:
    return Molecule(
        canonical_smiles=_WRONG,
        esmiles=_WRONG,
        name="I-266-A",
        status="pending",
        detections=[
            DetectionSource(
                source="image",
                page=56,
                bbox=(88.55, 274.31, 197.61, 361.42),
                evidence_id="ev-266",
            )
        ],
        properties={"detection_designations": [{"name": "I-266-A"}]},
    )


@pytest.fixture()
def library(tmp_path: Path) -> Path:
    DatabaseManager.get(str(tmp_path)).initialize()
    return tmp_path


def test_a_reprint_that_matches_the_printed_mass_replaces_the_reading(
    library: Path,
) -> None:
    """The corrected structure is persisted and evidenced, so a reading can bind."""
    calls: list[tuple[int, tuple[float, ...], float]] = []

    def render(pdf: str, page: int, bbox, scale: float) -> bytes:
        calls.append((page, tuple(bbox), scale))
        return b"png"

    issues: list[dict] = []
    recovered = recover_structures_by_printed_mass(
        pdf_path="ignored.pdf",
        library_root=library,
        doc_id="doc-1",
        candidates=[_candidate()],
        characterizations=_MS,
        issues=issues,
        render=render,
        recognize=lambda image: _RIGHT,
    )

    assert [item.canonical_smiles for item in recovered] == [_RIGHT]
    assert calls and calls[0][0] == 56 and calls[0][2] == 2.0
    assert any(
        issue["code"] == "structure_recovered_from_reprint" for issue in issues
    )
    stored = DatabaseManager.get(str(library)).execute(
        "SELECT name FROM molecules WHERE mol_id = ?", (_RIGHT,)
    )
    assert stored and stored[0]["name"] == "I-266-A"


def test_a_reprint_that_still_disagrees_changes_nothing(library: Path) -> None:
    """A second mismatch is not a correction; the review item stands."""
    issues: list[dict] = []
    recovered = recover_structures_by_printed_mass(
        pdf_path="ignored.pdf",
        library_root=library,
        doc_id="doc-1",
        candidates=[_candidate()],
        characterizations=_MS,
        issues=issues,
        render=lambda pdf, page, bbox, scale: b"png",
        recognize=lambda image: _WRONG,
    )

    assert recovered == []
    assert issues == []
    assert (
        DatabaseManager.get(str(library)).execute(
            "SELECT COUNT(*) AS n FROM molecules"
        )[0]["n"]
        == 0
    )


def test_an_unlabelled_drawing_is_named_after_the_designation_its_mass_matches(
    library: Path,
) -> None:
    """A designation with no drawing still names the drawing its LC-MS measures.

    CN121717757A cites ``I-2`` in its table and prints ``(M+H)+ = 504.1`` in
    实施例3; the claims drawing whose mass is 503.16 was read but never
    captioned. Exactly one unlabelled drawing matches, so the document has
    already said which structure it means — the promotion stores it under the
    designation and the association binds the readings by rule.
    """
    from mbforge.db.sqlite.database import DatabaseManager
    from mbforge.service.pipeline.patent.structure_recovery import (
        promote_structures_by_printed_mass,
    )

    DatabaseManager.get(str(library)).initialize()
    candidate = Molecule(
        canonical_smiles=(
            "COc1ccc(C(=O)NC23CCC(CC2)C(Nc2cc(C(F)(F)F)nc4ccc(Cl)cc34)C3)cc1"
        ),
        esmiles="",
        name="",
        status="pending",
        detections=[
            DetectionSource(
                source="image",
                page=31,
                bbox=(249.81, 339.82, 358.15, 419.74),
                evidence_id="ev-p32",
            )
        ],
        properties={},
    )
    issues: list[dict] = []

    promoted = promote_structures_by_printed_mass(
        library_root=library,
        doc_id="doc-1",
        candidates=[candidate],
        characterizations=[
            {
                "technique": "ms",
                "label_key": "I-2",
                "raw_text": "LC-MS:m/z:(M+H)+=504.1",
                "evidence_ids": ["ev-153"],
            }
        ],
        issues=issues,
    )

    assert [item.name for item in promoted] == ["I-2"]
    assert any(
        issue["code"] == "designation_promoted_by_printed_mass" for issue in issues
    )
    stored = DatabaseManager.get(str(library)).execute(
        "SELECT name FROM molecules WHERE mol_id = ?", (candidate.canonical_smiles,)
    )
    assert stored and stored[0]["name"] == "I-2"

    # A mass that matches two drawings is not a name for either.
    other = Molecule(
        canonical_smiles=(
            "COc1ccc(C(=O)NC23CCC(Nc4cc(C(F)(F)F)nc5ccc(Cl)cc45)(C2)C3)cc1"
        ),
        esmiles="",
        name="",
        status="pending",
        detections=[
            DetectionSource(
                source="image", page=113, bbox=(1.0, 2.0, 3.0, 4.0), evidence_id="ev-113"
            )
        ],
        properties={"structure_role": "complete"},
    )
    assert (
        promote_structures_by_printed_mass(
            library_root=library,
            doc_id="doc-2",
            candidates=[candidate, other],
            characterizations=[
                {
                    "technique": "ms",
                    "label_key": "I-3",
                    "raw_text": "LC-MS:m/z:(M+H)+=504.1",
                    "evidence_ids": ["ev-153"],
                }
            ],
            issues=[],
        )
        == []
    )
