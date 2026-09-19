"""Join raw Extract and Detection branches into SQL-backed evidence."""

from __future__ import annotations

import json
from collections.abc import Iterable, Sequence
from pathlib import Path
from typing import Any

from mbforge.core.evidence import SourceEvidence
from mbforge.core.molecule import Molecule
from mbforge.core.types import ExtractionResult
from mbforge.pipeline.artifacts.branch_io import (
    _bbox_in_frame,
    _extracted_from_artifact,
    _frame_map,
    detection_results,
)
from mbforge.pipeline.artifacts.evidence_models import (
    DetectionArtifact,
    DocumentEvidenceArtifact,
    ExtractArtifact,
    PageFrame,
)
from mbforge.core.evidence_kind import (
    IMAGE,
    MOLECULE,
    TABLE,
    TEXT,
    category_of,
    kind_rank,
    register_kind_vocab,
    register_kinds,
)
from mbforge.utils.logger import get_logger

logger = get_logger("mbforge.pipeline.artifacts.evidence_join")

# Kinds this stage mints, registered where they are minted.
register_kinds(
    {
        "text_span": TEXT,
        "table_span": TABLE,
        "image_region": IMAGE,
        "molecule": MOLECULE,
    }
)


def _extract_frames(artifact: ExtractArtifact) -> list[PageFrame]:
    return [
        PageFrame(
            page=page.page_num,
            width=page.width,
            height=page.height,
            rotation=page.rotation,
        )
        for page in artifact.pages
    ]


def _detection_frames(artifact: DetectionArtifact) -> list[PageFrame]:
    return [
        PageFrame(
            page=page.page_num,
            width=page.width,
            height=page.height,
            rotation=page.rotation,
        )
        for page in artifact.pages
    ]


def _result_coref(result: ExtractionResult) -> str:
    path = str(result.mol_img_path or "").replace("\\", "/")
    return path if path.startswith("storage/") else ""


def _figure_coref(doc_id: str) -> str:
    """Reference a figure region back to the source PDF.

    Figure regions are recorded as layout rectangles only; the pipeline no
    longer extracts or stores page images, so the source document is the
    honest reference for them.
    """
    return f"storage/{doc_id}/source.pdf"


def _validate_join_inputs(
    extracted: ExtractArtifact, detection: DetectionArtifact
) -> None:
    if extracted.doc_id != detection.doc_id:
        raise ValueError("cannot join artifacts from different doc_id values")
    if extracted.run_id != detection.run_id:
        raise ValueError("cannot join artifacts from different run_id values")
    extract_frames = _extract_frames(extracted)
    detection_frames = _detection_frames(detection)
    if extract_frames != detection_frames:
        raise ValueError("Extract and Detection page frames differ")
    frames = _frame_map(extract_frames)
    if {page.page_num for page in extracted.pages} != set(frames):
        raise ValueError("Extract pages and page frames do not match")
    for result in detection_results(detection):
        if result.page_idx is None or result.bbox_pdf is None:
            raise ValueError("detection result must contain page_idx and bbox_pdf")
        frame = frames.get(result.page_idx + 1)
        if frame is None:
            raise ValueError(f"detection references unknown page {result.page_idx + 1}")
        _bbox_in_frame(result.bbox_pdf, frame)


