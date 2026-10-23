"""Regression tests for review-state rules shared by both review entry points.

Covers ``mbforge.domain.review`` (error taxonomy + ``resolve_status_transition``)
and the shared ``MarkushSiteError`` status mapping.
"""

from __future__ import annotations

import pytest

from mbforge.domain.markush import MarkushSiteError
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
    assert issubclass(MarkushSiteError, MBForgeError)

    assert ReviewNotFoundError.status_code == 404
    assert ReviewNotFoundError.error_code == "not_found"
    assert ReviewConflictError.status_code == 409
    assert ReviewConflictError.error_code == "conflict"
    assert ReviewTransitionError.status_code == 422
    assert ReviewTransitionError.error_code == "validation_error"
    assert MarkushSiteError.status_code == 422
    assert MarkushSiteError.error_code == "validation_error"


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
