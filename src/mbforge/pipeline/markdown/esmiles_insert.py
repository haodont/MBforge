"""Assemble Markdown from joined source evidence."""

from __future__ import annotations

import re
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path

from mbforge.core.evidence import SourceEvidence
from mbforge.core.molecule import Molecule
from mbforge.pipeline.detection.formula_normalization import normalize_patent_formulas
from mbforge.utils.logger import get_logger

logger = get_logger(__name__)

_HEADING_PATTERNS = re.compile(
    r"^(Abstract|Introduction|Background|Methods|Materials and Methods|"
    r"Results|Discussion|Conclusion|References|Acknowledgments|"
    r"Supporting Information|Supplementary|Appendix|"
    r"\d+\.\s+|FIGURES?|TABLES?)$",
    re.IGNORECASE,
)
_TEXT_KINDS = {"text_span", "table_span", "ocr_label"}
_KIND_RANK = {
    "text_span": 0,
    "table_span": 1,
    "ocr_label": 2,
    "image_region": 3,
    "molecule": 4,
}
_IMAGE_SUFFIXES = {".gif", ".jpeg", ".jpg", ".png", ".svg", ".webp"}


@dataclass(frozen=True)
class _RenderedBlock:
    text: str
    evidence_ids: tuple[str, ...] = ()


@dataclass(frozen=True)
class _PlacedBlock:
    key: tuple[object, ...]
    block: _RenderedBlock


def _reading_key(
    item: SourceEvidence, *, tie_breaker: str | None = None
) -> tuple[object, ...]:
    x0, y0, x1, y1 = item.bbox
    return (
        item.page,
        -y1,
        x0,
        -y0,
        x1,
        _KIND_RANK[item.kind],
        tie_breaker or item.evidence_id,
    )


def _render_text(raw_text: str) -> str:
    lines: list[str] = []
    for paragraph in normalize_patent_formulas(raw_text).splitlines():
        stripped = paragraph.strip()
        if not stripped:
            continue
        if _HEADING_PATTERNS.match(stripped.split(".")[0].strip()):
            lines.append(f"## {stripped}")
        else:
            lines.append(stripped)
    return "\n".join(lines)


def _render_image(item: SourceEvidence, doc_id: str) -> str:
    coref = item.coref.strip()
    suffix = Path(coref).suffix.lower()
    prefix = f"storage/{doc_id}/"
    if coref.startswith(prefix) and suffix in _IMAGE_SUFFIXES:
        return f"![Source image]({coref[len(prefix) :]})"
    return f"<!-- image evidence={item.evidence_id} -->"


def _candidate_blocks(
    evidence: Sequence[SourceEvidence],
    candidates: Sequence[Molecule],
) -> list[_PlacedBlock]:
    evidence_by_id = {item.evidence_id: item for item in evidence}
    placed: list[_PlacedBlock] = []
    for candidate in candidates:
        if candidate.status == "rejected" or not candidate.esmiles.strip():
            continue
        detections = getattr(candidate, "detections", None)
        detection_ids = (
            [detection.evidence_id for detection in detections]
            if detections is not None
            else list(getattr(candidate, "evidence_ids", []))
        )
        molecule_evidence = [
            evidence_by_id[evidence_id]
            for evidence_id in detection_ids
            if evidence_id in evidence_by_id
            and evidence_by_id[evidence_id].kind == "molecule"
        ]
        if not molecule_evidence:
            continue
        primary = min(molecule_evidence, key=_reading_key)
        properties = getattr(candidate, "properties", {})
        raw_labels = (
            properties.get("refs", properties.get("ocr_labels", []))
            if isinstance(properties, dict)
            else []
        )
        if not raw_labels:
            raw_labels = getattr(candidate, "refs", [])
        labels = raw_labels if isinstance(raw_labels, list) else [raw_labels]
        labels = [label for label in labels if isinstance(label, str) and label.strip()]
        candidate_id = getattr(candidate, "candidate_id", None)
        if not candidate_id and isinstance(properties, dict):
            candidate_id = properties.get("candidate_id")
        candidate_header = f"%% candidate={candidate_id}\n" if candidate_id else ""
        label_headers = "".join(f"%% label={label}\n" for label in labels)
        block = _RenderedBlock(
            text=(
                "```esmiles\n"
                f"%% page={primary.page}\n"
                f"%% evidence={primary.evidence_id}\n"
                f"{candidate_header}"
                f"{label_headers}"
                f"{candidate.esmiles.strip()}\n"
                "```\n\n"
            ),
            evidence_ids=tuple(
                sorted({evidence_id for evidence_id in detection_ids if evidence_id})
            ),
        )
        placed.append(
            _PlacedBlock(
                key=_reading_key(primary, tie_breaker=primary.evidence_id),
                block=block,
            )
        )
    return placed


