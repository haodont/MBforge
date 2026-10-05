"""Load-failure cooldown shared by the local inference backends.

Every backend here loads lazily on first use and falls back to auto-downloading
its weights. When that load fails, the model object stays ``None`` — so without
a guard the *next* call retries the whole download + load sequence. In practice
that meant one missing model produced a fresh multi-second download attempt per
crop, per document, and per worker thread, and the log filled with repeated
ModelScope/HuggingFace failures.

:class:`LoadGuard` records the failure and suppresses further attempts for a
cooldown window, so a permanently unavailable model costs one attempt instead
of unbounded retries. The backend still reports the original error, and
:meth:`LoadGuard.reset` (called by ``unload``) lets an explicit retry through —
e.g. after the user downloads the weights from Settings.
"""

from __future__ import annotations

import threading
import time

from mbforge.foundation.logger import get_logger

logger = get_logger(__name__)

#: Default cooldown between failed load attempts. Long enough that a broken
#: model does not re-attempt per crop, short enough that a user who just fixed
#: the weights is not blocked for long.
DEFAULT_COOLDOWN_S = 300.0


class LoadGuard:
    """Cooldown gate for a lazily-loaded backend model (thread-safe)."""

    def __init__(self, name: str, cooldown_s: float = DEFAULT_COOLDOWN_S) -> None:
        self._name = name
        self._cooldown_s = cooldown_s
        self._lock = threading.Lock()
        self._failed_until = 0.0
        self._last_error = ""

    def should_attempt(self) -> bool:
        """Whether a load attempt is allowed right now."""
        with self._lock:
            if not self._failed_until:
                return True
            remaining = self._failed_until - time.monotonic()
            if remaining <= 0:
                # Cooldown elapsed: allow one more attempt.
                self._failed_until = 0.0
                return True
            return False

    def record_failure(self, error: str) -> None:
        """Start (or extend) the cooldown after a failed attempt."""
        with self._lock:
            first_failure = not self._failed_until
            self._failed_until = time.monotonic() + self._cooldown_s
            self._last_error = error
        if first_failure:
            logger.warning(
                "%s load failed; suppressing retries for %.0fs: %s",
                self._name,
                self._cooldown_s,
                error,
            )

    def record_success(self) -> None:
        """Clear the cooldown after a successful load."""
        with self._lock:
            self._failed_until = 0.0
            self._last_error = ""

    def reset(self) -> None:
        """Drop the cooldown so the next call attempts a load again."""
        with self._lock:
            self._failed_until = 0.0
            self._last_error = ""

    def last_error(self) -> str:
        """The most recent failure reason (empty when none is recorded)."""
        with self._lock:
            return self._last_error

    def in_cooldown(self) -> bool:
        """Whether a failed attempt is currently suppressing retries."""
        with self._lock:
            return bool(self._failed_until) and (
                self._failed_until - time.monotonic() > 0
            )


__all__ = ["DEFAULT_COOLDOWN_S", "LoadGuard"]
