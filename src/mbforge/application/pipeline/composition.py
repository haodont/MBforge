"""Effective stage selection — the pipeline composition root.

The current execution boundary is Extract → Join → Markdown → Patent.
The registry is the single source of truth for both the runner and
stage-checkpoint transitions.
"""

from __future__ import annotations

from mbforge.application.pipeline import (
    stages as _stage_modules,  # noqa: F401  (triggers registration)
)
from mbforge.application.pipeline.stage import DEPS as _REGISTRY_DEPS
from mbforge.application.pipeline.stage import ORDER as _REGISTRY_ORDER


def effective_stage_names() -> list[str]:
    """Return the stages in the current pipeline boundary."""
    return list(_REGISTRY_ORDER)


def stage_dependencies() -> dict[str, tuple[str, ...]]:
    """Return the execution DAG: stage → prerequisites that must succeed first.

    Extract is the root; join, markdown and patent form a linear tail.
    """
    return {name: tuple(_REGISTRY_DEPS.get(name, ())) for name in _REGISTRY_ORDER}
