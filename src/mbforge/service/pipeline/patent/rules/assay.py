"""Deterministic assay-method rule for section titles.

Only a title that declares an assay yields a method; the endpoint, target, and
type are the strings the title prints, and ``comparison_key`` is never generated.
"""

from __future__ import annotations

import re
from collections.abc import Mapping, Sequence
from typing import Any

#: Assay-declaring titles. Chinese and English sources both name the endpoint,
#: the assay platform, or a pharmacology section in the heading.
_ASSAY_HINT_RE = re.compile(
    r"抑制活性|激动活性|拮抗活性|结合活性|抑制率|活性测定|生物活性|药理|活性测试|"
    r"选择性|稳定性|代谢|测定|检测|筛选|评价|"
    r"\b(?:IC50|EC50|pIC50|pEC50|Ki|Kd)\b|"
    r"\b(?:assay|assays|inhibition|inhibitory|antagonis\w*|agonis\w*|potency|binding|"
    r"screening|mobilization|arrestin|FLIPR|HTRF|Caco\w*|selectivity|stability|"
    r"metabolic|pharmacolog\w*)\b",
    re.IGNORECASE,
)

#: Target named after ``对`` in a Chinese title, e.g. ``对MRGPRX2受体抑制活性``.
_ASSAY_TARGET_RE = re.compile(r"对\s*(?P<target>[A-Za-z][A-Za-z0-9\-]*)")

#: Receptor/cell token named in an English title, e.g. ``MRGPRX2 FLIPR Assay``.
#: Receptor/cell token. The boundaries are ASCII-aware on purpose: ``\b``
#: does not fire between ``MRGPRX2`` and the CJK text that follows it, since a
#: CJK character counts as a word character.
_ASSAY_TARGET_TOKEN_RE = re.compile(
    r"(?<![A-Za-z])(?P<target>[A-Z][A-Za-z]*\d[A-Za-z0-9]*)(?![A-Za-z0-9])"
)

#: First matching keyword wins (``活性`` fallback stays last).
_ASSAY_ENDPOINT_MAP = {
    "抑制活性": "抑制活性",
    "激动活性": "激动活性",
    "拮抗活性": "拮抗活性",
    "结合活性": "结合活性",
    "抑制率": "抑制率",
    "活性测定": "活性",
    "活性测试": "活性",
    "生物活性": "活性",
    "inhibition": "抑制活性",
    "antagonis": "拮抗活性",
    "agonis": "激动活性",
    "screening": "筛选",
    "assay": "测定",
    "活性": "活性",
}

_ASSAY_TYPE_RE = re.compile(r"\b(IC50|EC50|Ki|pIC50|IC-?50)\b", re.IGNORECASE)


#: Body headings that open an assay block: ``测试例1:MRGPRX2体外钙流测定试验``,
#: ``Test Example 2: …``. A result-table caption (``表1：MRGPRX2钙流试验结果``)
#: does not open a block — it reports the block it belongs to.
_ASSAY_BLOCK_HEADING_RE = re.compile(
    r"(?:测试例|试验例|测试实施例|Test\s*Example)\s*\d+\s*[:：]",
    re.IGNORECASE,
)


def _assay_target(text: str) -> str | None:
    """The target a heading names, by ``对X`` or by a receptor/cell token."""
    target_match = _ASSAY_TARGET_RE.search(text)
    if target_match:
        return target_match.group("target")
    token_match = _ASSAY_TARGET_TOKEN_RE.search(text)
    return token_match.group("target") if token_match is not None else None


def _assay_method(
    *,
    doc_id: str,
    section_id: str,
    page_num: int,
    page_end: int,
    text: str,
    evidence_ids: list[str],
    discriminator: str = "",
) -> dict:
    """Build one ``AssayMethod.to_dict()`` from the text that declares it."""
    from mbforge.domain.activity import AssayMethod, assay_method_id

    folded = text.casefold()
    endpoint = next(
        (
            mapped
            for keyword, mapped in _ASSAY_ENDPOINT_MAP.items()
            if keyword.casefold() in folded
        ),
        None,
    )
    type_match = _ASSAY_TYPE_RE.search(text)
    method = AssayMethod(
        assay_method_id=assay_method_id(doc_id, section_id, discriminator),
        doc_id=doc_id,
        target=_assay_target(text),
        endpoint=endpoint,
        assay_type=type_match.group(0) if type_match else None,
        raw_text=text,
        section_id=section_id,
        page_start=page_num,
        page_end=page_end,
        evidence_ids=list(evidence_ids),
    )
    return method.to_dict()


