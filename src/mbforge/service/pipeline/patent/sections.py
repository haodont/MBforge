"""Deterministic patent-section parsing from the SQL source evidence."""

from __future__ import annotations

import re
import unicodedata
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Any

from mbforge.domain.evidence_kind import TEXT_CATEGORIES, category_of
from mbforge.foundation.ids import stable_id
from mbforge.service.pipeline.labels import _explicit_compound_labels
from mbforge.service.pipeline.markdown.markers import _ESMILES_BLOCK_RE

# The optional prefix is either OCR page-margin noise or the publication
# paragraph marker every modern patent prints (``[0143]``, ``(0143)``, ``143.``).
# A Chinese heading may omit its colon, but an explicit whitespace/end boundary
# is required so a body phrase such as ``实施例1方法`` is not cut as a section.
# Dashes are accepted as separators because published titles join the label and
# the title with an em dash (``Example 2—Screening of Compounds``).
_HEADING_RE = re.compile(
    r"^\s*(?:#+\s*)?"
    r"(?:[\[(]\s*\d{1,4}\s*[\])]|\d{1,4}[.、]?)?\s*"
    r"(?P<kind>实施例|実施例|制备例|对比例|比较例|参考例|Example)\s*"
    # A trailing letter is part of the label (``Example 1a``) unless a chemical
    # name continues straight into it (``实施例5N-((1R,3S)-…`` names compound 5).
    # A lettered label alone is an assay example in US filings (``Example A``):
    # it stays uppercase so prose (``Examples of …``) is not cut as a section.
    r"(?P<num>\d+(?:[A-Za-z](?![-–—][(（]))?|(?-i:[A-Z]\d*))?"
    r"(?P<gap>\s*)"
    r"(?P<separator>[：:—–－.、-])?\s*"
    r"(?P<rest>.*?)\s*$",
    re.IGNORECASE,
)

_KIND_TO_ROLE = {
    "实施例": "example",
    "実施例": "example",
    "制备例": "preparation",
    "对比例": "comparison",
    "比较例": "comparison",
    "参考例": "reference",
    "example": "example",
    "assay": "bioassay",
}
_CANDIDATE_HEADER_RE = re.compile(r"^%%\s*candidate=(\S+)\s*$", re.MULTILINE)

#: Every section kind the deterministic pass can mint, via :func:`section_role`.
#: ``PatentSectionModel.kind`` stays an open ``str`` on purpose (a stored
#: artifact must still load after this set changes), so this tuple — not the
#: field type — is the published vocabulary.
SECTION_KINDS: tuple[str, ...] = (
    "example",
    "preparation",
    "comparison",
    "reference",
    "bioassay",
)

# Bioassay sections are numbered or bracketed, never bare prose. Published
# forms: ``(一)本发明化合物对MRGPRX2的抑制活性``, ``3. 检测结果``,
# ``[0144]生物活性研究(一)本发明化合物对MRGPRX2的抑制活性``.
_ASSAY_ENUM_RE = re.compile(
    r"[（(]\s*[一二三四五六七八九十\d]{1,3}\s*[)）]"
    r"|[一二三四五六七八九十]{1,3}、"
    r"|\d{1,2}(?:\.\d{1,2})*[.、]"
)
_PARAGRAPH_MARKER_RE = re.compile(r"^\s*(?:[\[(]\s*\d{1,4}\s*[\])]|\d{1,4}[.、]?)\s*")
#: Protocol prose inside a numbered step: units, pipetting verbs, sentence ends.
_PROTOCOL_TEXT_RE = re.compile(
    r"[。；;]|(?:μL|µL|mL|mg|kg|℃|分钟|小时|孵育|移液|加入|置于|室温)"
)
#: What makes a numbered line an assay section rather than a protocol step.
_ASSAY_DOMAIN_RE = re.compile(
    r"(?:活性|抑制|激动|拮抗|亲和|选择性|测定|检测|筛选|评价|生物学|药理|药效|"
    r"代谢|稳定性|溶解度|毒性|"
    r"IC50|EC50|pIC50|pEC50|Kd|Ki|assay|inhibition|antagonis|agonist|potency|screening)",
    re.IGNORECASE,
)


@dataclass(frozen=True)
class _Heading:
    """One recognized heading, from the example or the bioassay vocabulary."""

    kind: str
    title: str
    line: str


