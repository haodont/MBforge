"""Unit tests for the core stage registry (TODO/services-layer-plan.md A5)."""

from __future__ import annotations

import pytest

from mbforge.core.stage import ORDER, REGISTRY, StageResult, next_after, register
from mbforge.pipeline import stages as _pipeline_stages  # noqa: F401


@pytest.fixture
def _clean_registry():
    """Snapshot the registry so a test stage never leaks into other tests."""
    saved_reg = dict(REGISTRY)
    saved_order = list(ORDER)
    yield
    REGISTRY.clear()
    REGISTRY.update(saved_reg)
    ORDER[:] = saved_order


def test_registered_stage_needs_only_a_decorator(_clean_registry) -> None:
    """Adding a temporary stage = one class + one decorator."""

    @register(after="markdown")
    class TempProbeStage:
        name = "temp_probe"

        def execute(self, ctx) -> StageResult:  # type: ignore[no-untyped-def]
            return StageResult(stage="temp_probe", status="success", message="")

    assert "temp_probe" in REGISTRY
    assert REGISTRY["temp_probe"].name == "temp_probe"
    assert ORDER == [
        "extract",
        "detection",
        "join",
        "markdown",
        "temp_probe",
        "patent",
    ]
    assert next_after("markdown") == "temp_probe"
    assert next_after("temp_probe") == "patent"


def test_register_rejects_duplicate_and_unknown_after(_clean_registry) -> None:
    """Duplicate names and dangling ``after`` anchors fail loudly."""

    with pytest.raises(ValueError, match="already registered"):

        @register
        class ExtractAgain:
            name = "extract"

            def execute(self, ctx) -> StageResult:  # type: ignore[no-untyped-def]
                return StageResult(stage="extract", status="success", message="")

    with pytest.raises(ValueError, match="not registered"):

        @register(after="no_such_stage")
        class OrphanStage:
            name = "orphan"

            def execute(self, ctx) -> StageResult:  # type: ignore[no-untyped-def]
                return StageResult(stage="orphan", status="success", message="")


def test_next_after_walks_pipeline_order() -> None:
    """next_after mirrors the historical stage_checkpoint.next_stage semantics."""
    assert next_after(None) == "extract"
    assert next_after("extract") == "detection"
    assert next_after("patent") is None
    assert next_after("bogus") == "extract"
