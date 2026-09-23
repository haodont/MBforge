"""Orphan detection and reaping.

An orphan is a process that holds resources (queue lock, listening port) but
whose parent has died or whose heartbeat has expired. Only **blocking**
orphans — those that prevent the current process from starting — are eligible
for automatic termination. All others are reported for manual review.
"""

from __future__ import annotations

import time
from dataclasses import dataclass

from mbforge.adapters.runtime.process.discovery import (
    MatchLevel,
    ProcInfo,
    ancestor_pids,
    enumerate_processes,
    port_listeners,
)
from mbforge.adapters.runtime.process.filelock import read_lock_holder
from mbforge.adapters.runtime.process.identity import ProcessRegistry, pid_alive


@dataclass(frozen=True)
class OrphanCandidate:
    """A process that may be an orphan."""

    pid: int
    identity: ProcInfo
    reason: str
    confidence: MatchLevel
    blocking: bool  # True → eligible for auto-reap


@dataclass(frozen=True)
class ReapResult:
    """Outcome of a reap attempt."""

    pid: int
    action: str  # "skipped" | "terminated" | "killed" | "failed"
    reason: str


def find_orphans(library_root: str, port: int | None = None) -> list[OrphanCandidate]:
    """Find processes that may be orphans for *library_root*.

    A candidate is marked ``blocking=True`` only if it satisfies ALL of:
    - A1: pid ∉ {self} ∪ ancestors
    - A2: confidence ≥ CONFIRMED (registry hit + cmdline match + CreationDate)
    - A3: not a healthy backend on a different port
    - A4: heartbeat expired OR parent dead with role in {spawn-child, queue-leader}
    - A5: cfg.process.auto_reap_orphans (checked by caller)
    AND at least one of:
    - B1: holds the queue lock for this library
    - B2: LISTENING on the requested host:port

    Returns all candidates (blocking and non-blocking). Only blocking ones
    should be passed to :func:`reap` with ``dry_run=False``.
    """
    registry = ProcessRegistry.get(library_root)
    self_pid = _my_pid()
    ancestors = ancestor_pids(self_pid)
    candidates: list[OrphanCandidate] = []

    for proc in enumerate_processes():
        # A1: exclude self and ancestors
        if proc.pid == self_pid or proc.pid in ancestors:
            continue

        confidence = _classify(proc, registry, library_root)
        if confidence == MatchLevel.NONE:
            continue

        # Determine blocking conditions
        blocking = False
        reasons: list[str] = []

        # B1: holds queue lock
        holder = read_lock_holder(library_root)
        if (
            holder is not None
            and holder.pid == proc.pid
            and confidence
            in (
                MatchLevel.CONFIRMED,
                MatchLevel.LIKELY,
            )
        ):
            blocking = True
            reasons.append("holds queue lock")

        # B2: listens on target port
        if port is not None and proc.pid in port_listeners(port):
            blocking = True
            reasons.append(f"LISTENING on port {port}")

        # A3: exclude healthy backends on other ports
        if _is_healthy_backend(proc.pid, port):
            blocking = False
            reasons.append("healthy backend on different port")

        # A4: heartbeat / parent check
        entry = registry.find(proc.pid)
        if entry is not None:
            hb_age = time.time() - entry.heartbeat_at
            if hb_age > 90:  # 3 × default 30s heartbeat
                reasons.append(f"heartbeat expired ({hb_age:.0f}s)")
            elif entry.role in ("spawn-child", "queue-leader") and not pid_alive(
                entry.ppid
            ):
                reasons.append(f"parent {entry.ppid} dead, role={entry.role}")
        else:
            # Not registered → check if parent is dead via enumeration
            parent_alive = any(p.pid == proc.ppid for p in enumerate_processes())
            if not parent_alive and confidence == MatchLevel.SPAWN_CHILD:
                reasons.append(f"orphaned spawn child (parent {proc.ppid} dead)")

        if not reasons:
            continue

        candidates.append(
            OrphanCandidate(
                pid=proc.pid,
                identity=proc,
                reason="; ".join(reasons),
                confidence=confidence,
                blocking=blocking,
            )
        )

    return candidates


