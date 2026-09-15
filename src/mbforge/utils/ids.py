"""Identifier generators — MBForge’s single source of truth for IDs.

All generators are owned here (and re-exported from :mod:`mbforge.utils`) so
``uuid`` / ``hashlib`` are never imported elsewhere in the codebase:

* :func:`short_id` — random 64-bit hex id for entity/run identifiers.
* :func:`deterministic_id` — UUID5 for idempotency keys (identical
  ``(namespace, name)`` always yields the same id).
* :func:`stable_id` — SHA-256 deterministic id for content / geometry
  derived identity (identical parts always yield the same id).
"""

from __future__ import annotations

import hashlib
import uuid

#: Separator used when folding heterogeneous *parts* into one hashed key.
_SEP = "\x1f"

def short_id() -> str:
    """Return a 16-character hexadecimal identifier (64-bit random id)."""
    return uuid.uuid4().hex[:16]


def deterministic_id(namespace: str | uuid.UUID, name: str) -> str:
    """Return a deterministic UUID5: identical (namespace, name) → identical id.

    Deliberately NOT random — use for idempotency keys where the same
    canonical tuple must map to the same id across runs. ``namespace`` may be
    a :class:`uuid.UUID` instance or its canonical string form.
    """
    ns = namespace if isinstance(namespace, uuid.UUID) else uuid.UUID(str(namespace))
    return str(uuid.uuid5(ns, name))


def stable_id(*parts: str, length: int = 32) -> str:
    """Return a deterministic SHA-256 id from *parts* (default 32 hex chars).

    Identical parts in the same order map to the same id across runs. Use for
    content / geometry derived identity where the same canonical tuple must be
    stable (evidence ids, entry ids, candidate ids, …). ``length`` caps the
    hex digest (must be 1..64).
    """
    if not 1 <= length <= 64:
        raise ValueError("stable_id length must be in 1..64")
    payload = _SEP.join(str(part) for part in parts)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()[:length]
