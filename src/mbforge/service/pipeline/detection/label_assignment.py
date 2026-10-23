"""Spatially resolved assignment of printed compound numbers to drawings.

A number printed beside a structure is that structure's compound designation,
so linking an activity reading to a drawing means knowing which drawing the
number belongs to. Today the molecule pass reads a label out of a box expanded
15% around each MolDet box and copies whatever identifier it finds into the
structure's ``name`` (``extraction.crop_processor``). On a dense page that
window reaches the neighbouring drawing's number, so a structure inherits a
label it does not own. The measured consequence at 300 DPI: 31 labels shared by
two or more *different* structures, none of those pairs sharing a molecular
formula, association reporting ``molecule_candidate_ambiguous`` and attribution
falling from 58% to zero.

This module decides ownership from page geometry instead of from one expanded
window:

1. **Seeds.** A designation whose nearest drawing is clearly nearer than the
   runner-up, at a confident OCR read, is a case the page itself has settled.
2. **Convention.** The dominant relative print position (above, below, left,
   right, inside) is tallied over the seeds, so a document that numbers its
   drawings above them and one that numbers them to the left are both read
   correctly without a hard-coded convention. A page with no settled case
   reports no convention rather than inventing one.
3. **Claims.** Every print is scored against every drawing: the
   convention-matching position first, then the normalised gap, with the
   drawings' reading order as the last, deterministic tie-break. A side-band
   check keeps a number from claiming a drawing in the next column or row.
4. **Ambiguity instead of a guess.** A designation with more than one
   near-equally-good claimant is reported, not attached; so is a drawing that
   several numbers claim. The review queue owns those cases. One drawing never
   receives two designations, and one designation never receives two drawings.

Everything here is pure geometry over boxes: no OCR engine, no model weights,
no network, no database, so a synthetic page is a complete unit test.

Coordinate contract
-------------------
Every box is ``(x0, y0, x1, y1)`` in the page-image frame the crop-label OCR
already works in: origin top-left, y growing downward. A caller holding PDF
points must convert first (``y' = page_height_pt - y``); "above" is a smaller
``y``. Units are irrelevant as long as all boxes share them, because every
distance is normalised by the drawing's own size.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass, replace
from enum import StrEnum
from math import hypot

from mbforge.service.pipeline.detection.label_normalization import (
    normalize_coref_label,
)

#: Box in the page-image frame: ``(x0, y0, x1, y1)``, origin top-left, y down.
BBox = tuple[float, float, float, float]

#: A read this confident may help infer the page's print convention. Below it
#: the read is still allowed to claim a drawing, it just cannot be evidence for
#: what the page's numbering convention is.
_SEED_MIN_CONFIDENCE = 0.8
#: Farthest a designation may sit from a drawing and still be a settled case, as
#: a fraction of the drawing's larger side.
_SEED_MAX_NORMALIZED_GAP = 0.3
#: The runner-up must be at least this many times farther away than the winner
#: for the pair to count as settled. A number printed between two drawings is
#: not evidence for either.
_SEED_SEPARATION = 2.0
#: Farthest a designation may sit from a drawing and still claim it at all, as a
#: fraction of the drawing's larger side. Beyond this the number belongs to
#: another figure on the page.
_MAX_NORMALIZED_GAP = 0.75
#: A claimant is only exclusive when the runner-up is at least this many times
#: farther away. Equal distances stay ambiguous instead of being decided by
#: input order.
_AMBIGUITY_RATIO = 1.5
#: A designation printed above or below a drawing may be off-centre along x by
#: up to this fraction of the drawing's width and still belong to its column.
_BAND_ALIGN_FRACTION = 0.75
#: Guards the normalisations against a degenerate (zero-size) box.
_MIN_SPAN = 1.0


class OffsetClass(StrEnum):
    """Where a designation's centre sits relative to the drawing's box."""

    ABOVE = "above"
    BELOW = "below"
    LEFT = "left"
    RIGHT = "right"
    INSIDE = "inside"


@dataclass(frozen=True)
class StructureBox:
    """One detected drawing on a page.

    Attributes:
        structure_id: Stable identity the caller maps back to its detection row.
        bbox: The drawing's box in the page-image frame (y grows downward).
    """

    structure_id: str
    bbox: BBox


@dataclass(frozen=True)
class LabelRead:
    """One identifier-like OCR read and the position it was printed at.

    Attributes:
        text: The read string as OCR produced it (``"20"``, ``"4A"``).
        bbox: The read's tight box, in the same frame as the drawing boxes.
        confidence: OCR confidence; only used to pick convention seeds.
    """

    text: str
    bbox: BBox
    confidence: float = 1.0


@dataclass(frozen=True)
class LabelConvention:
    """The dominant printed position of a designation on the page.

    Attributes:
        offset_classes: Every relative position that tied for the top of the
            seed tally. More than one member means the page does not commit to
            one convention, so all of them are treated as canonical.
        support: Number of settled seed pairs the tally rests on.
    """

    offset_classes: frozenset[OffsetClass]
    support: int


@dataclass(frozen=True)
class PageLabelAssignment:
    """What one page's geometry decided.

    This is the assignment only; it emits no issue codes itself. The caller maps
    the two unresolved buckets onto the contract association already reads, so
    neither code changes meaning:

    - ``ambiguous`` → ``molecule_candidate_ambiguous``: the page printed a
      designation but geometry attaches it to more than one drawing (or to a
      drawing another designation claims), so association must keep reporting it
      instead of resolving it arbitrarily.
    - ``unassigned_labels`` / ``unlabeled_structures`` →
      ``molecule_label_unresolved``: a designation with no drawing, or a drawing
      with no designation. Both are gaps a reader can close and neither may be
      turned into a guessed pairing.

    Attributes:
        assignments: Designation key → ``structure_id``, in reading order. No
            structure appears twice and no designation appears twice.
        ambiguous: Designation key → the structures it could not be attached to
            exclusively. Two or more entries mean several drawings plausibly
            claim the number. A single entry means the drawing itself is claimed
            by several numbers, so naming it with either would be a guess.
        unassigned_labels: Designations no drawing plausibly owns, in reading
            order. Together with ``assignments`` and ``ambiguous`` they cover
            every designation the page printed.
        unlabeled_structures: Detected drawings left with no designation, in
            reading order.
        convention: The print convention inferred from this page, or ``None``
            when no confident, settled pair existed to infer one from.
    """

    assignments: dict[str, str]
    ambiguous: dict[str, tuple[str, ...]]
    unassigned_labels: tuple[str, ...]
    unlabeled_structures: tuple[str, ...]
    convention: LabelConvention | None


@dataclass(frozen=True)
class _Structure:
    """A drawing box with its reading-order index."""

    structure_id: str
    bbox: BBox
    order: int


@dataclass(frozen=True)
class _Print:
    """A label read with its designation key and reading-order index."""

    key: str
    bbox: BBox
    confidence: float
    order: int


@dataclass(frozen=True)
class _Claim:
    """One print's claim on one drawing."""

    structure: _Structure
    offset_class: OffsetClass
    gap: float
    class_rank: int

    @property
    def rank_key(self) -> tuple[int, float, int]:
        """Total, deterministic ordering: convention, distance, reading order."""
        return (self.class_rank, self.gap, self.structure.order)


