"""Small test helpers for publishing the current v2 artifact contract."""

from __future__ import annotations

from dataclasses import replace
from pathlib import Path
from typing import Any

from mbforge.adapters.persistence.source_evidence import persist_source_evidence
from mbforge.application.pipeline.artifacts import (
    build_detection_artifact,
    build_extract_artifact,
    join_evidence_artifacts,
    save_detection_branch,
    save_extract_branch,
)
from mbforge.application.pipeline.artifacts.evidence_models import PageFrame
from mbforge.application.pipeline.extract.text import ExtractedDocument, PageContent
from mbforge.domain.molecule import Molecule
from mbforge.domain.types import ExtractionResult


def publish_v2_run(
    library_root: str | Path,
    doc_id: str,
    run_id: str,
    extracted: ExtractedDocument,
    candidates: list[Molecule],
    molecule_stats: dict[str, Any] | None = None,
    *,
    width: float = 1000.0,
    height: float = 1000.0,
) -> list[PageFrame]:
    results: list[ExtractionResult] = []
    page_numbers = {page.page_num for page in extracted.pages}
    for candidate in candidates:
        detections = [
            detection
            for detection in candidate.detections
            if detection.page is not None and detection.bbox is not None
        ]
        if not detections:
            continue
        page_numbers.update(detection.page + 1 for detection in detections)
        for detection in detections:
            if detection.image_path:
                crop = (
                    Path(library_root)
                    / "storage"
                    / doc_id
                    / "crops"
                    / Path(detection.image_path).name
                )
                crop.parent.mkdir(parents=True, exist_ok=True)
                crop.write_bytes(b"png")
        for detection in detections:
            results.append(
                ExtractionResult(
                    esmiles=candidate.esmiles,
                    smiles=candidate.canonical_smiles,
                    name=candidate.name,
                    source=(candidate.sources[0] if candidate.sources else "image"),
                    moldet_conf=detection.conf_moldet,
                    bbox_pdf=detection.bbox,
                    page_idx=detection.page,
                    mol_img_path=(
                        Path(detection.image_path) if detection.image_path else None
                    ),
                    status=candidate.status,
                    properties=dict(candidate.properties),
                )
            )

    if not page_numbers:
        page_numbers = {1}
    missing_pages = sorted(page_numbers - {page.page_num for page in extracted.pages})
    if missing_pages:
        extracted = replace(
            extracted,
            pages=[
                *extracted.pages,
                *(PageContent(page_num=page, text="") for page in missing_pages),
            ],
            page_count=max(extracted.page_count, max(page_numbers)),
        )
    frames = [
        PageFrame(page=page, width=width, height=height)
        for page in sorted(page_numbers)
    ]
    extract = build_extract_artifact(doc_id, run_id, extracted, frames)
    detection = build_detection_artifact(
        doc_id,
        run_id,
        results,
        molecule_stats or {},
        frames,
        library_root=library_root,
    )
    save_extract_branch(library_root, extract)
    save_detection_branch(library_root, detection)
    joined = join_evidence_artifacts(extract, detection)
    persist_source_evidence(library_root, joined)
    return frames
