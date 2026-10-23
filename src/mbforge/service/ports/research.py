"""Conversation runtime boundaries; persistence lives in the repository port."""

from collections.abc import AsyncIterator
from typing import Protocol

from mbforge.contracts.research import ResearchEvent, ResearchTurnScope


class ResearchRuntime(Protocol):
    def stream(self, credential: str) -> AsyncIterator[ResearchEvent]: ...

    def is_active(self, session_id: str) -> bool: ...


class ResearchTurnRegistry(Protocol):
    def register(self, scope: ResearchTurnScope) -> str: ...

    def resolve(self, credential: str) -> ResearchTurnScope | None: ...

    def active(self, library_root: str, session_id: str, request_id: str) -> bool: ...

    def revoke(self, credential: str) -> None: ...


_runtime: ResearchRuntime | None = None
_registry: ResearchTurnRegistry | None = None


def configure_research_runtime(
    runtime: ResearchRuntime, registry: ResearchTurnRegistry
) -> None:
    global _runtime, _registry
    _runtime, _registry = runtime, registry


def get_research_runtime() -> ResearchRuntime:
    if _runtime is None:
        raise RuntimeError("research runtime is not configured")
    return _runtime


def get_research_registry() -> ResearchTurnRegistry:
    if _registry is None:
        raise RuntimeError("research registry is not configured")
    return _registry
