"""Deterministic compound-name rules.

A name is recorded only when the document printed it, in a section heading or in
the running text. A name never rewrites a structure, and an unresolved name stays
unresolved rather than being guessed at.
"""

from __future__ import annotations

import re
from collections.abc import Mapping, Sequence

from mbforge.domain.evidence import SourceEvidence
from mbforge.domain.evidence_kind import TEXT, category_of
from mbforge.foundation.ids import stable_id
from mbforge.service.pipeline.patent.sections import (
    ParsedSection as DocumentSection,
)
from mbforge.service.pipeline.patent.sections import match_section_heading

#: Printed names carry one of these suffixes (``…甲硫酰胺``, ``…吡啶``).
_CHEM_NAME_SUFFIX_RE = re.compile(
    r"(?:酰胺|胺|苯|吡啶|嘧啶|三唑|吡唑|噻唑|噁唑|嘧啶酮|酯|酮|酸|醇|醚|腈|炔|烯|烷)\s*$"
)


MAX_NAMES = 60


#: only.
_PROSE_NAME_RE = re.compile(
    r"(?:得到|获得|制得)\s*(?:化合物\s*)?"
    r"(?P<name>"
    r"(?:N-?)?"
    # A systematic name nests brackets all the way down
    # ("N-((1R,3S)-3-((6-氯…喹啉-4-基)氨基)环己基)-…-4-甲酰胺"), so parentheses and
    # digits belong inside it. The name ends where the sentence continues or a
    # round-bracket note begins ("(化合物38)" / "(12.6mg，产率9.5%)").
    r"[^，。；、\n]{6,260}?"
    r"(?:酰胺|胺|酯|酮|酸|醇|醚|腈|炔|烯|烷|苯|吡啶|嘧啶|三唑|吡唑|噻唑|噁唑|呋喃|喹啉|吲哚)"
    r")"
    r"(?=[（(][^）)]*[）)]|[，。；、\n]|$)"
)
#: A ``得到…`` clause often opens a workup sentence ("得到混合物在氮气保护下…")
#: rather than naming a product. Those fragments carry step wording, not chemistry.
_PROSE_NOT_A_NAME_RE = re.compile(
    r"(?:搅拌|反应|保护|室温|加热|冷却|过滤|浓缩|溶于|加入|滴加|洗涤|干燥|纯化|柱层析|℃|小时|分钟)"
)
#: A prose fragment this short is a reagent or a formula, not a compound name.
_MIN_PROSE_NAME_CHARS = 12
#: The fragment must look like a systematic name, not a sentence: a locant, a
#: stereo descriptor, or an N-substituent prefix.
_SYSTEMATIC_NAME_RE = re.compile(
    r"^(?:N-|\(?[0-9]{1,2}[RS]?,|[0-9]{1,2}-|[（(][0-9]{1,2}[RS])"
)


def extract_compound_names(
    sections: Sequence[DocumentSection],
    blocks_by_id: Mapping[str, SourceEvidence],
    doc_id: str,
) -> list[dict]:
    """Extract the chemistry name a section title prints for its compound.

    Corpus forms (forms §1/§2):
      ``[0095] 实施例1N-((1R,3S)-3-氨基环己基)甲酰胺的合成`` — the label is 1,
      ``N-`` starts the name; ``实施例1：N-(5-(3,5-二氟苄基)噻唑-2-基)-2-甲基丙硫酰胺``.

    Only the printed string is kept: a name is recorded, never derived from a
    structure, and a title whose remainder is not a chemical name is refused.
    """
    names: list[dict] = []
    seen: set[str] = set()
    for section in sections:
        if section.kind not in ("example", "preparation", "comparison", "reference"):
            continue
        match = match_section_heading(section.heading_line or section.title)
        if match is None:
            continue
        rest = (match.group("rest") or "").strip()
        name = re.sub(r"(?:的)?(?:合成|製法|制备|制造|合成方法)\s*$", "", rest).strip()
        name = name.strip("：:—-– ")
        if not name or not _CHEM_NAME_SUFFIX_RE.search(name):
            continue
        token = (match.group("num") or "").strip()
        from mbforge.domain.patent import example_label_key

        label_key = example_label_key(token) if token else ""
        name_id = stable_id("name", doc_id, section.section_id, name)
        if name_id in seen:
            continue
        seen.add(name_id)
        names.append(
            {
                "name_id": name_id,
                "label_key": label_key,
                "label_raw": section.title.split("：")[0][:200],
                "name_raw": name,
                "name_clean": " ".join(name.split()),
                "page": section.page_start,
                "evidence_ids": list(section.title_evidence_ids),
                "attribution": "resolved" if label_key else "unresolved",
            }
        )
        if len(names) >= MAX_NAMES:
            return names
    return names


#: ``得到化合物77-A(114.6mg，产率45.8%)`` / ``得到3-氯-N-((1R,3S)-...`` — a preparation
#: step naming its product in the running text rather than in a heading.
#:
#: This matters because the heading is not always where the name is printed: on a
#: scanned patent the structure is often never drawn at all (a chiral SFC split
#: reports only retention time and LC-MS), so the prose name is the only route
#: back to a structure. Measured on CN120329282A: 190 of 1014 text rows carry a
#: chemistry-name marker, 16 passages print a designation *and* a systematic


def extract_prose_compound_names(
    evidence: Sequence[SourceEvidence], doc_id: str
) -> list[dict]:
    """Extract compound names printed in running text, not in a heading.

    ``extract_compound_names`` reads section headings. A patent also names its
    products mid-paragraph — ``得到化合物77-A(114.6mg…)`` or a full systematic
    name after ``得到`` — and those passages are the only place a name exists when
    the structure was never drawn.

    Only the printed string is recorded. The designation is left unresolved: the
    prose rarely states which label the name belongs to, and guessing one would
    bind a reading to the wrong structure.
    """
    names: list[dict] = []
    seen: set[str] = set()
    for item in evidence:
        if category_of(item.kind) != TEXT:
            continue
        text = item.raw_text or ""
        if not text or len(text) > 4000:
            continue
        for match in _PROSE_NAME_RE.finditer(text):
            name = " ".join((match.group("name") or "").split())
            name = name.strip("，。；、：:—-– ")
            if len(name) < _MIN_PROSE_NAME_CHARS:
                continue
            if not _CHEM_NAME_SUFFIX_RE.search(name):
                continue
            if not _SYSTEMATIC_NAME_RE.search(name):
                continue
            if _PROSE_NOT_A_NAME_RE.search(name):
                continue
            name_id = stable_id("name", doc_id, "prose", item.evidence_id, name)
            if name_id in seen:
                continue
            seen.add(name_id)
            names.append(
                {
                    "name_id": name_id,
                    "label_key": "",
                    "label_raw": "",
                    "name_raw": name,
                    "name_clean": name,
                    "page": item.page - 1,
                    "evidence_ids": [item.evidence_id],
                    "attribution": "unresolved",
                }
            )
            if len(names) >= MAX_NAMES:
                return names
    return names