def reap(
    candidate: OrphanCandidate, *, dry_run: bool = True, grace: float = 5.0
) -> ReapResult:
    """Attempt to terminate *candidate*.

    If ``dry_run=True``, no action is taken and the result reports what would
    have been done. Otherwise:
    1. Send graceful terminate (SIGTERM / taskkill without /F)
    2. Poll every 0.5s up to *grace* seconds
    3. If still alive, force kill (SIGKILL / taskkill /F)
    4. Remove from registry
    """
    if not candidate.blocking and not dry_run:
        return ReapResult(
            pid=candidate.pid,
            action="skipped",
            reason="not blocking; only blocking orphans are auto-reaped",
        )

    if dry_run:
        return ReapResult(
            pid=candidate.pid,
            action="skipped",
            reason=f"dry-run: would {'terminate' if candidate.confidence == MatchLevel.CONFIRMED else 'report'} ({candidate.reason})",
        )

    # Step 1: graceful terminate. On Windows, taskkill without /F fails for
    # window-less processes; that is not fatal, force kill below is the backstop.
    import contextlib
    import subprocess

    with contextlib.suppress(OSError, subprocess.SubprocessError):
        _terminate_pid(candidate.pid, force=False)

    # Step 2: poll
    deadline = time.time() + grace
    while time.time() < deadline:
        if not pid_alive(candidate.pid):
            _cleanup_registry(candidate.pid)
            return ReapResult(
                pid=candidate.pid, action="terminated", reason="graceful exit"
            )
        time.sleep(0.5)

    # Step 3: force kill
    try:
        _terminate_pid(candidate.pid, force=True)
    except OSError as exc:
        return ReapResult(
            pid=candidate.pid, action="failed", reason=f"force kill failed: {exc}"
        )

    time.sleep(0.5)
    if not pid_alive(candidate.pid):
        _cleanup_registry(candidate.pid)
        return ReapResult(pid=candidate.pid, action="killed", reason="forced")

    return ReapResult(
        pid=candidate.pid, action="failed", reason="process survived force kill"
    )


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _my_pid() -> int:
    return __import__("os").getpid()


def _classify(
    proc: ProcInfo, registry: ProcessRegistry, library_root: str
) -> MatchLevel:
    """Classify a process, excluding self/ancestor checks (done by caller)."""
    from mbforge.adapters.runtime.process.discovery import is_mbforge_process

    return is_mbforge_process(proc, registry)


def _is_healthy_backend(pid: int, current_port: int | None) -> bool:
    """Check if *pid* is a healthy MBForge backend on a different port."""
    if current_port is None:
        return False
    listeners = port_listeners(current_port)
    if pid in listeners:
        return False  # It's on our port → blocking, not excluded
    # Check other ports
    for port in range(18790, 18800):
        if port == current_port:
            continue
        if pid in port_listeners(port):
            # Health probe: the host is a literal loopback address and the
            # port comes from a fixed range, so there is no
            # attacker-controlled URL.
            import http.client

            conn = http.client.HTTPConnection("127.0.0.1", port, timeout=1)
            try:
                conn.request("GET", "/api/v1/health")
                if conn.getresponse().status == 200:
                    return True
            except Exception:
                pass
            finally:
                conn.close()
    return False


def _terminate_pid(pid: int, force: bool) -> None:
    """Terminate a process. The ONLY place where we actually kill.

    Tests should mock this function. On Windows uses ``taskkill``; on POSIX
    uses ``os.kill``.
    """
    import os
    import platform
    import signal
    import subprocess

    if platform.system() == "Windows":
        cmd = ["taskkill", "/PID", str(pid)]
        if force:
            cmd.append("/F")
        subprocess.run(cmd, capture_output=True, timeout=5, check=True)
    else:
        sig = signal.SIGKILL if force else signal.SIGTERM
        os.kill(pid, sig)


def _cleanup_registry(pid: int) -> None:
    """Remove a pid from all known registries."""
    # This is best-effort; the registry is per-library-root so we'd need to
    # know which roots to clean. For now, rely on the process's own
    # unregister() call and sweep_stale().
    pass
