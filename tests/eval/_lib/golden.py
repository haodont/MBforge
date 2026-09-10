"""Integrity checks for the supervised golden references.

The two current references are intentionally partial: their activity tables
contain a small ``pending_manual`` tail and only a subset of rows has a
second reviewer.  This module keeps those facts visible while checking the
invariants required for deterministic pipeline calibration.
"""

from __future__ import annotations

import re
from dataclasses import asdict, dataclass
from typing import Any

_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
_REQUIRED_ACTIVITY_FIELDS = (
    "compound_label",
    "pdf_page",
    "value_text",
    "value_original",
    "value_canonical_nm",
    "metric",
    "target",
    "operator_original",
    "annotation_status",
)
_SAFE_MARKUSH_ROLES = frozenset(
    {
        "markush",
        "markush_substituent_catalog",
        "markush_variant_family",
        "markush_claim",
    }
)


@dataclass(frozen=True)
class GoldenValidation:
    """Validation result that separates hard errors from review warnings."""

    dataset_id: str | None
    errors: tuple[str, ...]
    warnings: tuple[str, ...]
    counts: dict[str, int]

    @property
    def valid(self) -> bool:
        """Return whether the reference is structurally usable."""
        return not self.errors

    @property
    def fully_supervised(self) -> bool:
        """Return whether no pending or single-review annotations remain."""
        return self.valid and not any(
            key in self.warnings
            for key in (
                "pending_manual_rows",
                "verified_rows_without_second_reviewer",
            )
        )

    def as_dict(self) -> dict[str, Any]:
        """Return a JSON-serializable validation payload."""
        payload = asdict(self)
        payload["valid"] = self.valid
        payload["fully_supervised"] = self.fully_supervised
        return payload


def _is_number(value: Any) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool)


def _status_counts(rows: list[dict[str, Any]]) -> dict[str, int]:
    statuses = {str(row.get("annotation_status")) for row in rows}
    return {
        status: sum(row.get("annotation_status") == status for row in rows)
        for status in statuses
    }


