"""Docking errors and the foundation-layer preprocessing + engine adapter."""

from __future__ import annotations

from mbforge.foundation.errors import MBForgeError


class DockingError(MBForgeError):
    """A docking run failed (bad input, engine error, parse failure)."""

    status_code = 400
    error_code = "docking_failed"


class DockingUnavailableError(MBForgeError):
    """A required docking dependency (engine / prep tool) is not installed."""

    status_code = 503
    error_code = "docking_unavailable"


__all__ = ["DockingError", "DockingUnavailableError"]
