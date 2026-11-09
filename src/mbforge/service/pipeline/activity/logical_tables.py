"""Group layout table fragments into logical tables.

A printed table can be split by the layout stage into several regions: a
cross-page continuation, a column break, or a repeated header. Classification
must run on the *logical* table, because a continuation fragment has no header
of its own — judging it alone loses the table.

The grouping is deliberately geometric and conservative:

* same document, consecutive page(s) only;
* the fragments share the same printed x-range (a few points of tolerance);
* the previous fragment reaches the bottom of its page and the next one starts
  at the top of its page (or the next fragment carries an explicit
  ``continued``/``续表`` caption);
* a fragment that prints its own metric header starts a new logical table
  unless it is captioned as a continuation.

A wrong merge is worse than a missed one: an unmerged continuation can still be
recovered from its parent's class, while a wrong merge would lend an activity
label to a table that has none.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass

#: Fragment x0/x1 may drift this much and still be the same printed column.
DEFAULT_X_TOLERANCE = 5.0
#: The previous fragment must reach this close to the page bottom (PDF points).
DEFAULT_BOTTOM_MARGIN = 0.12
#: The next fragment must start this close to the page top.
DEFAULT_TOP_MARGIN = 0.88
#: Column-count difference tolerated between fragments (``None`` = unknown).
DEFAULT_COLUMN_TOLERANCE = 1

_CONTINUED_RE = ("continued", "continuation", "cont'd", "续表", "续上表", "接上表")


@dataclass(frozen=True)
class TableFragment:
    """One layout table region, in PDF points (bottom-left origin)."""

    source: str
    page: int
    table: int
    bbox: tuple[float, float, float, float]
    page_width: float
    page_height: float
    #: Whether this fragment prints a header the classifier recognized (a
    #: metric/analytical/label header); a continuation tail has none.
    has_header: bool | None = None
    #: Number of table columns, when a recognizer reported it.
    column_count: int | None = None
    #: Header/caption text when OCR saw one, used to detect "continued".
    caption: str = ""
    #: The recognizer promoted the first DATA row to a header (a continuation
    #: fragment prints no header). This is the strongest continuation signal:
    #: it does not depend on how close the previous fragment reached the page
    #: bottom, which layout detection never guarantees.
    header_is_data: bool = False


@dataclass(frozen=True)
class LogicalTable:
    """Fragments that print one logical table, in reading order."""

    logical_id: str
    fragments: tuple[TableFragment, ...]

    @property
    def first(self) -> TableFragment:
        return self.fragments[0]

    @property
    def header_fragment(self) -> TableFragment | None:
        for fragment in self.fragments:
            if fragment.has_header:
                return fragment
        return None


def _x_aligned(
    previous: TableFragment, current: TableFragment, tolerance: float
) -> bool:
    return (
        abs(previous.bbox[0] - current.bbox[0]) <= tolerance
        and abs(previous.bbox[2] - current.bbox[2]) <= tolerance
    )


def _at_page_bottom(fragment: TableFragment, margin: float) -> bool:
    return fragment.bbox[1] <= fragment.page_height * margin


def _at_page_top(fragment: TableFragment, margin: float) -> bool:
    return fragment.bbox[3] >= fragment.page_height * margin


def _columns_compatible(
    previous: TableFragment, current: TableFragment, tolerance: int
) -> bool:
    if previous.column_count is None or current.column_count is None:
        return True
    return abs(previous.column_count - current.column_count) <= tolerance


def _is_continued_caption(caption: str) -> bool:
    lowered = (caption or "").lower()
    return any(marker in lowered for marker in _CONTINUED_RE)


def _continues(
    previous: TableFragment,
    current: TableFragment,
    *,
    x_tolerance: float,
    bottom_margin: float,
    top_margin: float,
    column_tolerance: int,
) -> bool:
    if previous.source != current.source:
        return False
    page_gap = current.page - previous.page
    if page_gap not in (0, 1):
        return False
    if not _x_aligned(previous, current, x_tolerance):
        return False
    if not _columns_compatible(previous, current, column_tolerance):
        return False
    if _is_continued_caption(current.caption):
        return True
    # A fragment that prints its own header is a new table, not a tail.
    if current.has_header and not current.header_is_data:
        return False
    if page_gap == 1:
        if current.header_is_data:
            return True
        return _at_page_bottom(previous, bottom_margin) and _at_page_top(
            current, top_margin
        )
    # Same page: a column break keeps the reading order and the width, but the
    # fragment must still look like a tail (no header) — covered above.
    return True


def group_fragments(
    fragments: list[TableFragment],
    *,
    x_tolerance: float = DEFAULT_X_TOLERANCE,
    bottom_margin: float = DEFAULT_BOTTOM_MARGIN,
    top_margin: float = DEFAULT_TOP_MARGIN,
    column_tolerance: int = DEFAULT_COLUMN_TOLERANCE,
) -> list[LogicalTable]:
    """Return logical tables in reading order (``source``, page, table)."""
    ordered = sorted(fragments, key=lambda f: (f.source, f.page, f.table))
    groups: list[list[TableFragment]] = []
    for fragment in ordered:
        if groups and _continues(
            groups[-1][-1],
            fragment,
            x_tolerance=x_tolerance,
            bottom_margin=bottom_margin,
            top_margin=top_margin,
            column_tolerance=column_tolerance,
        ):
            groups[-1].append(fragment)
            continue
        groups.append([fragment])
    return [
        LogicalTable(
            logical_id=f"{group[0].source}#p{group[0].page}t{group[0].table}",
            fragments=tuple(group),
        )
        for group in groups
    ]


#: Classes a fragment can hold when its own header was recognized. A fragment
#: whose header the classifier could not read is not a classification source.
HEADER_CLASSES: tuple[str, ...] = (
    "activity",
    "pk",
    "analytical",
    "synthesis",
    "glossary",
)
#: When several fragments carry a header, the strongest class wins. Activity
#: beats analytical because a column of IC50 beside a "Method"/LCMS column is
#: still an activity table.
CLASS_PRIORITY: dict[str, int] = {
    "activity": 0,
    "pk": 1,
    "analytical": 2,
    "synthesis": 3,
    "glossary": 4,
}


@dataclass(frozen=True)
class FragmentClass:
    """What the classifier read on one fragment, plus its value-shape signals."""

    name: str = "other"
    numeric_density: float = 0.0
    qualitative_values: int = 0
    unit_values: int = 0


def classify_logical_table(
    group: LogicalTable,
    classes: Mapping[tuple[str, int, int], FragmentClass],
) -> tuple[str, str]:
    """Return ``(class, source)`` for one logical table.

    A header-bearing fragment decides the class and the fragments without a
    header inherit it. When no fragment printed a readable header, a table that
    still prints plenty of numeric/qualitative values with a unit is surfaced as
    ``activity?`` for review instead of being silently dropped.
    """
    ranked: list[tuple[int, int, int, str]] = []
    for fragment in group.fragments:
        fragment_class = classes.get(
            (group.first.source, fragment.page, fragment.table)
        )
        if fragment_class is None or fragment_class.name not in HEADER_CLASSES:
            continue
        ranked.append(
            (
                CLASS_PRIORITY[fragment_class.name],
                fragment.page,
                fragment.table,
                fragment_class.name,
            )
        )
    if ranked:
        ranked.sort()
        _, page, table, name = ranked[0]
        return name, f"p{page}t{table}"

    shapes = [
        classes[(group.first.source, fragment.page, fragment.table)]
        for fragment in group.fragments
        if (group.first.source, fragment.page, fragment.table) in classes
    ]
    if shapes:
        density = max(shape.numeric_density for shape in shapes)
        qualitative = max(shape.qualitative_values for shape in shapes)
        units = max(shape.unit_values for shape in shapes)
        if (density >= 0.2 or qualitative >= 2) and units >= 1:
            return "activity?", "content_shape"
        if any(shape.name == "activity?" for shape in shapes):
            return "activity?", "inherited"
        if all(shape.name == "other" for shape in shapes):
            return "other", "content_shape"
        return shapes[0].name, "fragment"
    return "other", "unclassified"


__all__ = [
    "DEFAULT_BOTTOM_MARGIN",
    "DEFAULT_COLUMN_TOLERANCE",
    "DEFAULT_TOP_MARGIN",
    "DEFAULT_X_TOLERANCE",
    "CLASS_PRIORITY",
    "FragmentClass",
    "HEADER_CLASSES",
    "LogicalTable",
    "TableFragment",
    "classify_logical_table",
    "group_fragments",
]
