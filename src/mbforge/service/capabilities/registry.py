"""Capability registry — the single source of truth for agent-callable tasks.

Capabilities are user-level operations, not HTTP route mirrors. Adapters
(HTTP today) validate transport concerns; this module owns the mode guard,
input validation, and output type check.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Any, Literal

from pydantic import BaseModel
from pydantic import ValidationError as PydanticValidationError

from mbforge.foundation.errors import (
    CapabilityForbiddenError,
    NotFoundError,
    ValidationError,
)

CapabilityMode = Literal["readonly", "edit"]


@dataclass(frozen=True)
class CapabilityContext:
    """Server-resolved invocation context; callers never supply library_root."""

    library_root: str
    mode: CapabilityMode


@dataclass(frozen=True)
class CapabilityResult:
    """One capability response plus explicit truncation metadata."""

    data: BaseModel
    truncated: bool = False
    next_offset: int | None = None


@dataclass(frozen=True)
class Capability:
    """One agent-callable task and its typed contract."""

    name: str
    description: str
    input_model: type[BaseModel]
    output_model: type[BaseModel]
    mutating: bool
    handler: Callable[[CapabilityContext, Any], Awaitable[CapabilityResult]]


_REGISTRY: dict[str, Capability] = {}


def register(capability: Capability) -> None:
    """Register one capability; duplicate names are a programming error."""
    if capability.name in _REGISTRY:
        raise RuntimeError(f"duplicate capability: {capability.name}")
    _REGISTRY[capability.name] = capability


def all_capabilities() -> tuple[Capability, ...]:
    """Return capabilities in registration order (deterministic manifests)."""
    return tuple(_REGISTRY.values())


def get_capability(name: str) -> Capability:
    capability = _REGISTRY.get(name)
    if capability is None:
        raise NotFoundError("unknown capability", detail=name)
    return capability


async def invoke(
    name: str,
    context: CapabilityContext,
    payload: dict[str, Any],
) -> CapabilityResult:
    """Validate mode/input, run the handler, and enforce the output type."""
    capability = get_capability(name)
    if capability.mutating and context.mode != "edit":
        raise CapabilityForbiddenError(
            "capability requires edit mode",
            detail="send X-MBForge-Token for mutating capabilities",
        )
    try:
        request = capability.input_model.model_validate(payload)
    except PydanticValidationError as exc:
        raise ValidationError("invalid capability input", detail=str(exc)) from exc
    result = await capability.handler(context, request)
    if not isinstance(result.data, capability.output_model):
        raise RuntimeError(
            f"{name} returned {type(result.data).__name__}, "
            f"expected {capability.output_model.__name__}"
        )
    return result