def _evidence_sort_key(item: SourceEvidence) -> tuple[Any, ...]:
    bbox = item.bbox
    return (
        item.page,
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

    Comparison is by **category**, not by raw label: producers name their regions
    freely (``chem`` / ``figcx`` / …), so two figure regions from one model can
    carry different labels while playing the same role.
    """
    from mbforge.pipeline.detection.bbox_filter import bbox_area, bbox_iou

    def sort_key(item: SourceEvidence) -> tuple[Any, ...]:
        # Molecule first, then larger box, then the higher-ranked category.  The
        # last two keys only ever decide between boxes at the same location, i.e.
        # identical areas, so the winner is deterministic rather than arbitrary.
        return (
            item.page,
            0 if category_of(item.kind) == MOLECULE else 1,
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
                # Molecule boxes are sorted largest-first, so the first box
                # wins and lower-area duplicate detections are discarded.
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


def join_evidence_artifacts(
    extracted: ExtractArtifact, detection: DetectionArtifact
) -> DocumentEvidenceArtifact:
    """Validate both raw branches and create the final SQL source facts.

    This is the only place that turns a raw page bbox into a
    :class:`SourceEvidence`. Consequently the ID is computed after rotation
    and the visual page coordinate system are fixed. Rows sharing a location are
    arbitrated in this same pass — the location is the evidence ID, so only one
    row per location may survive.

    The producer declares its ``kind`` vocabulary in ``detection.meta.kind_vocab``
    (``{"chem": "image", ...}``); it is registered here so every downstream stage
    can map labels to categories without knowing the detector.
    """
    register_kind_vocab(detection.meta)

    _validate_join_inputs(extracted, detection)
    frames = _frame_map(_extract_frames(extracted))
    raw_document = _extracted_from_artifact(extracted)

    by_id: dict[str, SourceEvidence] = {}

    def add(item: SourceEvidence) -> None:
        """Record one claim, keeping a single row per location.

        ``evidence_id`` is the location, and it is the table's primary key, so two
        claims on the same box cannot both be stored. The stronger one keeps its
        ``kind``; neither side's content is thrown away — a text span and a figure
        at the same rect fold into one row carrying both ``raw_text`` and
        ``coref``.
        """
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
            coref=winner.coref or loser.coref,
            kind=winner.kind,
        )

    for page in raw_document.pages:
        frame = frames[page.page_num]
        # Figure regions arrive through ``figure_bboxes``; a raw artifact may
        # also carry one as a text span. Both feed one bbox set so each region
        # is emitted exactly once.
        image_bboxes: list[tuple[float, float, float, float]] = list(page.figure_bboxes)
        for span in page.text_spans:
            if span.block_type == 1:
                image_bboxes.append(span.bbox)
            elif span.block_type in {0, 2} and span.text.strip():
                add(
                    SourceEvidence.create(
                        doc_id=extracted.doc_id,
                        page=page.page_num,
                        bbox=_bbox_in_frame(span.bbox, frame),
                        raw_text=span.text,
                        kind="table_span" if span.block_type == 2 else "text_span",
                    )
                )
        for raw_bbox in dict.fromkeys(image_bboxes):
            add(
                SourceEvidence.create(
                    doc_id=extracted.doc_id,
                    page=page.page_num,
                    bbox=_bbox_in_frame(raw_bbox, frame),
                    coref=_figure_coref(extracted.doc_id),
                    kind="image_region",
                )
            )

    for result in detection_results(detection):
        if result.page_idx is None or result.bbox_pdf is None:
            raise ValueError("detection result must contain page_idx and bbox_pdf")
        coref = _result_coref(result)
        raw_text = (
            json.dumps(
                {
                    "name": result.name,
                    "smiles": result.smiles,
                    "esmiles": result.esmiles,
                    "moldet_conf": result.moldet_conf,
                },
                ensure_ascii=False,
                sort_keys=True,
            )
            if result.source == "image"
            else (result.name or result.context_text or result.smiles)
        )
        if not coref and not raw_text:
            raise ValueError("detection result has no source content")
        add(
            SourceEvidence.create(
                doc_id=extracted.doc_id,
                page=result.page_idx + 1,
                bbox=_bbox_in_frame(result.bbox_pdf, frames[result.page_idx + 1]),
                raw_text=raw_text,
                coref=coref,
                kind="molecule" if result.source == "image" else "text_span",
            )
        )

    evidence = _join_evidence_dedupe(list(by_id.values()))
    evidence.sort(key=_evidence_sort_key)
    return DocumentEvidenceArtifact(
        doc_id=extracted.doc_id,
        run_id=extracted.run_id,
        conventions={
            "extract_bbox": "pdf_bottom_left",
            "detection_bbox": "pdf_bottom_left",
            "joined_bbox": "pdf_bottom_left",
        },
        pages=list(frames.values()),
        evidence=evidence,
        evidence_ids=[item.evidence_id for item in evidence],
    )


def load_document_evidence(
    library_root: str | Path, doc_id: str
) -> list[SourceEvidence]:
    """Load source evidence facts from SQLite only."""
    from mbforge.services.documents.source_evidence import list_evidence

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
    from mbforge.pipeline.detection.correction import correct_molecules_with_context
    from mbforge.pipeline.detection.normalization import normalize_molecules

    candidates = correct_molecules_with_context(normalize_molecules(list(results)))
    by_location = {
        (item.page, item.bbox, item.kind): item.evidence_id for item in evidence
    }
    rejected_locations = {
        (result.page_idx + 1, result.bbox_pdf)
        for result in results
        if result.status == "rejected"
        and result.page_idx is not None
        and result.bbox_pdf is not None
    }
    for candidate in candidates:
        for detection in candidate.detections:
            if detection.page is None or detection.bbox is None:
                continue
            kind = "molecule" if detection.source == "image" else "text_span"
            detection.evidence_id = by_location.get(
                (detection.page + 1, detection.bbox, kind)
            )
            if (detection.page + 1, detection.bbox) in rejected_locations:
                candidate.status = "rejected"
    return candidates


def summarize_molecules(
    candidates: Sequence[Molecule], base: dict[str, Any] | None = None
) -> dict[str, Any]:
    """Build the post-Join molecule statistics without creating an ID."""
    pending = [item for item in candidates if item.status == "pending"]
    pending_review = [item for item in candidates if item.status == "pending_review"]
    rejected = [item for item in candidates if item.status == "rejected"]
    sources = sorted({source for item in candidates for source in item.sources})
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
            "sources": sources,
        }
    )
    return stats


# --- pages (ExtractStage output) ---------------------------------------------

__all__ = [
    "evidence_ids_for",
    "join_evidence_artifacts",
    "load_document_evidence",
    "summarize_molecules",
]
