"""Structured observability events for Markush operations.

Emits structured log events at INFO level for key Markush pipeline and
review operations. Each event includes:

- ``event_type``: kebab-case event name
- ``doc_id``, ``scaffold_id``, ``fragment_id``, etc.: entity references
- ``status``: success/failure/pending
- ``duration_ms``: operation latency (when applicable)
- ``metadata``: operation-specific context

Events are written to the standard logger as JSON-formatted INFO messages
when ``MBFORGE_LOG_FORMAT=json`` is set. Without that env var, they appear
as plain text INFO lines.

The consumer (monitoring, analytics) parses these events from the log stream
rather than querying a separate event store. This approach avoids adding a
dedicated events table and keeps the observability path independent of the
business transaction.

Event types:

- ``markush_candidate_created``
- ``markush_candidate_superseded``
- ``markush_decision_applied``
- ``markush_role_transitioned``
- ``markush_mount_suggested``
- ``markush_mount_confirmed``
- ``markush_match_completed``
- ``markush_generation_rejected``
- ``markush_generation_completed``
- ``markush_generated_promoted``
"""

from __future__ import annotations

import time
from collections.abc import Iterator
from contextlib import contextmanager
from typing import Any

from ..utils.logger import get_logger

logger = get_logger("mbforge.core.markush_events")


def emit_event(event_type: str, **fields: Any) -> None:
    """Emit a structured observability event.

    Args:
        event_type: Kebab-case event name (e.g., "markush-candidate-created").
        **fields: Additional event fields (doc_id, status, metadata, etc.).
    """
    payload = {"event_type": event_type, **fields}
    logger.info("Markush event: %s", event_type, extra={"event": payload})


@contextmanager
def timed_operation(event_type: str, **base_fields: Any) -> Iterator[dict[str, Any]]:
    """Context manager for timing an operation and emitting an event on exit.

    Usage:
        with timed_operation("markush-generation-completed", scaffold_id=sid) as ctx:
            ctx["count"] = do_work()
        # Emits event with duration_ms and count fields

    Args:
        event_type: Event name to emit on exit.
        **base_fields: Base fields to include in the event.

    Yields:
        A mutable dict for accumulating additional fields during the operation.
    """
    start_ms = time.perf_counter() * 1000
    ctx: dict[str, Any] = {}
    try:
        yield ctx
    finally:
        duration_ms = time.perf_counter() * 1000 - start_ms
        emit_event(event_type, duration_ms=duration_ms, **base_fields, **ctx)


# ── Event emitters for each Markush operation ────────────────────────────


def candidate_created(
    candidate_id: str,
    doc_id: str,
    predicted_role: str,
    recognition_status: str,
    reasons: list[str],
) -> None:
    """Emit markush_candidate_created event."""
    emit_event(
        "markush_candidate_created",
        candidate_id=candidate_id,
        doc_id=doc_id,
        predicted_role=predicted_role,
        recognition_status=recognition_status,
        reasons=reasons,
    )


def candidate_superseded(
    candidate_id: str,
    source_key: str,
    reason: str,
) -> None:
    """Emit markush_candidate_superseded event."""
    emit_event(
        "markush_candidate_superseded",
        candidate_id=candidate_id,
        source_key=source_key,
        reason=reason,
    )


def decision_applied(
    entity_type: str,
    entity_id: str,
    action: str,
    previous_state: str,
    new_state: str,
    reason: str = "",
) -> None:
    """Emit markush_decision_applied event."""
    emit_event(
        "markush_decision_applied",
        entity_type=entity_type,
        entity_id=entity_id,
        action=action,
        previous_state=previous_state,
        new_state=new_state,
        reason=reason,
    )


def role_transitioned(
    candidate_id: str,
    from_role: str,
    to_role: str,
    target_table: str,
    target_id: str,
) -> None:
    """Emit markush_role_transitioned event."""
    emit_event(
        "markush_role_transitioned",
        candidate_id=candidate_id,
        from_role=from_role,
        to_role=to_role,
        target_table=target_table,
        target_id=target_id,
    )


def mount_suggested(
    mount_id: str,
    site_id: str,
    fragment_id: str,
    origin: str,
    confidence: float | None,
    reasons: list[str],
) -> None:
    """Emit markush_mount_suggested event."""
    emit_event(
        "markush_mount_suggested",
        mount_id=mount_id,
        site_id=site_id,
        fragment_id=fragment_id,
        origin=origin,
        confidence=confidence,
        reasons=reasons,
    )


def mount_confirmed(
    mount_id: str,
    site_id: str,
    fragment_id: str,
    previous_status: str,
) -> None:
    """Emit markush_mount_confirmed event."""
    emit_event(
        "markush_mount_confirmed",
        mount_id=mount_id,
        site_id=site_id,
        fragment_id=fragment_id,
        previous_status=previous_status,
    )


def match_completed(
    scaffold_id: str,
    query_smiles: str,
    match_level: str,
    site_results: list[dict[str, Any]],
    duration_ms: float,
) -> None:
    """Emit markush_match_completed event."""
    emit_event(
        "markush_match_completed",
        scaffold_id=scaffold_id,
        query_smiles=query_smiles,
        match_level=match_level,
        site_count=len(site_results),
        duration_ms=duration_ms,
    )


def generation_rejected(
    scaffold_id: str,
    theoretical_count: int,
    requested_limit: int,
    reason: str,
) -> None:
    """Emit markush_generation_rejected event."""
    emit_event(
        "markush_generation_rejected",
        scaffold_id=scaffold_id,
        theoretical_count=theoretical_count,
        requested_limit=requested_limit,
        reason=reason,
    )


def generation_completed(
    run_id: str,
    scaffold_id: str,
    theoretical_count: int,
    generated_count: int,
    duration_ms: float,
    status: str,
    error: str | None = None,
) -> None:
    """Emit markush_generation_completed event."""
    emit_event(
        "markush_generation_completed",
        run_id=run_id,
        scaffold_id=scaffold_id,
        theoretical_count=theoretical_count,
        generated_count=generated_count,
        duration_ms=duration_ms,
        status=status,
        error=error,
    )


def generated_promoted(
    generated_id: str,
    run_id: str,
    target_mol_id: str,
    review_status: str,
) -> None:
    """Emit markush_generated_promoted event."""
    emit_event(
        "markush_generated_promoted",
        generated_id=generated_id,
        run_id=run_id,
        target_mol_id=target_mol_id,
        review_status=review_status,
    )
