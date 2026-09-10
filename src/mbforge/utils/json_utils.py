"""JSON parsing helpers."""

from __future__ import annotations

import json


def safe_json_loads[T](value: str | None, fallback: T) -> T:
    """Parse ``value`` as JSON, returning ``fallback`` on empty or invalid input."""
    if not value:
        return fallback
    try:
        return json.loads(value)  # type: ignore[no-any-return]
    except (TypeError, json.JSONDecodeError):
        return fallback
