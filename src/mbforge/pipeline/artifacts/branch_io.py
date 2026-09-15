"""Raw Extract and Detection branch artifact I/O."""

from __future__ import annotations

from collections.abc import Iterable, Sequence
from pathlib import Path
from typing import Any

from mbforge.core.types import ExtractionResult
from mbforge.pipeline.artifacts.evidence_models import (
    DetectionArtifact,
    ExtractArtifact,
    PageFrame,
)
from mbforge.pipeline.artifacts.json_io import read_json_object, write_json_atomic
from mbforge.pipeline.extract.text import ExtractedDocument, PageContent, TextSpan
from mbforge.storage.layout import LibraryLayout

_EXTRACT_FILE = "extract.json"
_DETECTION_FILE = "detection.json"
_STAGE_DIR = ".staging"


def artifact_path(library_root: str | Path, doc_id: str, name: str) -> Path:
    return LibraryLayout(library_root).storage_dir(doc_id) / name


def branch_path(library_root: str | Path, doc_id: str, filename: str) -> Path:
    return artifact_path(library_root, doc_id, _STAGE_DIR) / filename


def page_frames_from_pdf(pdf_path: str | Path) -> list[PageFrame]:
    """Read visual page frames once at a producer boundary."""
    import pymupdf

    from .evidence_models import PageFrame

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
    from .evidence_models import ExtractArtifact, ExtractPage

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
    from .evidence_models import DetectionArtifact

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
    from .evidence_models import DetectionPage

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
    path = branch_path(library_root, artifact.doc_id, _EXTRACT_FILE)
    write_json_atomic(path, artifact.model_dump(mode="json"))
    return path


def load_extract_branch(
    library_root: str | Path, doc_id: str, run_id: str
) -> ExtractArtifact | None:
    path = branch_path(library_root, doc_id, _EXTRACT_FILE)
    data = read_json_object(path)
    if data is None:
        return None
    try:
        from .evidence_models import ExtractArtifact

        artifact = ExtractArtifact.model_validate(data)
        if artifact.doc_id != doc_id or artifact.run_id != run_id:
            raise ValueError(f"Extract artifact does not match requested run: {path}")
        return artifact
    except ValueError as exc:
        raise ValueError(f"invalid Extract artifact: {path}") from exc


def save_detection_branch(
    library_root: str | Path, artifact: DetectionArtifact
) -> Path:
    path = branch_path(library_root, artifact.doc_id, _DETECTION_FILE)
    write_json_atomic(path, artifact.model_dump(mode="json"))
    return path


def load_detection_branch(
    library_root: str | Path, doc_id: str, run_id: str
) -> DetectionArtifact | None:
    path = branch_path(library_root, doc_id, _DETECTION_FILE)
    data = read_json_object(path)
    if data is None:
        return None
    try:
        from .evidence_models import DetectionArtifact

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


__all__ = [
    "build_detection_artifact",
    "build_extract_artifact",
    "branch_path",
    "detection_results",
    "load_detection_branch",
    "load_extract_branch",
    "page_frames_from_pdf",
    "save_detection_branch",
    "save_extract_branch",
]
