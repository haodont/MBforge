"""Local molecular docking: receptor/ligand preparation and engines.

No network and no model weights: preparation uses RDKit (core) plus an optional
external PDB→PDBQT tool, and the engine shells out to a locally installed
docking binary. Everything degrades with a clear error when a dependency is
missing, never silently.
"""

from __future__ import annotations

from functools import lru_cache

from mbforge.foundation.docking.engine import UnidockProEngine
from mbforge.foundation.docking.errors import DockingError, DockingUnavailableError
from mbforge.foundation.errors import ValidationError


@lru_cache(maxsize=4)
def get_docking_engine(name: str = "unidockpro") -> UnidockProEngine:
    """Return the configured docking engine (cached per process)."""
    if name in ("", "unidockpro", "unidock"):
        return UnidockProEngine()
    raise ValidationError(f"unknown docking engine: {name!r}")


__all__ = [
    "DockingError",
    "DockingUnavailableError",
    "UnidockProEngine",
    "get_docking_engine",
]
