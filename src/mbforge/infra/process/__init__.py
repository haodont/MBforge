"""Process governance sub-package.

Re-exports lock primitives so existing ``services/worker.py`` callers can
import from either location without breaking.
"""

from .discovery import (
    MatchLevel,
    ProcInfo,
    ancestor_pids,
    enumerate_processes,
    is_mbforge_process,
    port_listeners,
)
from .executors import drain_executors, gpu_gate, ocr_executor, pipeline_executor
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

__all__ = [
    "LockHolder",
    "LockMeta",
    "MatchLevel",
    "OrphanCandidate",
    "ProcInfo",
    "ProcessIdentity",
    "ProcessRegistry",
    "ReapResult",
    "ancestor_pids",
    "drain_executors",
    "enumerate_processes",
    "find_orphans",
    "gpu_gate",
    "is_mbforge_process",
    "ocr_executor",
    "orchestrate_shutdown",
    "pid_alive",
    "pipeline_executor",
    "port_listeners",
    "queue_lock_path",
    "read_lock_holder",
    "reap",
    "try_lock_existing",
    "try_lock_file",
    "unlock_file",
]
