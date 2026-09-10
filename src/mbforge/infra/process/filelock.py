"""Ownership-aware file lock for per-library single-owner resources.

Extracted from ``services/worker.py`` so process governance can report *who*
holds a library lock instead of only whether it is held.

The lock region stays byte 0 (one byte) on every platform, so a process
running the pre-extraction code and a process running this module can lock and
probe the same file. Owner metadata is appended from byte 1 onward, which
``read_lock_holder`` reads without taking the lock.
"""

from __future__ import annotations

import json
import os
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import IO

from ...storage.layout import LibraryLayout

_LOCK_FILENAME = "queue.lock"
_META_OFFSET = 1


@dataclass(frozen=True)
class LockMeta:
    """Metadata written into the lock file when a process acquires the lock."""

    pid: int
    host: str
    role: str
    started_at: float


@dataclass(frozen=True)
class LockHolder:
    """Recorded owner of a library lock.

    ``pid=None`` means the lock was created by an older version that did not
    record ownership (legacy format). Callers should pair this with
    :func:`is_library_locked` to distinguish a free lock from a legacy holder.
    """

    pid: int | None
    host: str
    role: str
    started_at: float | None
    legacy: bool


def queue_lock_path(library_root: str | Path) -> Path:
    """Return the lock file path for a library root (no I/O)."""
    return LibraryLayout(library_root).metadata_dir / _LOCK_FILENAME


def try_lock_existing(lock_path: Path) -> IO[bytes] | None:
    """Acquire a non-blocking exclusive lock on an existing file, or return None.

    Never creates the file, so callers that only want to know the lock state
    (such as ``is_library_locked``) can probe without side effects.
    """
    if not lock_path.is_file():
        return None
    handle = open(lock_path, "r+b")  # noqa: SIM115 — handle lives past the call
    try:
        return _acquire(handle)
    except OSError:
        handle.close()
        return None


def try_lock_file(lock_path: Path, meta: LockMeta) -> IO[bytes] | None:
    """Create ``lock_path`` if needed and acquire a non-blocking exclusive lock.

    Writes ``meta`` starting at byte offset 1 (the lock region remains byte 0,
    one byte, for cross-version compatibility). Returns an open handle when
    the lock was acquired, else ``None``.
    """
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    if not lock_path.exists():
        fd = os.open(lock_path, os.O_CREAT | os.O_WRONLY, 0o644)
        try:
            os.write(fd, b"\0")
        finally:
            os.close(fd)
    handle = try_lock_existing(lock_path)
    if handle is None:
        return None
    _write_meta(handle, meta)
    return handle


def unlock_file(handle: IO[bytes]) -> None:
    """Release a lock previously acquired by :func:`try_lock_file`.

    Clears recorded metadata so that a subsequent ``read_lock_holder`` returns
    ``legacy=True`` rather than stale information.
    """
    try:
        _clear_meta(handle)
        handle.seek(0)
        if os.name == "nt":
            import msvcrt

            msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)
        else:  # pragma: no cover — exercised on POSIX only
            import fcntl

            fcntl.flock(handle.fileno(), fcntl.LOCK_UN)
    finally:
        handle.close()


def read_lock_holder(library_root: str | Path) -> LockHolder | None:
    """Read the recorded lock owner without creating any directories or files.

    This is a pure read: it does **not** attempt to acquire the lock. The
    returned value represents the *last recorded* owner; callers must pair it
    with :func:`is_library_locked` to know whether the lock is currently held.

    Returns ``None`` when the lock file does not exist.
    """
    lock_path = queue_lock_path(library_root)
    if not lock_path.is_file():
        return None
    try:
        with open(lock_path, "rb") as handle:
            handle.seek(_META_OFFSET)
            raw = handle.read()
    except OSError:
        return None
    if not raw.strip():
        return LockHolder(pid=None, host="", role="", started_at=None, legacy=True)
    try:
        data = json.loads(raw.decode("utf-8"))
    except (ValueError, UnicodeDecodeError):
        return LockHolder(pid=None, host="", role="", started_at=None, legacy=True)
    return LockHolder(
        pid=data.get("pid"),
        host=data.get("host", ""),
        role=data.get("role", ""),
        started_at=data.get("started_at"),
        legacy=False,
    )


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _acquire(handle: IO[bytes]) -> IO[bytes]:
    """Apply the platform lock primitive on an open file handle."""
    handle.seek(0)
    if os.name == "nt":
        import msvcrt

        msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
    else:  # pragma: no cover — exercised on POSIX only
        import fcntl

        fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
    return handle


def _write_meta(handle: IO[bytes], meta: LockMeta) -> None:
    """Append JSON-encoded metadata after the locked byte."""
    payload = json.dumps(asdict(meta), separators=(",", ":")).encode("utf-8")
    handle.seek(_META_OFFSET)
    handle.write(payload)
    handle.truncate()
    handle.flush()


def _clear_meta(handle: IO[bytes]) -> None:
    """Remove recorded metadata, leaving only the locked byte."""
    handle.seek(_META_OFFSET)
    handle.truncate(_META_OFFSET)
    handle.flush()
