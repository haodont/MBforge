"""HTTP adapter for the capability registry.

Read-only calls need no credential. Mutating calls require the library's
capability token in ``X-MBForge-Token``; the registry re-checks this so a new
adapter cannot accidentally bypass the mode guard.
"""

from __future__ import annotations

import contextlib
import json
from typing import Annotated, Any

from fastapi import APIRouter, Body, Depends, Request
from fastapi.responses import PlainTextResponse
from pydantic import BaseModel

from mbforge.foundation.capability_token import (
    capability_token_path,
    ensure_capability_token,
    verify_capability_token,
)
from mbforge.foundation.layout import resolve_library_root
from mbforge.service.capabilities import (
    CapabilityContext,
    all_capabilities,
    invoke,
)

router = APIRouter()


class CapabilityInfo(BaseModel):
    name: str
    description: str
    mutating: bool
    input_schema: dict[str, Any]
    output_schema: dict[str, Any]


class CapabilityManifest(BaseModel):
    success: bool = True
    capabilities: list[CapabilityInfo]
    token_path: str


class CapabilityResponse(BaseModel):
    success: bool = True
    capability: str
    data: dict[str, Any]
    truncated: bool = False
    next_offset: int | None = None


def _context(request: Request) -> CapabilityContext:
    root = str(resolve_library_root(None))
    token = request.headers.get("x-mbforge-token")
    mode = "edit" if verify_capability_token(root, token) else "readonly"
    return CapabilityContext(library_root=root, mode=mode)


def _guide(token_path: str) -> str:
    lines = [
        "# MBForge capabilities",
        "",
        "Base URL: `http://127.0.0.1:18792`",
        "",
        "## Modes",
        "- `readonly`: omit `X-MBForge-Token`. Mutating capabilities return 403.",
        "- `edit`: read the token file and send `X-MBForge-Token`.",
        f"Token file: `{token_path}`",
        "",
        "## Invoke",
        "POST `/api/v1/capabilities/{name}` with a JSON body matching the input schema.",
        "A successful response wraps the result in `data`.",
        "",
    ]
    for capability in all_capabilities():
        mode = "edit" if capability.mutating else "readonly"
        schema = json.dumps(capability.input_model.model_json_schema(), indent=2)
        lines.extend(
            [
                f"### `{capability.name}`",
                "",
                capability.description,
                "",
                f"Mode: `{mode}`",
                "",
                "```json",
                schema,
                "```",
                "",
            ]
        )
    return "\n".join(lines)


@router.get("", response_model=CapabilityManifest)
async def capability_manifest() -> CapabilityManifest:
    root = str(resolve_library_root(None))
    return CapabilityManifest(
        capabilities=[
            CapabilityInfo(
                name=capability.name,
                description=capability.description,
                mutating=capability.mutating,
                input_schema=capability.input_model.model_json_schema(),
                output_schema=capability.output_model.model_json_schema(),
            )
            for capability in all_capabilities()
        ],
        token_path=str(capability_token_path(root)),
    )


@router.get("/guide", response_class=PlainTextResponse)
async def capability_guide() -> str:
    root = str(resolve_library_root(None))
    token_path = capability_token_path(root)
    # A read-only library can still serve the guide; writes will fail.
    with contextlib.suppress(OSError):
        ensure_capability_token(root)
    return _guide(str(token_path))


@router.post("/{name}", response_model=CapabilityResponse)
async def capability_invoke(
    name: str,
    payload: Annotated[dict[str, Any], Body(...)],
    context: Annotated[CapabilityContext, Depends(_context)],
) -> CapabilityResponse:
    result = await invoke(name, context, payload)
    return CapabilityResponse(
        capability=name,
        data=result.data.model_dump(mode="json"),
        truncated=result.truncated,
        next_offset=result.next_offset,
    )
