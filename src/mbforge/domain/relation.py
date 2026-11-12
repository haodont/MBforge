"""ADR 0001 relation-pair domain types.

The canonical unit is a document-local relation pair. These are the pure
producer-side types: a :class:`LabelAnchor` is one printed designation slot
(the fact), and :class:`PageGeometry` is the scanned-page metadata geometry
checks need. The resolution itself (``relation_pair``) is written by the
association pass and is not modeled here yet.

An anchor deliberately carries no ``mol_id``: the anchor is the fact, the
resolution is an assertion about it. Structures are referenced by ``mol_id``
only in a pair, never as SMILES.
"""

from __future__ import annotations

from dataclasses import dataclass

from mbforge.foundation.ids import stable_id


@dataclass(frozen=True)
class PageGeometry:
    """One scanned page's size and render resolution (PDF points)."""

    doc_id: str
    page: int
    width_pt: float
    height_pt: float
    render_dpi: float
    quality_class: str = "clean"


@dataclass(frozen=True)
class LabelAnchor:
    """One printed designation slot, cited to the evidence row it came from.

    ``label_raw`` is verbatim print (a substring of the cited row's text for a
    text source); ``label_key`` is the normalized key in its ``key_space``
    (``@example:N`` or a compound token). ``occurrence`` disambiguates a repeated
    label inside one evidence row.
    """

    anchor_id: str
    doc_id: str
    evidence_id: str
    page: int
    bbox: tuple[float, float, float, float]
    label_raw: str
    label_key: str
    key_space: str
    anchor_kind: str
    source: str
    occurrence: int = 0
    confidence: float | None = None

    @classmethod
    def create(
        cls,
        *,
        doc_id: str,
        evidence_id: str,
        page: int,
        bbox: tuple[float, float, float, float],
        label_raw: str,
        label_key: str,
        key_space: str,
        anchor_kind: str,
        source: str,
        occurrence: int = 0,
        confidence: float | None = None,
    ) -> LabelAnchor:
        return cls(
            anchor_id=stable_id(
                "anchor", doc_id, evidence_id, label_key, str(occurrence)
            ),
            doc_id=doc_id,
            evidence_id=evidence_id,
            page=page,
            bbox=bbox,
            label_raw=label_raw,
            label_key=label_key,
            key_space=key_space,
            anchor_kind=anchor_kind,
            source=source,
            occurrence=occurrence,
            confidence=confidence,
        )


__all__ = ["LabelAnchor", "PageGeometry"]
