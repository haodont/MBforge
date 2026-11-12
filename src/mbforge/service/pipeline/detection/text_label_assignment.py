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
from collections.abc import Sequence
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
#: A Chinese patent prints the compound number *under* its drawing (the caption
#: of a synthesis scheme), so the foot of a drawing is read as well as its
#: head.
_FOOT_BAND = 0.12
#: A caption is printed a few points below its drawing whatever the drawing's
#: height, so the foot band reaches at least this far.
_FOOT_MIN_REACH = 16.0


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


def _ocr_confusable_forms(text: str) -> set[str]:
    """The spellings a ``1``/``I``/``l`` confusion can turn a token into.

    Only the first character varies: a series letter (``I-60-3``) is read as a
    digit (``1-60-3``) often enough that a whole series reaches the library
    under the wrong letter.
    """
    if not text:
        return set()
    head = text[0]
    # The read ``1`` can stand for the letter ``I`` (and vice versa); ``l`` is
    # the lowercase of the same confusion.
    return {
        replacement + text[1:]
        for replacement in ("1", "I", "i", "l")
        if replacement != head
    }


def reconcile_printed_spelling(token: str, page_tokens: Sequence[str]) -> str:
    """Give *token* the spelling the same page prints, when that is certain.

    A caption read as ``1-60-3`` is not a designation at all (it carries no
    letter), so it never reaches the naming pass — while the page's own prose
    prints ``I-60-3``. When exactly one confusable spelling of the read token
    is printed on this page, that spelling is the compound's. Two spellings
    printed side by side mean the document itself is ambiguous, and the read
    stays as it is.
    """
    lowered = token.strip().lower()
    if not lowered:
        return token
    # A page prints its compounds inside sentences too (``化合物I-60-3(100mg)``),
    # so the word the caption is compared against may be embedded in a line.
    # The token being read is excluded, and a *bare* second spelling is what
    # makes the page ambiguous (``1-60-3`` and ``I-60-3`` both printed alone).
    printed = {
        form.lower()
        for item in page_tokens
        if item.strip().lower() != lowered
        for form in _embedded_tokens(item)
    }
    bare_spellings = {
        item.strip().lower()
        for item in page_tokens
        if " " not in item.strip() and "\u3000" not in item.strip()
    }
    # ``1-60-3`` printed on its own next to ``I-60-3`` printed inside a
    # sentence is one misread and one true spelling, not an ambiguity; the
    # ambiguity is two spellings both printed as standalone captions.
    if lowered in bare_spellings and any(
        form in bare_spellings for form in _ocr_confusable_forms(lowered)
    ):
        return token
    if not printed or lowered in printed:
        return token
    hits = [form for form in _ocr_confusable_forms(lowered) if form in printed]
    if len(hits) != 1:
        return token
    corrected = hits[0]
    # The page's own spelling is what the document prints: take that token
    # verbatim, including the case it was printed in.
    for item in page_tokens:
        for form in _embedded_tokens(item):
            if form.lower() == corrected:
                return form
    return corrected


def _embedded_tokens(text: str) -> list[str]:
    """The designation-shaped tokens a line prints, bare or embedded."""
    return [text.strip()] + re.findall(
        r"[A-Za-z1-9][A-Za-z0-9]*(?:-[A-Za-z0-9]+)*", text
    )


def _figure_caption(text: str) -> str | None:
    """Return the designation a ``figno`` caption prints, letter or not.

    ``bare_designation`` rejects a token without a letter because in prose a
    bare number is a step or a paragraph marker. The layout producer already
    separates the two cases: a region it classified as ``figno`` is something
    printed beside a drawing, which is what the letter rule approximates. So a
    caption that names a compound is a designation whatever its head looks
    like — ``14`` (a bare figure number), ``1-2`` (a claims-list entry whose
    series letter ``I`` was read as a digit) or ``1-273-A``.

    A head that is the ``1``/``I`` confusion is answered with the series letter
    when that spelling is itself a designation key; the association's
    reconciliation then gives the token the spelling the document prints.
    """
    cleaned = str(text or "").strip().strip(_TRIM)
    if not cleaned or len(cleaned) > _MAX_TOKEN:
        return None
    if any(char.isspace() for char in cleaned):
        return None
    if designation_key(cleaned):
        return cleaned
    for variant in _ocr_confusable_forms(cleaned):
        if designation_key(variant):
            return variant
    return None


