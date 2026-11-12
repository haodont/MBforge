"""Produce ADR 0001 ``label_anchor`` rows from the canonical evidence.

The anchor index is the printed-designation slot the association pass will
look up instead of rebuilding an in-memory index from candidate properties.
This first producer covers the two sources whose geometry already exists:

- **section headings** (``实施例17：…`` / ``Example 17``), re-using the Patent
  stage's own :func:`match_section_heading` so the anchor and the section cannot
  disagree, keyed into the ``@example:N`` space the deterministic path could
  never reach before;
- **bare prose designations** (a region whose whole text is a compound token
  such as ``A-5``), re-using :func:`bare_designation`.

OCR-read crop labels and table-cell row labels are deliberately not produced
yet: the molecule observation carries only the drawing bbox, not the label's
own box, and per-cell row-label boxes are generally absent. Those need a
producer change before they can satisfy the anchor geometry contract.

Anchors are derived from the minted evidence rows, so each one already carries
its ``evidence_id`` and PDF-point bbox; nothing here re-reads the page.
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import Any

from mbforge.domain.evidence_kind import TEXT_CATEGORIES, category_of, register_kinds
from mbforge.domain.patent import EXAMPLE_KEY_PREFIX, designation_key
from mbforge.domain.relation import LabelAnchor, PageGeometry
from mbforge.service.pipeline.detection.text_label_assignment import bare_designation
from mbforge.service.pipeline.layout.labels import kind_vocab
from mbforge.service.pipeline.layout.regions import DEFAULT_RENDER_DPI
from mbforge.service.pipeline.patent.sections import match_section_heading

# The producer compares evidence categories, so the layout label vocabulary must
# be registered before ``category_of`` is called — the same registration the
# evidence mint performs, repeated here so the producer is self-contained.
register_kinds(kind_vocab())

#: The layout producer reads page text with the local OCR reader, so a text
#: anchor's source is OCR text even on a page that also has a native layer.
_TEXT_SOURCE = "ocr_text"


def build_page_geometry(
    doc_id: str,
    frames: Sequence[Any],
    *,
    render_dpi: float = DEFAULT_RENDER_DPI,
) -> list[PageGeometry]:
    """One geometry row per page frame, at the contract render resolution."""
    return [
        PageGeometry(
            doc_id=doc_id,
            page=int(frame.page),
            width_pt=float(frame.width),
            height_pt=float(frame.height),
            render_dpi=render_dpi,
        )
        for frame in frames
    ]


def _heading_anchor(
    row: Any,
    doc_id: str,
    occurrences: dict[tuple[str, str], int],
) -> LabelAnchor | None:
    """The first example/preparation heading the row prints, if any."""
    for line in row.raw_text.splitlines():
        match = match_section_heading(line)
        if match is None:
            continue
        number = (match.group("num") or "").strip()
        if not number:
            continue
        # Derive the key through the one shared derivation, so an anchor only
        # exists in a space the association pass can also reach.
        key = designation_key(f"{match.group('kind')}{number}")
        if not key.startswith(EXAMPLE_KEY_PREFIX):
            continue
        return _anchor(
            row,
            doc_id,
            occurrences,
            label_raw=line.strip(),
            label_key=key,
            key_space="example",
            anchor_kind="section_heading",
        )
    return None


def _prose_anchor(
    row: Any,
    doc_id: str,
    occurrences: dict[tuple[str, str], int],
) -> LabelAnchor | None:
    """A region whose whole text is a bare compound designation."""
    token = bare_designation(row.raw_text)
    if token is None:
        return None
    key = designation_key(token)
    if not key or key.startswith(EXAMPLE_KEY_PREFIX):
        return None
    return _anchor(
        row,
        doc_id,
        occurrences,
        label_raw=token,
        label_key=key,
        key_space="compound",
        anchor_kind="prose",
    )


def _anchor(
    row: Any,
    doc_id: str,
    occurrences: dict[tuple[str, str], int],
    *,
    label_raw: str,
    label_key: str,
    key_space: str,
    anchor_kind: str,
) -> LabelAnchor:
    slot = (row.evidence_id, label_key)
    occurrence = occurrences.get(slot, 0)
    occurrences[slot] = occurrence + 1
    return LabelAnchor.create(
        doc_id=doc_id,
        evidence_id=row.evidence_id,
        page=row.page,
        bbox=tuple(row.bbox),
        label_raw=label_raw,
        label_key=label_key,
        key_space=key_space,
        anchor_kind=anchor_kind,
        source=_TEXT_SOURCE,
        occurrence=occurrence,
    )


def build_label_anchors(
    evidence: Sequence[Any],
    *,
    doc_id: str,
) -> list[LabelAnchor]:
    """Mint the document's printed-designation anchors from its evidence rows.

    A row yields at most one anchor: a heading takes precedence over a bare
    prose token, mirroring the section parser's own heading-first rule.
    """
    anchors: list[LabelAnchor] = []
    occurrences: dict[tuple[str, str], int] = {}
    for row in evidence:
        if getattr(row, "doc_id", None) != doc_id:
            continue
        if category_of(row.kind) not in TEXT_CATEGORIES:
            continue
        if not row.raw_text.strip():
            continue
        heading = _heading_anchor(row, doc_id, occurrences)
        if heading is not None:
            anchors.append(heading)
            continue
        prose = _prose_anchor(row, doc_id, occurrences)
        if prose is not None:
            anchors.append(prose)
    return anchors


__all__ = ["build_label_anchors", "build_page_geometry"]
