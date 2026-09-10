"""Unit tests for the models management router."""

from __future__ import annotations

import asyncio

import pytest

from mbforge.infra.models import (
    clear as clear_loaded_models,
)
from mbforge.infra.models import (
    test as run_model_test_sync,
)
from mbforge.models.common import (
    ModelTestRequest,
    ModelTestResponse,
    MoleculeRenderRequest,
)
from mbforge.routers.system.models import (
    render_molecule,
)
from mbforge.routers.system.models import (
    test_model as model_test_handler,
)
from mbforge.services.chem.chem import (
    render_molecule_png_sync as _render_molecule_sync,
)


def _capture_to_thread(monkeypatch: pytest.MonkeyPatch):
    """Patch asyncio.to_thread so callers can inspect what was offloaded."""
    calls: list[tuple[object, tuple, dict]] = []

    async def _fake_to_thread(func, *args, **kwargs):
        calls.append((func, args, kwargs))
        if func is run_model_test_sync:
            return {"ok": True, "error": "", "duration_ms": 42}
        if func is _render_molecule_sync:
            return {"success": True, "image_base64": "fake", "error": ""}
        return {}

    monkeypatch.setattr(asyncio, "to_thread", _fake_to_thread)
    return calls


def test_test_model_offloads_to_thread(monkeypatch: pytest.MonkeyPatch) -> None:
    """The model-test route delegates blocking inference to asyncio.to_thread."""
    calls = _capture_to_thread(monkeypatch)

    result = asyncio.run(model_test_handler(ModelTestRequest(model_id="molparser")))

    assert result == ModelTestResponse(ok=True, error="", duration_ms=42)
    assert len(calls) == 1
    assert calls[0][0] is run_model_test_sync


def test_render_molecule_offloads_to_thread(monkeypatch: pytest.MonkeyPatch) -> None:
    """The render route delegates RDKit/PIL drawing to asyncio.to_thread."""
    calls = _capture_to_thread(monkeypatch)

    result = asyncio.run(
        render_molecule(MoleculeRenderRequest(smiles="CCO", width=200, height=150))
    )

    assert result.success is True
    assert result.image_base64 == "fake"
    assert len(calls) == 1
    assert calls[0][0] is _render_molecule_sync
    assert calls[0][1] == ("CCO", 200, 150)


def test_clear_loaded_models_releases_both_singletons(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Model management clears in-process models without deleting downloaded weights."""
    from mbforge.backends import moldet_v2_ft, molparser

    moldet_v2_ft._detector_singleton = object()
    molparser._MODEL = object()
    monkeypatch.setattr("gc.collect", lambda: 0)
    monkeypatch.setattr("torch.cuda.is_available", lambda: False)

    result = clear_loaded_models()

    assert result["success"] is True
    assert all(not model["loaded"] for model in result["models"])
