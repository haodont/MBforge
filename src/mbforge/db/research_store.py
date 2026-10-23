"""Strict conversation snapshots; queue and Patent facts remain their own authorities."""

from __future__ import annotations

from pathlib import Path

from mbforge.contracts.research import ResearchSession, ResearchSessionSummary
from mbforge.db.sqlite.database import DatabaseManager
from mbforge.foundation.errors import ConflictError
from mbforge.foundation.layout import LibraryLayout


def load(library_root: str | Path, session_id: str) -> ResearchSession | None:
    with DatabaseManager.get(str(library_root)).kb_conn() as conn:
        row = conn.execute(
            "SELECT payload FROM research_sessions WHERE session_id = ?", (session_id,)
        ).fetchone()
    return ResearchSession.model_validate_json(row["payload"]) if row else None


def list_sessions(library_root: str | Path) -> list[ResearchSessionSummary]:
    with DatabaseManager.get(str(library_root)).kb_conn() as conn:
        rows = conn.execute(
            "SELECT session_id AS id, json_extract(payload, '$.title') AS title, updated_at, "
            "json_array_length(payload, '$.messages') AS message_count "
            "FROM research_sessions ORDER BY updated_at DESC LIMIT 100"
        ).fetchall()
    return [ResearchSessionSummary.model_validate(dict(row)) for row in rows]


def save(
    library_root: str | Path, session: ResearchSession, expected_revision: int | None
) -> None:
    # Revalidate copies too: callers may use model_copy to assemble a new revision.
    session = ResearchSession.model_validate(session.model_dump())
    with DatabaseManager.get(str(library_root)).kb_conn() as conn:
        if expected_revision is None:
            changed = conn.execute(
                "INSERT OR IGNORE INTO research_sessions(session_id, revision, updated_at, payload) VALUES (?, ?, ?, ?)",
                (
                    session.id,
                    session.revision,
                    session.updated_at,
                    session.model_dump_json(),
                ),
            ).rowcount
        else:
            if session.revision != expected_revision + 1:
                raise ConflictError("Research revision must advance by one")
            changed = conn.execute(
                "UPDATE research_sessions SET revision = ?, updated_at = ?, payload = ? WHERE session_id = ? AND revision = ?",
                (
                    session.revision,
                    session.updated_at,
                    session.model_dump_json(),
                    session.id,
                    expected_revision,
                ),
            ).rowcount
        if changed != 1:
            raise ConflictError("Research conversation changed; reload it")


def delete(library_root: str | Path, session_id: str, expected_revision: int) -> bool:
    with DatabaseManager.get(str(library_root)).kb_conn() as conn:
        deleted = (
            conn.execute(
                "DELETE FROM research_sessions WHERE session_id = ? AND revision = ?",
                (session_id, expected_revision),
            ).rowcount
            == 1
        )
        if not deleted:
            raise ConflictError(
                "Research conversation changed; reload it before deleting"
            )
        LibraryLayout(library_root).research_session_file(session_id).unlink(
            missing_ok=True
        )
        return True
