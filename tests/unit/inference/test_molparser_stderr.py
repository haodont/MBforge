"""MolParser must survive a stderr handle the server process cannot write to.

``transformers`` builds a tqdm bar while loading weights and tqdm flushes
``sys.stderr`` from its status printer. A backend spawned with a redirect whose
pipe is gone raises ``OSError: [Errno 22] Invalid argument`` inside
``from_pretrained``, so the model fails to load for a reason unrelated to the
weights — measured on CN120118069A.
"""

from __future__ import annotations

import sys

from mbforge.foundation.inference.molparser import _flushable_stderr


class _BrokenStream:
    """A stderr whose every flush raises, like a closed Windows pipe."""

    def __init__(self) -> None:
        self.written: list[str] = []

    def write(self, text: str) -> int:
        self.written.append(text)
        return len(text)

    def flush(self) -> None:
        raise OSError(22, "Invalid argument")


def test_a_broken_stderr_is_swapped_out_for_the_load(monkeypatch) -> None:
    broken = _BrokenStream()
    monkeypatch.setattr(sys, "stderr", broken)

    guard = _flushable_stderr()

    assert guard is not None
    with guard:
        assert sys.stderr is not broken
        sys.stderr.write("Loading weights")
        sys.stderr.flush()

    assert sys.stderr is broken


def test_a_working_stderr_is_left_alone(monkeypatch) -> None:
    class _Stream(_BrokenStream):
        def flush(self) -> None:
            return None

    stream = _Stream()
    monkeypatch.setattr(sys, "stderr", stream)

    assert _flushable_stderr() is None
    assert sys.stderr is stream
