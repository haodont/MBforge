"""Deterministic patent-section parsing from joined source evidence."""

from __future__ import annotations

import re
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Any

from mbforge.pipeline.labels import _explicit_compound_labels
from mbforge.pipeline.markdown.markers import _ESMILES_BLOCK_RE
from mbforge.utils.ids import stable_id

# The optional numeric prefix is OCR page-margin noise, not part of a title.
# A Chinese heading may omit its colon, but an explicit whitespace/end boundary
# is required so a body phrase such as ``实施例1方法`` is not cut as a section.
_HEADING_RE = re.compile(
    r"^\s*(?:#+\s*)?(?:\d{1,3}\s*)?"
    r"(?P<kind>实施例|制备例|对比例|比较例|参考例|Example)\s*"
    r"(?P<num>\d+[A-Za-z]?)?"
    r"(?P<gap>\s*)"
    r"(?P<separator>[：:])?\s*"
    r"(?P<rest>.*?)\s*$",
    re.IGNORECASE,
)

_KIND_TO_ROLE = {
    "实施例": "example",
    "制备例": "preparation",
    "对比例": "comparison",
    "比较例": "comparison",
    "参考例": "reference",
    "example": "example",
}
_CANDIDATE_HEADER_RE = re.compile(r"^%%\s*candidate=(\S+)\s*$", re.MULTILINE)


@dataclass
class ParsedSection:
    """One deterministic section projected from SQL source evidence."""

    section_id: str
    title: str
    kind: str
    page_start: int | None
    page_end: int | None
    raw_text: str
    labels: list[str]
    esmiles_candidate_ids: list[str]
    evidence_ids: list[str]
    title_evidence_ids: list[str]
    heading_line: str


def match_section_heading(line: str) -> re.Match[str] | None:
    """Return a valid section-heading match, excluding body false positives."""
    match = _HEADING_RE.match(line)
    if match is None:
        return None
    kind = match.group("kind").casefold()
    if kind == "example" and not match.group("num"):
        return None
    rest = match.group("rest").strip()
    if match.group("separator") is None and rest and not match.group("gap"):
        return None
    if (
        kind != "example"
        and not match.group("num")
        and match.group("separator") is None
    ):
        return None
    return match


def section_title(match: re.Match[str]) -> str:
    """Normalize OCR margin noise and heading punctuation into one title."""
    kind = match.group("kind")
    number = match.group("num") or ""
    rest = match.group("rest").strip()
    if kind.casefold() == "example":
        prefix = f"Example {number}" if number else "Example"
        separator = ":"
    else:
        prefix = f"{kind}{number}"
        separator = "："
    return f"{prefix}{separator}{rest}" if rest else prefix


def section_role(kind: str) -> str:
    """Return the normalized role for a matched heading keyword."""
    return _KIND_TO_ROLE.get(kind.casefold(), "example")


def section_id(doc_id: str, page_start: int | None, title: str) -> str:
    """Keep section IDs stable across the two stage projections."""
    return stable_id("section", doc_id, str(page_start or 0), title)


def segment_page_headings(pages: Sequence[Any]) -> list[tuple[int, str]]:
    """Return ``(page_num, line)`` anchors from extracted page text."""
    anchors: list[tuple[int, str]] = []
    for page in pages:
        for line in str(getattr(page, "text", "")).splitlines():
            if match_section_heading(line):
                anchors.append((int(page.page_num), line))
    return anchors


def _candidate_ids(section_text: str) -> list[str]:
    ids: list[str] = []
    for block in _ESMILES_BLOCK_RE.finditer(section_text):
        match = _CANDIDATE_HEADER_RE.search(block.group(1))
        if match and match.group(1) not in ids:
            ids.append(match.group(1))
    return ids


def _dedupe(values: Sequence[str]) -> list[str]:
    result: list[str] = []
    for value in values:
        if value not in result:
            result.append(value)
    return result


def parse_source_evidence_sections(
    evidence: Sequence[Any],
    doc_id: str,
) -> list[ParsedSection]:
    """Segment ordered SQL source-evidence blocks into sections (no Markdown).

    SQL-only sectioning path for the unified PatentStage. It does not read
    Markdown or Extract page text: a section is
    the block range between two heading blocks, and evidence provenance comes
    straight from the loaded SourceEvidence rows. Only text-bearing
    ``text_span``/``table_span`` blocks are eligible for heading detection.

    Args:
        evidence: SourceEvidence rows already in deterministic reading order
            (page ASC, bbox_y1 DESC, bbox_x0 ASC, bbox_y0 ASC, bbox_x1 ASC,
            evidence_id ASC).
        doc_id: must match every row.

    Returns:
        Sections whose ``evidence_ids`` are the SQL IDs actually used and whose
        ``title_evidence_ids`` are the heading block IDs.
    """
    blocks = list(evidence)
    if not blocks:
        return []
    for block in blocks:
        if getattr(block, "doc_id", None) != doc_id:
            raise ValueError("source evidence has a different doc_id")
        if not getattr(block, "evidence_id", ""):
            raise ValueError("source evidence contains an empty evidence_id")

    def _text_kind(item: Any) -> bool:
        return item.kind in {"text_span", "table_span"} and bool(item.raw_text.strip())

    def _heading_match(item: Any) -> re.Match[str] | None:
        for line in item.raw_text.splitlines():
            match = match_section_heading(line)
            if match is not None:
                return match
        return None

    head_indices = [
        index
        for index, block in enumerate(blocks)
        if _text_kind(block) and _heading_match(block) is not None
    ]
    if not head_indices:
        return []

    sections: list[ParsedSection] = []
    for position, head_index in enumerate(head_indices):
        next_index = (
            head_indices[position + 1]
            if position + 1 < len(head_indices)
            else len(blocks)
        )
        title_block = blocks[head_index]
        heading = _heading_match(title_block)
        if heading is None:
            raise AssertionError("heading block lost its match")
        used = [
            blocks[i] for i in range(head_index, next_index) if _text_kind(blocks[i])
        ]
        raw_text = "\n".join(block.raw_text for block in used)
        page_start = title_block.page
        last_block = blocks[next_index - 1]
        page_end = getattr(last_block, "page", None) or page_start
        sections.append(
            ParsedSection(
                section_id=section_id(doc_id, page_start, section_title(heading)),
                title=section_title(heading),
                kind=section_role(heading.group("kind")),
                page_start=page_start,
                page_end=page_end,
                raw_text=raw_text,
                labels=_explicit_compound_labels(raw_text),
                esmiles_candidate_ids=_candidate_ids(raw_text),
                evidence_ids=_dedupe([block.evidence_id for block in used]),
                title_evidence_ids=_dedupe([title_block.evidence_id]),
                heading_line=heading.group(0),
            )
        )
    return sections


__all__ = [
    "ParsedSection",
    "_HEADING_RE",
    "section_id",
    "match_section_heading",
    "parse_source_evidence_sections",
    "section_role",
    "section_title",
    "segment_page_headings",
]
