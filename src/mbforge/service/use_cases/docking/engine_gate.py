"""Engine-availability gate for docking.

Mirrors ``pipeline.model_gate``: a cheap predicate the docking worker consults
before claiming a job, so a missing engine / GPU leaves jobs ``pending`` instead
of failing them.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from mbforge.foundation.logger import get_logger

logger = get_logger(__name__)


@dataclass(frozen=True)
class DockingGateResult:
    """Whether the docking engine can run right now."""

    ready: bool
    engine: str
    reason: str

    def to_dict(self) -> dict[str, Any]:
        return {"ready": self.ready, "engine": self.engine, "reason": self.reason}


def _engine():  # noqa: ANN202 — patched in tests
    from mbforge.service.ports import get_runtime

    return get_runtime().docking_engine.get_docking_engine()


def evaluate_engine_gate() -> DockingGateResult:
    """Probe engine availability (no GPU work, safe to poll)."""
    try:
        engine = _engine()
        available, reason = engine.availability()
    except Exception as exc:  # noqa: BLE001 — a broken probe must not raise
        logger.warning("docking engine gate probe failed: %s", exc)
        return DockingGateResult(ready=False, engine="unknown", reason=str(exc)[:300])
    return DockingGateResult(
        ready=available, engine=getattr(engine, "name", "unknown"), reason=reason
    )


__all__ = ["DockingGateResult", "evaluate_engine_gate"]
