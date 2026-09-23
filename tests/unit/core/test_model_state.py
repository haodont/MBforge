"""Unit tests for the in-process model status store (infra.models.state)."""

from __future__ import annotations

import pytest

from mbforge.adapters.runtime.models import state as model_state


@pytest.fixture(autouse=True)
def _reset_state() -> None:
    """Reset the shared module-level state between tests."""
    model_state._model_status.clear()
    model_state._model_errors.clear()
    model_state._model_status.update({"moldet": "loading", "molparser": "loading"})


def test_dict_form_status_records_truncated_error() -> None:
    """A dict status with an error persists the failure reason (truncated)."""
    model_state.ensure("moldet", {"status": "error", "error": "x" * 1000})

    assert model_state.is_ready("moldet") is False
    assert len(model_state.get_error("moldet")) == 500  # truncated


def test_success_clears_error() -> None:
    """Reporting ready clears a previously recorded failure reason."""
    model_state.ensure("moldet", {"status": "error", "error": "boom"})
    model_state.ensure("moldet", {"status": "ready"})

    assert model_state.is_ready("moldet") is True
    assert model_state.get_error("moldet") is None


def test_plain_string_status_no_error() -> None:
    """Legacy plain-string writes keep working through the public writer."""
    model_state.ensure("molparser", "loading")

    assert model_state.get_all()["molparser"] == "loading"
    assert model_state.get_error("molparser") is None
