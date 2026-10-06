"""Assemble Markdown from the SQL source evidence."""

from __future__ import annotations

import re
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path

from mbforge.domain.evidence import SourceEvidence
from mbforge.domain.evidence_kind import IMAGE, category_of, is_text
from mbforge.domain.molecule import Molecule
from mbforge.domain.paragraphs import (
    EvidenceParagraph,
    group_paragraphs,
    paragraph_index,
    reading_key,
)
from mbforge.foundation.logger import get_logger
from mbforge.service.pipeline.detection.formula_normalization import (
    normalize_patent_formulas,
)

logger = get_logger(__name__)

_HEADING_PATTERNS = re.compile(
    r"^(Abstract|Introduction|Background|Methods|Materials and Methods|"
    r"Results|Discussion|Conclusion|References|Acknowledgments|"
    r"Supporting Information|Supplementary|Appendix|"
    r"\d+\.\s+|FIGURES?|TABLES?)$",
    re.IGNORECASE,
)


@dataclass(frozen=True)
class _RenderedBlock:
    text: str
    evidence_ids: tuple[str, ...] = ()


@dataclass(frozen=True)
class _PlacedBlock:
    key: tuple[object, ...]
    block: _RenderedBlock


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


def _render_paragraph(paragraph: EvidenceParagraph) -> str:
    """Render one patent paragraph, keeping its own indentation.

    The layout split the paragraph into fragments and gave each one a left
    edge; joining same-level fragments back into a line and expressing the
    deeper levels as nested list items is what re-reads as the document's own
    paragraph, marker included.
    """
    lines = [
        normalize_patent_formulas(line.text).strip()
        for line in paragraph.lines
        if line.text.strip()
    ]
    if not lines:
        return ""
    head = lines[0]
    head_level = paragraph.lines[0].level
    if _is_heading(head, paragraph):
        rendered = [f"## {head}"]
    elif head_level >= 1:
        rendered = [f"{'  ' * (head_level - 1)}- {head}"]
    else:
        rendered = [head]
    body = paragraph.lines[1:]
    if not body:
        return "\n".join(rendered)
    # A blank line keeps the list from being read as a lazy continuation of the
    # paragraph above it.
    rendered.append("")
    for line in body:
        text = normalize_patent_formulas(line.text).strip()
        if not text:
            continue
        rendered.append(f"{'  ' * max(0, line.level - 1)}- {text}")
    return "\n".join(rendered)


def _is_heading(text: str, paragraph: EvidenceParagraph) -> bool:
    """Whether a paragraph's first line reads as a section heading.

    Only the geometric signal (the block sits on the column centre) and the
    curated section-name list qualify.  ``is_heading_like`` is deliberately not
    consulted: it exists to decide that a short all-caps block starts on its
    own, which is also true of a figure label like ``A-2``.
    """
    if paragraph.centred:
        return True
    return bool(_HEADING_PATTERNS.match(text.split(".")[0].strip()))


def _render_image(item: SourceEvidence) -> str:
    """Render a figure region as a marker.

    Figure regions are layout rectangles only — the pipeline neither extracts
    nor stores page images — so a region contributes a comment that keeps its
    evidence id in place instead of linking a file that does not exist.
    """
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
        primary = min(molecule_evidence, key=reading_key)
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
                key=reading_key(primary, tie_breaker=primary.evidence_id),
                block=block,
            )
        )
    return placed


def _page_blocks(
    evidence: Sequence[SourceEvidence],
    page: int,
    candidate_blocks: list[_PlacedBlock],
    paragraphs: dict[str, EvidenceParagraph],
) -> list[_RenderedBlock]:
    page_evidence = [item for item in evidence if item.page == page]
    text_items = [item for item in page_evidence if is_text(item.kind)]
    slots: dict[int, list[_PlacedBlock]] = {}

    for item in page_evidence:
        if category_of(item.kind) != IMAGE:
            continue
        placed = _PlacedBlock(
            key=reading_key(item),
            block=_RenderedBlock(
                text=f"{_render_image(item)}\n\n",
                evidence_ids=(item.evidence_id,),
            ),
        )
        slot = sum(reading_key(text_item) < placed.key for text_item in text_items)
        slots.setdefault(slot, []).append(placed)

    for placed in candidate_blocks:
        if placed.key[0] != page:
            continue
        slot = sum(reading_key(text_item) < placed.key for text_item in text_items)
        slots.setdefault(slot, []).append(placed)

    result: list[_RenderedBlock] = [_RenderedBlock(f"<!-- PAGE {page} -->\n")]
    for slot in range(len(text_items) + 1):
        result.extend(
            item.block
            for item in sorted(slots.get(slot, []), key=lambda value: value.key)
        )
        if slot < len(text_items):
            block = _text_block(text_items[slot], paragraphs)
            if block is not None:
                result.append(block)
    return result


def _text_block(
    item: SourceEvidence, paragraphs: dict[str, EvidenceParagraph]
) -> _RenderedBlock | None:
    """Render one page's text slot, or ``None`` when it is a continuation.

    A paragraph is emitted once, on the page its first fragment sits on: a
    later fragment is the same text, not a new block.  Rows the grouping left
    out (tables, page furniture) keep the per-region rendering.
    """
    paragraph = paragraphs.get(item.evidence_id)
    if paragraph is None:
        rendered = _render_text(item.raw_text)
        evidence_ids = (item.evidence_id,)
    elif paragraph.starts_at(item.evidence_id):
        rendered = _render_paragraph(paragraph)
        evidence_ids = paragraph.evidence_ids
    else:
        return None
    if not rendered:
        return None
    return _RenderedBlock(text=f"{rendered}\n\n", evidence_ids=evidence_ids)


def _assemble_blocks(
    evidence: Sequence[SourceEvidence],
    candidates: Sequence[Molecule],
    pages: Sequence[int],
    doc_id: str,
    title: str,
) -> list[_RenderedBlock]:
    candidate_blocks = _candidate_blocks(evidence, candidates)
    paragraphs = paragraph_index(group_paragraphs(evidence))
    blocks: list[_RenderedBlock] = []
    for page in sorted(pages):
        blocks.extend(_page_blocks(evidence, page, candidate_blocks, paragraphs))
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
