"""Deterministic activity-to-molecule matching shared by both write paths.

PIPE-08 (repair plan section 5.4): ``molecules`` and
``activities`` used to carry two private copies of
``_link_activity_to_molecule()`` with independent ``used_rows`` tracking.
This module is the single owner of the matching rules. It is a pure,
side-effect-free matcher: it reads attributes off the inputs and returns
:class:`ActivityMatch` objects; all database writes stay in the callers.

Priority (repair plan section 5.4, item 4):

1. Row-label exact match (``row_label == mol.name``, stripped,
   case-insensitive).
2. Full-SMILES match (``row_smiles == canonical_smiles`` or ``esmiles``).
3. Same-page fallback — explicitly low-confidence
   (``ACTIVITY_PAGE_FALLBACK``), never disguised as a row-level match.

Unlike the historical per-record label-then-SMILES scan, rule priority is
global: a later row-label match beats an earlier SMILES-only match.

Page contract: ``activities.page_num`` is a 1-based ``PageNumber`` while
``DetectionSource.page`` is a 0-based ``PageIndex``; the fallback converts
exactly once via :func:`page_index_to_number` (see
:mod:`mbforge.pipeline.extract.pages`).

Duplicate assignment: each activity record is row-matched at most once
(tracked by input index), and duplicate rows sharing the same
``(table_idx, row_idx)`` coordinates are assigned at most once (tracked by
coordinate pair). The same-page fallback is limited to one molecule per
page, matching the historical ``used_pages`` behavior.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from typing import Any

from ...utils.logger import get_logger
from .normalization import normalize_reference_label

logger = get_logger(__name__)

# Structured reason codes (see the repair plan, section 11).
ACTIVITY_ROW_MATCHED = "ACTIVITY_ROW_MATCHED"
ACTIVITY_PAGE_FALLBACK = "ACTIVITY_PAGE_FALLBACK"
ACTIVITY_UNMATCHED = "ACTIVITY_UNMATCHED"


@dataclass(frozen=True)
class ActivityMatch:
    """One deterministic activity → molecule assignment.

    Attributes:
        candidate_key: Canonical SMILES of the molecule (its ``mol_id``),
            falling back to ``esmiles`` when no canonical form exists.
        record_key: Index of the matched record in the input
            ``activity_records`` sequence — stable for a given input.
        kind: ``"table_row"`` for row-level matches, ``"table"`` for the
            low-confidence same-page fallback.
        page_number: 1-based ``PageNumber`` of the matched record (row
            match) or of the fallback page; ``None`` when the record has
            no page.
        reason: Structured reason code — ``ACTIVITY_ROW_MATCHED`` or
            ``ACTIVITY_PAGE_FALLBACK``. The fallback is never reported as
            a row-level match.
    """

    candidate_key: str
    record_key: int
    kind: str
    page_number: int | None
    reason: str


@dataclass(frozen=True)
class ActivityVeto:
    """A candidate withheld from activity matching by a guard.

    Attributes:
        candidate_key: Canonical SMILES of the vetoed molecule.
        name: The candidate's label (e.g. the coref label that would have
            matched a ``row_label``).
        reason: Structured veto reason returned by the guard (e.g.
            ``FAMILY_CORE_MISMATCH``).
    """

    candidate_key: str
    name: str
    reason: str


def _is_page_number(value: Any) -> bool:
    """Return True for values usable as a 1-based ``PageNumber``."""
    return isinstance(value, int) and not isinstance(value, bool)


def _record_coords(rec: Any) -> tuple[Any, Any] | None:
    """Return the ``(table_idx, row_idx)`` identity of a record, if any."""
    table_idx = getattr(rec, "table_idx", None)
    row_idx = getattr(rec, "row_idx", None)
    if table_idx is None or row_idx is None:
        return None
    return (table_idx, row_idx)


def _primary_page_number(candidate: Any) -> int | None:
    """Convert the candidate's primary 0-based detection page to 1-based.

    Returns ``None`` when the candidate has no detections or no usable
    page — such candidates never participate in same-page matching and are
    never defaulted to the first page.
    """
    detections = getattr(candidate, "detections", None)
    if not detections:
        return None
    page = getattr(detections[0], "page", None)
    if not _is_page_number(page):
        return None
    return page + 1


def _candidate_label_values(candidate: Any) -> tuple[str, ...]:
    """Return explicit candidate labels in deterministic priority order.

    Coreference extraction preserves labels in candidate properties even when
    the display name is an image placeholder.  Activity matching must consume
    those labels, but only as explicit OCR/coreference evidence; it must not
    infer a label from the molecule structure.  ``ocr_labels`` are direct OCR
    reads of the annotation drawn next to the structure crop (DBSCAN "others"
    region) — the strongest explicit evidence for image-derived candidates.
    """
    values: list[str] = []
    name = getattr(candidate, "name", "")
    if isinstance(name, str) and name.strip():
        values.append(name.strip())
    properties = getattr(candidate, "properties", None)
    if isinstance(properties, dict):
        for key in ("normalized_label", "raw_coref_label", "coref_label", "label"):
            value = properties.get(key)
            if not isinstance(value, str) or not value.strip():
                continue
            cleaned = value.strip()
            if cleaned not in values:
                values.append(cleaned)
        ocr_labels = properties.get("ocr_labels")
        if isinstance(ocr_labels, list):
            for value in ocr_labels:
                if isinstance(value, str) and value.strip():
                    cleaned = value.strip()
                    if cleaned not in values:
                        values.append(cleaned)
        context_labels = properties.get("explicit_context_labels")
        if isinstance(context_labels, list):
            explicit = {
                value.strip()
                for value in context_labels
                if isinstance(value, str) and value.strip()
            }
            # Never choose among multiple labels inferred from surrounding
            # prose; only a unique explicit designation is safe to use.
            if len(explicit) == 1:
                value = next(iter(explicit))
                if value not in values:
                    values.append(value)
    return tuple(values)


def match_activities(
    candidates: Sequence[Any],
    activity_records: Sequence[Any],
    *,
    candidate_guard: Any | None = None,
    vetoes: list[ActivityVeto] | None = None,
) -> list[ActivityMatch]:
    """Match activity records to molecule candidates deterministically.

    Pure function: same input sequences always yield the same matches, so
    ``molecules`` (evidence + molecule aggregates) and
    ``activities`` (``activities`` rows) stay consistent by
    construction. Candidates without a canonical key, rejected candidates,
    and candidates that match nothing produce no ``ActivityMatch``; callers
    can treat their records as ``ACTIVITY_UNMATCHED``.

    Args:
        candidates: Molecule candidates in persistence order.
        activity_records: Activity records from the activity stage.
        candidate_guard: Optional callable returning a veto reason string
            for candidates that must not receive any activity (e.g. the
            family-core guard from :mod:`mbforge.pipeline.activity.family_gate`),
            or ``None`` to accept the candidate. Vetoed candidates are
            excluded from row matches *and* the same-page fallback so a
            mislabeled structure cannot absorb an activity by proximity.
        vetoes: Optional list populated with one :class:`ActivityVeto`
            per vetoed candidate, for review-queue reporting.

    Returns:
        At most one match per candidate, in candidate order.
    """
    records = list(activity_records)
    # Same-page fallback index: 1-based PageNumber → records sorted by
    # confidence (best first). Only integer page numbers participate.
    page_to_records: dict[int, list[tuple[int, Any]]] = {}
    for index, rec in enumerate(records):
        page_num = getattr(rec, "page_num", None)
        if not _is_page_number(page_num):
            continue
        page_to_records.setdefault(page_num, []).append((index, rec))
    for page_records in page_to_records.values():
        page_records.sort(
            key=lambda pair: float(getattr(pair[1], "confidence", 0) or 0),
            reverse=True,
        )

    # Pre-build O(1) lookup indexes so each candidate's _row_match is O(1)
    # amortised instead of O(R). Both indexes map the normalised key to the
    # list of record indices that carry it, preserving original record order.
    label_index: dict[str, list[int]] = {}
    reference_index: dict[str, list[int]] = {}
    smiles_index: dict[str, list[int]] = {}
    for i, rec in enumerate(records):
        row_label = getattr(rec, "row_label", None)
        if isinstance(row_label, str) and row_label.strip():
            label_index.setdefault(row_label.strip().lower(), []).append(i)
            reference = normalize_reference_label(row_label)
            if reference.key is not None and not reference.ambiguous:
                reference_index.setdefault(reference.key.lower(), []).append(i)
        row_smiles = getattr(rec, "row_smiles", None)
        if isinstance(row_smiles, str) and row_smiles.strip():
            smiles_index.setdefault(row_smiles.strip(), []).append(i)

    matches: list[ActivityMatch] = []
    used_rows: set[tuple[Any, Any]] = set()
    used_records: set[int] = set()
    used_pages: set[int] = set()
    for candidate in candidates:
        if getattr(candidate, "status", "") == "rejected":
            continue
        candidate_key = (
            getattr(candidate, "canonical_smiles", "")
            or getattr(candidate, "esmiles", "")
            or ""
        )
        if not candidate_key:
            continue
        if candidate_guard is not None:
            veto_reason = candidate_guard(candidate)
            if veto_reason is not None:
                logger.info(
                    "Activity match vetoed: reason=%s name=%r candidate=%s",
                    veto_reason,
                    getattr(candidate, "name", "") or "",
                    candidate_key[:60],
                )
                if vetoes is not None:
                    vetoes.append(
                        ActivityVeto(
                            candidate_key=candidate_key,
                            name=(getattr(candidate, "name", "") or "").strip(),
                            reason=veto_reason,
                        )
                    )
                continue
        match = _row_match(
            candidate,
            candidate_key,
            records,
            used_rows,
            used_records,
            label_index,
            reference_index,
            smiles_index,
        )
        if match is not None:
            matches.append(match)
            continue
        page_number = _primary_page_number(candidate)
        if (
            page_number is None
            or page_number in used_pages
            or page_number not in page_to_records
        ):
            logger.debug("Activity match: reason=%s kind=none", ACTIVITY_UNMATCHED)
            continue
        # Low-confidence same-page fallback: best-confidence record on the
        # candidate's page, at most one molecule per page.
        record_index, _rec = page_to_records[page_number][0]
        used_pages.add(page_number)
        matches.append(
            ActivityMatch(
                candidate_key=candidate_key,
                record_key=record_index,
                kind="table",
                page_number=page_number,
                reason=ACTIVITY_PAGE_FALLBACK,
            )
        )
    return matches


def _row_match(
    candidate: Any,
    candidate_key: str,
    records: list[Any],
    used_rows: set[tuple[Any, Any]],
    used_records: set[int],
    label_index: dict[str, list[int]],
    reference_index: dict[str, list[int]],
    smiles_index: dict[str, list[int]],
) -> ActivityMatch | None:
    """Row-level match for one candidate, or ``None``.

    Priority 1 is an exact row-label match against the candidate's explicit
    name or OCR/coreference label metadata; priority 2 is a full-SMILES match
    against the canonical SMILES or esmiles. Both passes skip records already
    claimed (by index or by duplicate ``(table_idx, row_idx)`` coordinates).

    Both passes use pre-built O(1) lookup indexes so the overall match cost
    is O(1) amortised per candidate rather than O(R) linear scan.
    """
    candidate_labels = _candidate_label_values(candidate)
    mol_canonical = (getattr(candidate, "canonical_smiles", "") or "").strip()
    mol_esmiles = (getattr(candidate, "esmiles", "") or "").strip()

    def _available(index: int, rec: Any) -> bool:
        if index in used_records:
            return False
        coords = _record_coords(rec)
        return coords is None or coords not in used_rows

    def _claim(index: int, rec: Any) -> ActivityMatch:
        used_records.add(index)
        coords = _record_coords(rec)
        if coords is not None:
            used_rows.add(coords)
        page_num = getattr(rec, "page_num", None)
        return ActivityMatch(
            candidate_key=candidate_key,
            record_key=index,
            kind="table_row",
            page_number=page_num if _is_page_number(page_num) else None,
            reason=ACTIVITY_ROW_MATCHED,
        )

    # Priority 1: exact row-label match (O(1) index lookup).
    for candidate_label in candidate_labels:
        for index in label_index.get(candidate_label.lower(), []):
            rec = records[index]
            if _available(index, rec):
                return _claim(index, rec)

        reference = normalize_reference_label(candidate_label)
        if reference.key is not None and not reference.ambiguous:
            candidate_page = _primary_page_number(candidate)
            for index in reference_index.get(reference.key.lower(), []):
                rec = records[index]
                record_page = getattr(rec, "page_num", None)
                if (
                    candidate_page is not None
                    and _is_page_number(record_page)
                    and candidate_page != record_page
                ):
                    continue
                if _available(index, rec):
                    return _claim(index, rec)

    # Priority 2: full-SMILES match (O(1) index lookup, never a prefix).
    # Union of both SMILES keys, sorted by original record index so the
    # semantics are identical to the former linear scan (first-match wins).
    p2: list[int] = []
    seen_p2: set[int] = set()
    for smiles_key in (mol_canonical, mol_esmiles):
        if not smiles_key:
            continue
        for idx in smiles_index.get(smiles_key, []):
            if idx not in seen_p2:
                seen_p2.add(idx)
                p2.append(idx)
    p2.sort()
    for index in p2:
        rec = records[index]
        if _available(index, rec):
            return _claim(index, rec)
    return None
