"""Timestamp run IDs and staged branch artifact mapping.

Run IDs are minted once per worker claim (i.e. once per ``run_pipeline``
invocation, which executes exactly one stage).  Per-document stage runs are
serialized by the queue (a row is re-queued between stages and only
re-claimed afterwards), so a fresh timestamp normally never collides; the
scan-and-increment guard below only exists to keep two *concurrent* rows for
the same document (double re-ingest) from ever sharing a run ID.

Artifact kinds follow the stage that publishes them:

- branch kinds under ``.staging/`` — ``extract.json``
  (extract) and ``detection.json`` (detection).
"""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from pathlib import Path

from mbforge.foundation.layout import LibraryLayout

#: UTC timestamp format for run IDs.
RUN_ID_FORMAT = "%Y%m%d%H%M%S"

# Kind filename for every fork branch under ``.staging/``.
_BRANCH_KIND_BY_STAGE: dict[str, str] = {
    "extract": "extract.json",
    "detection": "detection.json",
}

# Branch stage → kind file.
_KIND_BY_STAGE = _BRANCH_KIND_BY_STAGE


def stage_kind_file(stage: str) -> str | None:
    """Return the artifact filename published by *stage*, or ``None``."""
    return _KIND_BY_STAGE.get(stage)


def mint_run_id(library_root: str | Path, doc_id: str) -> str:
    """Mint a UTC ``YYYYMMDDHHMMSS`` run ID unique within *doc_id*.

    Uniqueness is enforced against published run directories and active
    staging-file run IDs;
    on collision the timestamp is advanced one second at a time.
    """
    layout = LibraryLayout(library_root)
    used = _existing_run_ids(layout.runs_dir(doc_id), layout.storage_dir(doc_id))
    now = datetime.now(UTC)
    candidate = now.strftime(RUN_ID_FORMAT)
    while candidate in used:
        now += timedelta(seconds=1)
        candidate = now.strftime(RUN_ID_FORMAT)
    return candidate


def _existing_run_ids(runs_dir: Path, storage_dir: Path) -> set[str]:
    """Collect run IDs already present in published and staged artifacts."""
    used: set[str] = set()
    if runs_dir.is_dir():
        for child in runs_dir.iterdir():
            if child.is_dir():
                used.add(child.name)
    staging = storage_dir / ".staging"
    if staging.is_dir():
        for path in staging.glob("*.json"):
            try:
                data = json.loads(path.read_text(encoding="utf-8"))
            except (OSError, ValueError):
                continue
            run_id = data.get("run_id") if isinstance(data, dict) else None
            if isinstance(run_id, str) and run_id:
                used.add(run_id)
    return used


def safe_run_id(run_id: str) -> bool:
    """Return True when *run_id* is safe to embed in a storage path."""
    return bool(run_id) and all(
        ch.isascii() and (ch.isalnum() or ch in "_-") for ch in run_id
    )
