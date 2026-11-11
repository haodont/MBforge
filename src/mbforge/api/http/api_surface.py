"""FastAPI adapter for the API surface capability.

The service layer only sees the neutral ``ApiRoute`` snapshot. This module
owns FastAPI/Pydantic introspection and is built once by the composition root
so a capability call never re-scans the app.
"""

from __future__ import annotations

from collections.abc import Iterable, Iterator
from typing import Any

from fastapi import FastAPI
from fastapi.routing import APIRoute
from pydantic import AliasChoices, AliasPath, BaseModel
from pydantic_core import PydanticUndefined

from mbforge.service.ports.api_surface import ApiField, ApiRoute


def _effective_api_routes(
    routes: Iterable[Any],
) -> Iterator[tuple[str, set[str], Any, Any]]:
    """Yield ``(path, methods, body_field, dependant)`` for real API routes.

    FastAPI 0.141 wraps included routers in lazy ``_IncludedRouter`` objects,
    so ``app.routes`` is not a flat ``APIRoute`` list.  ``effective_route_contexts``
    is the maintained flattening path across both eager and lazy includes.
    """
    for route in routes:
        if isinstance(route, APIRoute):
            yield (
                route.path,
                set(route.methods or ()),
                route.body_field,
                route.dependant,
            )
            continue
        flatten = getattr(route, "effective_route_contexts", None)
        if not callable(flatten):
            continue
        for context in flatten():
            if not isinstance(getattr(context, "original_route", None), APIRoute):
                continue
            yield (
                context.path,
                set(context.methods or ()),
                context.body_field,
                context.dependant,
            )


def _request_model(body_field: Any) -> type[BaseModel] | None:
    annotation = getattr(getattr(body_field, "field_info", None), "annotation", None)
    if isinstance(annotation, type) and issubclass(annotation, BaseModel):
        return annotation
    return None


def _type_name(annotation: Any) -> str:
    if isinstance(annotation, type):
        return annotation.__name__
    return str(annotation).replace("typing.", "")


def _default(info: Any) -> Any | None:
    if info.is_required():
        return None
    if info.default_factory is not None:
        return "<factory>"
    value = info.default
    if value is PydanticUndefined:
        return None
    if isinstance(value, (str, int, float, bool)) or value is None:
        return value
    return repr(value)


def _aliases(info: Any) -> tuple[str, ...]:
    aliases: list[str] = []
    if info.alias:
        aliases.append(str(info.alias))
    validation = info.validation_alias
    if isinstance(validation, AliasChoices):
        aliases.extend(str(choice) for choice in validation.choices)
    elif isinstance(validation, AliasPath):
        aliases.append(".".join(str(part) for part in validation.path))
    elif isinstance(validation, str):
        aliases.append(validation)
    return tuple(dict.fromkeys(aliases))


def _constraints(info: Any) -> dict[str, Any]:
    constraints: dict[str, Any] = {}
    for metadata in info.metadata:
        for name in ("gt", "ge", "lt", "le", "min_length", "max_length", "pattern"):
            value = getattr(metadata, name, None)
            if value is None:
                continue
            if isinstance(value, (str, int, float, bool)):
                constraints[name] = value
            else:
                constraints[name] = str(value)
    return constraints


def _field(name: str, info: Any) -> ApiField:
    return ApiField(
        name=name,
        type=_type_name(info.annotation),
        required=info.is_required(),
        default=_default(info),
        description=info.description,
        aliases=_aliases(info),
        constraints=_constraints(info),
    )


def _fields(model: type[BaseModel]) -> tuple[ApiField, ...]:
    return tuple(_field(name, info) for name, info in model.model_fields.items())


def _param_fields(dependant: Any, attribute: str) -> tuple[ApiField, ...]:
    params = getattr(dependant, attribute, None) if dependant is not None else None
    return tuple(_field(str(param.name), param.field_info) for param in params or ())


class FastApiSurfaceProvider:
    """Immutable snapshot of the app's API routes and request models."""

    def __init__(self, app: FastAPI) -> None:
        routes = [
            ApiRoute(
                path=path,
                methods=tuple(sorted(methods)),
                request_model=model.__name__ if model is not None else None,
                fields=_fields(model) if model is not None else (),
                query_params=_param_fields(dependant, "query_params"),
                path_params=_param_fields(dependant, "path_params"),
            )
            for path, methods, body_field, dependant in _effective_api_routes(
                app.routes
            )
            for model in (_request_model(body_field),)
        ]
        routes.sort(key=lambda route: (route.path, route.methods))
        self._routes = tuple(routes)

    def routes(self) -> tuple[ApiRoute, ...]:
        return self._routes
