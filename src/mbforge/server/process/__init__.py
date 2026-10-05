"""Process governance sub-package.

Public surface for the background task gateway (``tasks``) and the process
governance primitives (locks, identity, discovery, reaping, ordered shutdown).
"""

# Tests: (none)

from mbforge.server.process.discovery import (
    MatchLevel,
    ProcInfo,
    ancestor_pids,
    enumerate_processes,
    is_mbforge_process,
    port_listeners,
)
from mbforge.server.process.filelock import (
    LockHolder,
    LockMeta,
    queue_lock_path,
    read_lock_holder,
    try_lock_existing,
    try_lock_file,
    unlock_file,
)
from mbforge.server.process.identity import (
    ProcessIdentity,
    ProcessRegistry,
    pid_alive,
)
from mbforge.server.process.reaper import (
    OrphanCandidate,
    ReapResult,
    find_orphans,
    reap,
)
from mbforge.server.process.shutdown import orchestrate_shutdown
from mbforge.server.process.tasks import (
    TaskHandle,
    TaskManager,
    TaskPool,
    tasks,
)

__all__ = [
    "LockHolder",
    "LockMeta",
    "MatchLevel",
    "OrphanCandidate",
    "ProcInfo",
    "ProcessIdentity",
    "ProcessRegistry",
    "ReapResult",
    "TaskHandle",
    "TaskManager",
    "TaskPool",
    "ancestor_pids",
    "enumerate_processes",
    "find_orphans",
    "is_mbforge_process",
    "orchestrate_shutdown",
    "pid_alive",
    "port_listeners",
    "queue_lock_path",
    "read_lock_holder",
    "reap",
    "tasks",
    "try_lock_existing",
    "try_lock_file",
    "unlock_file",
]