def page_designations(
    regions: list[dict[str, Any]], page_height: float
) -> list[TextDesignation]:
    """Return the designations the page prints in its own text, with positions.

    The boxes are converted from the producer's PDF frame (points, bottom-left
    origin) into the frame the geometry reads (top-left, y down).
    """
    # The page's own spellings decide what a misread caption was: a token the
    # page prints nowhere is not corrected (no evidence), one it prints once is.
    page_tokens = [
        str(region.get("text") or "").strip()
        for region in regions
        if str(region.get("kind") or "text") != "molecule"
    ]
    designations: list[TextDesignation] = []
    for region in regions:
        if str(region.get("kind") or "text") == "molecule":
            continue
        raw = str(region.get("text") or "").strip()
        token = bare_designation(raw)
        if token is None and str(region.get("kind") or "text") == "figno":
            token = _figure_caption(raw)
        if token is None:
            # A caption the OCR read with the wrong letter is not a designation
            # yet; the page's own spelling may make it one.
            token = bare_designation(reconcile_printed_spelling(raw, page_tokens))
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


def _foot_band(structure: tuple[float, float, float, float]) -> tuple[float, float]:
    """Return the vertical band at the foot of a drawing."""
    bottom = structure[3]
    height = max(structure[3] - structure[1], 1.0)
    reach = max(_FOOT_BAND * height, _FOOT_MIN_REACH)
    return bottom - _FOOT_BAND * height, bottom + reach


def _at_the_foot(
    print_box: tuple[float, float, float, float],
    structure: tuple[float, float, float, float],
) -> bool:
    """Return whether a print sits at the foot of a drawing.

    A CN patent prints the compound number under its drawing, as the caption of
    a synthesis step. The print's band and the drawing's foot must meet.
    """
    low, high = _foot_band(structure)
    return print_box[1] <= high and print_box[3] >= low


def _under_gap(
    print_box: tuple[float, float, float, float],
    structure: tuple[float, float, float, float],
) -> float | None:
    """The horizontal distance from a print printed under a drawing.

    ``None`` when the print is not centred under the drawing: a number that
    sits beside the drawing it is not under names no drawing.
    """
    left, right = structure[0], structure[2]
    if print_box[0] < left - 4.0 or print_box[2] > right + 4.0:
        return None
    return 0.0


def _box_gap(
    print_box: tuple[float, float, float, float],
    structure: tuple[float, float, float, float],
) -> float:
    """The straight-line distance between two boxes; 0 when they touch."""
    gap_x = max(0.0, max(print_box[0], structure[0]) - min(print_box[2], structure[2]))
    gap_y = max(0.0, max(print_box[1], structure[1]) - min(print_box[3], structure[3]))
    return (gap_x**2 + gap_y**2) ** 0.5


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
            under = _under_gap(designation.bbox, bbox) is not None
            if under:
                # A caption printed under the drawing names that drawing.
                if not _at_the_foot(designation.bbox, bbox):
                    continue
                gap = 0.0
            else:
                if not _at_the_head(designation.bbox, bbox):
                    continue
                gap = _horizontal_gap(designation.bbox, bbox)
                if gap is None:
                    continue
            if gap > max_gap:
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

    # A caption the first pass could not place may still be centred over an
    # unused drawing instead of under it: CN121717757A p32 prints one column's
    # caption below its structure and the middle column's 7 pt above it. The
    # recovery only runs on what is left over, so it cannot displace a pairing
    # the page's own convention already decided.
    for print_index, designation in enumerate(designations):
        if print_index in used_prints:
            continue
        best: tuple[float, int] | None = None
        for structure_index, (_structure_id, bbox) in enumerate(structures):
            if structure_index in used_structures:
                continue
            if _under_gap(designation.bbox, bbox) is None:
                continue
            gap = _box_gap(designation.bbox, bbox)
            if gap > _FOOT_MIN_REACH:
                continue
            if best is None or gap < best[0]:
                best = (gap, structure_index)
        if best is None:
            continue
        used_prints.add(print_index)
        used_structures.add(best[1])
        assignments[designation.text] = structures[best[1]][0]
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
