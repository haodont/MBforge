"""Readable raw branch artifacts and the SQL source-evidence boundary."""

from __future__ import annotations

import json
import os
import tempfile
from collections.abc import Iterable, Sequence
from contextlib import suppress
from pathlib import Path
from typing import TYPE_CHECKING, Any

from ..core.evidence import SourceEvidence
from ..storage.layout import LibraryLayout
from ..utils.logger import get_logger
from .detection.types import ExtractionResult, NormalizedMolecule
from .extract_text import ExtractedDocument, PageContent, TextSpan

if TYPE_CHECKING:
    from .context import PipelineContext
    from .evidence_artifacts import (
        DetectionArtifact,
        DocumentEvidenceArtifact,
        ExtractArtifact,
        PageFrame,
    )

logger = get_logger("mbforge.pipeline.stage_artifacts")

_EXTRACT_FILE = "extract.json"
_DETECTION_FILE = "detection.json"
_STAGE_DIR = ".staging"
_IMAGE_SUFFIXES = {".gif", ".jpeg", ".jpg", ".png", ".svg", ".webp"}


def _artifact_path(library_root: str | Path, doc_id: str, name: str) -> Path:
    return LibraryLayout(library_root).storage_dir(doc_id) / name


def _read_json(path: Path) -> dict[str, Any] | None:
    if not path.is_file():
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError) as exc:
        logger.warning("Ignoring unreadable artifact %s: %s", path, exc)
        return None
    if not isinstance(data, dict):
        logger.warning(
            "Ignoring artifact %s: expected object, got %s", path, type(data).__name__
        )
        return None
    return data


# --- evidence fork/join -----------------------------------------------------
#
# New producers use independent branch files. The Join writes source-evidence
# facts to SQLite, which is the only runtime evidence store.
_KIND_RANK = {
    "text_span": 0,
    "table_span": 1,
    "ocr_label": 2,
    "image_region": 3,
    "molecule": 4,
}


def _branch_path(library_root: str | Path, doc_id: str, filename: str) -> Path:
    return _artifact_path(library_root, doc_id, _STAGE_DIR) / filename


def _write_json_atomic(path: Path, payload: dict[str, Any]) -> None:
    """Write one JSON object and publish it with an atomic replacement."""
    path.parent.mkdir(parents=True, exist_ok=True)
    temp_name: str | None = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="w",
            encoding="utf-8",
            dir=path.parent,
            prefix=f".{path.name}.",
            suffix=".tmp",
            delete=False,
        ) as handle:
            temp_name = handle.name
            json.dump(payload, handle, ensure_ascii=False, indent=2, default=str)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temp_name, path)
    except Exception:
        if temp_name is not None:
            with suppress(OSError):
                Path(temp_name).unlink()
        raise
    logger.info("Saved stage artifact %s", path)


def page_frames_from_pdf(pdf_path: str | Path) -> list[PageFrame]:
    """Read visual page frames once at a producer boundary."""
    import pymupdf

    from .evidence_artifacts import PageFrame

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


def build_extract_artifact(
    doc_id: str,
    run_id: str,
    extracted: ExtractedDocument,
    pages: Sequence[PageFrame],
) -> ExtractArtifact:
    """Project Extract output to a readable raw branch.

    Evidence IDs are deliberately absent here. Native coordinates and page
    rotation are resolved together by :func:`join_evidence_artifacts`.
    """
    from .evidence_artifacts import ExtractArtifact, ExtractPage

    page_list = list(pages)
    frames = _frame_map(page_list)
    if set(frames) != {page.page_num for page in extracted.pages}:
        raise ValueError("Extract pages and page frames do not match")
    extract_pages = []
    for page in extracted.pages:
        frame = frames[page.page_num]
        extract_pages.append(
            ExtractPage(
                page_num=frame.page,
                width=frame.width,
                height=frame.height,
                rotation=frame.rotation,
                **{
                    key: value
                    for key, value in _page_to_dict(page).items()
                    if key != "page_num"
                },
            )
        )
    return ExtractArtifact(
        doc_id=doc_id,
        run_id=run_id,
        meta={
            "parser": extracted.parser,
            "title": extracted.title,
            "ocr_stats": extracted.ocr_stats,
        },
        pages=extract_pages,
    )


def _relative_crop_path(
    library_root: str | Path,
    doc_id: str,
    image_path: str | None,
    *,
    staging_dir: str | Path | None = None,
) -> str:
    if not image_path:
        return ""
    # DetectionSource may carry an absolute working path; the artifact stores
    # only the canonical library-relative crop reference.
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


