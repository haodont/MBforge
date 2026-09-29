"""Small test helpers for publishing the current SQL source-evidence contract.

A run's only artifact is the ``source_evidence`` table: tests mint it with the
real :func:`mint_evidence` and persist it with ``persist_source_evidence`` so the
readers under test see exactly what Extract would write.
"""

from __future__ import annotations

from dataclasses import replace
from pathlib import Path
from typing import Any

from mbforge.db.source_evidence import persist_source_evidence
from mbforge.domain.molecule import Molecule
from mbforge.domain.types import ExtractionResult
from mbforge.service.pipeline.artifacts import mint_evidence
from mbforge.service.pipeline.artifacts.evidence_models import PageFrame
from mbforge.service.pipeline.extract.text import ExtractedDocument, PageContent

#: ``block_type`` → the layout label the evidence mint registers for it.
_BLOCK_KIND = {0: "text", 1: "figcx", 2: "tab"}
_BLOCK_REGION_TYPE = {0: "text", 1: "image", 2: "table"}


def _synthesize_regions(extracted: ExtractedDocument) -> None:
    """Give a page typed regions when it only carries the legacy span views.

    The layout producer derives ``text_spans``/``figure_bboxes`` from its typed
    regions; tests that hand-build the legacy views get regions synthesized here
    so ``mint_evidence`` — which reads the regions — sees the same layout.
    """
    for page in extracted.pages:
        if page.regions:
            continue
        regions: list[dict[str, Any]] = []
        for order, span in enumerate(page.text_spans):
            regions.append(
                {
                    "region_id": f"r{order}",
                    "kind": _BLOCK_KIND.get(span.block_type, "text"),
                    "type": _BLOCK_REGION_TYPE.get(span.block_type, "text"),
                    "bbox": list(span.bbox),
                    "reading_order": order,
                    "text": span.text,
                }
            )
        for offset, bbox in enumerate(page.figure_bboxes):
            regions.append(
                {
                    "region_id": f"f{offset}",
                    "kind": "figcx",
                    "type": "image",
                    "bbox": list(bbox),
                    "reading_order": len(page.text_spans) + offset,
                    "text": "",
                }
            )
        page.regions = regions


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
                    smiles=candidate.canonical_smiles,
                    esmiles=candidate.esmiles,
                    name=candidate.name,
                    moldet_conf=detection.conf_moldet,
                    bbox_pdf=detection.bbox,
                    page_idx=detection.page,
                    mol_img_path=detection.image_path,
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
    _synthesize_regions(extracted)
    frames = [
        PageFrame(page=page, width=width, height=height)
        for page in sorted(page_numbers)
    ]
    evidence = mint_evidence(
        extracted, frames, results, doc_id=doc_id, library_root=library_root
    )
    persist_source_evidence(library_root, evidence)
    return frames


__all__ = ["publish_v2_run"]
