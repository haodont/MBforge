from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient

from mbforge.adapters.inference.moldet_v2_ft import MoleculeBbox, MoleculeResult


def _import_sample(client: TestClient, library_root: Path, sample_pdf: Path) -> str:
    """Import ``sample_pdf`` into ``library_root`` and return its ``doc_id``."""
    with sample_pdf.open("rb") as f:
        resp = client.post(
            "/api/v1/library/import",
            files={"file": ("sample.pdf", f, "application/pdf")},
            data={"library_root": str(library_root)},
        )
    assert resp.status_code == 200, resp.text
    data = resp.json()
    assert data["success"] is True
    return data["document"]["doc_id"]


@pytest.mark.parametrize(
    "bboxes",
    [
        [(0.1, 0.1, 0.2, 0.2)],
        [(0.1, 0.1, 0.2, 0.2), (0.5, 0.5, 0.6, 0.6)],
    ],
)
def test_extract_pdf_page_with_mock(
    app_client: TestClient,
    tmp_library: Path,
    sample_pdf: Path,
    bboxes: list[tuple[float, float, float, float]],
) -> None:
    """Every detected molecule maps to a result; context_text stays empty
    since identifier/coref labels are no longer produced."""
    doc_id = _import_sample(app_client, tmp_library, sample_pdf)

    result = MoleculeResult(
        bboxes=[MoleculeBbox(category_id=1, bbox=bbox, score=0.9) for bbox in bboxes],
    )

    with (
        patch(
            "mbforge.application.use_cases.molecule.detection.detect_molecules",
            return_value=result,
        ),
        patch("mbforge.adapters.inference.molparser.load"),
        patch("mbforge.adapters.inference.molparser.predict") as mock_predict,
    ):
        mock_predict.return_value.esmiles = "CCO"
        mock_predict.return_value.smiles = "CCO"
        resp = app_client.post(
            "/api/v1/moldet/extract-pdf-page",
            json={
                "library_root": str(tmp_library),
                "doc_id": doc_id,
                "page": 1,
            },
        )

    assert resp.status_code == 200
    data = resp.json()
    assert data["count"] == len(bboxes)
    assert len(data["molecules"]) == len(bboxes)
    assert data["molecules"][0]["smiles"] == "CCO"
    assert data["molecules"][0]["confidence"] == 0.9
    assert all(m["context_text"] == "" for m in data["molecules"])
    assert data["page_num"] == 1
