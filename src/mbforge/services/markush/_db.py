"""DB-handle resolution for the Markush services.

Routers pass ``library_root`` only; services own the DatabaseManager
handle (AGENTS.md: routers must not import DatabaseManager).
"""

from __future__ import annotations

import asyncio
import sqlite3
from collections.abc import Callable

from ...storage.sqlite.database import DatabaseManager
from ...utils.errors import ValidationError


def resolve_db(library_root: str | None) -> DatabaseManager:
    """Return the DatabaseManager for *library_root* (required)."""
    if not library_root:
        raise ValidationError("library_root is required")
    return DatabaseManager.get(library_root)


def _run_sync[T](
    db: DatabaseManager, operation: Callable[[sqlite3.Connection], T]
) -> T:
    with db.mol_conn() as conn:
        return operation(conn)


async def run_db_sync[T](
    db: DatabaseManager, operation: Callable[[sqlite3.Connection], T]
) -> T:
    """Run ``operation`` inside ``db.mol_conn()`` on the infra sync pool."""
    from ...infra.process.executors import sync_executor

    loop = asyncio.get_running_loop()
    return await loop.run_in_executor(sync_executor(), _run_sync, db, operation)