@dataclass(frozen=True)
class _Outcome:
    """What the page decides for one designation."""

    key: str
    order: int
    claim: _Claim | None = None
    contested: tuple[str, ...] = ()


def _ordered(bbox: Sequence[float]) -> BBox:
    """Return *bbox* as floats with ``x0 <= x1`` and ``y0 <= y1``."""
    x0, y0, x1, y1 = (float(value) for value in bbox)
    return (min(x0, x1), min(y0, y1), max(x0, x1), max(y0, y1))


def _center(bbox: BBox) -> tuple[float, float]:
    return ((bbox[0] + bbox[2]) / 2.0, (bbox[1] + bbox[3]) / 2.0)


def _span(bbox: BBox) -> tuple[float, float]:
    return (bbox[2] - bbox[0], bbox[3] - bbox[1])


def _outward(value: float, low: float, high: float) -> float:
    """How far *value* lies outside ``[low, high]``; 0 when inside."""
    if value < low:
        return low - value
    if value > high:
        return value - high
    return 0.0


def _overlap(low_a: float, high_a: float, low_b: float, high_b: float) -> float:
    """Length shared by two 1-D spans; 0 when they are disjoint."""
    return max(0.0, min(high_a, high_b) - max(low_a, low_b))


def _gap(label: BBox, structure: BBox) -> float:
    """Straight-line gap between two boxes; 0 when they overlap or touch."""
    gap_x = max(0.0, max(label[0], structure[0]) - min(label[2], structure[2]))
    gap_y = max(0.0, max(label[1], structure[1]) - min(label[3], structure[3]))
    return hypot(gap_x, gap_y)


def _normalized_gap(label: BBox, structure: BBox) -> float:
    """The gap in units of the drawing's larger side, so layout scale drops out."""
    width, height = _span(structure)
    return _gap(label, structure) / max(width, height, _MIN_SPAN)


