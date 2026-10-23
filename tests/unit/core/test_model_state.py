"""Unit tests for the in-process model status store (``mbforge.server.models.state``)."""

from __future__ import annotations

import pytest

from mbforge.server.models import state as model_state


@pytest.fixture(autouse=True)
def _reset_state() -> None:
    """Reset the shared module-level state for isolated runs."""
    model_state._model_status.clear()
    model_state._model_errors.clear()
    model_state._model_status.update({"moldet": "loading", "molparser": "loading"})


def test_status_store_records_and_clears_failure_reasons() -> None:
    """A dict status persists a truncated failure reason, reporting ready clears
    it, and the legacy plain-string writer still works without an error."""
    model_state.ensure("moldet", {"status": "error", "error": "x" * 1000})
    assert model_state.is_ready("moldet") is False
    assert len(model_state.get_error("moldet")) == 500  # truncated

    model_state.ensure("moldet", {"status": "ready"})
    assert model_state.is_ready("moldet") is True
    assert model_state.get_error("moldet") is None

    model_state.ensure("molparser", "loading")
    assert model_state.get_all()["molparser"] == "loading"
    assert model_state.get_error("molparser") is None
