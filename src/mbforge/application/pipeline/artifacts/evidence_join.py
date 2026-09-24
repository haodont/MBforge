"""Mint the canonical ``SourceEvidence`` rows from one page of Extract output.

This is the only place that turns a raw page bbox into a
:class:`SourceEvidence`, so the evidence ID is computed after the visual page
coordinate system is fixed and rows sharing a location are arbitrated in the
same pass — the location *is* the evidence ID, so only one row per location may
survive.

``kind`` is the producer's own label, stored verbatim.  The closed label →
category mapping lives in :mod:`mbforge.domain.evidence_kind`; readers compare
categories, never label strings.
"""

from __future__ import annotations

import json
from collections.abc import Iterable, Sequence
from pathlib import Path
from typing import Any

from mbforge.application.pipeline.artifacts.evidence_models import PageFrame
from mbforge.application.pipeline.extract.text import ExtractedDocument
from mbforge.application.pipeline.layout.labels import kind_vocab
from mbforge.domain.evidence import SourceEvidence
from mbforge.domain.evidence_kind import (
    IMAGE,
    MOLECULE,
    category_of,
    kind_rank,
    register_kinds,
)
from mbforge.domain.molecule import Molecule
from mbforge.domain.types import ExtractionResult
from mbforge.foundation.layout import LibraryLayout
from mbforge.foundation.logger import get_logger

logger = get_logger("mbforge.application.pipeline.artifacts.evidence_join")

# The closed label → category mapping is declared in code: the layout producer's
# own labels plus the molecule label.  A reader that only opens SQL gets it by
# importing this module (or ``hydration``), never from a producer artifact.
register_kinds(kind_vocab())

#: Observation fields the evidence row already carries in its own columns.
_LOCATION_FIELDS = ("page_idx", "bbox_pdf")


def page_frames_from_pdf(pdf_path: str | Path) -> list[PageFrame]:
    """Read the visual page frames once at the producer boundary."""
    import pymupdf

    document = pymupdf.open(str(pdf_path))
    try:
        return [
            PageFrame(
                page=index + 1,
                width=float(page.rect.width),
                height=float(page.rect.height),
                rotation=int(page.rotation),
            )
            for index, page in enumerate(document)
        ]
    finally:
        document.close()


def _frame_map(pages: Sequence[PageFrame]) -> dict[int, PageFrame]:
    frames = {page.page: page for page in pages}
    if len(frames) != len(pages):
        raise ValueError("page frames must contain each page number once")
    return frames


def _validated_bbox(
    bbox: Iterable[float], width: float, height: float
) -> tuple[float, float, float, float]:
    raw_values = list(bbox)
    if len(raw_values) != 4:
        raise ValueError("bbox must contain exactly four coordinates")
    x0, y0, x1, y1 = (float(value) for value in raw_values)
    values = (x0, y0, x1, y1)
    if not (0 <= x0 <= x1 <= width and 0 <= y0 <= y1 <= height):
        raise ValueError("bbox is outside page frame")
    return values


def _bbox_in_frame(
    bbox: Iterable[float], frame: PageFrame
) -> tuple[float, float, float, float]:
    return _validated_bbox(bbox, frame.width, frame.height)


def _canonical_crop_path(
    library_root: str | Path,
    doc_id: str,
    image_path: str | None,
    *,
    staging_dir: str | Path | None,
) -> str:
    """Rewrite a crop path to its library-relative reference, or return ``""``.

    The crop must already be archived (canonically, or in this run's staging
    directory) — a row that references a missing image is a defect, not a fact.
    """
    if not image_path:
        return ""
    name = Path(str(image_path).replace("\\", "/")).name
    if not name or name in {".", ".."}:
        return ""
    layout = LibraryLayout(library_root)
    canonical_path = layout.crop(doc_id, name)
    staged_path = (
        Path(staging_dir) / "crops" / name if staging_dir is not None else None
    )
    if not canonical_path.is_file() and (
        staged_path is None or not staged_path.is_file()
    ):
        raise ValueError(f"molecule crop is not archived: {name}")
    return f"storage/{doc_id}/crops/{name}"


