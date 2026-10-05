"""Unit tests for the ingest model gate predicate.

Covers the two contracts the queue worker and the readiness endpoint rely on:
which models count as required, and how a partially-ready set is reported.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

from mbforge.server.resource_manager import (
    REQUIRED_PIPELINE_MODEL_IDS,
    RESOURCE_CATALOG,
)
from mbforge.server.resource_types import (
    ResourceStatus,
    ResourceStatusResult,
    ResourceType,
)
from mbforge.service.ports import get_runtime
from mbforge.service.use_cases.pipeline import model_gate

#: A gate scope deliberately different from the real catalog set, so the tests
#: prove the predicate reads the port attribute instead of hardcoding ids.
_STUB_IDS = ("moldet", "hiro_layout")


@dataclass
class _StubResourceManager:
    """Minimal stand-in for the resource-manager capability."""

    results: dict[str, Any] = field(default_factory=dict)
    required_pipeline_model_ids: tuple[str, ...] = _STUB_IDS

    def check(self, resource_id: str) -> Any:
        result = self.results[resource_id]
        if isinstance(result, Exception):
            raise result
        return result


def _install(monkeypatch, results: dict[str, Any]) -> None:
    manager = _StubResourceManager(results=results)
    monkeypatch.setattr(
        model_gate, "get_runtime", lambda: SimpleNamespace(resource_manager=manager)
    )


def _status(
    resource_id: str,
    status: ResourceStatus,
    *,
    name: str = "",
    error: str = "",
) -> ResourceStatusResult:
    return ResourceStatusResult(
        id=resource_id,
        name=name or resource_id,
        type=ResourceType.MODEL,
        status=status,
        error=error,
    )


def test_gate_blocks_and_reports_every_missing_required_model(monkeypatch) -> None:
    """A non-ready model blocks the gate and is reported with its status."""
    _install(
        monkeypatch,
        {
            "moldet": _status("moldet", ResourceStatus.NOT_FOUND, name="MolDetv2-FT"),
            "hiro_layout": _status(
                "hiro_layout", ResourceStatus.PARTIAL, name="Hiro-Layout"
            ),
        },
    )

    gate = model_gate.evaluate_model_gate()

    assert gate.ready is False
    # The scope comes from the port, not from a hardcoded list in the predicate.
    assert gate.required == _STUB_IDS
    # Reported in required order, so the message is stable across polls.
    assert gate.missing_ids() == ("moldet", "hiro_layout")
    assert gate.reason() == "missing models: moldet (not_found), hiro_layout (partial)"
    assert gate.to_dict()["missing"][0] == {
        "id": "moldet",
        "name": "MolDetv2-FT",
        "status": "not_found",
        "error": None,
    }


def test_gate_is_ready_when_every_required_model_is_ready(monkeypatch) -> None:
    """All-ready yields no blocking entries and no reason."""
    _install(
        monkeypatch,
        {rid: _status(rid, ResourceStatus.READY) for rid in _STUB_IDS},
    )

    gate = model_gate.evaluate_model_gate()

    assert gate.ready is True
    assert gate.missing == ()
    assert gate.reason() is None
    assert gate.to_dict()["missing"] == []


def test_gate_blocks_when_a_probe_raises(monkeypatch) -> None:
    """A failing probe must block, never silently unblock, processing."""
    _install(
        monkeypatch,
        {
            "moldet": RuntimeError("probe exploded"),
            "hiro_layout": _status("hiro_layout", ResourceStatus.READY),
        },
    )

    gate = model_gate.evaluate_model_gate()

    assert gate.ready is False
    assert gate.missing_ids() == ("moldet",)
    assert gate.missing[0].status == "error"
    assert gate.missing[0].error == "probe exploded"


def test_required_model_set_is_the_extract_dependency_set() -> None:
    """Pins the gate scope: optional OCR and import-only packages stay out.

    Gating on a resource that never reaches ``ready`` would deadlock the queue
    forever, so the set is asserted against the catalog's own model entries.
    """
    assert REQUIRED_PIPELINE_MODEL_IDS == (
        "moldet",
        "molparser",
        "hiro_layout",
        "slanet_table",
    )
    # The port the gate reads through must expose exactly this set.
    assert (
        get_runtime().resource_manager.required_pipeline_model_ids
        == REQUIRED_PIPELINE_MODEL_IDS
    )
    for resource_id in REQUIRED_PIPELINE_MODEL_IDS:
        assert RESOURCE_CATALOG[resource_id].type is ResourceType.MODEL


def test_gate_blocks_against_the_real_resource_manager(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """Real wiring end-to-end: an empty model cache reads as blocked.

    The other tests stub the capability, so this one guards the seam they skip
    — the runtime port actually resolving ``check`` against the model cache.
    """
    from mbforge.foundation import paths

    empty_cache = tmp_path / "models"
    empty_cache.mkdir()
    monkeypatch.setattr(paths, "get_model_cache_dir", lambda: str(empty_cache))

    gate = model_gate.evaluate_model_gate()

    assert gate.ready is False
    assert gate.required == REQUIRED_PIPELINE_MODEL_IDS
    assert set(gate.missing_ids()) == set(REQUIRED_PIPELINE_MODEL_IDS)