def build_detection_artifact(
    doc_id: str,
    run_id: str,
    results: Sequence[ExtractionResult],
    molecule_stats: dict[str, Any],
    pages: Sequence[PageFrame],
    *,
    library_root: str | Path,
    staging_dir: str | Path | None = None,
) -> DetectionArtifact:
    """Project raw Detection results to a readable branch.

    MolDet boxes are already in the visual page's bottom-left PDF coordinate
    system. They are validated at Join, but never rotated a second time here.
    """
    from .evidence_artifacts import DetectionArtifact

    frames = _frame_map(pages)
    results_by_page: dict[int, list[dict[str, Any]]] = {
        frame.page: [] for frame in pages
    }
    for result in results:
        data = result.to_dict()
        if result.page_idx is None:
            raise ValueError("detection result must contain page_idx")
        frame = frames.get(result.page_idx + 1)
        if frame is None:
            raise ValueError(f"missing page frame for page {result.page_idx + 1}")
        if result.source == "image":
            coref = _relative_crop_path(
                library_root,
                doc_id,
                result.mol_img_path,
                staging_dir=staging_dir,
            )
            if not coref:
                raise ValueError("image detection has no archived molecule crop")
            data["mol_img_path"] = coref
        results_by_page[frame.page].append(data)
    from .evidence_artifacts import DetectionPage

    return DetectionArtifact(
        doc_id=doc_id,
        run_id=run_id,
        meta={
            "molecule_stats": {
                key: value
                for key, value in molecule_stats.items()
                if key not in {"candidates", "results"}
            }
        },
        pages=[
            DetectionPage(
                page_num=frame.page,
                width=frame.width,
                height=frame.height,
                rotation=frame.rotation,
                detections=results_by_page[frame.page],
            )
            for frame in pages
        ],
    )


def save_extract_branch(library_root: str | Path, artifact: ExtractArtifact) -> Path:
    path = _branch_path(library_root, artifact.doc_id, _EXTRACT_FILE)
    _write_json_atomic(path, artifact.model_dump(mode="json"))
    return path


def load_extract_branch(
    library_root: str | Path, doc_id: str, run_id: str
) -> ExtractArtifact | None:
    path = _branch_path(library_root, doc_id, _EXTRACT_FILE)
    data = _read_json(path)
    if data is None:
        return None
    try:
        from .evidence_artifacts import ExtractArtifact

        artifact = ExtractArtifact.model_validate(data)
        if artifact.doc_id != doc_id or artifact.run_id != run_id:
            raise ValueError(f"Extract artifact does not match requested run: {path}")
        return artifact
    except ValueError as exc:
        raise ValueError(f"invalid Extract artifact: {path}") from exc


def save_detection_branch(
    library_root: str | Path, artifact: DetectionArtifact
) -> Path:
    path = _branch_path(library_root, artifact.doc_id, _DETECTION_FILE)
    _write_json_atomic(path, artifact.model_dump(mode="json"))
    return path


def load_detection_branch(
    library_root: str | Path, doc_id: str, run_id: str
) -> DetectionArtifact | None:
    path = _branch_path(library_root, doc_id, _DETECTION_FILE)
    data = _read_json(path)
    if data is None:
        return None
    try:
        from .evidence_artifacts import DetectionArtifact

        artifact = DetectionArtifact.model_validate(data)
        if artifact.doc_id != doc_id or artifact.run_id != run_id:
            raise ValueError(f"Detection artifact does not match requested run: {path}")
        return artifact
    except ValueError as exc:
        raise ValueError(f"invalid Detection artifact: {path}") from exc


def detection_results(artifact: DetectionArtifact) -> list[ExtractionResult]:
    """Decode the raw Detection branch without normalizing it."""
    try:
        return [
            ExtractionResult.from_dict(item)
            for page in artifact.pages
            for item in page.detections
        ]
    except (KeyError, TypeError, ValueError) as exc:
        raise ValueError("invalid raw detection result") from exc


def _extract_frames(artifact: ExtractArtifact) -> list[PageFrame]:
    from .evidence_artifacts import PageFrame

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
    from .evidence_artifacts import PageFrame

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


