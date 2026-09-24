"""Immutable source evidence shared by extraction and domain objects."""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Any

from mbforge.foundation.ids import stable_id


def _normalise_bbox(
    bbox: tuple[float, float, float, float] | list[float] | None,
) -> tuple[float, float, float, float]:
    if bbox is None:
        raise ValueError("bbox is required")
    if not isinstance(bbox, (tuple, list)):
        raise ValueError("bbox must be a four-coordinate tuple or list")
    if len(bbox) != 4:
        raise ValueError("bbox must contain exactly four coordinates")
    x0, y0, x1, y1 = (float(value) for value in bbox)
    values = (x0, y0, x1, y1)
    if not all(math.isfinite(value) for value in values):
        raise ValueError("bbox coordinates must be finite")
    if min(values) < 0 or x0 > x1 or y0 > y1:
        raise ValueError("bbox must satisfy 0 <= x0 <= x1 and 0 <= y0 <= y1")
    return values


def _location_id(
    doc_id: str,
    page: int,
    bbox: tuple[float, float, float, float],
) -> str:
    """Stable ID of a page region.

    Identity is the **location only** — doc, page, bbox.  ``kind`` deliberately
    stays out of it: a producer's label is an attribute of the region, so
    re-classifying one does not mint a new evidence row.
    """
    parts = (
        "evidence-v1",
        doc_id,
        str(page),
        *(f"{round(value, 2):.2f}" for value in bbox),
    )
    return stable_id(*parts)


@dataclass(frozen=True)
class SourceEvidence:
    """One immutable source region and its raw content.

    A source evidence object is valid only when it has a geometric location.
    Secondary domain objects reference it by ``evidence_id``; they do not
    create page-only source evidence of their own.

    ``kind`` is the **producer's own label** (``text`` / ``sec`` / ``head`` /
    ``tab`` / ``molecule`` …) stored verbatim; readers map it to a category
    through :mod:`mbforge.domain.evidence_kind`.  ``raw_text`` is the row's
    single payload column — recognized text, a Markdown table, or, for a
    molecule, the observation JSON.  A region the producer found but could not
    read carries an empty payload; that is a legal row.
    """

    doc_id: str
    page: int
    bbox: tuple[float, float, float, float]
    evidence_id: str = ""
    raw_text: str = ""
    kind: str = "text"

    def __post_init__(self) -> None:
        if not self.doc_id:
            raise ValueError("doc_id must not be empty")
        if (
            not isinstance(self.page, int)
            or isinstance(self.page, bool)
            or self.page < 1
        ):
            raise ValueError("page must be a positive 1-based integer")
        if not self.kind:
            raise ValueError("kind must not be empty")
        normalised = _normalise_bbox(self.bbox)
        if normalised != self.bbox:
            object.__setattr__(self, "bbox", normalised)
        if not self.evidence_id:
            object.__setattr__(
                self,
                "evidence_id",
                _location_id(
                    self.doc_id,
                    self.page,
                    normalised,
                ),
            )

    def to_dict(self) -> dict[str, Any]:
        return {
            "doc_id": self.doc_id,
            "page": self.page,
            "evidence_id": self.evidence_id,
            "bbox": list(self.bbox),
            "raw_text": self.raw_text,
            "kind": self.kind,
        }

    @classmethod
    def create(
        cls,
        *,
        doc_id: str,
        page: int,
        bbox: tuple[float, float, float, float] | list[float],
        raw_text: str = "",
        kind: str = "text",
    ) -> SourceEvidence:
        normalised = _normalise_bbox(bbox)
        return cls(
            doc_id=doc_id,
            page=page,
            bbox=normalised,
            raw_text=raw_text,
            kind=kind,
            evidence_id=_location_id(
                doc_id,
                page,
                normalised,
            ),
        )

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> SourceEvidence:
        bbox = data.get("bbox")
        if bbox is None:
            raise ValueError("bbox is required")
        normalised = _normalise_bbox(bbox)
        return cls(
            doc_id=data["doc_id"],
            page=data["page"],
            bbox=normalised,
            evidence_id=data.get("evidence_id", ""),
            raw_text=data.get("raw_text", ""),
            kind=data.get("kind", "text"),
        )


__all__ = ["SourceEvidence"]
