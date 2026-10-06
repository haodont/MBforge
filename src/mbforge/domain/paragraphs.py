"""Patent paragraph grouping over the canonical source evidence.

Patents number their paragraphs — ``[0001]``, ``[0002]``, … — and that marker,
not the layout model, is the authoritative paragraph boundary.  A single
paragraph is routinely split into two layout regions, or across a column or a
page break, and the continuation fragment carries no marker of its own::

    [0003] MRGX2 is Gq-coupled … cultured mast cells (D.     <- page 2
    Fujisawa et al., J Allergy Clin Immunol …                <- page 3

The layout also encodes the document's own indentation in each region's left
edge.  A patent's enumerated sub-items sit one level in, and their children one
level further::

    x0≈85   703 rows   [0006] One aspect … wherein:
    x0≈124  279 rows   (a) C1-4 alkyl …       (1) L is selected from …
    x0≈159   50 rows   R¹ is selected from
    x0≈193   20 rows   (b) a cyclic group …

Both readers agree on paragraphs by calling this module: the Markdown stage
renders one block per paragraph with its indentation, and the evidence reader
annotates each row with the paragraph and line it belongs to.

Two limitations are deliberate.  A bbox is *region* level, so an indent inside
a single region is invisible.  A two-column page would defeat the left-edge
signal entirely; such rows land off the indent grid and degrade to standalone
blocks rather than being mis-grouped.
"""

from __future__ import annotations

import re
from collections.abc import Iterable
from dataclasses import dataclass, field

from mbforge.domain.evidence import SourceEvidence
from mbforge.domain.evidence_kind import TEXT, category_of, kind_rank
from mbforge.foundation.ids import stable_id

#: ``[0001]`` / ``【0001】`` opening a line.  Four digits is the WIPO/AU/CN
#: convention; three covers older filings.
PARAGRAPH_MARKER_RE = re.compile(r"^[\[【]\s*(?P<number>\d{3,4})\s*[\]】]")

#: Enumerator opening a sibling item — ``(a)``, ``(b)``, ``(1)``, ``(iv)``.
#: Uppercase single letters are deliberately absent: ``(R)`` / ``(S)`` are
#: stereodescriptors that start a line in this corpus, not list items.
_ITEM_RE = re.compile(r"^\(\s*(?:\d{1,2}|[a-z]|[ivxlcdm]{1,4})\s*\)(?=\s)")

#: Labels whose text may continue the open numbered paragraph.  Measured on a
#: real WIPO filing: body prose is ``text`` and section text/headings are
#: ``sec``.  ``head`` / ``foot`` / ``lineno`` / ``figno`` / ``cap`` / ``title``
#: / ``bib`` / ``toc`` are page furniture or standalone blocks and are never
#: absorbed into a paragraph.
PARAGRAPH_FRAGMENT_KINDS = frozenset({"text", "sec"})

#: Left edges within this many points belong to the same indent level.
_GRID_TOLERANCE = 10.0
#: A level must carry at least this many regions to count; the threshold is
#: what drops figure labels and formula numbers sitting between prose regions.
_MIN_CLUSTER_ROWS = 3
#: A centred block sits within this many points of the column centre…
_CENTRE_TOLERANCE = 25.0
#: …is no wider than this share of the column…
_CENTRE_MAX_WIDTH = 0.7
#: …and starts at least this far into it.  Body prose that merely happens to
#: be narrow still starts at the margin; a centred heading cannot.
_CENTRE_MIN_INSET = 0.15
#: Row share used as the column's right edge, ignoring full-bleed outliers.
_RIGHT_EDGE_PERCENTILE = 0.9

_HEADING_MAX_CHARS = 80
_HEADING_MAX_WORDS = 8


def reading_key(
    item: SourceEvidence, *, tie_breaker: str | None = None
) -> tuple[object, ...]:
    """Reading order of one evidence region.

    Page, then top-to-bottom, then left-to-right; ``kind_rank`` and the tie
    breaker only disambiguate regions that share a geometry.
    """
    x0, y0, x1, y1 = item.bbox
    return (
        item.page,
        -y1,
        x0,
        -y0,
        x1,
        kind_rank(item.kind),
        tie_breaker or item.evidence_id,
    )


