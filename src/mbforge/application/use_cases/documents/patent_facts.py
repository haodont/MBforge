"""Read-side access to the document-level Patent facts artifact.

Patent facts are read directly from ``storage/{doc_id}/patent_facts.json``.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from mbforge.application.pipeline.patent.artifact import PatentFactsArtifact
from mbforge.foundation.layout import LibraryLayout
from mbforge.foundation.logger import get_logger

logger = get_logger("mbforge.application.use_cases.documents.patent_facts")


def _load_json_file(path: Path, label: str) -> dict[str, Any] | None:
    if not path.is_file():
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError) as exc:
        logger.warning("Ignoring unreadable %s: %s (%s)", path, label, exc)
        return None
    if not isinstance(data, dict):
        logger.warning(
            "Ignoring artifact %s: expected object, got %s",
            path,
            type(data).__name__,
        )
        return None
    return data


def load_patent_facts(
    library_root: str | Path, doc_id: str
) -> PatentFactsArtifact | None:
    """Return the published patent facts for *doc_id*, or ``None``."""
    layout = LibraryLayout(library_root)
    data = _load_json_file(
        layout.storage_dir(doc_id) / "patent_facts.json", "patent facts"
    )
    if data is None:
        return None
    try:
        return PatentFactsArtifact.model_validate(data)
    except Exception as exc:  # noqa: BLE001
        logger.warning("Ignoring malformed patent facts for %s: %s", doc_id, exc)
        return None


def iter_published_doc_ids(library_root: str | Path) -> list[str]:
    """Return document IDs with a current Patent facts artifact."""
    root = LibraryLayout(library_root).storage_root
    if not root.is_dir():
        return []
    out: list[str] = []
    for child in sorted(root.iterdir()):
        if (child / "patent_facts.json").is_file():
            out.append(child.name)
    return out
