"""On-disk registry of MBForge processes for a library root.

Each running process writes a JSON record at ``{root}/.mbforge/proc-{pid}.json`` so
that other processes can enumerate live instances, detect orphans, and report
who holds the queue lock.
"""

from __future__ import annotations

import atexit
import contextlib
import json
import os
import socket
import sys
import threading
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import ClassVar

from mbforge.foundation.layout import LibraryLayout


@dataclass(frozen=True)
class ProcessIdentity:
    """A registered MBForge process."""

    pid: int
    ppid: int
    role: str
    cmdline: str
    started_at: float
    port: int | None
    heartbeat_at: float
    host: str


def pid_alive(pid: int) -> bool:
    """Return True if *pid* is currently alive (cross-platform)."""
    if pid <= 0:
        return False
    if os.name == "nt":
        import ctypes

        _PROCESS_QUERY_LIMITED_INFORMATION = 0x1000  # noqa: N806
        _STILL_ACTIVE = 259  # noqa: N806
        kernel32 = ctypes.windll.kernel32
        handle = kernel32.OpenProcess(_PROCESS_QUERY_LIMITED_INFORMATION, False, pid)
        if not handle:
            return False
        try:
            code = ctypes.c_ulong()
            if not kernel32.GetExitCodeProcess(handle, ctypes.byref(code)):
                return False
            return code.value == _STILL_ACTIVE
        finally:
            kernel32.CloseHandle(handle)
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    return True


class ProcessRegistry:
    """Per-library-root singleton registry.

    Usage::

        reg = ProcessRegistry.get(library_root)
        identity = reg.register("server", port=18792)
        ...
        reg.heartbeat()
        ...
        reg.unregister()   # called from lifespan finally + atexit
    """

    _instances: ClassVar[dict[str, ProcessRegistry]] = {}
    _lock: ClassVar[threading.Lock] = threading.Lock()

    def __init__(self, library_root: str) -> None:
        self._root = LibraryLayout(library_root).library_root
        self._registry_dir = self._root / ".mbforge"
        self._identity: ProcessIdentity | None = None
        self._atexit_registered = False

    @classmethod
    def get(cls, library_root: str | Path) -> ProcessRegistry:
        """Return the singleton registry for *library_root*."""
        key = str(LibraryLayout(library_root).library_root)
        with cls._lock:
            if key not in cls._instances:
                cls._instances[key] = cls(key)
            return cls._instances[key]

    @property
    def registry_dir(self) -> Path:
        self._registry_dir.mkdir(parents=True, exist_ok=True)
        return self._registry_dir

    def register(self, role: str, port: int | None = None) -> ProcessIdentity:
        """Register this process and write its identity file.

        Returns the created :class:`ProcessIdentity`. Calling multiple times
        overwrites the previous record for the same pid.
        """
        now = _now()
        identity = ProcessIdentity(
            pid=os.getpid(),
            ppid=os.getppid(),
            role=role,
            cmdline=_current_cmdline(),
            started_at=now,
            port=port,
            heartbeat_at=now,
            host=socket.gethostname(),
        )
        self._write_identity(identity)
        self._identity = identity
        if not self._atexit_registered:
            atexit.register(self.unregister)
            self._atexit_registered = True
        return identity

    def heartbeat(self) -> None:
        """Update the heartbeat timestamp on disk."""
        if self._identity is None:
            return
        updated = self._identity.__class__(
            **{**asdict(self._identity), "heartbeat_at": _now()}
        )
        self._write_identity(updated)
        self._identity = updated

    def unregister(self) -> None:
        """Remove this process's identity file."""
        if self._identity is None:
            return
        path = self._identity_file(self._identity.pid)
        with contextlib.suppress(OSError):
            path.unlink(missing_ok=True)
        self._identity = None

    def sweep_stale(self) -> list[ProcessIdentity]:
        """Delete records whose pid is no longer alive and return them."""
        stale: list[ProcessIdentity] = []
        if not self._registry_dir.is_dir():
            return stale
        for entry in self._procs_entries():
            try:
                identity = self._read_entry(entry)
            except (OSError, ValueError):
                continue
            if not pid_alive(identity.pid):
                with contextlib.suppress(OSError):
                    entry.unlink()
                stale.append(identity)
        return stale

    def all_identities(self) -> list[ProcessIdentity]:
        """Return all currently registered identities (may include dead ones)."""
        result: list[ProcessIdentity] = []
        if not self._registry_dir.is_dir():
            return result
        for entry in self._procs_entries():
            try:
                result.append(self._read_entry(entry))
            except (OSError, ValueError):
                continue
        return result

    def find(self, pid: int) -> ProcessIdentity | None:
        """Look up a specific pid, or None."""
        path = self._identity_file(pid)
        if not path.is_file():
            return None
        try:
            return self._read_entry(path)
        except (OSError, ValueError):
            return None

    # -- Internal -----------------------------------------------------------

    def _procs_entries(self) -> list[Path]:
        """Return the ``proc-*.json`` identity records in the registry dir."""
        if not self._registry_dir.is_dir():
            return []
        return [
            entry
            for entry in self._registry_dir.iterdir()
            if entry.suffix == ".json" and entry.name.startswith("proc-")
        ]

    def _identity_file(self, pid: int) -> Path:
        return self._registry_dir / f"proc-{pid}.json"

    def _write_identity(self, identity: ProcessIdentity) -> None:
        self._registry_dir.mkdir(parents=True, exist_ok=True)
        path = self._identity_file(identity.pid)
        tmp = path.with_suffix(".tmp")
        tmp.write_text(json.dumps(asdict(identity)), encoding="utf-8")
        tmp.replace(path)

    @staticmethod
    def _read_entry(path: Path) -> ProcessIdentity:
        raw = path.read_text(encoding="utf-8")
        data = json.loads(raw)
        return ProcessIdentity(**data)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _now() -> float:
    import time

    return time.time()


def _current_cmdline() -> str:
    """Return a best-effort command line for the current process."""
    exe = sys.executable
    args = sys.argv
    parts = [exe] + args
    return " ".join(parts)
