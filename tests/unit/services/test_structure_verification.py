"""Structure verification rows: formula, masses and the printed-mass delta.

Covers ``use_cases.documents.structure_verification.verify_structures`` — the
read surface that lets a reader check a recognized structure against the mass
the document printed for it, without a pipeline run and without a write.
"""

from __future__ import annotations

import json
from pathlib import Path

from mbforge.db.source_evidence import persist_source_evidence
from mbforge.domain.evidence import SourceEvidence
from mbforge.service.use_cases.documents.structure_verification import (
    verify_structures,
)

#: 1-D of CN119504738A: 2-methyl-2H-pyrazolo[4,3-c]pyridin-4-yl
#: cyclohexane-1,4-diamine — C13H19N5, monoisotopic 245.1641.
SMILES = "Cn1cc2c(N[C@H]3CC[C@@H](N)CC3)nccc2n1"
#: The same structure as its hydrochloride salt, as the document drew it.
SALT_SMILES = "Cl.Cn1cc2c(N[C@H]3CC[C@@H](N)CC3)nccc2n1"
#: 1-C of the same document: the Boc-protected intermediate.
BOC_SMILES = "Cn1cc2c(N[C@H]3CC[C@@H](NC(=O)OC(C)(C)C)CC3)nccc2n1"


def _molecule_evidence(
    doc_id: str,
    page: int,
    bbox: tuple[float, float, float, float],
    smiles: str,
    label: str,
) -> SourceEvidence:
    """A molecule row as the molecule pass writes it."""
    return SourceEvidence.create(
        doc_id=doc_id,
        page=page,
        bbox=bbox,
        kind="molecule",
        raw_text=json.dumps(
            {
                "smiles": smiles,
                "esmiles": smiles,
                "moldet_conf": 0.94,
                "mol_img_path": f"storage/{doc_id}/crops/mol_{page}.png",
                "name": "",
                "properties": {"ocr_labels": [label]},
            },
            ensure_ascii=False,
        ),
    )


def _text_evidence(doc_id: str, page: int, text: str) -> SourceEvidence:
    return SourceEvidence.create(
        doc_id=doc_id,
        page=page,
        bbox=(60.0, 700.0, 533.0, 720.0),
        kind="text",
        raw_text=text,
    )


def test_verify_structures_checks_each_structure_against_the_printed_mass(
    tmp_path: Path,
) -> None:
    """One row per structure: its chemistry, its designation and the delta.

    A printed mass that agrees with the structure is a match, one that
    disagrees is a mismatch, and a printed mass no structure claims stays
    unowned instead of being attributed to a neighbour.
    """
    doc_id = "doc-verify"
    persist_source_evidence(
        tmp_path,
        [
            # 化合物4: the printed mass agrees with the drawn structure.
            _molecule_evidence(
                doc_id, 62, (113.0, 565.0, 191.0, 653.0), SMILES, "化合物4"
            ),
            _text_evidence(doc_id, 62, "[0327] 化合物4: LC-MS,M/Z(ESI):246.17[M+H]+"),
            # 化合物9: the printed mass belongs to another structure.
            _molecule_evidence(
                doc_id, 63, (113.0, 285.0, 190.0, 361.0), SALT_SMILES, "化合物9"
            ),
            _text_evidence(doc_id, 63, "[0333] 化合物9: LC-MS,M/Z(ESI):300.50[M+H]+"),
            # A printed mass no structure of this document claims.
            _text_evidence(doc_id, 64, "[0337] 化合物11: LC-MS,M/Z(ESI):345.10[M+H]+"),
        ],
    )

    report = verify_structures(tmp_path, doc_id)

    assert report["summary"]["structures"] == 2
    assert report["summary"]["printed_ms_lines"] == 3
    assert report["summary"]["printed_ms_unowned"] == 1
    assert report["summary"]["mass_matches"] == 1
    assert report["summary"]["mass_mismatches"] == 1
    assert report["summary"]["structures_without_printed_ms"] == 0

    matched = next(item for item in report["items"] if item["label_keys"] == ["4"])
    assert matched["page"] == 62
    assert matched["evidence_id"]
    assert matched["formula"] == "C13H19N5"
    assert matched["exact_mass"] == 245.164
    assert matched["mass_basis"] == "largest_fragment"
    assert matched["mass_check"] == "match"
    check = matched["printed_ms"][0]
    assert check["printed_mz"] == 246.17
    assert check["adduct"] == "+H"
    assert check["expected_mz"] == 246.1713
    assert abs(check["delta"]) < 0.01
    assert check["verdict"] == "match"
    assert check["evidence_ids"]

    mismatched = next(item for item in report["items"] if item["label_keys"] == ["9"])
    assert mismatched["mass_check"] == "mismatch"
    assert mismatched["printed_ms"][0]["verdict"] == "mismatch"
    # The salt is stored as written, but the mass check weighs the parent.
    # The stored salt is neutral HCl plus a neutral amine, so its whole-SMILES
    # formula counts one hydrogen too many for the salt as drawn.
    assert mismatched["formula"] == "C13H20ClN5"
    assert mismatched["main_formula"] == "C13H19N5"
    assert mismatched["exact_mass"] == 245.164


def test_verify_structures_scopes_and_pages_its_rows(tmp_path: Path) -> None:
    """``page`` and ``label`` narrow the rows; the counts describe the scope."""
    doc_id = "doc-scope"
    persist_source_evidence(
        tmp_path,
        [
            _molecule_evidence(doc_id, 10, (10.0, 10.0, 20.0, 20.0), SMILES, "化合物4"),
            _molecule_evidence(
                doc_id, 11, (30.0, 30.0, 40.0, 40.0), BOC_SMILES, "化合物5"
            ),
        ],
    )

    assert verify_structures(tmp_path, doc_id, page=11)["summary"]["structures"] == 1
    scoped = verify_structures(tmp_path, doc_id, label="化合物5")
    assert scoped["summary"]["structures"] == 1
    assert scoped["items"][0]["label_keys"] == ["5"]
    # A structure no printed mass covers is reported, not silently dropped.
    assert scoped["summary"]["structures_without_printed_ms"] == 1
    assert scoped["items"][0]["mass_check"] == "no_printed_mass"