def is_heading_like(line: str) -> bool:
    """True for a short, all-caps line such as ``BACKGROUND OF THE INVENTION``.

    ``R² is selected from`` does not qualify.  Used only to stop a heading
    being absorbed by the paragraph that precedes it.
    """
    stripped = line.strip()
    if not stripped or len(stripped) > _HEADING_MAX_CHARS:
        return False
    if not any(char.isalpha() for char in stripped):
        return False
    if stripped.upper() != stripped:
        return False
    return len(stripped.split()) <= _HEADING_MAX_WORDS


@dataclass(frozen=True)
class IndentGrid:
    """The document's left-edge levels, discovered rather than assumed.

    ``levels`` are ascending x0 coordinates; :meth:`level_of` maps a region's
    left edge to its level, or ``-1`` when it matches none — page furniture,
    figure labels, or a page whose columns defeat the signal.
    """

    levels: tuple[float, ...]
    column_left: float
    column_right: float
    tolerance: float = _GRID_TOLERANCE

    def level_of(self, x0: float) -> int:
        if not self.levels:
            return -1
        index = min(range(len(self.levels)), key=lambda i: abs(x0 - self.levels[i]))
        if abs(x0 - self.levels[index]) <= self.tolerance:
            return index
        return -1

    @property
    def width(self) -> float:
        return max(0.0, self.column_right - self.column_left)

    @property
    def centre(self) -> float:
        return (self.column_left + self.column_right) / 2


def _grid_rows(rows: Iterable[SourceEvidence]) -> list[SourceEvidence]:
    return [
        item
        for item in rows
        if item.kind in PARAGRAPH_FRAGMENT_KINDS and item.raw_text.strip()
    ]


def indent_grid(rows: Iterable[SourceEvidence]) -> IndentGrid:
    """Derive the document's indent levels from the regions' left edges."""
    candidates = _grid_rows(rows)
    if not candidates:
        return IndentGrid(levels=(), column_left=0.0, column_right=0.0)

    edges = sorted(item.bbox[0] for item in candidates)
    clusters: list[list[float]] = [[edges[0]]]
    for edge in edges[1:]:
        if edge - clusters[-1][-1] <= _GRID_TOLERANCE:
            clusters[-1].append(edge)
        else:
            clusters.append([edge])

    keep = [cluster for cluster in clusters if len(cluster) >= _MIN_CLUSTER_ROWS]
    # A short document has no majority to defend: keep every edge it has.
    levels = tuple(
        round(sum(cluster) / len(cluster), 2) for cluster in (keep or clusters)
    )
    rights = sorted(item.bbox[2] for item in candidates)
    right = rights[min(len(rights) - 1, int(len(rights) * _RIGHT_EDGE_PERCENTILE))]
    return IndentGrid(levels=levels, column_left=levels[0], column_right=right)


def is_centred(item: SourceEvidence, grid: IndentGrid) -> bool:
    """True for a narrow, lettered block centred on the column.

    Geometrically a figure label is centred too; callers decide whether the
    region's *kind* can be a heading.
    """
    if grid.width <= 0:
        return False
    if not any(char.isalpha() for char in item.raw_text):
        return False
    x0, _, x1, _ = item.bbox
    if x1 - x0 > _CENTRE_MAX_WIDTH * grid.width:
        return False
    if x0 - grid.column_left < _CENTRE_MIN_INSET * grid.width:
        return False
    return abs((x0 + x1) / 2 - grid.centre) <= _CENTRE_TOLERANCE


@dataclass(frozen=True)
class ParagraphLine:
    """One rendered line of a paragraph, at its own indent level."""

    level: int
    text: str
    #: Regions that contributed to this line.
    evidence_ids: tuple[str, ...] = ()