def _offset_class(label: BBox, structure: BBox) -> OffsetClass:
    """Classify where the print sits relative to the drawing.

    The axis a print leaves the box by, measured in the box's own units, is the
    axis that names the position. A number printed at the top-left corner of a
    drawing is therefore ``ABOVE`` when it clears the top edge by more than it
    clears the left edge — corner prints are inherently ambiguous, and the
    larger outward clearance is the deterministic answer.
    """
    label_x, label_y = _center(label)
    width, height = _span(structure)
    horizontal = _outward(label_x, structure[0], structure[2]) / max(width, _MIN_SPAN)
    vertical = _outward(label_y, structure[1], structure[3]) / max(height, _MIN_SPAN)
    if horizontal == 0.0 and vertical == 0.0:
        return OffsetClass.INSIDE
    if horizontal >= vertical:
        return OffsetClass.LEFT if label_x < structure[0] else OffsetClass.RIGHT
    return OffsetClass.ABOVE if label_y < structure[1] else OffsetClass.BELOW


def _band_aligned(offset_class: OffsetClass, label: BBox, structure: BBox) -> bool:
    """Whether the read's baseline band lines up with the drawing's box.

    A number printed above a drawing belongs to that drawing's column, so its
    x-span must overlap the drawing's or its centre stay within the drawing's
    own width of the drawing's centre; a number printed beside it must line up
    vertically instead. A read that misses the band by more than that belongs to
    a different column or row.
    """
    label_x, label_y = _center(label)
    structure_x, structure_y = _center(structure)
    width, height = _span(structure)
    if offset_class in (OffsetClass.ABOVE, OffsetClass.BELOW):
        return _overlap(label[0], label[2], structure[0], structure[2]) > 0.0 or abs(
            label_x - structure_x
        ) <= _BAND_ALIGN_FRACTION * max(width, _MIN_SPAN)
    if offset_class in (OffsetClass.LEFT, OffsetClass.RIGHT):
        return _overlap(label[1], label[3], structure[1], structure[3]) > 0.0 or abs(
            label_y - structure_y
        ) <= _BAND_ALIGN_FRACTION * max(height, _MIN_SPAN)
    return True


def _claim(
    print_box: _Print, structure: _Structure, convention: LabelConvention | None
) -> _Claim | None:
    """Score one print against one drawing, or reject the pair outright."""
    offset_class = _offset_class(print_box.bbox, structure.bbox)
    if not _band_aligned(offset_class, print_box.bbox, structure.bbox):
        return None
    gap = _normalized_gap(print_box.bbox, structure.bbox)
    if gap > _MAX_NORMALIZED_GAP:
        return None
    canonical = convention is None or offset_class in convention.offset_classes
    return _Claim(
        structure=structure,
        offset_class=offset_class,
        gap=gap,
        class_rank=0 if canonical else 1,
    )


def _claims(
    print_box: _Print,
    structures: Sequence[_Structure],
    convention: LabelConvention | None,
) -> list[_Claim]:
    """Every plausible claim one print has on the page, best first."""
    scored: list[_Claim] = []
    for structure in structures:
        claim = _claim(print_box, structure, convention)
        if claim is not None:
            scored.append(claim)
    scored.sort(key=lambda claim: claim.rank_key)
    return scored


def _split_print(claims: Sequence[_Claim]) -> tuple[_Claim | None, tuple[str, ...]]:
    """Pick one print's owner, or report the drawings that tie for it."""
    if not claims:
        return None, ()
    winner = claims[0]
    tied = [
        claim
        for claim in claims
        if claim.class_rank == winner.class_rank
        and claim.gap <= winner.gap * _AMBIGUITY_RATIO
    ]
    if len(tied) > 1:
        return None, tuple(claim.structure.structure_id for claim in tied)
    return winner, ()


def _intersects(a: BBox, b: BBox) -> bool:
    """Whether two boxes share any area (a touching edge does not count)."""
    return (
        _overlap(a[0], a[2], b[0], b[2]) > 0.0
        and _overlap(a[1], a[3], b[1], b[3]) > 0.0
    )


def _inside(inner: BBox, outer: BBox) -> bool:
    """Whether *inner*'s centre lies within *outer*."""
    x, y = _center(inner)
    return outer[0] <= x <= outer[2] and outer[1] <= y <= outer[3]


