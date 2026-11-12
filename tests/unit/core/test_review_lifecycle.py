"""Regression tests for review-state rules shared by both review entry points.

Covers ``mbforge.domain.review`` (error taxonomy + ``resolve_status_transition``).
"""

from __future__ import annotations

import pytest

from mbforge.domain.review import (
    ReviewConflictError,
    ReviewNotFoundError,
    ReviewTransitionError,
    resolve_status_transition,
)
from mbforge.foundation.errors import MBForgeError


def test_review_errors_inherit_mbforge_error_with_status_code() -> None:
    assert issubclass(ReviewNotFoundError, MBForgeError)
    assert issubclass(ReviewConflictError, MBForgeError)
    assert issubclass(ReviewTransitionError, MBForgeError)

    assert ReviewNotFoundError.status_code == 404
    assert ReviewNotFoundError.error_code == "not_found"
    assert ReviewConflictError.status_code == 409
    assert ReviewConflictError.error_code == "conflict"
    assert ReviewTransitionError.status_code == 422
    assert ReviewTransitionError.error_code == "validation_error"


def test_resolve_status_transition_allows_terminal_reopen_and_rejects_invalid() -> None:
    """Terminal actions and reopen resolve to their targets; an action invalid
    for the current state or an unsupported action raises."""
    targets = {"confirm": "confirmed", "reject": "rejected"}

    assert (
        resolve_status_transition("pending", "confirm", action_targets=targets)
        == "confirmed"
    )
    assert (
        resolve_status_transition("pending", "reject", action_targets=targets)
        == "rejected"
    )
    assert (
        resolve_status_transition("confirmed", "reopen", action_targets=targets)
        == "pending"
    )

    with pytest.raises(ReviewTransitionError, match="cannot confirm from rejected"):
        resolve_status_transition(
            "rejected", "confirm", action_targets={"confirm": "confirmed"}
        )
    with pytest.raises(ReviewTransitionError, match="unsupported action: archive"):
        resolve_status_transition(
            "pending", "archive", action_targets={"confirm": "confirmed"}
        )


def test_a_reading_bound_by_a_later_pass_closes_its_queue_item(tmp_path) -> None:
    """An answered question must leave the queue.

    The example-label fallback bound thirty ``实施例…`` readings in
    CN120943813A while their ``designation_unbound`` items stayed pending, so a
    human was asked to decide a link that already existed. Only items whose
    reading is bound are closed; an unrelated item keeps waiting.
    """
    from mbforge.db.sqlite.database import DatabaseManager
    from mbforge.service.ports import get_repositories

    DatabaseManager.get(str(tmp_path)).initialize()
    review = get_repositories(str(tmp_path)).review
    for item_id, measurement_id in (("unbound-1", "m-1"), ("unbound-2", "m-2")):
        review.insert_review_item(
            item_id=item_id,
            kind="designation_unbound",
            doc_id="doc-1",
            page=94,
            name="30A",
            reasons=["designation_without_structure"],
            payload={"doc_id": "doc-1", "measurement_id": measurement_id},
        )

    closed = review.resolve_bound_designations("doc-1", ["m-1"])

    assert closed == 1
    assert review.get_item("designation_unbound", "unbound-1")["status"] == "confirmed"
    assert review.get_item("designation_unbound", "unbound-2")["status"] == "pending"

    # A repeat run finds nothing left to close.
    assert review.resolve_bound_designations("doc-1", ["m-1"]) == 0
