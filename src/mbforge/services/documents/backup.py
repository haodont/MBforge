"""Create recoverable snapshots before destructive document changes."""

from __future__ import annotations

import json
import shutil
import sqlite3
from datetime import UTC, datetime
from pathlib import Path

from ...storage.layout import LibraryLayout
from ...storage.sqlite.database import DatabaseManager


def create_backup(
    library_root: str | Path,
    doc_id: str,
    operation: str,
) -> Path:
    """Snapshot the library database and one document before mutation."""
    layout = LibraryLayout(library_root)
    timestamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%S%fZ")
    backup_root = layout.metadata_dir / "backups" / f"{timestamp}_{operation}_{doc_id}"
    backup_root.mkdir(parents=True, exist_ok=False)

    storage_dir = layout.storage_dir(doc_id)
    if storage_dir.exists():
        shutil.copytree(storage_dir, backup_root / "storage" / doc_id)

    db = DatabaseManager.get(str(layout.library_root))
    db.initialize()
    with sqlite3.connect(str(backup_root / "library.db")) as destination, db.mol_conn() as source:
        source.backup(destination)

    (backup_root / "manifest.json").write_text(
        json.dumps(
            {"doc_id": doc_id, "operation": operation, "created_at": timestamp},
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )
    return backup_root


__all__ = ["create_backup"]
