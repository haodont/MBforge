"""Identifier generation helpers."""

from __future__ import annotations

import uuid


def short_id() -> str:
    """Return a 16-character hexadecimal identifier."""
    return uuid.uuid4().hex[:16]
