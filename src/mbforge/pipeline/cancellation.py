"""Cooperative cancellation for pipeline tasks.

A small encapsulated registry replaces route-direct access to a
module-private set: the queue router signals cancellation through
``CancellationRegistry.cancel()``, long-running stages poll a bound
checkpoint at page / batch / chunk / retry boundaries, and the runner
unregisters the task id on every terminal state (success, failure,
cancelled) so the registry never leaks entries.

Third-party blocking calls (OCR backends, MolParser, LLM completions) are
never force-killed; the first checkpoint after such a call returns stops any
further writes.
"""

from __future__ import annotations

import threading
from collections.abc import Callable

from ..utils.logger import get_logger
from .stage_result import PipelineErrorCode

logger = get_logger("mbforge.pipeline.cancellation")

# Distinct error code for user cancellation; ordinary failures keep their
# stage-specific codes so the queue can tell the two terminal states apart.
PIPELINE_CANCELLED = PipelineErrorCode.PIPELINE_CANCELLED

# A cooperative cancellation checkpoint: raises TaskCancelledError when the
# owning task has been cancelled, otherwise returns immediately.
CancelCheck = Callable[[], None]


class TaskCancelledError(RuntimeError):
    """Raised at a cooperative checkpoint after the user cancels a task."""

    error_code = PIPELINE_CANCELLED

    def __init__(self, task_id: str | None = None) -> None:
        super().__init__("Pipeline cancelled by user")
        self.task_id = task_id


class CancellationRegistry:
    """Thread-safe set of task IDs the user asked to cancel.

    All mutations go through this class; nothing outside the pipeline package
    touches the backing set. Entries are removed by ``unregister()`` — the
    runner calls it in a ``finally`` on every terminal state, and the queue
    router calls it when a pending future is cancelled before the runner
    ever starts.
    """

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._cancelled: set[str] = set()

    def cancel(self, task_id: str) -> None:
        """Mark ``task_id`` as cancelled (idempotent)."""
        with self._lock:
            self._cancelled.add(task_id)

    def is_cancelled(self, task_id: str | None) -> bool:
        if task_id is None:
            return False
        with self._lock:
            return task_id in self._cancelled

    def unregister(self, task_id: str | None) -> None:
        """Drop any cancellation mark for ``task_id`` (idempotent)."""
        if task_id is None:
            return
        with self._lock:
            self._cancelled.discard(task_id)

    def __len__(self) -> int:
        with self._lock:
            return len(self._cancelled)


# Shared registry used by the runner and the queue router.
default_registry = CancellationRegistry()


def make_cancel_check(
    registry: CancellationRegistry, task_id: str | None
) -> CancelCheck:
    """Return a cooperative checkpoint closure bound to ``task_id``.

    The closure is a no-op when ``task_id`` is None so long-running helpers
    can call it unconditionally at page/batch/chunk/retry boundaries.
    """

    def _check() -> None:
        if registry.is_cancelled(task_id):
            logger.info("Cancellation checkpoint hit for task %s", task_id)
            raise TaskCancelledError(task_id)

    return _check
