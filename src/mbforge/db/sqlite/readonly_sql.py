"""Read-only SQL access for the agent's ``library_sql`` tool.

The assistant may ask ad-hoc questions the structured tools do not cover, so the
``library_sql`` tool runs a single read-only SELECT against the library
database. Safety is layered — never a single check:

1. A dedicated connection opened with ``mode=ro`` (URI), so no statement can
   write even if the guard were bypassed.
2. ``PRAGMA query_only=ON`` on that connection as a second write barrier.
3. A statement guard: exactly one statement, starting with ``SELECT``/``WITH``,
   with SQLite-internal tables and ``ATTACH``/``PRAGMA``/``VACUUM`` refused.
4. A row cap, per-value truncation, and a progress-handler deadline so a
   pathological query cannot exhaust memory or hang the request thread.
"""

from __future__ import annotations

import sqlite3
from contextlib import closing
from pathlib import Path
from typing import Any

from mbforge.foundation.errors import ValidationError
from mbforge.foundation.logger import get_logger

logger = get_logger("mbforge.db.sqlite.readonly_sql")

#: Default and maximum number of rows a tool query may return.
DEFAULT_MAX_ROWS = 200
MAX_ROWS_LIMIT = 1000
#: Long text values (evidence/crops) are truncated before leaving the DB.
MAX_VALUE_CHARS = 2000
#: SQLite VM instructions before a query is interrupted (~1s of work).
_PROGRESS_OPS = 2_000_000

#: Substrings that must not appear anywhere in an agent-supplied query.
_DENIED_TOKENS = ("sqlite_master", "sqlite_", "attach", "detach", "pragma", "vacuum")


def validate_readonly_sql(sql: str) -> str:
    """Return the normalized single read-only statement, or raise ValidationError.

    This is a defence-in-depth gate on top of the read-only connection; it aims
    to reject obvious misuse with a clear message, not to parse SQL.
    """
    statement = sql.strip()
    if statement.endswith(";"):
        statement = statement[:-1].rstrip()
    if not statement:
        raise ValidationError("sql is empty")
    if ";" in statement:
        raise ValidationError("only a single SQL statement is allowed")
    first = statement.split(None, 1)[0].lower()
    if first not in ("select", "with"):
        raise ValidationError("only read-only SELECT / WITH statements are allowed")
    lowered = statement.lower()
    for token in _DENIED_TOKENS:
        if token in lowered:
            raise ValidationError(f"disallowed token in query: {token}")
    return statement


def _connect_readonly(db_path: Path) -> sqlite3.Connection:
    # ``uri=True`` + ``mode=ro`` makes the file unwritable for this connection.
    conn = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA query_only=ON")
    return conn


def introspect_schema(db_path: str | Path) -> list[dict[str, Any]]:
    """Return ``[{table, columns:[{name,type}]}]`` for the library database.

    FTS5 shadow tables (``*_data/_idx/_content/_docsize/_config``) are hidden so
    the model sees the business tables it should query.
    """
    path = Path(db_path)
    if not path.is_file():
        return []
    schema: list[dict[str, Any]] = []
    with closing(_connect_readonly(path)) as conn:
        tables = conn.execute(
            "SELECT name FROM sqlite_master WHERE type IN ('table','view') "
            "AND name NOT LIKE 'sqlite_%' ORDER BY name"
        ).fetchall()
        for row in tables:
            name = row["name"]
            if name.endswith(("_data", "_idx", "_content", "_docsize", "_config")):
                continue
            columns = conn.execute(
                "SELECT name, type FROM pragma_table_info(?)", (name,)
            ).fetchall()
            schema.append(
                {
                    "table": name,
                    "columns": [
                        {"name": column["name"], "type": column["type"]}
                        for column in columns
                    ],
                }
            )
    return schema


def _truncate(value: Any) -> Any:
    if isinstance(value, str) and len(value) > MAX_VALUE_CHARS:
        return value[:MAX_VALUE_CHARS] + "…"
    if isinstance(value, (bytes, bytearray, memoryview)):
        return f"<{len(bytes(value))} bytes>"
    return value


def run_query(
    db_path: str | Path, sql: str, *, max_rows: int = DEFAULT_MAX_ROWS
) -> dict[str, Any]:
    """Execute one guarded read-only SELECT and return a tabular result.

    Returns ``{columns, rows, row_count, truncated}``. ``rows`` is a list of
    value lists (JSON-friendly), so the shape survives the tool boundary.
    """
    statement = validate_readonly_sql(sql)
    capped = max(1, min(int(max_rows), MAX_ROWS_LIMIT))
    path = Path(db_path)
    if not path.is_file():
        raise ValidationError("library database does not exist")

    def _deadline() -> int:
        # Any non-zero return aborts the statement with OperationalError("interrupted").
        return 1

    conn = _connect_readonly(path)
    try:
        conn.set_progress_handler(_deadline, _PROGRESS_OPS)
        try:
            cursor = conn.execute(statement)
            columns = [description[0] for description in (cursor.description or [])]
            fetched = cursor.fetchmany(capped + 1)
        except sqlite3.OperationalError as exc:
            raise ValidationError(f"query failed: {exc}") from exc
    finally:
        conn.close()

    truncated = len(fetched) > capped
    rows = [[_truncate(value) for value in tuple(row)] for row in fetched[:capped]]
    return {
        "columns": columns,
        "rows": rows,
        "row_count": len(rows),
        "truncated": truncated,
    }


__all__ = [
    "DEFAULT_MAX_ROWS",
    "MAX_ROWS_LIMIT",
    "introspect_schema",
    "run_query",
    "validate_readonly_sql",
]
