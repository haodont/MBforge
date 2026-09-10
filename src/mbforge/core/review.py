"""Review value objects and the shared pending/terminal/reopen state machine.

The value objects (:class:`ReviewState`, :class:`ReviewDecision`) plus the
``resolve_status_transition`` helper and the shared review exception types
are defined here so every review workflow (native review queue, Markush
review, activity review) relies on a single source of truth for legal
transitions. Audit persistence for decisions lives in
:mod:`mbforge.storage.review_audit`.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import Any

from ..utils.errors import MBForgeError

PENDING = "pending"
APPROVED = "approved"
REJECTED = "rejected"


@dataclass(frozen=True)
class ReviewState:
    """Review lifecycle state attached to a domain record."""

    status: str = PENDING
    version: int = 0
    reviewed_at: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "status": self.status,
            "version": self.version,
            "reviewed_at": self.reviewed_at,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> ReviewState:
        return cls(
            status=data.get("status", PENDING),
            version=data.get("version", 0),
            reviewed_at=data.get("reviewed_at"),
        )


@dataclass(frozen=True)
class ReviewDecision:
    """One append-only human decision on a review item.

    ``choice`` is the value the reviewer picked (e.g. a corrected label
    or molecule name); ``payload`` carries kind-specific context.
    """

    item_kind: str  # ambiguous_coref | activity_match | ...
    target_id: str
    action: str  # approved | rejected
    choice: str | None = None
    reviewer: str = ""
    comment: str = ""
    payload: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "item_kind": self.item_kind,
            "target_id": self.target_id,
            "action": self.action,
            "choice": self.choice,
            "reviewer": self.reviewer,
            "comment": self.comment,
            "payload": self.payload,
        }


class ReviewConflictError(MBForgeError):
    """Raised when a reviewer acts on a stale optimistic-lock version."""

    status_code = 409
    error_code = "conflict"


class ReviewTransitionError(MBForgeError):
    """Raised when an action is not legal from the current review state."""

    status_code = 422
    error_code = "validation_error"


class ReviewNotFoundError(MBForgeError):
    """Raised when the requested review entity cannot be located."""

    status_code = 404
    error_code = "not_found"


def resolve_status_transition(
    current_status: str,
    action: str,
    *,
    action_targets: Mapping[str, str],
) -> str:
    """Resolve the shared pending/terminal/reopen review lifecycle.

    Actions in ``action_targets`` are legal only while an item is pending.
    Every review workflow may reopen a confirmed or rejected item back to
    pending. Domain-specific confirmation actions should perform their own
    side effects before calling this helper for their status transition.
    """
    if action == "reopen":
        if current_status not in {"confirmed", "rejected"}:
            raise ReviewTransitionError(f"cannot reopen from {current_status}")
        return "pending"

    target_status = action_targets.get(action)
    if target_status is None:
        raise ReviewTransitionError(f"unsupported action: {action}")
    if current_status != "pending":
        raise ReviewTransitionError(f"cannot {action} from {current_status}")
    return target_status
