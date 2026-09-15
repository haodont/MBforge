"""Effective stage selection — the pipeline composition root.

The current execution boundary is Extract ∥ Detection → Markdown → Patent.
The registry is the single source of truth for both the runner and
stage-checkpoint transitions.
"""

from __future__ import annotations

from mbforge.core.stage import DEPS as _REGISTRY_DEPS
from mbforge.core.stage import ORDER as _REGISTRY_ORDER

from . import stages as _stage_modules  # noqa: F401  (triggers registration)


def effective_stage_names() -> list[str]:
    """Return the stages in the current pipeline boundary."""
    return list(_REGISTRY_ORDER)


def stage_dependencies() -> dict[str, tuple[str, ...]]:
    """Return the execution DAG: stage → prerequisites that must succeed first.

    Roots (Extract, Detection) have no prerequisites; the join fans in both;
    the linear tail depends on its single predecessor.
    """
    return {name: tuple(_REGISTRY_DEPS.get(name, ())) for name in _REGISTRY_ORDER}
