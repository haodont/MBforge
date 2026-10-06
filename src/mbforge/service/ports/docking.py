"""Docking engine port.

The application depends on this narrow boundary instead of a concrete engine,
so tests can inject a deterministic fake and future engines (DiffDock, …) can
be swapped in without touching use cases. The request/pose value objects live in
:mod:`mbforge.domain.docking` (shared with the engine implementations).
"""

from __future__ import annotations

from typing import Protocol

from mbforge.domain.docking import DockingPose, DockingRequest


class DockingEngine(Protocol):
    """A molecular docking engine (prepares inputs and runs the search)."""

    name: str

    def availability(self) -> tuple[bool, str]:
        """Return ``(available, reason)`` — reason is empty when available."""
        ...

    def dock(self, request: DockingRequest) -> list[DockingPose]:
        """Prepare inputs, run the search, and return ranked poses.

        Raises a ``MBForgeError`` subclass on failure; the caller records it on
        the job.
        """
        ...


__all__ = ["DockingEngine", "DockingPose", "DockingRequest"]