def _body_heading_text(text: str) -> str | None:
    """The heading phrase that follows a body assay marker, or ``None``."""
    match = _ASSAY_BLOCK_HEADING_RE.search(text)
    if match is None:
        return None
    tail = text[match.end() : match.end() + 120].split("[")[0].split("\n")[0]
    return tail.strip() or None


def extract_assay_methods_from_body(
    blocks: Sequence[tuple[str, str]],
    doc_id: str,
    section_id: str,
    page_num: int,
    page_end: int,
) -> list[dict]:
    """One method per assay block a section prints in its body.

    *blocks* are ``(evidence_id, raw_text)`` in document order, of every
    category: an assay block ends where the next one begins, so the result table
    under a heading belongs to it. Only a heading that names an assay (a platform,
    an endpoint or a target) yields a method; a heading that names nothing we can
    read stays text rather than becoming a guess.
    """
    headings = [
        (index, text)
        for index, (_, text) in enumerate(blocks)
        if _ASSAY_BLOCK_HEADING_RE.search(text)
    ]
    methods: list[dict] = []
    for position, (index, text) in enumerate(headings):
        heading_text = _body_heading_text(text)
        if heading_text is None:
            continue
        target = _assay_target(heading_text)
        if not target and not _ASSAY_HINT_RE.search(heading_text):
            continue
        end = headings[position + 1][0] if position + 1 < len(headings) else len(blocks)
        methods.append(
            _assay_method(
                doc_id=doc_id,
                section_id=section_id,
                page_num=page_num,
                page_end=page_end,
                text=heading_text,
                evidence_ids=[blocks[i][0] for i in range(index, end)],
                discriminator=blocks[index][0],
            )
        )
    return methods


def section_assay_methods(
    doc_id: str,
    section: Any,
    blocks_by_id: Mapping[str, Any],
) -> list[dict]:
    """Every assay method one section declares: its title first, then its body.

    A patent declares assays in the section title (rare in Chinese filings) or,
    far more often, in body blocks: ``测试例1:MRGPRX2体外钙流测定试验``. The body
    block owns the evidence that follows it, so a result table is scoped to the
    assay printed above it instead of to the whole section.
    """
    methods: list[dict] = []
    title_method = extract_assay_method_from_title(
        section.title,
        doc_id,
        section.section_id,
        section.page_start,
        section.page_end,
        evidence_ids=list(section.title_evidence_ids),
    )
    if title_method is not None:
        methods.append(title_method)
    ordered = sorted(
        (blocks_by_id[eid] for eid in section.evidence_ids if eid in blocks_by_id),
        key=lambda block: (block.page, block.reading_order),
    )
    methods.extend(
        extract_assay_methods_from_body(
            [(block.evidence_id, block.raw_text) for block in ordered],
            doc_id,
            section.section_id,
            section.page_start,
            section.page_end,
        )
    )
    return methods


def extract_assay_method_from_title(
    title: str,
    doc_id: str,
    section_id: str,
    page_num: int,
    page_end: int,
    *,
    evidence_ids: list[str] | None = None,
) -> dict | None:
    """Extract the assay method declared by a section title.

    Returns ``AssayMethod.to_dict()`` or ``None`` when the title carries
    no assay hint. ``comparison_key`` stays ``None`` — never
    auto-generated.
    """
    if not _ASSAY_HINT_RE.search(title):
        return None
    return _assay_method(
        doc_id=doc_id,
        section_id=section_id,
        page_num=page_num,
        page_end=page_end,
        text=title,
        evidence_ids=list(evidence_ids or []),
    )
