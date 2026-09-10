"""Router tests for POST /api/v1/molparser/recognize."""

from __future__ import annotations

import base64
import io
from unittest.mock import patch

from fastapi.testclient import TestClient
from PIL import Image

from mbforge.pipeline.detection.recognition import RecognizedMolecule


def _png_base64() -> str:
    buf = io.BytesIO()
    Image.new("L", (16, 16), 255).save(buf, format="PNG")
    return base64.b64encode(buf.getvalue()).decode("ascii")


def test_recognize_returns_esmiles_smiles_coref(
    app_client: TestClient,
) -> None:
    with patch(
        "mbforge.routers.molecule.molparser.recognize_molecule",
        return_value=RecognizedMolecule(
            esmiles="CCO<sep>NH2",
            smiles="CCO",
            coref=["4A", "2"],
            coref_primary="4A",
        ),
    ):
        resp = app_client.post(
            "/api/v1/molparser/recognize",
            json={"image_base64": _png_base64(), "ext": "png"},
        )
    assert resp.status_code == 200, resp.text
    assert resp.json() == {
        "esmiles": "CCO<sep>NH2",
        "smiles": "CCO",
        "coref": ["4A", "2"],
        "coref_primary": "4A",
        "success": True,
    }


def test_recognize_maps_molparser_failure_to_503(app_client: TestClient) -> None:
    with patch(
        "mbforge.routers.molecule.molparser.recognize_molecule",
        return_value=RecognizedMolecule(
            esmiles="", smiles="", coref=[]
        ),
    ):
        resp = app_client.post(
            "/api/v1/molparser/recognize",
            json={"image_base64": _png_base64(), "ext": "png"},
        )
    assert resp.status_code == 503
