"""Small atomic JSON helpers shared by artifact modules."""

from __future__ import annotations

import json
import os
import tempfile
from contextlib import suppress
from pathlib import Path
from typing import Any

from mbforge.foundation.logger import get_logger

logger = get_logger("mbforge.application.pipeline.artifacts.json_io")


def read_json_object(path: Path) -> dict[str, Any] | None:
    if not path.is_file():
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError) as exc:
        logger.warning("Ignoring unreadable artifact %s: %s", path, exc)
        return None
    if not isinstance(data, dict):
        logger.warning(
            "Ignoring artifact %s: expected object, got %s", path, type(data).__name__
        )
        return None
    return data


def write_json_atomic(path: Path, payload: dict[str, Any]) -> None:
    """Write one JSON object and publish it with an atomic replacement."""
    path.parent.mkdir(parents=True, exist_ok=True)
    temp_name: str | None = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="w",
            encoding="utf-8",
            dir=path.parent,
            prefix=f".{path.name}.",
            suffix=".tmp",
            delete=False,
        ) as handle:
            temp_name = handle.name
            json.dump(payload, handle, ensure_ascii=False, indent=2, default=str)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temp_name, path)
    except Exception:
        if temp_name is not None:
            with suppress(OSError):
                Path(temp_name).unlink()
        raise
    logger.info("Saved stage artifact %s", path)


__all__ = ["read_json_object", "write_json_atomic"]
