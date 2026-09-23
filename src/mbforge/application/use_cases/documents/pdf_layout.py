"""Document overlay payloads for the PDF viewer.

Both overlays come from a single SQL read of the ``source_evidence`` index —
the only runtime evidence store — so the endpoint never reloads an Extract or
Detection branch and never re-normalizes a candidate. The row's **category**
decides which overlay consumes it:

- text category → ``text`` blocks
- table category → ``table`` blocks
- image category → ``image`` blocks
- ``molecule`` → molecule-overlay entries, grouped by page

The row ``kind`` is the **producer's own label** (a layout class name such as
``chem`` or ``mnote``, or ``molecule``).  ``evidence_kind.category_of`` maps it to
the category above, so a new detector's vocabulary needs teaching in one place.

Coordinate contract: Extract evidence is converted to **bottom-left origin
points** (y grows upward) before the Join writes SQLite, and the molecule-
detection chain already uses that convention. The frontend ``pdfToCss``
converter assumes bottom-left, so layout and molecule boxes are served
without another y-axis conversion.

The frontend filters blocks and candidates by the current 1-based page and
scales the PDF-point bboxes to CSS pixels itself.
"""

from __future__ import annotations

import json
from contextlib import suppress
from typing import Any

from mbforge.application.pipeline.artifacts.hydration import (
    load_detections,
    load_extracted,
    register_branch_kind_vocab,
)
from mbforge.application.pipeline.extract.text import ExtractedDocument
from mbforge.application.use_cases.documents.source_evidence import list_evidence
from mbforge.domain.evidence import SourceEvidence
from mbforge.domain.evidence_kind import (
    IMAGE,
    MOLECULE,
    TABLE,
    TEXT_CATEGORIES,
    category_of,
)
from mbforge.domain.molecule import Molecule


def load_document_bboxes(
    library_root: str, doc_id: str
) -> tuple[ExtractedDocument | None, list[Molecule] | None]:
    """Artifact-side reader for the molecule reverse lookup (a click on a box).

    Unlike the overlay readers below this one restores the Detection branch;
    it backs :func:`mbforge.application.use_cases.molecule.queries.molecules_by_location`.
    """
    restored = load_detections(library_root, doc_id)
    candidates = restored[0] if restored is not None else None
    return load_extracted(library_root, doc_id), candidates


def build_document_overlay(library_root: str, doc_id: str, path: str) -> dict[str, Any]:
    """Both page overlays of one document, from one ``source_evidence`` read.

    A single pass over the evidence rows fills both payloads — the row's
    category decides the consumer — so opening a document costs one indexed
    SELECT. ``pages`` is keyed by 1-based visual page (as JSON strings);
    ``source`` reports whether the molecule side had any row.

    One branch ``meta`` read comes first: a producer names its regions freely and
    SQL stores only that label, so the declared ``kind_vocab`` must be registered
    before labels can be mapped to categories.  Both branches can contribute rows,
    so both vocabularies are registered. It is cached per document.
    """
    register_branch_kind_vocab(library_root, doc_id)
    text_by_page: dict[int, list[dict[str, Any]]] = {}
    image_by_page: dict[int, list[dict[str, Any]]] = {}
    pages: dict[str, list[dict[str, Any]]] = {}
    count = 0
    for item in list_evidence(library_root, doc_id):
        category = category_of(item.kind)
        if category == MOLECULE:
            pages.setdefault(str(item.page), []).append(_molecule_entry(item))
            count += 1
        elif category == IMAGE:
            image_by_page.setdefault(item.page, []).append(_block(item, "image", None))
        elif category in TEXT_CATEGORIES:
            text_by_page.setdefault(item.page, []).append(
                _block(
                    item,
                    "table" if category == TABLE else "text",
                    (item.raw_text or "").strip() or None,
                )
            )

    # Text/table blocks lead their page, then its figure regions; ``index`` is
    # the viewer's selection key, so it is stamped once the order is final.
    blocks: list[dict[str, Any]] = []
    for page in sorted({*text_by_page, *image_by_page}):
        for entry in (*text_by_page.get(page, ()), *image_by_page.get(page, ())):
            entry["index"] = len(blocks)
            blocks.append(entry)

    return {
        "success": True,
        "path": path,
        "from_cache": True,
        "blocks": blocks,
        "pages": pages,
        "count": count,
        "source": "source_evidence" if count else "empty",
    }


def _block(
    item: SourceEvidence, block_type: str, content: str | None
) -> dict[str, Any]:
    """One evidence row → one layout block (``index`` is stamped after ordering)."""
    return {
        "evidence_id": item.evidence_id,
        "page": item.page,
        "block_type": block_type,
        "kind": item.kind,
        "bbox": item.bbox,
        "content": content,
        "index": 0,
        "angle": 0.0,
    }


def _molecule_entry(item: SourceEvidence) -> dict[str, Any]:
    """One molecule row → one overlay entry.

    Molecule metadata is stored as JSON in ``raw_text`` because the canonical
    SQL evidence row is the only runtime source for the overlay.
    """
    x0, y0, x1, y1 = item.bbox
    page_idx = item.page - 1
    crop = item.coref or None
    metadata: dict[str, Any] = {}
    with suppress(json.JSONDecodeError, TypeError):
        decoded = json.loads(item.raw_text or "")
        if isinstance(decoded, dict):
            metadata = decoded

    confidence = metadata.get("moldet_conf", 0.0)
    try:
        confidence = float(confidence or 0.0)
    except (TypeError, ValueError):
        confidence = 0.0
    return {
        "evidence_id": item.evidence_id,
        "esmiles": str(metadata.get("esmiles", "") or ""),
        "smiles": str(metadata.get("smiles", "") or ""),
        "name": str(metadata.get("name", "") or ""),
        "source": "image" if crop else "text",
        "moldet_conf": confidence,
        "bbox_pdf": [x0, y0, x1, y1],
        "page_idx": page_idx,
        "context_text": "" if crop else item.raw_text,
        "mol_img_path": crop,
        "status": "pending",
        "properties": {},
        "mol_id": None,
        "doc_id": item.doc_id,
        "page": page_idx,
        "bbox_x0": x0,
        "bbox_y0": y0,
        "bbox_x1": x1,
        "bbox_y1": y1,
        "crop_relpath": crop,
        "conf_moldet": confidence,
    }
