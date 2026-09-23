"""Process enumeration and MBForge identification.

Windows: single PowerShell CIM query for all processes (JSON output).
POSIX: /proc-based enumeration or fallback to ps.

The ``is_mbforge_process`` classifier tightens the dangerous heuristic in
``__main__.py`` that treated *any* ``python.exe`` as MBForge.
"""

from __future__ import annotations

import json
import os
import re
import subprocess
from dataclasses import dataclass
from enum import StrEnum

from mbforge.adapters.runtime.process.identity import ProcessRegistry


@dataclass(frozen=True)
class ProcInfo:
    """Information about a running process."""

    pid: int
    ppid: int
    name: str
    cmdline: str
    creation_date: str  # CIM CreationDate or ISO timestamp


class MatchLevel(StrEnum):
    """How confidently we can say a process is MBForge."""

    CONFIRMED = "confirmed"
    LIKELY = "likely"
    SPAWN_CHILD = "spawn_child"
    NONE = "none"


# ---------------------------------------------------------------------------
# Enumeration
# ---------------------------------------------------------------------------


def enumerate_processes() -> list[ProcInfo]:
    """Return information about every running process.

    On Windows this uses a single PowerShell CIM query. If PowerShell/CIM is
    unavailable it falls back to an empty list (callers should handle this).
    On POSIX it parses ``ps -eo pid,ppid,comm,args --no-headers``.
    """
    if os.name == "nt":
        return _enumerate_windows()
    return _enumerate_posix()


def _enumerate_windows() -> list[ProcInfo]:
    """Use PowerShell Get-CimInstance Win32_Process (JSON output)."""
    cmd = [
        "powershell",
        "-NoProfile",
        "-Command",
        (
            "Get-CimInstance Win32_Process | "
            "Select-Object ProcessId,ParentProcessId,Name,CommandLine,CreationDate | "
            "ConvertTo-Json -Compress"
        ),
    ]
    try:
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=10,
            check=True,
        )
    except (OSError, subprocess.SubprocessError):
        return []
    raw = result.stdout.strip()
    if not raw:
        return []
    try:
        data = json.loads(raw)
    except ValueError:
        return []
    if isinstance(data, dict):
        data = [data]
    results: list[ProcInfo] = []
    for item in data:
        pid = item.get("ProcessId")
        ppid = item.get("ParentProcessId")
        if pid is None:
            continue
        results.append(
            ProcInfo(
                pid=int(pid),
                ppid=int(ppid) if ppid else 0,
                name=item.get("Name", ""),
                cmdline=item.get("CommandLine") or "",
                creation_date=item.get("CreationDate", ""),
            )
        )
    return results


def _enumerate_posix() -> list[ProcInfo]:
    """Parse ``ps -eo pid,ppid,comm,args --no-headers``."""
    try:
        result = subprocess.run(
            ["ps", "-eo", "pid,ppid,comm,args", "--no-headers"],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=5,
            check=True,
        )
    except (OSError, subprocess.SubprocessError):
        return []
    results: list[ProcInfo] = []
    for line in result.stdout.splitlines():
        parts = line.split(None, 3)
        if len(parts) < 4:
            continue
        results.append(
            ProcInfo(
                pid=int(parts[0]),
                ppid=int(parts[1]),
                name=parts[2],
                cmdline=parts[3],
                creation_date="",
            )
        )
    return results


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def port_listeners(port: int) -> list[int]:
    """Return PIDs of processes LISTENING on *port* (cross-platform).

    Uses ``netstat -ano -p tcp`` on Windows and ``ss -tlnp`` on Linux.
    """
    if os.name == "nt":
        return _port_listeners_windows(port)
    return _port_listeners_posix(port)


def _port_listeners_windows(port: int) -> list[int]:
    """Parse ``netstat -ano -p tcp`` for LISTENING entries on *port*."""
    try:
        result = subprocess.run(
            ["netstat", "-ano", "-p", "tcp"],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=5,
            check=True,
        )
    except (OSError, subprocess.SubprocessError):
        return []
    pids: list[int] = []
    pattern = re.compile(
        r"^\s*TCP\s+\S+:(?P<port>\d+)\s+\S+\s+LISTENING\s+(?P<pid>\d+)", re.MULTILINE
    )
    for m in pattern.finditer(result.stdout):
        if int(m.group("port")) == port:
            pids.append(int(m.group("pid")))
    return pids


def _port_listeners_posix(port: int) -> list[int]:
    """Parse ``ss -tlnp`` for LISTEN entries on *port*."""
    try:
        result = subprocess.run(
            ["ss", "-tlnp"],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=5,
            check=True,
        )
    except (OSError, subprocess.SubprocessError):
        return []
    pids: list[int] = []
    pattern = re.compile(
        rf":{port}\s+.*users:\(\(\"(?P<name>[^\"]+)\",pid=(?P<pid>\d+)"
    )
    for m in pattern.finditer(result.stdout):
        pids.append(int(m.group("pid")))
    return pids