def _page_blocks(
    evidence: Sequence[SourceEvidence],
    doc_id: str,
    page: int,
    candidate_blocks: list[_PlacedBlock],
) -> list[_RenderedBlock]:
    page_evidence = [item for item in evidence if item.page == page]
    text_items = [item for item in page_evidence if item.kind in _TEXT_KINDS]
    slots: dict[int, list[_PlacedBlock]] = {}

    for item in page_evidence:
        if item.kind != "image_region":
            continue
        placed = _PlacedBlock(
            key=_reading_key(item),
            block=_RenderedBlock(
                text=f"{_render_image(item, doc_id)}\n\n",
                evidence_ids=(item.evidence_id,),
            ),
        )
        slot = sum(_reading_key(text_item) < placed.key for text_item in text_items)
        slots.setdefault(slot, []).append(placed)

    for placed in candidate_blocks:
        if placed.key[0] != page:
            continue
        slot = sum(_reading_key(text_item) < placed.key for text_item in text_items)
        slots.setdefault(slot, []).append(placed)

    result: list[_RenderedBlock] = [_RenderedBlock(f"<!-- PAGE {page} -->\n")]
    for slot in range(len(text_items) + 1):
        result.extend(
            item.block
            for item in sorted(slots.get(slot, []), key=lambda value: value.key)
        )
        if slot < len(text_items):
            text_item = text_items[slot]
            rendered = _render_text(text_item.raw_text)
            if rendered:
                result.append(
                    _RenderedBlock(
                        text=f"{rendered}\n\n",
                        evidence_ids=(text_item.evidence_id,),
                    )
                )
    return result


def _assemble_blocks(
    evidence: Sequence[SourceEvidence],
    candidates: Sequence[Molecule],
    pages: Sequence[int],
    doc_id: str,
    title: str,
) -> list[_RenderedBlock]:
    candidate_blocks = _candidate_blocks(evidence, candidates)
    blocks: list[_RenderedBlock] = []
    for page in sorted(pages):
        blocks.extend(_page_blocks(evidence, doc_id, page, candidate_blocks))
    body = "".join(block.text for block in blocks)
    if not re.search(r"^#{1,6}\s", body, re.MULTILINE):
        blocks.insert(0, _RenderedBlock(f"# {title}\n\n"))
    return blocks


def insert_esmiles_blocks(
    evidence_or_artifact: Sequence[SourceEvidence] | object,
    output_path: str,
    *,
    candidates: Sequence[Molecule] | None = None,
    pages: Sequence[object] | None = None,
    doc_id: str | None = None,
    title: str | None = None,
) -> str:
    """Write final Markdown assembled from source evidence."""
    if hasattr(evidence_or_artifact, "evidence"):
        artifact = evidence_or_artifact
        evidence = list(getattr(artifact, "evidence", []))
        candidates = list(getattr(artifact, "candidates", []))
        doc_id = doc_id or str(getattr(artifact, "doc_id", ""))
        pages = list(getattr(artifact, "pages", []))
    else:
        evidence = list(evidence_or_artifact)  # type: ignore[arg-type]
    page_numbers = [
        int(
            getattr(
                page,
                "page",
                getattr(page, "page_num", page),
            )
        )
        for page in (pages or sorted({item.page for item in evidence}))
    ]
    actual_doc_id = doc_id or (evidence[0].doc_id if evidence else "document")
    blocks = _assemble_blocks(
        evidence,
        list(candidates or []),
        page_numbers,
        actual_doc_id,
        title or actual_doc_id,
    )
    parts: list[str] = []
    for block in blocks:
        parts.append(block.text)

    content = "".join(parts)
    output = Path(output_path)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(content, encoding="utf-8")
    logger.info("Markdown written to %s", output)
    return str(output)
