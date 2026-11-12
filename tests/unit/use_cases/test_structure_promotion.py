"""Promoting one withheld drawing into the concrete library.

The Markush role gate withholds a closed, labelled drawing when the prose
around it mentions generic structure. That is right, but without a decision
path back the compound never reaches ``molecules`` and no reading can be
linked to it. This test protects the promotion contract: the drawing must
already exist in the document's evidence, a scaffold is refused, the call is
idempotent, and the promoted molecule is a stored row an attribution can
reference.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from mbforge.db.sqlite.database import DatabaseManager
from mbforge.domain.evidence import SourceEvidence
from mbforge.foundation.errors import ConflictError, NotFoundError
from mbforge.db.source_evidence import persist_source_evidence
from mbforge.service.use_cases.documents.structure_promotion import promote_structure

_DOC_ID = "doc-promote"
_CANONICAL = "Cn1cc(C(=O)NCC2CCCC(Nc3cc(C(F)(F)F)nc4ccc(Cl)cc34)C2)cn1"


def _molecule_row(smiles: str, name: str, x0: float) -> SourceEvidence:
    payload = {
        "smiles": smiles,
        "esmiles": smiles,
        "mol_img_path": "",
        "moldet_conf": 0.95,
        "name": name,
        "properties": {
            # The prose next to the drawing is a generic-structure definition,
            # which is what makes the role gate withhold this compound.
            "role_contexts": ["R1 为氢、卤素或 C1-6 烷基"],
        },
    }
    return SourceEvidence.create(
        doc_id=_DOC_ID,
        page=70,
        bbox=(x0, 200.0, x0 + 160.0, 380.0),
        raw_text=json.dumps(payload),
        kind="molecule",
    )


@pytest.fixture()
def library(tmp_path: Path) -> Path:
    DatabaseManager.get(str(tmp_path)).initialize()
    persist_source_evidence(
        tmp_path,
        [
            _molecule_row(_CANONICAL, "30A", 100.0),
            _molecule_row("*c1ccccc1", "scaffold", 300.0),
        ],
    )
    return tmp_path


def test_a_withheld_drawing_becomes_a_stored_structure(library: Path) -> None:
    """The promoted drawing is a molecule row, once, and a scaffold never is.

    ``molecules`` is what an attribution references. Without this the reading
    stays unowned even though the document printed the compound's number beside
    a closed structure — the exact CN120118069A case.
    """
    first = promote_structure(
        str(library),
        _DOC_ID,
        smiles=_CANONICAL,
        reason="实施例30A:产物图,印号30A",
    )
    assert first["promoted"] is True
    assert first["mol_id"] == _CANONICAL
    assert first["name"] == "30A"
    assert first["page"] == 70

    stored = DatabaseManager.get(str(library))
    row = stored.execute(
        "SELECT name, properties FROM molecules WHERE mol_id = ?", (_CANONICAL,)
    )
    assert row and row[0]["name"] == "30A"
    properties = json.loads(row[0]["properties"])
    assert properties["structure_role"] == "complete"
    assert properties["promotion"]["reason"] == "实施例30A:产物图,印号30A"

    again = promote_structure(str(library), _DOC_ID, smiles=_CANONICAL)
    assert again["promoted"] is False

    with pytest.raises(ConflictError):
        promote_structure(str(library), _DOC_ID, smiles="*c1ccccc1")
    with pytest.raises(NotFoundError):
        promote_structure(str(library), _DOC_ID, smiles="CCO")
    with pytest.raises(NotFoundError):
        promote_structure(str(library), "another-doc", smiles=_CANONICAL)