def ancestor_pids(pid: int | None = None) -> set[int]:
    """Return the set of ancestor PIDs up to PID 1 (inclusive)."""
    if pid is None:
        pid = os.getpid()
    ancestors: set[int] = set()
    current = pid
    visited: set[int] = set()
    while current and current not in visited:
        visited.add(current)
        ancestors.add(current)
        parent = _get_ppid(current)
        if parent is None or parent == current:
            break
        current = parent
    return ancestors


def _get_ppid(pid: int) -> int | None:
    """Return the parent PID of *pid*, or None if unknown."""
    if os.name == "nt":
        try:
            result = subprocess.run(
                [
                    "powershell",
                    "-NoProfile",
                    "-Command",
                    f"(Get-CimInstance Win32_Process -Filter 'ProcessId={pid}').ParentProcessId",
                ],
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=3,
                check=True,
            )
            val = result.stdout.strip()
            return int(val) if val.isdigit() else None
        except (OSError, subprocess.SubprocessError, ValueError):
            return None
    try:
        with open(f"/proc/{pid}/status", encoding="utf-8") as f:
            for line in f:
                if line.startswith("PPid:"):
                    return int(line.split()[1])
    except OSError:
        pass
    return None


# ---------------------------------------------------------------------------
# MBForge identification
# ---------------------------------------------------------------------------

_MBFORGE_CMDLINE_RE = re.compile(
    r"-m\s+mbforge|mbforge\.app|uvicorn.*mbforge", re.IGNORECASE
)
_SPAWN_RE = re.compile(r"multiprocessing\.(?:spawn|fork)|--multiprocessing-fork")


def is_mbforge_process(p: ProcInfo, registry: ProcessRegistry) -> MatchLevel:
    """Classify how confidently *p* is an MBForge process.

    Returns one of :class:`MatchLevel`. Callers should only auto-reap
    processes at **CONFIRMED** level.
    """
    # A1: never classify self
    if p.pid == os.getpid():
        return MatchLevel.NONE

    # Check registration first
    entry = registry.find(p.pid)
    if (
        entry is not None
        and _cmdline_matches(entry.cmdline, p.cmdline)
        and _creation_date_ok(entry, p.creation_date)
    ):
        return MatchLevel.CONFIRMED

    # Fallback heuristics
    if _MBFORGE_CMDLINE_RE.search(p.cmdline):
        return MatchLevel.LIKELY

    if _SPAWN_RE.search(p.cmdline):
        # Check if any ancestor is confirmed
        for apid in ancestor_pids(p.pid):
            if apid == p.pid:
                continue
            ancestor_entry = registry.find(apid)
            if ancestor_entry is not None:
                return MatchLevel.SPAWN_CHILD
            # Also check via enumeration
            for proc in enumerate_processes():
                if proc.pid == apid and is_mbforge_process(proc, registry) in (
                    MatchLevel.CONFIRMED,
                    MatchLevel.LIKELY,
                ):
                    return MatchLevel.SPAWN_CHILD

    return MatchLevel.NONE


def _cmdline_matches(recorded: str, live: str) -> bool:
    """Check whether two command lines are close enough (token-level)."""
    if not recorded or not live:
        return False

    # Normalize: strip quotes, collapse whitespace
    def tokens(s: str) -> list[str]:
        return [t.strip('"').strip("'") for t in s.split() if t]

    rec_tokens = tokens(recorded)
    live_tokens = tokens(live)
    # Require that all recorded tokens appear in live (order preserved)
    if not rec_tokens:
        return True
    li = 0
    for rt in rec_tokens:
        found = False
        while li < len(live_tokens):
            if live_tokens[li] == rt:
                found = True
                li += 1
                break
            li += 1
        if not found:
            return False
    return True


def _creation_date_ok(identity, cim_creation_date: str) -> bool:
    """On Windows, verify the process CreationDate is within 5s of started_at."""
    if not cim_creation_date or identity.started_at is None:
        return True  # Can't verify → allow
    if os.name != "nt":
        return True
    try:
        # CIM CreationDate format: 20260904095827.xxxxxx+480
        dt_str = cim_creation_date.split(".")[0]
        import datetime

        dt = datetime.datetime.strptime(dt_str, "%Y%m%d%H%M%S")
        # Assume local timezone; compare as naive
        elapsed = abs(dt.timestamp() - identity.started_at)
        return elapsed < 5.0
    except (ValueError, TypeError):
        return True
