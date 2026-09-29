"""Create recoverable snapshots before destructive document changes.

A backup captures *only* the affected document's data — the document's
``storage/`` tree and the document-scoped rows in the unified database —
rather than a copy of the entire ``library.db``.  Old snapshots are pruned
to a bounded number so the ``backups/`` directory cannot grow without limit.

The database export is owned by the persistence layer
(``DatabaseRepository.snapshot_document``); this module owns the filesystem
half (storage tree, manifest, pruning).
"""

from __future__ import annotations

import contextlib
import json
import shutil
from datetime import UTC, datetime
from pathlib import Path

from mbforge.foundation.layout import LibraryLayout
from mbforge.service.ports import get_database

# Keep at most this many most-recent backups, pruning the oldest.
MAX_BACKUPS = 20


def _prune_old_backups(layout: LibraryLayout) -> None:
    """Delete oldest snapshots beyond ``MAX_BACKUPS``."""
    backups_dir = layout.metadata_dir / "backups"
    if not backups_dir.is_dir():
        return
    ordered = sorted(backups_dir.iterdir(), key=lambda p: p.name)
    for path in ordered[:-MAX_BACKUPS]:
        if path.is_dir():
            shutil.rmtree(path, ignore_errors=True)
        else:
            with contextlib.suppress(OSError):
                path.unlink(missing_ok=True)


def create_backup(
    library_root: str | Path,
    doc_id: str,
    operation: str,
) -> Path:
    """Snapshot the affected document before mutation.

    Stores the document's ``storage/`` tree plus a JSON export of the
    document-scoped database rows, and prunes to a bounded set.  Returns the
    created backup directory.
    """
    layout = LibraryLayout(library_root)
    timestamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%S%fZ")
    backup_root = layout.metadata_dir / "backups" / f"{timestamp}_{operation}_{doc_id}"
    backup_root.mkdir(parents=True, exist_ok=False)

    storage_dir = layout.storage_dir(doc_id)
    if storage_dir.exists():
        shutil.copytree(storage_dir, backup_root / "storage" / doc_id)

    db_snapshot = get_database(str(layout.library_root)).snapshot_document(doc_id)

    (backup_root / "database.json").write_text(
        json.dumps(db_snapshot, ensure_ascii=False, default=str, indent=2),
        encoding="utf-8",
    )
    (backup_root / "manifest.json").write_text(
        json.dumps(
            {
                "doc_id": doc_id,
                "operation": operation,
                "created_at": timestamp,
                "tables": sorted(db_snapshot.keys()),
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )

    with contextlib.suppress(OSError):
        _prune_old_backups(layout)
    return backup_root


__all__ = ["create_backup", "MAX_BACKUPS"]
