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
from mbforge.utils.logger import get_logger

_KIND_RANK = {
    "text_span": 0,
    "table_span": 1,
    "ocr_label": 2,
    "image_region": 3,
    "molecule": 4,
}

logger = get_logger("mbforge.pipeline.artifacts.evidence_join")


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
        _KIND_RANK.get(item.kind, 99),
        item.evidence_id,
    )


def _join_evidence_dedupe(
    items: Sequence[SourceEvidence],
) -> list[SourceEvidence]:
    """Apply the existing molecule-over-image geometric precedence.

    Molecule evidence is emitted first and wins against overlapping image
    regions. Text evidence is retained because its raw text is an independent
    fact used by OCR/layout readers. Exact IDs are merged before this pass;
    this function only handles the separate geometric precedence rule.
    """
    from mbforge.pipeline.detection.bbox_filter import bbox_area, bbox_iou

    def sort_key(item: SourceEvidence) -> tuple[Any, ...]:
        return (
            item.page,
            0 if item.kind == "molecule" else 1,
            -bbox_area(item.bbox),
            item.evidence_id,
        )

    kept: list[SourceEvidence] = []
    for item in sorted(items, key=sort_key):
        discard = False
        for existing in kept:
            if existing.page != item.page:
                continue
            if existing.kind not in {"molecule", "image_region"} or item.kind not in {
                "molecule",
                "image_region",
            }:
                continue
            iou = bbox_iou(existing.bbox, item.bbox)
            same_region_kind = existing.kind == item.kind and existing.kind in {
                "molecule",
                "image_region",
            }
            if same_region_kind and iou <= 0.5:
                continue
            if not same_region_kind and iou <= 0.0:
                continue
            if existing.kind == "molecule" and item.kind == "image_region":
                discard = True
                break
            if existing.kind == item.kind == "molecule":
                # Molecule boxes are sorted largest-first, so the first box
                # wins and lower-area duplicate detections are discarded.
                discard = True
                break
            if existing.kind == item.kind == "image_region":
                discard = True
                break
        if not discard:
            kept.append(item)
    return kept


def join_evidence_artifacts(
    extracted: ExtractArtifact, detection: DetectionArtifact
) -> DocumentEvidenceArtifact:
    """Validate both raw branches and create the final SQL source facts.

    This is the only place that turns a raw page bbox into a
    :class:`SourceEvidence`. Consequently the ID is computed after rotation
    and the visual page coordinate system are fixed. Equal IDs are merged in
    this same pass; a differing payload is a hard conflict.
    """
    _validate_join_inputs(extracted, detection)
    frames = _frame_map(_extract_frames(extracted))
    raw_document = _extracted_from_artifact(extracted)

    by_id: dict[str, SourceEvidence] = {}

    def add(item: SourceEvidence) -> None:
        previous = by_id.get(item.evidence_id)
        if previous is not None:
            if previous.to_dict() != item.to_dict():
                raise ValueError(f"conflicting evidence payload for {item.evidence_id}")
            return
        by_id[item.evidence_id] = item

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
