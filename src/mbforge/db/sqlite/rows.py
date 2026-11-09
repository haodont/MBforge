"""Shared SQLite row conversion helpers."""

from __future__ import annotations

import sqlite3
from typing import Any


def row_to_dict(row: sqlite3.Row | None) -> dict[str, Any] | None:
    """Return *row* as a plain dict, or ``None`` when there is no row."""
    return dict(row) if row is not None else None