def observation_payload(
    result: ExtractionResult,
    *,
    doc_id: str,
    library_root: str | Path,
    staging_dir: str | Path | None,
) -> dict[str, Any]:
    """Return the JSON payload stored in a molecule row's ``raw_text``.

    The observation keeps everything that has no column of its own; the location
    (``page_idx`` / ``bbox_pdf``) is dropped because the row's ``page`` and
    ``bbox_x0..y1`` already carry it.  ``mol_img_path`` is rewritten to the
    canonical library-relative crop reference.
    """
    payload = result.to_dict()
    payload["mol_img_path"] = _canonical_crop_path(
        library_root, doc_id, result.mol_img_path, staging_dir=staging_dir
    )
    return {key: value for key, value in payload.items() if key not in _LOCATION_FIELDS}


def observation_from_payload(
    raw_text: str, *, page: int, bbox: Sequence[float]
) -> ExtractionResult:
    """Rebuild one molecule observation from its row payload plus the row location."""
    payload = json.loads(raw_text)
    if not isinstance(payload, dict):
        raise ValueError("molecule payload must be a JSON object")
    return ExtractionResult.from_dict(
        {
            **payload,
            "page_idx": page - 1,
            "bbox_pdf": list(bbox),
        }
    )


def _location_key(page: int, bbox: Iterable[float]) -> tuple[int, tuple[str, ...]]:
    """Location key formatted exactly as :func:`domain.evidence._location_id` does."""
    return (page, tuple(f"{round(float(value), 2):.2f}" for value in bbox))


def _reading_order_hint(document: Any) -> dict[tuple[int, tuple[str, ...]], int]:
    """Map a layout region's location to its column-aware reading order."""
    hint: dict[tuple[int, tuple[str, ...]], int] = {}
    for page in document.pages:
        for region in page.regions:
            bbox = region.get("bbox")
            if not isinstance(bbox, (list, tuple)) or len(bbox) != 4:
                continue
            try:
                hint[_location_key(page.page_num, bbox)] = int(
                    region.get("reading_order", 0)
                )
            except (TypeError, ValueError):
                continue
    return hint


def _region_evidence(
    region: dict[str, Any], doc_id: str, page: int, frame: PageFrame
) -> SourceEvidence:
    """Turn one typed layout region into source evidence.

    ``kind`` is the detector's own label (``text`` / ``sec`` / ``figcx`` …), kept
    verbatim.  Content is the recognized text when there is any; a region the
    producer located but could not read carries an empty payload.
    """
    return SourceEvidence.create(
        doc_id=doc_id,
        page=page,
        bbox=_bbox_in_frame(region.get("bbox") or (), frame),
        raw_text=str(region.get("text") or "").strip(),
        kind=str(region.get("kind") or "text"),
    )


def _evidence_sort_key(
    item: SourceEvidence,
    order_hint: dict[tuple[int, tuple[str, ...]], int] | None = None,
) -> tuple[Any, ...]:
    """Sort key for the evidence list.

    A row whose location carries a layout ``reading_order`` sorts by it (inside
    its page, ahead of everything unordered), which is what makes a two-column
    patent read correctly. The trailing raster keys remain as tie-breakers; the
    hint is unique per row, so they never decide between two ordered rows.
    """
    bbox = item.bbox
    hint = order_hint.get(_location_key(item.page, bbox)) if order_hint else None
    return (
        item.page,
        0 if hint is not None else 1,
        hint if hint is not None else 0,
        -bbox[3],
        bbox[0],
        -bbox[1],
        bbox[2],
        kind_rank(item.kind),
        item.evidence_id,
    )


