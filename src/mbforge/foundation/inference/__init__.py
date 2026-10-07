"""MBForge fixed model backends — local inference package.

Provides lazy-loading wrappers for the heavyweight local models used by the
pipeline (MolParser-Mobile for chemical structure recognition and MolDetv2
for molecule detection). Model assets are resolved through the seam in
:mod:`mbforge.foundation.inference.assets`, which the server composition root
configures — this package never imports ``server``.

Every submodule the runtime provider resolves lazily by attribute must be bound
here first: ``_DynamicModule`` uses ``getattr`` on this package, and a submodule
that was never imported is simply absent (``table_slanet`` was, so table
recognition silently degraded to empty).
"""

from __future__ import annotations

from mbforge.foundation.inference import (
    molparser,  # noqa: F401
    table_slanet,  # noqa: F401
)