def _image_coref(doc_id: str, page: PageContent) -> str:
    for image in page.ocr_images:
        name = Path(str(image).replace("\\", "/")).name
        if name:
            return f"storage/{doc_id}/images/{name}"
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
    from .detection.bbox_filter import bbox_area, bbox_iou

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
        for span in page.text_spans:
            bbox = _bbox_in_frame(span.bbox, frame)
            if span.block_type in {0, 2} and span.text.strip():
                add(
                    SourceEvidence.create(
                        doc_id=extracted.doc_id,
                        page=page.page_num,
                        bbox=bbox,
                        raw_text=span.text,
                        kind="table_span" if span.block_type == 2 else "text_span",
                    )
                )
            elif span.block_type == 1:
                add(
                    SourceEvidence.create(
                        doc_id=extracted.doc_id,
                        page=page.page_num,
                        bbox=bbox,
                        coref=_image_coref(extracted.doc_id, page),
                        kind="image_region",
                    )
                )
        image_bboxes = [span.bbox for span in page.text_spans if span.block_type == 1]
        image_bboxes.extend(page.figure_bboxes)
        for raw_bbox in image_bboxes:
            bbox = _bbox_in_frame(raw_bbox, frame)
            add(
                SourceEvidence.create(
                    doc_id=extracted.doc_id,
                    page=page.page_num,
                    bbox=bbox,
                    coref=_image_coref(extracted.doc_id, page),
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
    from .evidence_artifacts import DocumentEvidenceArtifact

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
    from ..services.documents.source_evidence import list_evidence

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


def _extracted_from_evidence(
    raw_artifact: Any, evidence: Sequence[SourceEvidence] | None = None
) -> ExtractedDocument:
    """Rebuild ExtractedDocument metadata from raw branch + SQL facts."""
    text_kinds = {"text_span", "table_span", "ocr_label"}
    if evidence is None:
        evidence = list(getattr(raw_artifact, "evidence", []))
    raw_document = _extracted_from_artifact(raw_artifact)
    raw_pages = {page.page_num: page for page in raw_document.pages}
    frame_pages = _extract_frames(raw_artifact)
    pages: list[PageContent] = []
    for frame in frame_pages:
        page_items = [item for item in evidence if item.page == frame.page]
        text_items = [item for item in page_items if item.kind in text_kinds]
        image_items = [item for item in page_items if item.kind == "image_region"]
        raw_page = raw_pages.get(frame.page)
        pages.append(
            PageContent(
                page_num=frame.page,
                text="\n".join(item.raw_text for item in text_items),
                text_spans=[
                    TextSpan(
                        text=item.raw_text,
                        bbox=item.bbox,
                        block_type=2 if item.kind == "table_span" else 0,
                    )
                    for item in text_items
                ],
                figure_bboxes=[item.bbox for item in image_items],
                ocr_images=[
                    Path(item.coref).name
                    for item in image_items
                    if item.coref and Path(item.coref).suffix.lower() in _IMAGE_SUFFIXES
                ],
                ocr_dpi=raw_page.ocr_dpi if raw_page else 0,
                ocr_backend=raw_page.ocr_backend if raw_page else None,
                ocr_attempts=raw_page.ocr_attempts if raw_page else 0,
                ocr_elapsed_ms=raw_page.ocr_elapsed_ms if raw_page else 0,
                ocr_error=raw_page.ocr_error if raw_page else None,
            )
        )
    meta = getattr(raw_artifact, "meta", {})
    parser = str(meta.get("parser", "pymupdf"))
    title = meta.get("title")
    return ExtractedDocument(
        raw_text="\n\n".join(page.text for page in pages if page.text),
        page_count=len(pages),
        parser=parser,
        title=title,
        pages=pages,
        ocr_stats=dict(meta.get("ocr_stats", {})),
    )


def _candidates_from_evidence(
    results: Sequence[ExtractionResult],
    evidence: Sequence[SourceEvidence],
) -> list[NormalizedMolecule]:
    from .detection.correction import correct_molecules_with_context
    from .detection.normalization import normalize_molecules

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
    candidates: Sequence[NormalizedMolecule], base: dict[str, Any] | None = None
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


def _page_to_dict(page: PageContent) -> dict[str, Any]:
    return {
        "page_num": page.page_num,
        "text": page.text,
        "ocr_dpi": page.ocr_dpi,
        "text_spans": [
            {"text": s.text, "bbox": list(s.bbox), "block_type": s.block_type}
            for s in page.text_spans
        ],
        "figure_bboxes": [list(bbox) for bbox in page.figure_bboxes],
        "ocr_backend": page.ocr_backend,
        "ocr_attempts": page.ocr_attempts,
        "ocr_elapsed_ms": page.ocr_elapsed_ms,
        "ocr_error": page.ocr_error,
        "ocr_images": list(page.ocr_images),
    }


def _page_from_dict(data: dict[str, Any]) -> PageContent:
    return PageContent(
        page_num=int(data["page_num"]),
        text=str(data.get("text", "")),
        ocr_dpi=int(data.get("ocr_dpi", 0)),
        text_spans=[
            TextSpan(
                text=str(s.get("text", "")),
                bbox=tuple(float(v) for v in s.get("bbox", [])),
                block_type=int(s.get("block_type", 0)),
            )
            for s in data.get("text_spans", [])
            if isinstance(s, dict)
        ],
        figure_bboxes=[
            tuple(float(v) for v in bbox) for bbox in data.get("figure_bboxes", [])
        ],
        ocr_backend=data.get("ocr_backend"),
        ocr_attempts=int(data.get("ocr_attempts", 0)),
        ocr_elapsed_ms=int(data.get("ocr_elapsed_ms", 0)),
        ocr_error=data.get("ocr_error"),
        ocr_images=[str(name) for name in data.get("ocr_images", [])],
    )


def _extracted_from_artifact(artifact: ExtractArtifact) -> ExtractedDocument:
    meta = artifact.meta
    pages = [_page_from_dict(page.model_dump(mode="json")) for page in artifact.pages]
    return ExtractedDocument(
        raw_text="\n\n".join(page.text for page in pages if page.text),
        page_count=len(pages),
        parser=str(meta.get("parser", "pymupdf")),
        title=meta.get("title"),
        pages=pages,
        ocr_stats=dict(meta.get("ocr_stats", {})),
    )


def load_extracted(
    library_root: str | Path, doc_id: str, run_id: str | None = None
) -> ExtractedDocument | None:
    """Restore text metadata from the raw branch and bbox/text from SQL."""
    effective_run_id = run_id or _latest_branch_run_id(
        library_root, doc_id, _EXTRACT_FILE
    )
    if effective_run_id is not None:
        branch = load_extract_branch(library_root, doc_id, effective_run_id)
        if branch is not None:
            evidence = load_document_evidence(library_root, doc_id)
            return _extracted_from_evidence(branch, evidence)
    return None


def _latest_branch_run_id(
    library_root: str | Path, doc_id: str, filename: str
) -> str | None:
    """Read the run ID embedded in the fixed branch file."""
    path = _branch_path(library_root, doc_id, filename)
    data = _read_json(path)
    if data is None:
        return None
    run_id = data.get("run_id")
    return run_id if isinstance(run_id, str) and run_id else None


def load_detections(
    library_root: str | Path, doc_id: str, run_id: str | None = None
) -> tuple[list[NormalizedMolecule], dict[str, Any]] | None:
    """Restore normalized candidates from raw results plus SQL evidence."""
    effective_run_id = run_id or _latest_branch_run_id(
        library_root, doc_id, _DETECTION_FILE
    )
    if effective_run_id is not None:
        branch = load_detection_branch(library_root, doc_id, effective_run_id)
        if branch is not None:
            evidence = load_document_evidence(library_root, doc_id)
            results = detection_results(branch)
            candidates = _candidates_from_evidence(results, evidence)
            return candidates, summarize_molecules(
                candidates, dict(branch.meta.get("molecule_stats", {}))
            )
    return None


# --- context hydration -------------------------------------------------------


def hydrate_context_from_artifacts(ctx: PipelineContext) -> None:
    """Fill missing PipelineContext fields from stage artifacts (idempotent).

    ``rough_md_path`` is intentionally not hydrated: it is a staging temp
    file that stages regenerate when absent.
    """
    layout = LibraryLayout(ctx.library_root)
    if ctx.run_id:
        # Each worker claim mints its own run ID, so a later stage must
        # resolve the extract/detection branches through the checkpoint's
        # per-stage records instead of assuming they share ctx.run_id.
        from .stage_checkpoint import latest_stage_run_id

        evidence = load_document_evidence(ctx.library_root, ctx.doc_id)
        ctx.document_evidence = evidence
        extract_run_id = latest_stage_run_id(ctx.staging_dir, "extract") or ctx.run_id
        extract_branch = load_extract_branch(
            ctx.library_root, ctx.doc_id, extract_run_id
        )
        if ctx.extracted is None and extract_branch is not None:
            ctx.extracted = _extracted_from_evidence(extract_branch, evidence)
        if not ctx.candidates:
            detection_run_id = (
                latest_stage_run_id(ctx.staging_dir, "detection") or ctx.run_id
            )
            detection_branch = load_detection_branch(
                ctx.library_root, ctx.doc_id, detection_run_id
            )
            if detection_branch is not None:
                candidates = _candidates_from_evidence(
                    detection_results(detection_branch), evidence
                )
                ctx.candidates = candidates
                ctx.molecule_stats = summarize_molecules(
                    candidates, dict(detection_branch.meta.get("molecule_stats", {}))
                )

    if ctx.document_md_path is None:
        candidate = layout.document_md(ctx.doc_id)
        if candidate.exists():
            ctx.document_md_path = candidate
    logger.debug(
        "Context hydration for %s: extracted=%s candidates=%d md=%s",
        ctx.doc_id,
        ctx.extracted is not None,
        len(ctx.candidates),
        ctx.document_md_path,
    )
