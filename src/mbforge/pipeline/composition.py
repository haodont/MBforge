"""Effective stage selection — the pipeline composition root.

The current execution boundary is Extract ∥ Detection → Markdown → Patent.
The registry is the single source of truth for both the runner and
stage-checkpoint transitions.
"""

from __future__ import annotations

from ..core.stage import ORDER as _REGISTRY_ORDER
from . import stages as _stage_modules  # noqa: F401  (triggers registration)


def effective_stage_names() -> list[str]:
    """Return the stages in the current pipeline boundary."""
    return list(_REGISTRY_ORDER)
