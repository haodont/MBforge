"""In-process model status tracking.

Shared state for the model server — replaces the module-level globals that
used to live in ``server.py``. Tracks per-model status and the last failure
reason (sanitized) so the readiness diagnostics and the SSE event stream can
surface model availability without tightly coupling to the FastAPI app
instance.
"""

from __future__ import annotations

from typing import Any

# Model status tracking
_model_status: dict[str, str] = {
    "moldet": "loading",
    "molparser": "loading",
}

# Last failure reason per model (sanitized), cleared on success. Used by the
# readiness diagnostics to surface why a model download/load failed.
_model_errors: dict[str, str] = {}

_ERROR_MAX_LEN = 500


def _normalize(status: str | dict[str, Any]) -> tuple[str, str | None]:
    """Return ``(status, error)`` from a plain string or dict form.

    A dict of the form ``{"status": ..., "error": ...}`` persists the failure
    reason alongside the status; a falsy ``error`` clears the recorded reason.
    """
    if isinstance(status, dict):
        value = str(status.get("status", "error"))
        error = status.get("error")
        return value, (str(error) if error else None)
    return status, None


def set_model_status(name: str, status: str | dict[str, Any]) -> None:
    """Update model status (legacy writer).

    Accepts a plain status string or a dict of the form
    ``{"status": ..., "error": ...}``.
    """
    value, error = _normalize(status)
    _model_status[name] = value
    if error:
        _model_errors[name] = error[:_ERROR_MAX_LEN]
    else:
        _model_errors.pop(name, None)


def ensure(name: str, status: str | dict[str, Any]) -> None:
    """Update model status and persist a sanitized failure reason.

    This is the public status writer — callers reporting a download or load
    outcome go through here so the event stream and readiness diagnostics
    observe one consistent state. Failure reasons are truncated; success
    clears any previously recorded reason.
    """
    set_model_status(name, status)


def is_ready(name: str) -> bool:
    """Return whether ``name`` is currently marked ready."""
    return _model_status.get(name) == "ready"


def get_error(name: str) -> str | None:
    """Return the last recorded failure reason for a model, if any."""
    return _model_errors.get(name)


def get_all() -> dict[str, str]:
    """Get current model statuses."""
    return _model_status.copy()