def _seed(
    print_box: _Print, structures: Sequence[_Structure]
) -> tuple[OffsetClass, _Structure] | None:
    """The settled pair one read demonstrates, or ``None`` when it is not settled.

    Two different layouts count as settled, and distinguishing them matters:

    * an *inline* number, whose own centre lies inside exactly one drawing. A
      number that merely clips a drawing's edge is not inline — that is the
      tight row gutter, where a number printed under one drawing touches the
      next. Letting that seed made a page of tight gutters infer an ``INSIDE``
      convention and hand every number to the drawing *above* the one it was
      printed under.
    * a *clear* number, standing outside every drawing and nearer to one of them
      by a wide margin. A number between two drawings is exactly the case the
      convention is meant to resolve, so it cannot also define the convention.
    """
    touching = [item for item in structures if _intersects(print_box.bbox, item.bbox)]
    if touching:
        if len(touching) != 1 or not _inside(print_box.bbox, touching[0].bbox):
            return None
        return OffsetClass.INSIDE, touching[0]
    nearest = _claims(print_box, structures, None)
    if not nearest or nearest[0].gap > _SEED_MAX_NORMALIZED_GAP:
        return None
    if len(nearest) > 1 and nearest[1].gap <= nearest[0].gap * _SEED_SEPARATION:
        return None
    return nearest[0].offset_class, nearest[0].structure


def _infer_convention(
    structures: Sequence[_Structure], prints: Sequence[_Print]
) -> LabelConvention | None:
    """Tally the print position over the pairs the page has already settled.

    Only pairs no reader would dispute speak for the document's convention; the
    cases the convention exists to resolve — a number between two drawings, a
    number clipping a neighbour — are excluded by :func:`_seed`. Reads are
    counted per settled pair, so OCR reading one printed number twice is one
    piece of evidence, not two votes.
    """
    tally: dict[OffsetClass, int] = {}
    seen: set[tuple[str, str]] = set()
    for print_box in prints:
        if print_box.confidence < _SEED_MIN_CONFIDENCE:
            continue
        settled = _seed(print_box, structures)
        if settled is None:
            continue
        offset_class, structure = settled
        pair = (print_box.key, structure.structure_id)
        if pair in seen:
            continue
        seen.add(pair)
        tally[offset_class] = tally.get(offset_class, 0) + 1
    if not tally:
        return None
    support = max(tally.values())
    dominant = frozenset(
        offset_class for offset_class, count in tally.items() if count == support
    )
    return LabelConvention(offset_classes=dominant, support=support)


def _designation_key(text: str) -> str:
    """Canonical key for a printed designation, folding OCR spellings.

    ``化合物20`` / ``compound 20`` / ``20`` are one designation, so two reads of
    the same printed number compete as one designation rather than as several
    different labels. The normalizer decides what a designation is; text it does
    not recognize still gets a whitespace-collapsed key so it can be reported
    instead of silently dropped.
    """
    normalized = normalize_coref_label(text)
    if normalized is not None:
        return normalized.normalized
    return " ".join(text.split())


def _place_structures(structures: Sequence[StructureBox]) -> list[_Structure]:
    """Normalize, deduplicate, and put the drawings into reading order."""
    placed: dict[str, _Structure] = {}
    for structure in structures:
        structure_id = structure.structure_id.strip()
        if not structure_id or structure_id in placed:
            continue
        placed[structure_id] = _Structure(
            structure_id=structure_id, bbox=_ordered(structure.bbox), order=0
        )
    ordered = sorted(placed.values(), key=lambda item: (item.bbox[1], item.bbox[0]))
    return [replace(structure, order=order) for order, structure in enumerate(ordered)]


def _place_prints(labels: Sequence[LabelRead]) -> list[_Print]:
    """Normalize, key, and put the reads into reading order."""
    placed: list[_Print] = []
    for label in labels:
        text = label.text.strip()
        if not text:
            continue
        placed.append(
            _Print(
                key=_designation_key(text),
                bbox=_ordered(label.bbox),
                confidence=float(label.confidence),
                order=0,
            )
        )
    placed.sort(key=lambda item: (item.bbox[1], item.bbox[0], item.key))
    return [replace(print_box, order=order) for order, print_box in enumerate(placed)]


def _group_prints(prints: Sequence[_Print]) -> dict[str, list[_Print]]:
    """Group reads by designation key, preserving reading order."""
    grouped: dict[str, list[_Print]] = {}
    for print_box in prints:
        grouped.setdefault(print_box.key, []).append(print_box)
    return grouped


