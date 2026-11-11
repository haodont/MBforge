"""Capability registry — the single source of truth for agent-callable tasks.

Capabilities are user-level operations, not HTTP route mirrors. Adapters
(HTTP today) validate transport concerns; this module owns the mode guard,
input validation, and output type check.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Any, Literal

from pydantic import BaseModel, Field
from pydantic import ValidationError as PydanticValidationError

from mbforge.foundation.errors import (
    CapabilityForbiddenError,
    NotFoundError,
    ValidationError,
)
from mbforge.service.use_cases.documents.document_refs import is_full_doc_id
from mbforge.service.use_cases.documents.library import LibraryStore

if TYPE_CHECKING:
    from mbforge.service.ports.api_surface import ApiSurfaceProvider

CapabilityMode = Literal["readonly", "edit"]

#: Shown to agents in the published input schema: what a ``doc_id`` may be.
DOC_ID_DESCRIPTION = (
    "Document reference: the full 64-character doc_id, a unique doc_id "
    "prefix (8 hex characters or more), the exact file name, the exact "
    "document title, or the 12-character short_id returned by resolve_document."
)


def doc_id_field(**overrides: Any) -> Any:
    """Return the shared ``doc_id`` field with its agent-facing description."""
    params: dict[str, Any] = {
        "min_length": 1,
        "max_length": 128,
        "description": DOC_ID_DESCRIPTION,
    }
    params.update(overrides)
    return Field(..., **params)


@dataclass(frozen=True)
class CapabilityContext:
    """Server-resolved invocation context; callers never supply library_root."""

    library_root: str
    mode: CapabilityMode
    api_surface: ApiSurfaceProvider | None = None


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
    if not capability.name:
        raise RuntimeError("capability name must not be empty")
    for label in ("input_model", "output_model"):
        model = getattr(capability, label)
        if not isinstance(model, type) or not issubclass(model, BaseModel):
            raise TypeError(f"{capability.name} {label} must be a BaseModel subclass")
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


def _resolve_document_reference(
    context: CapabilityContext, payload: dict[str, Any]
) -> dict[str, Any]:
    """Map a human document reference in *payload* to its canonical doc_id.

    Agents and users hold a title, a file name, or a hash prefix — not the
    64-character SHA-256 id. Resolution happens once, here, so every
    document-scoped capability accepts the same references. A reference that
    matches nothing is left untouched: the handler then reports the document
    as missing, exactly as it did before.
    """
    reference = payload.get("doc_id")
    if not isinstance(reference, str):
        return payload
    ref = reference.strip()
    if not ref or is_full_doc_id(ref):
        return payload
    if not Path(context.library_root).is_dir():
        return payload

    resolved = LibraryStore.get(context.library_root).resolve_reference(ref)
    if resolved is None:
        return payload
    return {**payload, "doc_id": resolved}


async def invoke(
    name: str,
    context: CapabilityContext,
    payload: dict[str, Any],
) -> CapabilityResult:
    """Validate mode/input, run the handler, and enforce the output type."""
    capability = get_capability(name)
    if capability.mutating and context.mode != "edit":
        raise CapabilityForbiddenError(
            "mutating capability requires edit mode",
            detail=capability.name,
        )
    try:
        request = capability.input_model.model_validate(
            _resolve_document_reference(context, payload)
        )
    except PydanticValidationError as exc:
        errors = exc.errors(include_input=False, include_url=False)
        fields = "; ".join(
            f"{'.'.join(str(part) for part in error['loc'])}: {error['msg']}"
            for error in errors
        )
        raise ValidationError(
            "invalid capability input",
            detail=fields or "validation failed",
            context={"validation_errors": errors},
        ) from exc
    result = await capability.handler(context, request)
    if not isinstance(result.data, capability.output_model):
        raise RuntimeError(
            f"{name} returned {type(result.data).__name__}, "
            f"expected {capability.output_model.__name__}"
        )
    return result