def _join_evidence_dedupe(
    items: Sequence[SourceEvidence],
) -> list[SourceEvidence]:
    """Arbitrate evidence so one location yields one row.

    Two rules:

    1. **One row per location** ``(doc_id, page, bbox)``.  ``evidence_id`` is the
       location, and it is the table's PRIMARY KEY, so two claims on the same box
       must collapse to a single row before the insert.  The surviving row keeps
       the winner's ``kind``.
    2. **Molecule over figure** for overlapping (but not identical) boxes.  Text is
       never discarded here — its raw text is an independent fact used by
       OCR/layout readers.

    A claim that carries content is never displaced by one that does not:
    ``raw_text`` outranks box geometry, so a layout region re-typed to a molecule
    (R3) — which claims the molecule with MolDet's own geometry but no payload —
    leaves the molecule pass' row, and its SMILES, in place.

    Comparison is by **category**, not by raw label: producers name their regions
    freely (``chem`` / ``figcx`` / …), so two figure regions from one model can
    carry different labels while playing the same role.
    """
    from mbforge.application.pipeline.detection.bbox_filter import bbox_area, bbox_iou

    def sort_key(item: SourceEvidence) -> tuple[Any, ...]:
        # Molecule first, then content, then larger box, then the higher-ranked
        # category.  Content before size: the two sides of an overlap are usually
        # one molecule seen by two detectors, and only the molecule pass' row
        # holds the recognition payload.  The size and rank keys only ever decide
        # between equally content-bearing boxes, so the winner stays deterministic.
        return (
            item.page,
            0 if category_of(item.kind) == MOLECULE else 1,
            0 if item.raw_text else 1,
            -bbox_area(item.bbox),
            -kind_rank(item.kind),
            item.evidence_id,
        )

    geometric = {MOLECULE, IMAGE}
    kept: list[SourceEvidence] = []
    seen_locations: set[tuple[str, int, tuple[float, float, float, float]]] = set()
    for item in sorted(items, key=sort_key):
        location = (item.doc_id, item.page, item.bbox)
        if location in seen_locations:
            continue
        discard = False
        item_category = category_of(item.kind)
        for existing in kept:
            if existing.page != item.page:
                continue
            existing_category = category_of(existing.kind)
            if existing_category not in geometric or item_category not in geometric:
                continue
            iou = bbox_iou(existing.bbox, item.bbox)
            same_region_kind = existing_category == item_category
            if same_region_kind and iou <= 0.5:
                continue
            if not same_region_kind and iou <= 0.0:
                continue
            if existing_category == MOLECULE and item_category == IMAGE:
                discard = True
                break
            if existing_category == item_category == MOLECULE:
                # Molecule boxes are sorted content-then-size-first, so the
                # first box wins and lower-value duplicate detections drop out.
                discard = True
                break
            if existing_category == item_category == IMAGE:
                discard = True
                break
        if not discard:
            kept.append(item)
            seen_locations.add(location)
    return kept


def _location_precedence(item: SourceEvidence) -> tuple[int, str]:
    """Ordering used when two claims share one location.  Higher wins.

    Category first (molecule > figure > table > text), then the label itself so
    the outcome is deterministic when two labels share a category.
    """
    return (kind_rank(item.kind), item.kind)


def mint_evidence(
    extracted: ExtractedDocument,
    frames: Sequence[PageFrame],
    results: Sequence[ExtractionResult] = (),
    *,
    library_root: str | Path,
    staging_dir: str | Path | None = None,
) -> list[SourceEvidence]:
    """Create the document's canonical source evidence, ordered for reading."""
    page_frames = list(frames)
    frame_by_page = _frame_map(page_frames)
    if {page.page_num for page in extracted.pages} != set(frame_by_page):
        raise ValueError("Extract pages and page frames do not match")
    for result in results:
        if result.page_idx is None or result.bbox_pdf is None:
            raise ValueError("molecule result must contain page_idx and bbox_pdf")
        frame = frame_by_page.get(result.page_idx + 1)
        if frame is None:
            raise ValueError(f"molecule references unknown page {result.page_idx + 1}")
        _bbox_in_frame(result.bbox_pdf, frame)

    order_hint = _reading_order_hint(extracted)
    by_id: dict[str, SourceEvidence] = {}

    def add(item: SourceEvidence) -> None:
        """Record one claim, keeping a single row per location."""
        previous = by_id.get(item.evidence_id)
        if previous is None:
            by_id[item.evidence_id] = item
            return
        if previous.to_dict() == item.to_dict():
            return
        winner, loser = (
            (item, previous)
            if _location_precedence(item) > _location_precedence(previous)
            else (previous, item)
        )
        by_id[item.evidence_id] = SourceEvidence.create(
            doc_id=winner.doc_id,
            page=winner.page,
            bbox=winner.bbox,
            raw_text=winner.raw_text or loser.raw_text,
            kind=winner.kind,
        )

    for page in extracted.pages:
        frame = frame_by_page[page.page_num]
        # A page carrying typed regions came from the local layout producer:
        # those regions are the authoritative layout (they keep the detector's
        # own ``kind``), and the derived text_spans/figure_bboxes are only a
        # legacy view for the markdown stage. Minting both would duplicate rows.
        for region in page.regions:
            add(_region_evidence(region, extracted.doc_id, page.page_num, frame))

    for result in results:
        if result.page_idx is None or result.bbox_pdf is None:  # pragma: no cover
            raise ValueError("molecule result must contain page_idx and bbox_pdf")
        page = result.page_idx + 1
        add(
            SourceEvidence.create(
                doc_id=extracted.doc_id,
                page=page,
                bbox=_bbox_in_frame(result.bbox_pdf, frame_by_page[page]),
                raw_text=json.dumps(
                    observation_payload(
                        result,
                        doc_id=extracted.doc_id,
                        library_root=library_root,
                        staging_dir=staging_dir,
                    ),
                    ensure_ascii=False,
                    sort_keys=True,
                ),
                kind="molecule",
            )
        )

    evidence = _join_evidence_dedupe(list(by_id.values()))
    evidence.sort(key=lambda item: _evidence_sort_key(item, order_hint))
    return evidence