def _decide_designation(
    key: str,
    prints: Sequence[_Print],
    structures: Sequence[_Structure],
    convention: LabelConvention | None,
) -> _Outcome:
    """Decide one designation from all of its prints, or report a contest."""
    winners: dict[str, _Claim] = {}
    contested: list[str] = []
    for print_box in prints:
        winner, tied = _split_print(_claims(print_box, structures, convention))
        if winner is not None:
            current = winners.get(winner.structure.structure_id)
            if current is None or winner.rank_key < current.rank_key:
                winners[winner.structure.structure_id] = winner
        contested.extend(tied)
    order = prints[0].order
    if len(winners) == 1:
        claim = next(iter(winners.values()))
        # A second print of the same designation that is itself contested makes
        # the designation two-sided unless it only ever points back at the same
        # drawing (a repeated read of one print, not a second print).
        if any(
            structure_id != claim.structure.structure_id for structure_id in contested
        ):
            return _Outcome(
                key=key,
                order=order,
                contested=tuple(
                    dict.fromkeys([claim.structure.structure_id, *contested])
                ),
            )
        return _Outcome(key=key, order=order, claim=claim)
    if len(winners) > 1:
        return _Outcome(
            key=key,
            order=order,
            contested=tuple(dict.fromkeys([*winners, *contested])),
        )
    if contested:
        return _Outcome(key=key, order=order, contested=tuple(dict.fromkeys(contested)))
    return _Outcome(key=key, order=order)


def _resolve_structure_contests(
    outcomes: Sequence[_Outcome],
) -> tuple[dict[str, str], dict[str, tuple[str, ...]]]:
    """Attach the decided designations, withholding drawings claimed by several.

    A drawing carries one compound number. When two designations each decide on
    the same drawing with comparable support, naming it with either is a guess,
    so the drawing stays unlabeled and both designations are reported. When one
    of them is clearly closer it wins and the other simply stays unassigned: the
    drawing's identity is right even though a designation went unused.
    """
    claimed: dict[str, list[_Outcome]] = {}
    for outcome in outcomes:
        if outcome.claim is not None:
            claimed.setdefault(outcome.claim.structure.structure_id, []).append(outcome)

    assigned: dict[str, str] = {}
    ambiguous: dict[str, tuple[str, ...]] = {
        outcome.key: outcome.contested for outcome in outcomes if outcome.contested
    }
    for structure_id, contenders in claimed.items():
        contenders = sorted(
            contenders, key=lambda item: (item.claim.rank_key, item.order)
        )
        best = contenders[0]
        runner_up = contenders[1] if len(contenders) > 1 else None
        if runner_up is not None and runner_up.claim.gap <= best.claim.gap * (
            _AMBIGUITY_RATIO
        ):
            for outcome in contenders:
                ambiguous[outcome.key] = (structure_id,)
            continue
        assigned[best.key] = structure_id
    return assigned, ambiguous


def assign_labels(
    structures: Sequence[StructureBox], labels: Sequence[LabelRead]
) -> PageLabelAssignment:
    """Assign one page's printed designations to the drawings that own them.

    The result is a pure function of the boxes: the page's own settled cases
    define its numbering convention, every read then competes for the drawings
    that convention makes plausible, and anything the geometry does not settle
    is reported as ambiguous instead of being attached by proximity alone.

    Args:
        structures: The page's detected drawings with stable ids.
        labels: The page's candidate designation reads with print positions.

    Returns:
        A :class:`PageLabelAssignment` describing the decided, ambiguous and
        unattached designations, plus the convention observed on the page.
    """
    placed_structures = _place_structures(structures)
    placed_prints = _place_prints(labels)
    convention = _infer_convention(placed_structures, placed_prints)

    outcomes = [
        _decide_designation(key, prints, placed_structures, convention)
        for key, prints in _group_prints(placed_prints).items()
    ]
    decided, ambiguous_keys = _resolve_structure_contests(outcomes)

    ordered = sorted(outcomes, key=lambda outcome: outcome.order)
    assignments = {
        outcome.key: decided[outcome.key]
        for outcome in ordered
        if outcome.key in decided
    }
    ambiguous = {
        outcome.key: ambiguous_keys[outcome.key]
        for outcome in ordered
        if outcome.key in ambiguous_keys
    }
    unassigned = tuple(
        outcome.key
        for outcome in ordered
        if outcome.key not in assignments and outcome.key not in ambiguous
    )
    taken = set(assignments.values())
    unlabeled = tuple(
        structure.structure_id
        for structure in placed_structures
        if structure.structure_id not in taken
    )
    return PageLabelAssignment(
        assignments=assignments,
        ambiguous=ambiguous,
        unassigned_labels=unassigned,
        unlabeled_structures=unlabeled,
        convention=convention,
    )


__all__ = [
    "BBox",
    "LabelConvention",
    "LabelRead",
    "OffsetClass",
    "PageLabelAssignment",
    "StructureBox",
    "assign_labels",
]