@dataclass(frozen=True)
class EvidenceParagraph:
    """One paragraph: a numbered run, or a standalone unnumbered block."""

    paragraph_id: str
    #: Marker digits (``"0001"``); ``None`` for a block the document never
    #: numbered — a heading, or prose that predates the first marker.
    number: str | None
    page: int
    lines: tuple[ParagraphLine, ...]
    evidence_ids: tuple[str, ...]
    #: The block sits on the column centre, so it reads as a heading.
    centred: bool = False

    @property
    def text(self) -> str:
        """The paragraph's raw text, flattened onto one line."""
        return " ".join(line.text for line in self.lines)

    def starts_at(self, evidence_id: str) -> bool:
        """True when *evidence_id* contributed this paragraph's first fragment."""
        return bool(self.evidence_ids) and self.evidence_ids[0] == evidence_id


@dataclass(frozen=True)
class ParagraphAnchor:
    """Where one evidence row sits inside its paragraph."""

    paragraph_id: str
    number: str | None
    start: bool
    line: int
    level: int


@dataclass
class _LineDraft:
    level: int
    parts: list[str] = field(default_factory=list)
    evidence_ids: list[str] = field(default_factory=list)


@dataclass
class _Draft:
    doc_id: str
    number: str | None
    page: int
    first_evidence_id: str
    segment_index: int
    centred: bool
    lines: list[_LineDraft] = field(default_factory=list)
    evidence_ids: list[str] = field(default_factory=list)


def _segments(raw_text: str) -> list[str]:
    """Split one region's text into segments, each starting at a marker line."""
    segments: list[str] = []
    pending: list[str] = []
    for line in raw_text.splitlines():
        stripped = line.strip()
        if not stripped:
            continue
        if pending and PARAGRAPH_MARKER_RE.match(stripped):
            segments.append(" ".join(pending))
            pending = []
        pending.append(stripped)
    if pending:
        segments.append(" ".join(pending))
    return segments


def _is_prose(segment: str) -> bool:
    """False for a digit/symbol-only region such as a figure or formula label."""
    return any(char.isalpha() for char in segment)


def _start(
    item: SourceEvidence,
    segment_index: int,
    segment: str,
    *,
    number: str | None,
    level: int,
    centred: bool,
) -> _Draft:
    return _Draft(
        doc_id=item.doc_id,
        number=number,
        page=item.page,
        first_evidence_id=item.evidence_id,
        segment_index=segment_index,
        centred=centred,
        lines=[
            _LineDraft(
                level=max(level, 0),
                parts=[segment],
                evidence_ids=[item.evidence_id],
            )
        ],
        evidence_ids=[item.evidence_id],
    )


def _append(draft: _Draft, item: SourceEvidence, segment: str, level: int) -> None:
    """Add a fragment to the open paragraph, as a continuation or a new line."""
    last = draft.lines[-1]
    if last.level == level and not _ITEM_RE.match(segment):
        last.parts.append(segment)
    else:
        last = _LineDraft(
            level=max(level, 0),
            parts=[segment],
            evidence_ids=[item.evidence_id],
        )
        draft.lines.append(last)
    if item.evidence_id not in last.evidence_ids:
        last.evidence_ids.append(item.evidence_id)
    if item.evidence_id not in draft.evidence_ids:
        draft.evidence_ids.append(item.evidence_id)


