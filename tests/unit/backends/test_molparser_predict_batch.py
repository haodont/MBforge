from __future__ import annotations

import pytest
from PIL import Image

from mbforge.backends import molparser as molparser_module
from mbforge.backends.molparser import predict, predict_batch


@pytest.fixture
def _restore_state():
    orig_model = molparser_module._MODEL
    orig_available = molparser_module._AVAILABLE
    orig_error = molparser_module._ERROR
    orig_load = molparser_module.load
    molparser_module._MODEL = None
    molparser_module._AVAILABLE = False
    molparser_module._ERROR = ""
    # Lazy-load on first use would silently replace the forced-unavailable
    # state above, so keep load() a no-op while the simulation is in effect.
    molparser_module.load = lambda: None
    try:
        yield
    finally:
        molparser_module._MODEL = orig_model
        molparser_module._AVAILABLE = orig_available
        molparser_module._ERROR = orig_error
        molparser_module.load = orig_load


def _img() -> Image.Image:
    return Image.new("RGB", (16, 16), "white")


def _install_fake(captions: list[str]) -> None:
    class _Fake:
        def recognize(self, images):
            return captions

    molparser_module._MODEL = _Fake()
    molparser_module._AVAILABLE = True


def test_predict_batch_not_available(_restore_state):
    results = predict_batch([_img(), _img()])
    assert len(results) == 2
    assert results[0].esmiles == ""
    assert results[0].properties.get("error")


def test_predict_batch_returns_esmiles_and_smiles(_restore_state):
    _install_fake(["CCO", "c1ccccc1"])
    results = predict_batch([_img(), _img()])
    assert len(results) == 2
    assert results[0].esmiles == "CCO"
    assert results[0].smiles == "CCO"
    assert "sru" not in results[0].properties
    assert results[1].esmiles == "c1ccccc1"


def test_predict_separates_markush_layer1(_restore_state):
    _install_fake(["*c1ccccc1<sep><a>0:R[1]</a>"])
    r = predict(_img())
    # Layer 2 keeps the full E-SMILES; Layer 1 exposes the parseable SMILES.
    assert r.esmiles == "*c1ccccc1<sep><a>0:R[1]</a>"
    assert r.smiles == "*c1ccccc1"
    assert r.properties.get("markush") is True
    assert "sru" not in r.properties


def test_predict_strips_isolated_trailing_sep(_restore_state):
    _install_fake(["CCO<sep>"])
    r = predict(_img())
    assert r.esmiles == "CCO"
    assert r.smiles == "CCO"
