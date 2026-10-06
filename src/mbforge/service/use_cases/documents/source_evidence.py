"""Queries for the canonical document source-evidence table.

The persistence layer owns the SQL; this module validates inputs and returns
domain objects, reaching the database only through the ``EvidenceRepository``
port.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from pathlib import Path

from mbforge.domain.evidence import SourceEvidence, _normalise_bbox
from mbforge.domain.paragraphs import group_paragraphs, paragraph_anchors
from mbforge.foundation.errors import NotFoundError, ValidationError
from mbforge.service.ports import get_repositories
from mbforge.service.use_cases.documents.backup import create_backup


@dataclass(frozen=True)
class AnnotatedEvidence:
    """One evidence row plus the paragraph and line it belongs to.

    ``paragraph_id`` is empty for a row that is not part of any paragraph
    (tables, figures, molecules); ``paragraph_number`` is the patent's own
    ``[0001]`` marker for a numbered paragraph and ``None`` otherwise.
    ``paragraph_line`` indexes the line inside the paragraph and
    ``indent_level`` is its left-edge depth (0 = body margin, as the layout
    encoded it).
    """

    evidence: SourceEvidence
    paragraph_id: str = ""
    paragraph_number: str | None = None
    paragraph_start: bool = False
    paragraph_line: int = 0
    indent_level: int = 0


def resolve(library_root: str | Path, evidence_id: str) -> SourceEvidence | None:
    """Resolve one canonical evidence ID to its immutable source object."""
    if not evidence_id:
        return None
    return get_repositories(str(library_root)).evidence.get(evidence_id)


def _require_page(page: int | None) -> None:
    if page is not None and (
        not isinstance(page, int) or isinstance(page, bool) or page < 1
    ):
        raise ValueError("page must be a positive 1-based integer")


def list_evidence(
    library_root: str | Path,
    doc_id: str,
    page: int | None = None,
    kind: str | None = None,
) -> list[SourceEvidence]:
    """Load one document's source evidence.

    ``page`` and ``kind`` are optional filters for page/layout readers; the
    returned objects always come from SQLite rather than the JSON snapshot.
    """
    if not doc_id:
        return []
    _require_page(page)
    return get_repositories(str(library_root)).evidence.list(
        doc_id, page=page, kind=kind
    )


def list_page_evidence_with_paragraphs(
    library_root: str | Path,
    doc_id: str,
    page: int,
) -> list[AnnotatedEvidence]:
    """Load one page's evidence, each row tagged with its patent paragraph.

    Paragraphs are grouped over the **whole** document, because a paragraph
    that starts on this page may continue on the next one; only rows on
    ``page`` are returned.
    """
    if not doc_id:
        return []
    _require_page(page)
    rows = list_evidence(library_root, doc_id)
    anchors = paragraph_anchors(group_paragraphs(rows))
    annotated: list[AnnotatedEvidence] = []
    for item in rows:
        if item.page != page:
            continue
        anchor = anchors.get(item.evidence_id)
        annotated.append(
            AnnotatedEvidence(
                evidence=item,
                paragraph_id=anchor.paragraph_id if anchor else "",
                paragraph_number=anchor.number if anchor else None,
                paragraph_start=anchor.start if anchor else False,
                paragraph_line=anchor.line if anchor else 0,
                indent_level=anchor.level if anchor else 0,
            )
        )
    return annotated


def at(
    library_root: str | Path,
    doc_id: str,
    page: int,
    bbox: tuple[float, float, float, float] | list[float],
) -> list[SourceEvidence]:
    """Return all source evidence whose bbox intersects ``bbox``."""
    if not doc_id:
        return []
    if not isinstance(page, int) or isinstance(page, bool) or page < 1:
        raise ValueError("page must be a positive 1-based integer")
    normalised = _normalise_bbox(bbox)
    return get_repositories(str(library_root)).evidence.at(doc_id, page, normalised)


def _normalise_text(value: str) -> str:
    return re.sub(r"\s+", " ", value).strip()


def find_text(
    library_root: str | Path, doc_id: str, query: str
) -> list[SourceEvidence]:
    """Return source evidence containing ``query`` after whitespace folding."""
    needle = _normalise_text(query)
    if not doc_id or not needle:
        return []
    return [
        evidence
        for evidence in list_evidence(library_root, doc_id)
        if needle in _normalise_text(evidence.raw_text)
    ]


def update_molecule(
    library_root: str | Path,
    doc_id: str,
    evidence_id: str,
    name: str,
    smiles: str,
) -> str:
    """Update editable molecule metadata while preserving the evidence ID."""
    name = name.strip()
    smiles = smiles.strip()
    if not doc_id or not evidence_id:
        raise ValidationError("doc_id and evidence_id are required")
    if not smiles:
        raise ValidationError("smiles is required")

    repository = get_repositories(str(library_root)).evidence
    row = repository.molecule_metadata(evidence_id, doc_id)
    if row is None:
        raise NotFoundError("source evidence not found", detail=evidence_id)
    kind, raw_text = row
    if kind != "molecule":
        raise ValidationError("source evidence is not a molecule")

    try:
        metadata = json.loads(raw_text or "")
    except json.JSONDecodeError:
        metadata = {}
    if not isinstance(metadata, dict):
        metadata = {"raw_text": raw_text or ""}
    metadata["name"] = name
    metadata["smiles"] = smiles
    metadata["esmiles"] = smiles
    metadata["moldet_conf"] = 1.0

    create_backup(library_root, doc_id, "evidence_update")
    updated = repository.update_molecule_raw_text(
        evidence_id, doc_id, json.dumps(metadata, ensure_ascii=False, sort_keys=True)
    )
    if updated != 1:
        raise NotFoundError("source evidence not found", detail=evidence_id)
    return evidence_id


__all__ = [
    "AnnotatedEvidence",
    "at",
    "find_text",
    "list_evidence",
    "list_page_evidence_with_paragraphs",
    "resolve",
    "update_molecule",
]
