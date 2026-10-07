"""Model-asset seam for the inference backends.

The heavy inference backends live in ``foundation`` and must not import
``server``. The concrete resource manager — catalog, cache-dir resolution,
download and verification — is a server concern, so it is *injected* here by
the composition root (``server/runtime_provider.create_runtime_provider``)
instead of being imported across layers.

The default resolver is **local-only**: it resolves nothing and never
downloads, so importing or exercising a backend without a configured resolver
degrades cleanly (the backend reports "model not found") rather than reaching
into another layer.
"""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path
from typing import Protocol, runtime_checkable


@runtime_checkable
class ResourceResolver(Protocol):
    """The subset of ``server.resource_manager.ResourceManager`` backends need."""

    def get_molparser_path(self) -> Path | None: ...

    def get_slanet_path(self) -> Path | None: ...

    def resolve_model_for_backend(
        self, model_id: str, subpath: str | None = None
    ) -> Path | None: ...

    def ensure(self, model_id: str) -> object: ...


class _NullResolver:
    """Local-only resolver: nothing is resolved and nothing is downloaded."""

    def get_molparser_path(self) -> Path | None:
        return None

    def get_slanet_path(self) -> Path | None:
        return None

    def resolve_model_for_backend(
        self, model_id: str, subpath: str | None = None
    ) -> Path | None:
        return None

    def ensure(self, model_id: str) -> object:
        return None


_resolver: ResourceResolver = _NullResolver()
_status_sink: Callable[[str, str], None] | None = None


def configure_resource_resolver(resolver: ResourceResolver) -> None:
    """Install the concrete resource resolver (called by the composition root)."""
    global _resolver
    _resolver = resolver


def get_resource_resolver() -> ResourceResolver:
    """Return the active resolver (the local-only default until configured)."""
    return _resolver


def configure_model_status_sink(sink: Callable[[str, str], None] | None) -> None:
    """Install the sink that records per-model load status (see ``prewarm``)."""
    global _status_sink
    _status_sink = sink


def emit_model_status(name: str, status: str) -> None:
    """Record a model's load status via the installed sink (no-op if unset)."""
    if _status_sink is not None:
        _status_sink(name, status)


__all__ = [
    "ResourceResolver",
    "configure_model_status_sink",
    "configure_resource_resolver",
    "emit_model_status",
    "get_resource_resolver",
]
