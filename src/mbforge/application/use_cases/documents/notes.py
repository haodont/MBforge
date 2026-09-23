"""Notes persistence — per-library markdown notes with a JSON index.

Each note is a Markdown file under the library's notes directory, indexed
by a JSON sidecar. Business rules (index upsert, delete filtering, and the
backlink match) live here; the router only validates and delegates.
"""

from __future__ import annotations

import json
from pathlib import Path

from mbforge.foundation.errors import ValidationError
from mbforge.foundation.files import ensure_dir
from mbforge.foundation.layout import InvalidPathError, LibraryLayout, validate_doc_id
from mbforge.foundation.logger import get_logger

logger = get_logger("mbforge.application.use_cases.documents.notes")

NOTES_INDEX = "notes_index.json"


def _notes_root(library_root: str) -> Path:
    if not library_root:
        raise ValidationError("No root path provided")
    return LibraryLayout(Path(library_root)).notes_dir


def _index_path(library_root: str) -> Path:
    return _notes_root(library_root) / NOTES_INDEX


def load_index(library_root: str) -> list[dict]:
    p = _index_path(library_root)
    if not p.exists():
        return []
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except Exception as e:
        logger.warning("Failed to load notes index: %s", e)
        return []


def save_index(library_root: str, index: list[dict]) -> None:
    notes_dir = _notes_root(library_root)
    ensure_dir(notes_dir)
    _index_path(library_root).write_text(
        json.dumps(index, ensure_ascii=False, indent=2), encoding="utf-8"
    )


def _validate_note_id(note_id: str) -> None:
    """Reject note ids that could be used for path traversal."""
    try:
        validate_doc_id(note_id)
    except InvalidPathError as exc:
        raise InvalidPathError(f"invalid note_id: {note_id!r}") from exc


def read_note(library_root: str, note_id: str) -> str:
    _validate_note_id(note_id)
    notes_path = _notes_root(library_root) / f"{note_id}.md"
    if notes_path.exists():
        return notes_path.read_text(encoding="utf-8")
    return ""


def write_note(library_root: str, note_id: str, content: str) -> None:
    _validate_note_id(note_id)
    notes_dir = _notes_root(library_root)
    ensure_dir(notes_dir)
    notes_path = notes_dir / f"{note_id}.md"
    notes_path.write_text(content, encoding="utf-8")


def delete_note(library_root: str, note_id: str) -> None:
    _validate_note_id(note_id)
    notes_path = _notes_root(library_root) / f"{note_id}.md"
    if notes_path.exists():
        notes_path.unlink()


def upsert_index_entry(library_root: str, note_id: str, serialized: dict) -> list[dict]:
    """Insert or replace ``note_id`` in the index and persist it."""
    index = load_index(library_root)
    existing = next((i for i, e in enumerate(index) if e.get("id") == note_id), None)
    if existing is not None:
        index[existing] = serialized
    else:
        index.append(serialized)
    save_index(library_root, index)
    return index


def remove_index_entry(library_root: str, note_id: str) -> list[dict]:
    """Drop ``note_id`` from the index and persist it."""
    index = load_index(library_root)
    index = [n for n in index if n.get("id") != note_id]
    save_index(library_root, index)
    return index


def backlinks_for(library_root: str, target_id: str) -> list[dict]:
    """Return index entries whose ``links`` reference ``target_id``."""
    index = load_index(library_root)
    return [n for n in index if target_id in str(n.get("links", []))]
