"""In-process model lifecycle and status (infra layer).

Groups the model status store (used by the SSE event stream, the readiness
diagnostics and download/load outcome reporting) together with the lifecycle
operations (loaded-state / unload / smoke test) that the
``interfaces/http/system/models.py`` endpoints delegate to. Backend singletons are
imported lazily inside functions so importing this package never pulls in
torch/transformers at app startup.
"""

from __future__ import annotations

from mbforge.adapters.runtime.models.lifecycle import clear, loaded
from mbforge.adapters.runtime.models.lifecycle import run_test as test
from mbforge.adapters.runtime.models.state import (
    ensure,
    get_all,
    get_error,
    is_ready,
    set_model_status,
)

__all__ = [
    "clear",
    "ensure",
    "get_all",
    "get_error",
    "is_ready",
    "loaded",
    "set_model_status",
    "test",
]
