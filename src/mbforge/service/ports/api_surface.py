"""Port for a snapshot of the live HTTP API surface."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Protocol


@dataclass(frozen=True)
class ApiField:
    """One request-model field as seen by an HTTP caller."""

    name: str
    type: str
    required: bool
    default: Any | None
    description: str | None
    aliases: tuple[str, ...]
    constraints: dict[str, Any]


@dataclass(frozen=True)
class ApiRoute:
    """One HTTP route and its request model, if it has one."""

    path: str
    methods: tuple[str, ...]
    request_model: str | None
    fields: tuple[ApiField, ...]


class ApiSurfaceProvider(Protocol):
    """Snapshot source for the live HTTP routes."""

    def routes(self) -> tuple[ApiRoute, ...]: ...
