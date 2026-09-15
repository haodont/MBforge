"""Process governance sub-package.

Public surface for the background task gateway (``tasks``), the GPU inference
gate (``gpu_gate``), and the process governance primitives (locks, identity,
discovery, reaping, ordered shutdown).
"""

from .discovery import (
    MatchLevel,
    ProcInfo,
    ancestor_pids,
    enumerate_processes,
    is_mbforge_process,
    port_listeners,
)
from .filelock import (
    LockHolder,
    LockMeta,
    queue_lock_path,
    read_lock_holder,
    try_lock_existing,
    try_lock_file,
    unlock_file,
)
from .identity import ProcessIdentity, ProcessRegistry, pid_alive
from .reaper import OrphanCandidate, ReapResult, find_orphans, reap
from .shutdown import orchestrate_shutdown
from .tasks import TaskHandle, TaskManager, TaskPool, gpu_gate, tasks

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
    "gpu_gate",
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
