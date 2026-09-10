"""Markush leakage and classification evaluator (golden-agnostic).

A Markush leakage is when a generic structure (Formula I, an R-group
system, or any row whose ``molecule_role`` is ``markush`` /
``markush_substituent_catalog``) is incorrectly registered as a concrete
library molecule. Reports:

    leakage_count            number of golden markush rows classified
                             as concrete by the candidate
    leakage_rate             leakage_count / anchors_total (must be 0)
    recall                   fraction of golden markush anchors recovered
    role_classification      fraction of recovered anchors whose role is
                             semantically safe for the golden role
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any

from .activity import by_label


@dataclass(frozen=True)
class MarkushMetrics:
    """Numeric metrics emitted by the Markush evaluator."""

    leakage_count: int
    leakage_rate: float
    recall: float
    role_classification_accuracy: float
    anchors_total: int
    anchors_recovered: int

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


# Runtime ``complete`` is the concrete-library role. The other runtime roles
# are deliberately non-concrete and therefore safe for a Markush anchor.
CONCRETE_ROLES = frozenset({"concrete", "concrete_structure_image", "complete"})
MARKUSH_GOLDEN_ROLES = frozenset(
    {
        "markush",
        "markush_substituent_catalog",
        "markush_variant_family",
        "markush_claim",
    }
)
SAFE_MARKUSH_RUNTIME_ROLES = frozenset(
    {"scaffold", "fragment", "review_required", *MARKUSH_GOLDEN_ROLES}
)


def _role_matches(golden_role: Any, candidate_role: Any) -> bool:
    """Compare golden roles with runtime roles without hiding leakage."""
    if golden_role in MARKUSH_GOLDEN_ROLES:
        return candidate_role in SAFE_MARKUSH_RUNTIME_ROLES
    return golden_role == candidate_role


def score_markush(
    markush_anchors: list[dict[str, Any]],
    candidate: dict[str, Any],
) -> MarkushMetrics:
    """Score Markush classification against the golden anchors."""
    gold_by_label = by_label(markush_anchors)
    cand_by_label = by_label(candidate.get("molecules", []))

    common = sorted(set(gold_by_label) & set(cand_by_label))

    leakage = sum(
        1
        for label in common
        if cand_by_label[label].get("molecule_role") in CONCRETE_ROLES
    )

    recall = len(common) / max(len(gold_by_label), 1)

    role_hits = sum(
        1
        for label in common
        if _role_matches(
            gold_by_label[label].get("role"),
            cand_by_label[label].get("molecule_role"),
        )
    )

    return MarkushMetrics(
        leakage_count=leakage,
        leakage_rate=leakage / max(len(gold_by_label), 1),
        recall=recall,
        role_classification_accuracy=role_hits / max(len(common), 1),
        anchors_total=len(gold_by_label),
        anchors_recovered=len(common),
    )