def group_paragraphs(
    rows: Iterable[SourceEvidence], *, grid: IndentGrid | None = None
) -> list[EvidenceParagraph]:
    """Group text evidence into paragraphs, in reading order.

    Only :data:`TEXT`-category rows take part, and only in three ways: a row
    starts a numbered paragraph (a marker), starts a standalone block (a
    centred or heading-like line), or continues the open numbered paragraph —
    as an extra line when its indent level differs from the line above, or as
    more text of that line.

    Every other text row — page furniture (``head`` / ``foot`` / ``title`` /
    ``bib`` …), a digit-only label, or a region whose left edge is off the
    document's indent grid — is left out of the grouping entirely.  It neither
    contributes to nor interrupts a paragraph, so a running header on the next
    page cannot split a paragraph that spans the page break.

    A document with no markers yields one unnumbered paragraph per prose row,
    which is the pre-paragraph behaviour.
    """
    ordered = sorted(rows, key=reading_key)
    resolved = grid if grid is not None else indent_grid(ordered)
    drafts: list[_Draft] = []
    current: _Draft | None = None
    for item in ordered:
        if category_of(item.kind) != TEXT:
            continue
        level = resolved.level_of(item.bbox[0])
        # Figure and equation labels are centred too, but they are not prose
        # and never introduce a section.
        centred = is_centred(item, resolved) and item.kind in PARAGRAPH_FRAGMENT_KINDS
        for segment_index, segment in enumerate(_segments(item.raw_text)):
            marker = PARAGRAPH_MARKER_RE.match(segment)
            if marker is not None:
                current = _start(
                    item,
                    segment_index,
                    segment,
                    number=marker.group("number"),
                    level=level,
                    centred=centred,
                )
                drafts.append(current)
                continue
            # Centring is checked before the indent grid: a heading sits on the
            # column centre, which is by definition off the body's left edges.
            if centred:
                current = _start(
                    item,
                    segment_index,
                    segment,
                    number=None,
                    level=level,
                    centred=True,
                )
                drafts.append(current)
                continue
            if (
                not _is_prose(segment)
                or level < 0
                or item.kind not in PARAGRAPH_FRAGMENT_KINDS
            ):
                continue
            if is_heading_like(segment):
                current = _start(
                    item,
                    segment_index,
                    segment,
                    number=None,
                    level=level,
                    centred=False,
                )
                drafts.append(current)
                continue
            if current is not None and current.number is not None:
                _append(current, item, segment, level)
                continue
            current = _start(
                item,
                segment_index,
                segment,
                number=None,
                level=level,
                centred=centred,
            )
            drafts.append(current)
    return [_freeze(draft) for draft in drafts]


def _freeze(draft: _Draft) -> EvidenceParagraph:
    return EvidenceParagraph(
        paragraph_id=stable_id(
            "paragraph-v1",
            draft.doc_id,
            draft.first_evidence_id,
            str(draft.segment_index),
        ),
        number=draft.number,
        page=draft.page,
        lines=tuple(
            ParagraphLine(
                level=line.level,
                text=" ".join(line.parts),
                evidence_ids=tuple(line.evidence_ids),
            )
            for line in draft.lines
        ),
        evidence_ids=tuple(draft.evidence_ids),
        centred=draft.centred,
    )


def paragraph_index(
    paragraphs: Iterable[EvidenceParagraph],
) -> dict[str, EvidenceParagraph]:
    """Map every evidence id of a paragraph to that paragraph."""
    index: dict[str, EvidenceParagraph] = {}
    for paragraph in paragraphs:
        for evidence_id in paragraph.evidence_ids:
            index.setdefault(evidence_id, paragraph)
    return index


def paragraph_anchors(
    paragraphs: Iterable[EvidenceParagraph],
) -> dict[str, ParagraphAnchor]:
    """Map every evidence id to its paragraph, line and indent level."""
    anchors: dict[str, ParagraphAnchor] = {}
    for paragraph in paragraphs:
        for line_index, line in enumerate(paragraph.lines):
            for evidence_id in line.evidence_ids:
                if evidence_id in anchors:
                    continue
                anchors[evidence_id] = ParagraphAnchor(
                    paragraph_id=paragraph.paragraph_id,
                    number=paragraph.number,
                    start=paragraph.starts_at(evidence_id),
                    line=line_index,
                    level=line.level,
                )
    return anchors


__all__ = [
    "PARAGRAPH_FRAGMENT_KINDS",
    "PARAGRAPH_MARKER_RE",
    "EvidenceParagraph",
    "IndentGrid",
    "ParagraphAnchor",
    "ParagraphLine",
    "group_paragraphs",
    "indent_grid",
    "is_centred",
    "is_heading_like",
    "paragraph_anchors",
    "paragraph_index",
    "reading_key",
]
