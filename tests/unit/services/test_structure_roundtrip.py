"""Round-trip visual verification: render a SMILES, read it back, compare.

Covers ``use_cases.documents.structure_roundtrip`` — the pure verdict core
(``round_trip_check``, ``render_depiction``) and the evidence-selecting
orchestration (``verify_structure_roundtrip``). The recognizer is injected,
so no model weights or network are needed.
"""

from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from mbforge.db.source_evidence import persist_source_evidence
from mbforge.domain.evidence import SourceEvidence
from mbforge.foundation.errors import NotFoundError
from mbforge.service.use_cases.documents.structure_roundtrip import (
    render_depiction,
    round_trip_check,
    verify_structure_roundtrip,
)

#: L-alanine and its enantiomer: one graph, two stereo readings.
ALANINE = "C[C@H](N)C(=O)O"
D_ALANINE = "C[C@@H](N)C(=O)O"
#: A different molecule entirely, for the divergent branch.
BENZENE = "c1ccccc1"

#: Sentinel crop: the stub reads it separately from the depiction.
CROP = object()


def _predict(depiction_read: str, crop_read: str | None = None):
    """A recognizer stub with separate readings for the depiction and the crop."""

    def predict(image):
        if image is CROP:
            return SimpleNamespace(
                smiles=crop_read if crop_read is not None else depiction_read
            )
        return SimpleNamespace(smiles=depiction_read)

    return predict


def test_round_trip_check_reports_the_verdict_ladder_and_crop_consistency() -> None:
    """Every verdict on both signals: self-consistency and crop fidelity.

    The crop reading is independent of the depiction reading, so a stored
    SMILES can read back as itself while disagreeing with the original crop —
    the case a fidelity check must catch.
    """
    assert render_depiction(ALANINE) is not None

    same = round_trip_check(ALANINE, CROP, _predict(ALANINE))
    assert same["self_consistency"] == "consistent"
    assert same["canonical_smiles"]
    assert same["recovered_canonical"] == same["canonical_smiles"]
    assert same["crop_consistency"] == "consistent"
    assert same["crop_smiles"] == ALANINE
    assert same["depiction"] is not None
    assert same["notes"]

    # The drawing reads back as itself, but the crop shows another molecule.
    misassociated = round_trip_check(ALANINE, CROP, _predict(ALANINE, BENZENE))
    assert misassociated["self_consistency"] == "consistent"
    assert misassociated["crop_consistency"] == "divergent"

    # The crop carries the enantiomer: same graph, different stereo.
    graph = round_trip_check(ALANINE, CROP, _predict(ALANINE, D_ALANINE))
    assert graph["crop_consistency"] == "graph_consistent"

    # Without a crop the fidelity signal is reported as unavailable.
    no_crop = round_trip_check(ALANINE, None, _predict(ALANINE))
    assert no_crop["crop_consistency"] == "no_crop"
    assert no_crop["crop_smiles"] == ""

    divergent = round_trip_check(ALANINE, None, _predict(BENZENE))
    assert divergent["self_consistency"] == "divergent"

    stereo = round_trip_check(ALANINE, None, _predict(D_ALANINE))
    assert stereo["self_consistency"] == "graph_consistent"

    unreadable = round_trip_check(ALANINE, None, _predict(""))
    assert unreadable["self_consistency"] == "unreadable"

    broken = round_trip_check("this is not a smiles", None, _predict(ALANINE))
    assert broken["self_consistency"] == "not_renderable"
    assert broken["depiction"] is None

    # A Markush scaffold reads back as itself under the dummy-as-methyl convention.
    markush = round_trip_check("*c1ccccc1", CROP, _predict("Cc1ccccc1"))
    assert markush["self_consistency"] == "consistent"
    assert markush["crop_consistency"] == "consistent"
    assert any("Markush" in note for note in markush["notes"])

    # The recognizer keeps dummies on a patent crop but reads methyls on a clean
    # depiction: the two conventions must still compare as consistent.
    mixed = round_trip_check("*c1ccccc1", CROP, _predict("Cc1ccccc1", "*c1ccccc1"))
    assert mixed["crop_consistency"] == "consistent"


def _molecule_evidence(doc_id: str, page: int, smiles: str) -> SourceEvidence:
    """A molecule row as the molecule pass writes it."""
    return SourceEvidence.create(
        doc_id=doc_id,
        page=page,
        bbox=(10.0, 10.0, 90.0, 90.0),
        kind="molecule",
        raw_text=json.dumps(
            {
                "smiles": smiles,
                "esmiles": smiles,
                "moldet_conf": 0.94,
                "mol_img_path": f"storage/{doc_id}/crops/mol_{page}.png",
                "name": "",
                "properties": {"ocr_labels": ["化合物1"]},
            },
            ensure_ascii=False,
        ),
    )


def test_verify_structure_roundtrip_selects_the_row_and_survives_no_pdf(
    tmp_path: Path,
) -> None:
    """The evidence_id picks one structure; a missing PDF only drops the crop.

    Two rows are stored and only the requested one is verified. With no stored
    PDF there is no crop, so the self-consistency half still runs and the
    fidelity signal is reported as unavailable rather than guessed.
    """
    doc_id = "doc-roundtrip"
    rows = [
        _molecule_evidence(doc_id, 1, ALANINE),
        _molecule_evidence(doc_id, 2, BENZENE),
    ]
    persist_source_evidence(tmp_path, rows)
    evidence_id = rows[0].evidence_id

    report = verify_structure_roundtrip(
        tmp_path, doc_id, evidence_id, predict=_predict(ALANINE)
    )

    assert report["evidence_id"] == evidence_id
    assert report["self_consistency"] == "consistent"
    assert report["smiles"]
    assert report["page"] == 1
    assert report["crop_consistency"] == "no_crop"
    assert report["image_base64"]
    assert report["notes"]

    with pytest.raises(NotFoundError):
        verify_structure_roundtrip(
            tmp_path, doc_id, "no-such-evidence", predict=_predict(ALANINE)
        )