def match_assay_heading(line: str) -> str | None:
    """Return the title of a numbered bioassay heading, or ``None``.

    Such headings declare a measurement, so they carry the assay a value
    belongs to. A heading is short and stands alone: protocol sentences
    (``3. 稳定性测定步骤a. 将198 μL肝细胞…``) and generic numbered steps
    (``1. 材料与仪器``) stay body text.
    """
    stripped = _PARAGRAPH_MARKER_RE.sub("", line).strip()
    if not stripped or len(stripped) > 45:
        return None
    if _ASSAY_ENUM_RE.search(stripped) is None:
        return None
    if _PROTOCOL_TEXT_RE.search(stripped):
        return None
    title = " ".join(stripped.split())
    if not _ASSAY_DOMAIN_RE.search(title):
        return None
    return title


def _match_heading(line: str) -> _Heading | None:
    """Recognize an example/preparation heading or a bioassay heading."""
    match = match_section_heading(line)
    if match is not None:
        return _Heading(kind=match.group("kind"), title=section_title(match), line=line)
    title = match_assay_heading(line)
    if title is not None:
        return _Heading(kind="assay", title=title, line=line)
    return None


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


_DIGIT_GAP_RE = re.compile(r"(?<=\d)\s+(?=\d)")


def _normalize_heading_text(line: str) -> str:
    """Normalize a heading's spelling without touching the stored print.

    Japanese filings print ``実施例 1 0 3`` and ``実施例２および3``; the native
    text layer and OCR both insert spaces between digits and emit full-width
    digits. Collapsing only digit-separating spaces and applying NFKC lets the
    heading regex see the token a reader sees, while ``ParsedSection.heading_line``
    keeps the verbatim print for the anchor.
    """
    return _DIGIT_GAP_RE.sub("", unicodedata.normalize("NFKC", line))


def match_section_heading(line: str) -> re.Match[str] | None:
    """Return a valid section-heading match, excluding body false positives."""
    match = _HEADING_RE.match(_normalize_heading_text(line))
    if match is None:
        return None
    kind = match.group("kind").casefold()
    if kind == "example" and not match.group("num"):
        return None
    rest = match.group("rest").strip()
    # A chemical name may follow the number directly (``实施例5N-((…``): an ASCII
    # capital continues the name, while a Chinese body phrase such as
    # ``实施例1方法`` is not a heading at all.
    if (
        match.group("separator") is None
        and rest
        and not match.group("gap")
        and not re.match(r"[A-Z]", rest)
    ):
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


def example_token(section: ParsedSection) -> str | None:
    """Return the example label a section declares (``实施例5：…`` → ``5``).

    Activity tables index their rows by example label, so ``实施例5`` designates
    the compound that section prepares — a document-local identity, never a
    global alias for every compound that happens to share the number.
    """
    if section.kind not in ("example", "preparation"):
        return None
    match = match_section_heading(section.heading_line)
    if match is None:
        return None
    return (match.group("num") or "").strip() or None


def section_id(doc_id: str, page_start: int | None, title: str) -> str:
    """Keep section IDs stable across the two stage projections."""
    return stable_id("section", doc_id, str(page_start or 0), title)


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
    ``text``-category blocks (prose and tables) are eligible for heading detection.

    Args:
        evidence: SourceEvidence rows already in deterministic reading order
            (page ASC, ``reading_order``, then bbox_y1 DESC, bbox_x0 ASC,
            bbox_y0 ASC, bbox_x1 ASC, evidence_id ASC).
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
        return category_of(item.kind) in TEXT_CATEGORIES and bool(item.raw_text.strip())

    def _heading_match(item: Any) -> _Heading | None:
        for line in item.raw_text.splitlines():
            heading = _match_heading(line)
            if heading is not None:
                return heading
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
                section_id=section_id(doc_id, page_start, heading.title),
                title=heading.title,
                kind=section_role(heading.kind),
                page_start=page_start,
                page_end=page_end,
                raw_text=raw_text,
                labels=_explicit_compound_labels(raw_text),
                esmiles_candidate_ids=_candidate_ids(raw_text),
                evidence_ids=_dedupe([block.evidence_id for block in used]),
                title_evidence_ids=_dedupe([title_block.evidence_id]),
                heading_line=heading.line,
            )
        )
    return sections


__all__ = [
    "ParsedSection",
    "SECTION_KINDS",
    "_HEADING_RE",
    "example_token",
    "match_assay_heading",
    "match_section_heading",
    "parse_source_evidence_sections",
    "section_id",
    "section_role",
    "section_title",
]
