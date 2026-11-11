"""Attach the designations a page prints in its own text to the drawings they name.

The molecule pass reads a compound number off the crop around a drawing. That
window misses a number printed in the margin: a US application prints its
compound list as ``[drawing][A-5]`` — the number in the gutter beside the
drawing — and the crop never reaches it. The layout producer has already read
that number: it is a text region of its own, with a position. So the number
that names a drawing can come from the page's text instead of from the crop.

Two rules keep this from guessing:

- **Only a bare token is a read.** A phrase that merely mentions a compound
  (``目标化合物1的制备``) names no drawing; the crop pass keeps deciding those.
- **One number names one drawing, one drawing carries one number.** The page is
  matched as a whole, so a number in the gutter between two columns cannot take
  the drawing of the neighbouring column: the pair that is left over keeps its
  number, and the contested one is reported instead of attached.

The geometry is the one the crop pass already uses (a print belongs to the
drawing it is printed at the head of), applied to the page's own text.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any

from mbforge.domain.patent import designation_key

#: A printed token this long is a sentence, not a designation.
_MAX_TOKEN = 32

#: Punctuation a printed number may carry around it. Brackets are *not*
#: trimmed: ``[0331]`` is a paragraph marker, not a compound.
_TRIM = " \t\r\n.,;"

#: A designation that carries no letter is a number the document uses for
#: something else — a paragraph, a step, a page. Only a token with a letter in
#: it names a compound.
_LETTER_RE = re.compile(r"[^\W\d_]", re.UNICODE)

#: How far a print may sit from the head of a drawing, as a fraction of the
#: drawing's height.
_HEAD_BAND = 0.15


def to_top_down(
    bbox: tuple[float, float, float, float], page_height: float
) -> tuple[float, float, float, float]:
    """Convert a PDF box (points, bottom-left origin) into the frame the
    geometry reads (top-left, y down)."""
    x0, y0, x1, y1 = bbox
    return (x0, page_height - y1, x1, page_height - y0)


@dataclass(frozen=True)
class TextDesignation:
    """One designation the page prints, with the position it is printed at."""

    text: str
    bbox: tuple[float, float, float, float]


def bare_designation(text: str) -> str | None:
    """Return the printed token when it is nothing but a compound designation.

    ``A-5`` and ``化合物7`` are designations; ``目标化合物7的制备`` and ``A-5 to
    A-30`` are not — they mention designations, they do not print one. A token
    without a letter in it is not a compound either: ``[0331]`` is a paragraph
    marker and ``1`` is a step.
    """
    stripped = str(text or "").strip()
    if not stripped or len(stripped) > _MAX_TOKEN:
        return None
    cleaned = stripped.strip(_TRIM)
    if not cleaned or any(char.isspace() for char in cleaned):
        return None
    if not _LETTER_RE.search(cleaned):
        return None
    if not designation_key(cleaned):
        return None
    return cleaned


def page_designations(
    regions: list[dict[str, Any]], page_height: float
) -> list[TextDesignation]:
    """Return the designations the page prints in its own text, with positions.

    The boxes are converted from the producer's PDF frame (points, bottom-left
    origin) into the frame the geometry reads (top-left, y down).
    """
    designations: list[TextDesignation] = []
    for region in regions:
        if str(region.get("kind") or "text") == "molecule":
            continue
        token = bare_designation(region.get("text") or "")
        if token is None:
            continue
        bbox = region.get("bbox") or ()
        if len(bbox) != 4:
            continue
        try:
            x0, y0, x1, y1 = (float(value) for value in bbox)
        except (TypeError, ValueError):
            continue
        designations.append(
            TextDesignation(
                text=token,
                bbox=to_top_down((x0, y0, x1, y1), page_height),
            )
        )
    return designations


def _head_band(structure: tuple[float, float, float, float]) -> tuple[float, float]:
    """Return the vertical band at the head of a drawing."""
    top = structure[1]
    height = max(structure[3] - structure[1], 1.0)
    return top - _HEAD_BAND * height, top + _HEAD_BAND * height


def _at_the_head(
    print_box: tuple[float, float, float, float],
    structure: tuple[float, float, float, float],
) -> bool:
    """Return whether a print sits at the head of a drawing.

    The number of a compound list is printed at the drawing's top edge, so the
    print's band and the drawing's head must meet.
    """
    low, high = _head_band(structure)
    return print_box[1] <= high and print_box[3] >= low


def _columns(
    structures: list[tuple[str, tuple[float, float, float, float]]],
) -> list[tuple[float, float, list[int]]]:
    """Group a page's drawings into the columns they are printed in.

    A compound list is printed in columns: every drawing of one column sits
    left of every drawing of the next. The numbers are printed in the gutter
    right after their own column's drawings, so the column a number belongs to
    is the one it is printed after — the column whose drawings end just before
    the number and whose successor starts just after it.
    """
    spans: list[list[Any]] = []
    for index, (_structure_id, bbox) in enumerate(structures):
        left, right = bbox[0], bbox[2]
        for span in spans:
            if left <= span[1] and right >= span[0]:
                span[0] = min(span[0], left)
                span[1] = max(span[1], right)
                span[2].append(index)
                break
        else:
            spans.append([left, right, [index]])
    spans.sort(key=lambda span: span[0])
    return spans


def _column_of(
    print_box: tuple[float, float, float, float],
    spans: list[list[Any]],
) -> list[int] | None:
    """Return the drawings of the column the print is printed after.

    ``None`` when the print does not sit in a gutter — a number printed above
    its drawing belongs to no column, and the caller then judges every column.
    """
    for position, span in enumerate(spans):
        right, indices = span[1], span[2]
        if right > print_box[0]:
            continue
        following = spans[position + 1] if position + 1 < len(spans) else None
        if following is not None and following[0] < print_box[2]:
            # The print sits inside the next column's drawings.
            continue
        return indices
    return None


def _horizontal_gap(
    print_box: tuple[float, float, float, float],
    structure: tuple[float, float, float, float],
) -> float | None:
    """Return the horizontal distance from a print to a drawing beside it.

    ``None`` when the drawing is not beside the print: a print that is above or
    below a drawing names no drawing by proximity.
    """
    if structure[2] <= print_box[0]:
        return print_box[0] - structure[2]
    if structure[0] >= print_box[2]:
        return structure[0] - print_box[2]
    return None


@dataclass(frozen=True)
class TextLabelAssignment:
    """What the page's own text decided about its drawings.

    Attributes:
        assignments: designation → structure id, one entry each.
        contested: designations that could not be attached to exactly one
            drawing, in reading order.
    """

    assignments: dict[str, str]
    contested: tuple[str, ...]


def assign_text_labels(
    structures: list[tuple[str, tuple[float, float, float, float]]],
    designations: list[TextDesignation],
    *,
    max_gap: float = 120.0,
) -> TextLabelAssignment:
    """Match a page's printed designations to the drawings beside them.

    Every pairing is a distance: the print sits at the head of a drawing and
    beside it, so the horizontal gap is what separates two candidates. The page
    is matched as a whole — a drawing carries one number and a number names one
    drawing — and the closest pairs are taken first, so a number printed in the
    gutter between two columns keeps the drawing of its own column.
    """
    pairs: list[tuple[float, int, int]] = []
    spans = _columns(structures)
    for print_index, designation in enumerate(designations):
        column = _column_of(designation.bbox, spans)
        for structure_index, (_structure_id, bbox) in enumerate(structures):
            if column is not None and structure_index not in column:
                # The print sits in the gutter of its own column: a drawing of
                # the next column is not its compound, however close it is.
                continue
            if not _at_the_head(designation.bbox, bbox):
                continue
            gap = _horizontal_gap(designation.bbox, bbox)
            if gap is None or gap > max_gap:
                continue
            pairs.append((gap, print_index, structure_index))
    pairs.sort()

    used_prints: set[int] = set()
    used_structures: set[int] = set()
    assignments: dict[str, str] = {}
    for _gap, print_index, structure_index in pairs:
        if print_index in used_prints or structure_index in used_structures:
            continue
        used_prints.add(print_index)
        used_structures.add(structure_index)
        assignments[designations[print_index].text] = structures[structure_index][0]
    contested = tuple(
        designation.text
        for index, designation in enumerate(designations)
        if index not in used_prints
    )
    return TextLabelAssignment(assignments=assignments, contested=contested)


__all__ = [
    "TextDesignation",
    "TextLabelAssignment",
    "assign_text_labels",
    "bare_designation",
    "page_designations",
    "to_top_down",
]
