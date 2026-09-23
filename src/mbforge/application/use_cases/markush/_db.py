"""Database repository resolution for Markush use cases."""

from __future__ import annotations

import sqlite3
from collections.abc import Callable

from mbforge.application.ports import DatabaseRepository, get_database
from mbforge.foundation.errors import ValidationError


def resolve_db(library_root: str | None) -> DatabaseRepository:
    """Return the configured database repository for *library_root*."""
    if not library_root:
        raise ValidationError("library_root is required")
    return get_database(library_root)


def _run_sync[T](
    db: DatabaseRepository, operation: Callable[[sqlite3.Connection], T]
) -> T:
    with db.mol_conn() as conn:
        return operation(conn)


async def run_db_sync[T](
    db: DatabaseRepository, operation: Callable[[sqlite3.Connection], T]
) -> T:
    """Run ``operation`` inside ``db.mol_conn()`` on the infra sync pool."""
    from mbforge.application.ports import get_runtime

    runtime = get_runtime()
    return await runtime.process.tasks.run(
        runtime.process.TaskPool.SYNC, _run_sync, db, operation
    )