def load_document_evidence(
    library_root: str | Path, doc_id: str
) -> list[SourceEvidence]:
    """Load source evidence facts from SQLite only."""
    from mbforge.application.use_cases.documents.source_evidence import list_evidence

    return list_evidence(library_root, doc_id)


def evidence_ids_for(
    artifact: Any | None,
    *,
    page: int | None = None,
    bbox: Iterable[float] | None = None,
    raw_text: str = "",
    kind: str | None = None,
) -> list[str]:
    """Resolve secondary data to existing source evidence IDs only.

    ``raw_text`` may identify a line inside a multi-line source text block;
    page and bbox filters still constrain the result to the original region.
    """
    if artifact is None:
        return []
    expected_bbox: tuple[float, float, float, float] | None = None
    if bbox is not None:
        values = list(bbox)
        if len(values) != 4:
            return []
        try:
            x0, y0, x1, y1 = (float(value) for value in values)
        except (TypeError, ValueError):
            return []
        expected_bbox = (x0, y0, x1, y1)
    items = (
        artifact if isinstance(artifact, list) else getattr(artifact, "evidence", [])
    )
    return sorted(
        {
            item.evidence_id
            for item in items
            if (page is None or item.page == page)
            and (expected_bbox is None or item.bbox == expected_bbox)
            and (not raw_text or raw_text in item.raw_text)
            and (kind is None or item.kind == kind)
        }
    )


def _candidates_from_evidence(
    results: Sequence[ExtractionResult],
    evidence: Sequence[SourceEvidence],
) -> list[Molecule]:
    from mbforge.application.pipeline.detection.correction import (
        correct_molecules_with_context,
    )
    from mbforge.application.pipeline.detection.normalization import normalize_molecules

    candidates = correct_molecules_with_context(normalize_molecules(list(results)))
    by_location = {
        (item.page, item.bbox, item.kind): item.evidence_id for item in evidence
    }
    for candidate in candidates:
        for detection in candidate.detections:
            if detection.page is None or detection.bbox is None:
                continue
            detection.evidence_id = by_location.get(
                (detection.page + 1, detection.bbox, "molecule")
            )
    return candidates


def summarize_molecules(
    candidates: Sequence[Molecule], base: dict[str, Any] | None = None
) -> dict[str, Any]:
    """Build the post-extract molecule statistics without creating an ID."""
    pending = [item for item in candidates if item.status == "pending"]
    pending_review = [item for item in candidates if item.status == "pending_review"]
    rejected = [item for item in candidates if item.status == "rejected"]
    stats = dict(base or {})
    stats.update(
        {
            "molecule_count": len(pending) + len(pending_review),
            "rejected_count": len(rejected),
            "pending_review_count": len(pending_review),
            "total_candidates": len(candidates),
            "corrected_count": sum(
                1 for item in candidates if item.properties.get("corrections")
            ),
        }
    )
    return stats


__all__ = [
    "evidence_ids_for",
    "load_document_evidence",
    "mint_evidence",
    "observation_from_payload",
    "observation_payload",
    "page_frames_from_pdf",
    "summarize_molecules",
]
