"""Capability token storage.

The token is a local intent guard, not a strong security boundary: any process
running as the same OS user can read the file. It separates read-only callers
from callers that explicitly opt into mutating capabilities.
"""

from __future__ import annotations

import os
import secrets
import time
from pathlib import Path


def _read_token(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8").strip()
    except (OSError, UnicodeDecodeError):
        return ""


def capability_token_path(library_root: str | Path) -> Path:
    """Return the token path for one library."""
    return Path(library_root).expanduser().resolve() / ".mbforge" / "capability-token"


def ensure_capability_token(library_root: str | Path) -> str:
    """Create the token on first use and return it."""
    path = capability_token_path(library_root)
    existing = _read_token(path)
    if existing:
        return existing

    path.parent.mkdir(parents=True, exist_ok=True)
    token = secrets.token_urlsafe(32)
    try:
        fd = os.open(path, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
    except FileExistsError:
        for _ in range(10):
            existing = _read_token(path)
            if existing:
                return existing
            time.sleep(0.01)
        path.write_text(token, encoding="utf-8")
        return token
    with os.fdopen(fd, "w", encoding="utf-8") as handle:
        handle.write(token)
    return token


def verify_capability_token(
    library_root: str | Path,
    presented: str | None,
) -> bool:
    """Return True only when ``presented`` matches the stored token."""
    if not presented:
        return False
    path = capability_token_path(library_root)
    expected = _read_token(path)
    if not expected:
        return False
    try:
        presented_bytes = presented.encode("utf-8")
    except UnicodeEncodeError:
        return False
    return secrets.compare_digest(presented_bytes, expected.encode("utf-8"))