def validate_reference(
    reference: dict[str, Any], *, expected_folder: str | None = None
) -> GoldenValidation:
    """Validate one v2 golden reference without accessing its source PDF."""
    errors: list[str] = []
    warnings: list[str] = []
    dataset_id = reference.get("dataset_id")

    if reference.get("schema_version") != 2:
        errors.append("schema_version must be 2")
    if not isinstance(dataset_id, str) or not dataset_id:
        errors.append("dataset_id is required")
    elif expected_folder and dataset_id != f"{expected_folder}.v1":
        errors.append(
            f"dataset_id {dataset_id!r} does not match {expected_folder!r}.v1"
        )

    source = reference.get("source")
    if not isinstance(source, dict):
        errors.append("source must be an object")
        source = {}
    page_count = source.get("pdf_page_count")
    if not isinstance(page_count, int) or page_count <= 0:
        errors.append("source.pdf_page_count must be a positive integer")
    digest = source.get("sha256")
    if not isinstance(digest, str) or not _SHA256_RE.fullmatch(digest):
        errors.append("source.sha256 must be a lowercase 64-character hex digest")

    rows = reference.get("activity_rows")
    if not isinstance(rows, list) or not rows:
        errors.append("activity_rows must be a non-empty array")
        rows = []
    labels: list[str] = []
    ids: list[str] = []
    for index, row in enumerate(rows):
        if not isinstance(row, dict):
            errors.append(f"activity_rows[{index}] must be an object")
            continue
        missing = [key for key in _REQUIRED_ACTIVITY_FIELDS if key not in row]
        if missing:
            errors.append(f"activity_rows[{index}] missing: {', '.join(missing)}")
        label = row.get("compound_label")
        if isinstance(label, str) and label:
            labels.append(label)
        row_id = row.get("id")
        if isinstance(row_id, str) and row_id:
            ids.append(row_id)
        page = row.get("pdf_page")
        if (
            isinstance(page_count, int)
            and isinstance(page, int)
            and not 1 <= page <= page_count
        ):
            errors.append(f"activity_rows[{index}].pdf_page is outside source range")
        for key in ("value_original", "value_canonical_nm"):
            if key in row and not _is_number(row[key]):
                errors.append(f"activity_rows[{index}].{key} must be numeric")

    if len(labels) != len(set(labels)):
        errors.append("activity_rows compound_label values must be unique")
    if len(ids) != len(set(ids)):
        errors.append("activity_rows id values must be unique")

    markush = reference.get("markush_anchors")
    if not isinstance(markush, list) or not markush:
        errors.append("markush_anchors must be a non-empty array")
        markush = []
    for index, anchor in enumerate(markush):
        if not isinstance(anchor, dict):
            errors.append(f"markush_anchors[{index}] must be an object")
            continue
        if anchor.get("expected_review_required") is not True:
            errors.append(f"markush_anchors[{index}] must require review")
        if anchor.get("can_enter_concrete_library") is not False:
            errors.append(f"markush_anchors[{index}] cannot enter concrete library")
        if anchor.get("role") not in _SAFE_MARKUSH_ROLES:
            errors.append(f"markush_anchors[{index}] has an unsafe/unknown role")

    concrete = reference.get("concrete_molecule_anchors")
    if not isinstance(concrete, list) or not concrete:
        errors.append("concrete_molecule_anchors must be a non-empty array")
        concrete = []
    concrete_labels = [
        anchor.get("compound_label")
        for anchor in concrete
        if isinstance(anchor, dict) and isinstance(anchor.get("compound_label"), str)
    ]
    if len(concrete_labels) != len(set(concrete_labels)):
        errors.append("concrete_molecule_anchors labels must be unique")

    overview = reference.get("annotation_status_overview")
    if not isinstance(overview, dict):
        errors.append("annotation_status_overview must be an object")
        overview = {}
    computed_overview = {
        "rows_total": len(rows),
        "rows_verified": sum(
            row.get("annotation_status") == "verified"
            for row in rows
            if isinstance(row, dict)
        ),
        "rows_pending_manual": sum(
            row.get("annotation_status") == "pending_manual"
            for row in rows
            if isinstance(row, dict)
        ),
        "rows_in_review": sum(
            row.get("annotation_status") == "in_review"
            for row in rows
            if isinstance(row, dict)
        ),
        "rows_needs_review": sum(
            row.get("annotation_status") == "needs_review"
            for row in rows
            if isinstance(row, dict)
        ),
        "rows_disputed": sum(
            row.get("annotation_status") == "disputed"
            for row in rows
            if isinstance(row, dict)
        ),
        "markush_anchors_total": len(markush),
        "concrete_anchors_total": len(concrete),
    }
    for key, expected in computed_overview.items():
        if overview.get(key) != expected:
            errors.append(
                f"annotation_status_overview.{key}={overview.get(key)!r} "
                f"does not match {expected!r}"
            )

    coverage = reference.get("coverage")
    if not isinstance(coverage, dict):
        errors.append("coverage must be an object")
        coverage = {}
    activity_coverage = coverage.get("activity")
    if isinstance(activity_coverage, dict) and activity_coverage.get("rows") != len(
        rows
    ):
        errors.append("coverage.activity.rows does not match activity_rows")

    pending = computed_overview["rows_pending_manual"]
    if pending:
        warnings.append("pending_manual_rows")
    verified_without_second = sum(
        row.get("annotation_status") == "verified" and not row.get("second_reviewer")
        for row in rows
        if isinstance(row, dict)
    )
    if verified_without_second:
        warnings.append("verified_rows_without_second_reviewer")
    smiles_coverage = coverage.get("smiles_coverage")
    if (
        isinstance(smiles_coverage, dict) and smiles_coverage.get("canonical", 0) == 0
    ) or not isinstance(smiles_coverage, dict):
        warnings.append("canonical_smiles_not_annotated")

    counts = {
        "activity_rows": len(rows),
        "verified_activity_rows": computed_overview["rows_verified"],
        "pending_activity_rows": pending,
        "verified_rows_with_second_reviewer": computed_overview["rows_verified"]
        - verified_without_second,
        "markush_anchors": len(markush),
        "concrete_molecule_anchors": len(concrete),
        "full_text_mentions": len(
            coverage.get("full_text_molecule_index", {}).get("mentions", [])
            if isinstance(coverage.get("full_text_molecule_index"), dict)
            else []
        ),
    }
    return GoldenValidation(
        dataset_id=dataset_id if isinstance(dataset_id, str) else None,
        errors=tuple(errors),
        warnings=tuple(dict.fromkeys(warnings)),
        counts=counts,
    )


__all__ = ["GoldenValidation", "validate_reference"]
