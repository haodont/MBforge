"""Expose the backend's live HTTP request contract to agents.

The registry describes capabilities; this module describes the REST surface
those capabilities sit beside.  It is intentionally a snapshot port: the
composition root builds it once from the live FastAPI app, and the service
only filters and serializes what it is given.
"""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field

from mbforge.service.capabilities.registry import (
    Capability,
    CapabilityContext,
    CapabilityResult,
    register,
)
from mbforge.service.ports.api_surface import ApiRoute


class GetApiSurfaceInput(BaseModel):
    path_contains: str | None = Field(
        None,
        max_length=200,
        description="Case-insensitive substring filter on the route path.",
    )
    offset: int = Field(0, ge=0)
    limit: int = Field(50, ge=1, le=200)


class ApiFieldInfo(BaseModel):
    name: str
    type: str
    required: bool
    default: Any | None = None
    description: str | None = None
    aliases: list[str] = Field(default_factory=list)
    constraints: dict[str, Any] = Field(default_factory=dict)


class ApiRouteInfo(BaseModel):
    path: str
    methods: list[str]
    request_model: str | None = None
    fields: list[ApiFieldInfo] = Field(default_factory=list)


class GetApiSurfaceOutput(BaseModel):
    """A page of routes; ``offset``/``total`` describe the filtered set."""

    routes: list[ApiRouteInfo]
    offset: int
    total: int


def _route_info(route: ApiRoute) -> ApiRouteInfo:
    return ApiRouteInfo(
        path=route.path,
        methods=list(route.methods),
        request_model=route.request_model,
        fields=[
            ApiFieldInfo(
                name=field.name,
                type=field.type,
                required=field.required,
                default=field.default,
                description=field.description,
                aliases=list(field.aliases),
                constraints=field.constraints,
            )
            for field in route.fields
        ],
    )


async def get_api_surface(
    context: CapabilityContext, request: GetApiSurfaceInput
) -> CapabilityResult:
    """Filter and page the startup snapshot; never introspect per call."""
    provider = context.api_surface
    if provider is None:
        raise RuntimeError("API surface provider is not configured")

    needle = (request.path_contains or "").strip().casefold()
    routes = [
        route
        for route in provider.routes()
        if not needle or needle in route.path.casefold()
    ]
    routes.sort(key=lambda route: (route.path, route.methods))

    total = len(routes)
    page = routes[request.offset : request.offset + request.limit]
    next_offset = request.offset + len(page)
    truncated = next_offset < total
    return CapabilityResult(
        data=GetApiSurfaceOutput(
            routes=[_route_info(route) for route in page],
            offset=request.offset,
            total=total,
        ),
        truncated=truncated,
        next_offset=next_offset if truncated else None,
    )


register(
    Capability(
        name="get_api_surface",
        description=(
            "List the backend's registered HTTP routes with each route's "
            "request-model fields, types, defaults, aliases, and constraints. "
            "Use it before calling a REST endpoint instead of guessing its "
            "path or payload."
        ),
        input_model=GetApiSurfaceInput,
        output_model=GetApiSurfaceOutput,
        mutating=False,
        handler=get_api_surface,
    )
)
