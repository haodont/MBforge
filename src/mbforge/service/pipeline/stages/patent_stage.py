"""Stage 3: the single SQL-backed patent-facts parser.

Patent consumes the SourceEvidence rows written by Extract. Sections,
entries, examples, assay methods, and activity measurements are assembled once
and published as ``patent_facts.json``.

Reads:
    SQL ``source_evidence`` for ``ctx.doc_id``

Writes:
    storage/{doc_id}/patent_facts.json
    SQLite ``molecules`` rows for concrete candidates with linked activity

Only existing ``evidence_id`` values are written into derived facts. Link and
Persist are not invoked here.
"""

from __future__ import annotations

import re
from collections.abc import Callable, Collection, Mapping, Sequence
from dataclasses import dataclass, field
from typing import Any

from mbforge.contracts.patent import (
    DraftCoverage,
    DraftMeasurement,
    DraftValue,
    PatentDraft,
    PatentGap,
    PatentGapAnswer,
)
from mbforge.contracts.patent_runtime import PatentAnalysisBudget, PatentTaskScope
from mbforge.domain.evidence import SourceEvidence
from mbforge.domain.evidence_kind import TEXT, category_of
from mbforge.domain.patent_analysis import evidence_signature
from mbforge.foundation.ids import short_id, stable_id
from mbforge.foundation.logger import get_logger
from mbforge.service.pipeline.patent.artifact import (
    EvidenceReadCoverage,
    PatentFactsArtifact,
    PatentSectionModel,
)
from mbforge.service.pipeline.patent.association import apply_gap_links, associate_facts
from mbforge.service.pipeline.patent.llm_gaps import (
    DEFAULT_MAX_GAPS,
    FAMILY_ISSUE_CODES,
    TURNS_PER_GAP,
    build_gaps,
)
from mbforge.service.pipeline.patent.llm_merge import MergeResult, merge_submission
from mbforge.service.pipeline.patent.sections import (
    _HEADING_RE,
    example_token,
    match_section_heading,
    parse_source_evidence_sections,
)
from mbforge.service.pipeline.patent.sections import (
    ParsedSection as DocumentSection,
)
from mbforge.service.pipeline.run.context import PipelineContext
from mbforge.service.pipeline.stage import PipelineErrorCode, StageResult, register
from mbforge.service.ports import get_patent_analysis_runtime, get_repositories
from mbforge.service.use_cases.documents import patent_facts

logger = get_logger("mbforge.service.pipeline.stages.patent")

#: Target compounds declared in a section title, e.g. ``化合物13和14``.
_COMPOUND_LABEL = r"\d{1,4}[A-Za-z]?(?:-[A-Za-z])?"
_COMPOUND_TOKEN_RE = re.compile(
    rf"(?:化合物\s*(?P<zh>{_COMPOUND_LABEL}(?:\s*和\s*{_COMPOUND_LABEL})*)|"
    rf"compound\s+(?P<en>{_COMPOUND_LABEL}(?:\s+and\s+{_COMPOUND_LABEL})*))",
    re.IGNORECASE,
)

#: Internal compound codes in parentheses, e.g. ``(IGP-20024-01)``.
_CODE_RE = re.compile(r"[（(]([A-Za-z][A-Za-z0-9\-]{2,})[)）]")

#: A designation followed by one of these is a quantity, not a compound number.
_MASS_SUFFIX_RE = re.compile(
    r"(?i)^\s*(?:\d|\.\s*\d|mg\b|g\b|kg\b|ug\b|μg\b|ml\b|μl\b|mol\b|mmol\b|"
    r"nm\b|mm\b|μm\b|um\b|%)"
)

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
_ASSAY_TARGET_TOKEN_RE = re.compile(r"\b(?P<target>[A-Z][A-Za-z]*\d[A-Za-z0-9]*)\b")

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

__all__ = [
    "DocumentSection",
    "PatentStage",
    "_HEADING_RE",
    "extract_assay_method_from_title",
    "extract_entries_from_title",
]


@dataclass
class ExtractionOutcome:
    """All facts produced by one SQL evidence pass."""

    sections: list[DocumentSection]
    entries: list[dict]
    assay_methods: list[dict]
    examples: list[dict]
    measurements: list[dict]
    issues: list[dict]
    #: Preparation routes (``PatentFactsArtifact.synthesis_steps``): deterministic,
    #: zero-token, verbatim steps with the section they were printed in.
    routes: list[dict] = field(default_factory=list)
    #: Chemistry names printed for a designation, and the printed spectra /
    #: elemental lines with the owner each passage names.
    names: list[dict] = field(default_factory=list)
    characterizations: list[dict] = field(default_factory=list)
    #: Readings joined to the structure their example heading declares. Each entry
    #: carries whether the example's printed product mass reproduces the structure.
    structure_activity: list[dict] = field(default_factory=list)
    #: The evidence rows this pass read; the LLM path needs their pages and a
    #: signature of the exact set it analyzed.
    evidence: list[SourceEvidence] = field(default_factory=list)


@dataclass
class LlmAnalysis:
    """Result of the optional LLM-led pass over the rule draft."""

    #: disabled | succeeded | partial | fallback
    status: str = "disabled"
    #: deterministic | hybrid
    mode: str = "deterministic"
    merge: MergeResult | None = None
    #: Associations the model made (label_raw -> a recognized structure). Consumed
    #: by ``association.apply_gap_links``; they never become a reading.
    links: list[dict[str, Any]] = field(default_factory=list)
    llm: dict[str, Any] = field(default_factory=dict)
    coverage: EvidenceReadCoverage | None = None
    issues: list[dict[str, Any]] = field(default_factory=list)


def _example_facts(sections: list[DocumentSection]) -> list[dict]:
    """Project example sections without copying their source text."""
    examples: list[dict] = []
    for example_idx, section in enumerate(
        (item for item in sections if item.kind == "example"), 1
    ):
        examples.append(
            {
                "example_idx": example_idx,
                "page_num": section.page_start,
                "heading": section.title,
                "labels": list(section.labels),
                "esmiles_candidate_ids": list(section.esmiles_candidate_ids),
                "evidence_ids": list(section.evidence_ids),
            }
        )
    return examples


def _family_issues(
    characterizations: Sequence[Mapping[str, Any]],
    names: Sequence[Mapping[str, Any]],
    routes: Sequence[Mapping[str, Any]],
) -> list[dict[str, Any]]:
    """One report per passage that names no designation this document resolves.

    The report is a function of the passage's ``attribution``, so it is derived
    here rather than inline: the association pass can change that attribution, and
    the reports then have to be re-derived from the state it produced.
    """
    issues: list[dict[str, Any]] = []
    for family, code in (
        (characterizations, FAMILY_ISSUE_CODES[0]),
        (names, FAMILY_ISSUE_CODES[1]),
        (routes, FAMILY_ISSUE_CODES[2]),
    ):
        for item in family:
            if item["attribution"] != "unresolved":
                continue
            issues.append(
                {
                    "code": code,
                    "message": (
                        f"{code}: one printed passage names no designation this "
                        "document resolves"
                    ),
                    "severity": "info",
                    "evidence_ids": list(item["evidence_ids"][:50]),
                    "related_fact_id": None,
                }
            )
    return issues


#: A route is prose that prepares something: 制得/合成/収率/synthesized/prepared.
_ROUTE_SIGNAL_RE = re.compile(
    r"(?:制得|合成|製|収率|收率|产率|yield|synthes\w*|prepar\w*)", re.IGNORECASE
)
#: A step is only what the document printed as a step.
_STEP_MARKER_RE = re.compile(
    r"^\s*(?:步骤\s*\d|第\s*[一二三四五六七八九十\d]{1,3}\s*步|"
    r"Step\s*\d|\(\s*\d+\s*\)|（\s*\d+\s*）)",
    re.IGNORECASE,
)
_YIELD_RE = re.compile(
    r"(?:收率|収率|产率|yield)\s*[:：]?\s*\d+(?:\.\d+)?\s*%", re.IGNORECASE
)
#: ``制得化合物7`` / ``得白色固体化合物11`` — the route names its own product.
_ROUTE_PRODUCT_RE = re.compile(
    r"(?:制得|得到|得)\s*(?:[\u4e00-\u9fff]{0,4}(?:固体|粉末|油状物|油状|晶体))?\s*"
    r"(化合物\s*\d+[A-Za-z]?(?:-\d+)?)"
)
#: A shared-method or precedent sentence: the fact that a group of compounds was
#: made the same way (``synthesized using a similar method``, ``参考实施例1方法``).
_METHOD_NOTE_RE = re.compile(
    r"(?:similar method|analogous|in the same manner|according to the method|"
    r"参考实施例\s*\d+|按照?(?:与)?(?:上述|实施例\s*\d+)方法|按实施例\s*\d+的方法)",
    re.IGNORECASE,
)


def extract_synthesis_routes(
    sections: Sequence[DocumentSection],
    blocks_by_id: Mapping[str, SourceEvidence],
    doc_id: str,
) -> list[dict]:
    """Extract preparation routes from the example/preparation sections.

    The route lives in the *body*, not under a ``合成路线`` heading: none of the
    thirteen corpus documents prints such a heading, so this rule is built on the
    forms the corpus does print —

    * ``The following compounds were synthesized using a similar method…``
    * ``参考实施例1方法，制得化合物36.8mg，收率16.5%`` (CN121270515A)
    * ``ＤＭＡ(2 mL)中、2-ブロモ-N-(中間体71)(92 m g、0.2 57 m mο1)に、`` (JP2023544789A)

    Every string is copied verbatim; a step exists only where the document printed
    one (``步骤1`` / ``第1步`` / ``Step 1`` / ``(1)``), and the yield is the printed
    expression, never a converted number.
    """
    from mbforge.domain.patent import compound_label_key, example_label_key

    routes: list[dict] = []
    for section in sections:
        if section.kind not in ("example", "preparation"):
            continue
        blocks = [
            (evidence_id, blocks_by_id[evidence_id])
            for evidence_id in section.evidence_ids
            if evidence_id in blocks_by_id
        ]
        body = "\n".join(item.raw_text or "" for _, item in blocks)
        if not body.strip() or not _ROUTE_SIGNAL_RE.search(body):
            continue

        steps: list[dict] = []
        current: dict | None = None
        for evidence_id, item in blocks:
            for line in (item.raw_text or "").splitlines():
                if _STEP_MARKER_RE.match(line):
                    current = {
                        "step_no": len(steps) + 1,
                        "text": line.strip(),
                        "evidence_ids": [evidence_id],
                    }
                    steps.append(current)
                    continue
                if current is not None and line.strip():
                    current["text"] = f"{current['text']}\n{line.strip()}"
                    if evidence_id not in current["evidence_ids"]:
                        current["evidence_ids"].append(evidence_id)

        note = next(
            (
                line.strip()
                for _, item in blocks
                for line in (item.raw_text or "").splitlines()
                if _METHOD_NOTE_RE.search(line)
            ),
            "",
        )
        yield_match = _YIELD_RE.search(body)
        product_match = _ROUTE_PRODUCT_RE.search(body)
        product_raw = ""
        if product_match is not None:
            # ``参考实施例1方法，制得化合物36.8mg，收率16.5%`` prints a mass, not
            # compound 36 — the same quantity guard the entry pass uses.
            tail = body[product_match.end(1) :]
            if not _MASS_SUFFIX_RE.match(tail):
                product_raw = product_match.group(1)
        token = example_token(section)
        # Declaration beats inference (forms §8.4): a product the route prints is
        # its own identity; otherwise the section's own label designates it.
        label_key = (
            compound_label_key(product_raw)
            or (example_label_key(token) if token else None)
            or ""
        )
        label_raw = product_raw or (f"实施例{token}" if token else "")
        routes.append(
            {
                "route_id": stable_id(
                    "route", doc_id, str(section.page_start or 0), section.title
                ),
                "section_id": section.section_id,
                "kind": section.kind,
                "title": section.title,
                "label_raw": label_raw,
                "label_key": label_key,
                "product_label": product_raw,
                "page_start": section.page_start,
                "page_end": section.page_end,
                "evidence_ids": list(section.evidence_ids),
                "steps": steps,
                "step_count": len(steps),
                "yield_raw": yield_match.group(0) if yield_match else "",
                "method_note": note,
                "attribution": "resolved" if label_key else "unresolved",
            }
        )
    return routes


#: Spectra and elemental lines as the corpus prints them: ``1H NMR (400 MHz,
#: CDCl3) δ …``, ``MS (ESI) m/z: 456.2 [M+H]+``, ``LCMS: m/z 329.0 [M+H]+``,
#: ``元素分析`` / ``Anal. Calcd for …``.
_NMR_LINE_RE = re.compile(r"(?:\bNMR\b|核磁|氢谱)", re.IGNORECASE)
_MS_LINE_RE = re.compile(
    r"(?:\bMS\s*\(|\bLC[ -]?MS\b|\bLCMS\b|\bHRMS\b|\bMS\s*m/z\b|\bESI\b|质谱)",
    re.IGNORECASE,
)
_ELEMENTAL_LINE_RE = re.compile(
    r"(?:元素分析|\bAnal\.?\s*(?:Calcd|calc\.?)|calcd\.?\s*for)", re.IGNORECASE
)
#: How a document prints a designation anywhere in a passage.
_DESIGNATION_MENTION_RE = re.compile(
    r"(?:化合物|实施例|実施例|制备例|compound|example)\s*[#:：]?\s*"
    r"(\d+[A-Za-z]?(?:-[A-Za-z0-9]+)?)",
    re.IGNORECASE,
)
#: Printed names carry one of these suffixes (``…甲硫酰胺``, ``…吡啶``).
_CHEM_NAME_SUFFIX_RE = re.compile(
    r"(?:酰胺|胺|苯|吡啶|嘧啶|三唑|吡唑|噻唑|噁唑|嘧啶酮|酯|酮|酸|醇|醚|腈|炔|烯|烷)\s*$"
)
MAX_CHARACTERIZATIONS = 60
MAX_NAMES = 60


def _backfill_entry_names(entries: list[dict], names: Sequence[dict]) -> int:
    """Fill an entry's empty ``name_raw`` from the name its section printed.

    A printed name never overwrites one already recorded, and an entry the
    document never named stays unnamed.
    """
    by_key = {
        str(name.get("label_key") or ""): str(name.get("name_raw") or "")
        for name in names
        if name.get("label_key")
    }
    filled = 0
    for entry in entries:
        if entry.get("name_raw"):
            continue
        value = by_key.get(str(entry.get("label_key") or ""))
        if value:
            entry["name_raw"] = value
            filled += 1
    return filled


def _designation_keys(text: str) -> list[str]:
    """Document-local identity keys for the designations a passage prints.

    ``化合物77`` → ``77``, ``实施例1`` → ``@example:1``: an example designates the
    compound its own section prepares, so the two never share a key.
    """
    keys: list[str] = []
    from mbforge.domain.patent import example_label_key
    from mbforge.service.pipeline.activity.normalization import (
        normalize_reference_label,
    )

    for match in _DESIGNATION_MENTION_RE.finditer(text or ""):
        # ``参考实施例1方法，制得化合物36.8mg`` prints a mass, not compound 36.
        if _MASS_SUFFIX_RE.match((text or "")[match.end(1) :]):
            continue
        reference = normalize_reference_label(match.group(0))
        if reference.reference_type == "example" and reference.key:
            key = example_label_key(reference.key)
        elif reference.key and reference.reference_type in ("compound", "e_series"):
            key = reference.key
        else:
            continue
        if key not in keys:
            keys.append(key)
    return keys


def _technique_of(line: str) -> str | None:
    """The technique a printed line belongs to, or ``None`` when it is neither."""
    if _NMR_LINE_RE.search(line):
        return "nmr"
    if _MS_LINE_RE.search(line):
        return "ms"
    if _ELEMENTAL_LINE_RE.search(line):
        return "elemental"
    return None


#: A preparation step's own heading: ``第三步：(1S,3R)-…(A1-6)的合成``. A
#: characterization line printed under such a heading belongs to the compound the
#: heading names, which is how a scanned patent lays a step out.
_STEP_HEADING_RE = re.compile(
    r"(?:第[一二三四五六七八九十]+步|步骤\s*\d+|实施例\s*[\dA-Za-z-]+|中间体\s*[\dA-Za-z-]+)"
    r".*?(?:的)?(?:合成|制备|制法|制得)"
)
#: The heading usually names its product in parentheses after the chemistry:
#: ``…甲酰胺(A1-6)的合成``.
_HEADING_PRODUCT_RE = re.compile(
    r"[(（]\s*([A-Za-z0-9][\dA-Za-z-]{0,11})\s*[)）]\s*(?:的)?(?:合成|制备)"
)
#: How far above a characterization line its step heading may sit. Measured on
#: CN120329282A: 33 of 38 MS lines are exactly 5 rows below their heading and the
#: furthest observed is 17. The bound keeps a distant heading from lending its
#: designation to an unattached mass line.
_CHARACTERIZATION_HEADING_LOOKBACK = 24


def _characterization_owner(
    evidence: Sequence[SourceEvidence],
    row: SourceEvidence,
    order: int,
) -> str:
    """The designation a characterization line inherits from its step heading.

    A characterization line often arrives as its own evidence row
    (``[0168] LC-MS,M/Z(ESI):444.1[M+H]+`` is 33 characters) while the compound it
    describes is named by the preparation heading printed above it. A step's body
    sits between the two: measured on CN120329282A, 38 of 38 printed MS lines have
    a step heading earlier on their page, 33 of them at exactly 5 rows. Looking
    only at the immediately preceding row therefore finds almost nothing.

    Only a *step heading* grants the link, and only the designation that heading
    itself prints. A reading printed above the spectrum does not: the reading's
    compound and the spectrum's compound are not necessarily the same, and binding
    a mass to the wrong structure corrupts the very check these lines feed.

    The search stops at the page boundary and at a bounded distance, so a long
    document cannot lend a distant heading's designation to a stray mass line.
    """
    if order <= 0:
        return ""
    for back in range(1, _CHARACTERIZATION_HEADING_LOOKBACK + 1):
        index = order - back
        if index < 0:
            break
        previous = evidence[index]
        if previous.page != row.page:
            break
        text = previous.raw_text or ""
        if not _STEP_HEADING_RE.search(text):
            continue
        keys = _designation_keys(text)
        if len(keys) == 1:
            return keys[0]
        product = _HEADING_PRODUCT_RE.search(text)
        if product is not None:
            product_keys = _designation_keys(product.group(1))
            if len(product_keys) == 1:
                return product_keys[0]
        return ""
    return ""


def extract_characterization(
    evidence: Sequence[SourceEvidence], doc_id: str
) -> list[dict]:
    """Extract printed spectra and elemental data, verbatim, with their owner.

    The activity pass refuses these lines by design (``_NON_ACTIVITY_TABLE_RE``:
    ``NMR|LCMS|MS``), but the text itself is already SQL evidence. Nothing is
    re-typed or converted: the line is copied, the technique is named, and the
    designation is resolved only when the passage names exactly one.

    A line that names no designation of its own falls back to the nearest one
    printed above it on the same page, because that is how a preparation section
    is laid out: the step heading names the compound, the characterization line
    follows.

    The fallback is deliberately narrow — one designation owns at most one
    characterization *per technique* on a page. A page that prints several MS
    lines under one heading describes several compounds (a product and its
    intermediates), and letting all of them inherit the same designation would
    bind a mass to the wrong structure; that would corrupt the very check these
    lines feed. Those lines stay unresolved instead, which is what surfaces them
    as a gap for a reader to settle.
    """
    items: list[dict] = []
    seen: set[str] = set()
    for order, row in enumerate(evidence):
        text = row.raw_text or ""
        if not text.strip():
            continue
        row_keys = _designation_keys(text)
        for line in text.splitlines():
            technique = _technique_of(line)
            if technique is None:
                continue
            stripped = line.strip()
            line_keys = _designation_keys(stripped) or row_keys
            label_key = line_keys[0] if len(line_keys) == 1 else ""
            if not label_key:
                label_key = _characterization_owner(evidence, row, order)
            characterization_id = stable_id(
                "characterization", doc_id, row.evidence_id, technique, stripped
            )
            if characterization_id in seen:
                continue
            seen.add(characterization_id)
            items.append(
                {
                    "characterization_id": characterization_id,
                    "technique": technique,
                    "raw_text": stripped,
                    "label_key": label_key,
                    "page": row.page,
                    "evidence_ids": [row.evidence_id],
                    "attribution": "resolved" if label_key else "unresolved",
                }
            )
            if len(items) >= MAX_CHARACTERIZATIONS:
                return items
    return items


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
#: name, yet only 5 names reached the artifact while extraction read headings
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


#: ``MS (ESI) m/z: 456.2 [M+H]+`` — the printed mass and the adduct it names.
_MS_MZ_RE = re.compile(
    r"m/z[^0-9]{0,12}(?P<mz>\d+(?:\.\d+)?)\s*(?:\[\s*M\s*(?P<sign>[+-])\s*(?P<adduct>[A-Za-z0-9]+)\s*\]?)?",
    re.IGNORECASE,
)
#: Proton/electron-accurate adduct corrections (monoisotopic masses + electron).
_ADDUCT_DELTA = {
    "+H": 1.00728,
    "+Na": 22.98922,
    "+K": 38.96316,
    "+NH4": 18.03383,
    "-H": -1.00728,
}
#: Tolerance the dormant matcher in ``detection/label_recovery`` already uses.
MASS_TOLERANCE_DA = 0.6


def find_mass_mismatches(
    characterizations: Sequence[dict],
    candidates: Sequence[Any],
    *,
    tolerance: float = MASS_TOLERANCE_DA,
) -> list[dict]:
    """Printed MS mass versus the mass of the structure that claims the label.

    This is the detection half of a correction: a mismatch is *evidence*, never an
    edit. The structure the document recognized and the mass it printed for that
    designation disagree, which is worth a human's attention — and nothing here
    writes a SMILES or picks a replacement.
    """
    from mbforge.service.pipeline.detection.label_recovery import _exact_mass
    from mbforge.service.pipeline.patent.association import _candidate_label_keys

    by_key: dict[str, Any] = {}
    for candidate in candidates:
        for key in _candidate_label_keys(candidate):
            by_key.setdefault(key, candidate)

    mismatches: list[dict] = []
    for item in characterizations:
        if item.get("technique") != "ms" or not item.get("label_key"):
            continue
        candidate = by_key.get(str(item["label_key"]))
        if candidate is None:
            continue
        match = _MS_MZ_RE.search(str(item.get("raw_text") or ""))
        if match is None:
            continue
        printed = float(match.group("mz"))
        adduct = f"{match.group('sign') or '+'}{match.group('adduct') or 'H'}"
        delta_mass = _ADDUCT_DELTA.get(adduct)
        if delta_mass is None:
            continue
        structure_mass = _exact_mass(
            str(getattr(candidate, "canonical_smiles", "") or "")
        )
        if structure_mass is None:
            continue
        expected = structure_mass + delta_mass
        if abs(printed - expected) <= tolerance:
            continue
        mismatches.append(
            {
                "mol_id": str(getattr(candidate, "mol_id", "") or ""),
                "label_key": str(item["label_key"]),
                "printed_mz": printed,
                "adduct": adduct,
                "calculated_mass": round(structure_mass, 4),
                "delta": round(printed - expected, 4),
                "structure_smiles": str(
                    getattr(candidate, "canonical_smiles", "") or ""
                ),
                "raw_text": str(item.get("raw_text") or "")[:400],
                "evidence_ids": list(item.get("evidence_ids") or []),
            }
        )
    return mismatches


def extract_entries_from_title(
    title: str,
    doc_id: str,
    section_id: str,
    page_num: int,
    *,
    evidence_ids: list[str] | None = None,
) -> list[dict]:
    """Extract title-declared compound entries.

    Returns ``CompoundEntry.to_dict()``-shaped dicts.
    """
    from mbforge.domain.patent import (
        ROLE_EXAMPLE,
        ROLE_PREPARATION,
        CompoundEntry,
        entry_id,
        label_key_for,
    )

    role = (
        ROLE_PREPARATION
        if "制备" in title or re.search(r"\b(?:prepare|synthes)\w*\b", title, re.I)
        else ROLE_EXAMPLE
    )
    codes = _CODE_RE.findall(title)
    entries: list[dict] = []
    for label in _mentioned_labels(title):
        label_raw = f"化合物{label}"
        entry = CompoundEntry(
            entry_id=entry_id(doc_id, section_id, label_key_for(label_raw)),
            doc_id=doc_id,
            label_raw=label_raw,
            label_key=label_key_for(label_raw),
            entry_role=role,
            name_raw=" / ".join(codes),
            section_id=section_id,
            evidence_ids=list(evidence_ids or []),
        )
        entries.append(entry.to_dict())
    return entries


def _entry_role(section_kind: str) -> str:
    """Map a section kind to the entry role the title path assigns."""
    from mbforge.domain.patent import ROLE_EXAMPLE, ROLE_PREPARATION

    return ROLE_PREPARATION if section_kind == "preparation" else ROLE_EXAMPLE


def _example_identity_entry(section: DocumentSection, doc_id: str) -> dict | None:
    """Return the entry standing for an example section's own product.

    Activity tables index their rows by example label, so ``实施例7`` designates
    the compound that section prepares even when its body never prints a
    ``化合物7`` designation.
    """
    from mbforge.domain.patent import CompoundEntry, entry_id, example_label_key

    token = example_token(section)
    if token is None:
        return None
    label_raw = section.title.split("：", 1)[0].split(":", 1)[0].strip()
    label_key = example_label_key(token)
    return CompoundEntry(
        entry_id=entry_id(doc_id, section.section_id, label_key),
        doc_id=doc_id,
        label_raw=label_raw or token,
        label_key=label_key,
        entry_role=_entry_role(section.kind),
        section_id=section.section_id,
        evidence_ids=list(section.title_evidence_ids),
    ).to_dict()


def _mentioned_labels(text: str) -> list[str]:
    """Return the compound designations named by ``text`` (title vocabulary).

    A designation followed by a quantity is a mass reading, not a number
    (``制得化合物36.8mg`` names no compound 36).
    """
    labels: list[str] = []
    for match in _COMPOUND_TOKEN_RE.finditer(text):
        if _MASS_SUFFIX_RE.match(text[match.end() :]):
            continue
        group = match.group("zh") or match.group("en") or ""
        for label in re.split(r"\s*(?:和|and)\s*", group, flags=re.I):
            label = label.strip()
            if label and label not in labels:
                labels.append(label)
    return labels


def extract_entries_from_body(
    blocks: list[tuple[str, str]],
    doc_id: str,
    section_id: str,
    role: str,
) -> list[dict]:
    """Mint entries for compounds the section body declares.

    Titles often name only the prepared example (``实施例3：化合物12的合成``)
    while most patents name the compound in the body prose. Both are read so a
    measurement can link to the section that really declares it.

    Args:
        blocks: ``(evidence_id, raw_text)`` pairs in reading order. An entry
            keeps only the blocks that actually name it.
        role: ``ROLE_*`` value derived from the section kind.
    """
    from mbforge.domain.patent import CompoundEntry, entry_id, label_key_for

    entries: dict[str, dict] = {}
    for evidence_id, text in blocks:
        for label in _mentioned_labels(text):
            label_raw = f"化合物{label}"
            label_key = label_key_for(label_raw)
            entry = entries.get(label_key)
            if entry is None:
                entry = CompoundEntry(
                    entry_id=entry_id(doc_id, section_id, label_key),
                    doc_id=doc_id,
                    label_raw=label_raw,
                    label_key=label_key,
                    entry_role=role,
                    section_id=section_id,
                    evidence_ids=[],
                ).to_dict()
                entries[label_key] = entry
            if evidence_id not in entry["evidence_ids"]:
                entry["evidence_ids"].append(evidence_id)
    return list(entries.values())


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
    from mbforge.domain.activity import AssayMethod, assay_method_id

    if not _ASSAY_HINT_RE.search(title):
        return None

    target = None
    target_match = _ASSAY_TARGET_RE.search(title)
    if target_match:
        target = target_match.group("target")
    else:
        # English titles name the receptor or cell line instead (``MRGPRX2``).
        token_match = _ASSAY_TARGET_TOKEN_RE.search(title)
        if token_match is not None:
            target = token_match.group("target")
    folded = title.casefold()
    endpoint = next(
        (
            mapped
            for keyword, mapped in _ASSAY_ENDPOINT_MAP.items()
            if keyword.casefold() in folded
        ),
        None,
    )
    type_match = _ASSAY_TYPE_RE.search(title)
    method = AssayMethod(
        assay_method_id=assay_method_id(doc_id, section_id),
        doc_id=doc_id,
        target=target,
        endpoint=endpoint,
        assay_type=type_match.group(0) if type_match else None,
        raw_text=title,
        section_id=section_id,
        page_start=page_num,
        page_end=page_end,
        evidence_ids=list(evidence_ids or []),
    )
    return method.to_dict()


def _candidate_payload(candidate: dict[str, Any]) -> dict[str, Any]:
    """Serialize one review candidate for the artifact (conflict included)."""
    payload = dict(candidate)
    conflict = payload.pop("conflict", None)
    if conflict is not None:
        payload["conflict"] = conflict.model_dump()
    return payload


def _answer_scope(answer: PatentGapAnswer, gaps: Collection[PatentGap]) -> set[str]:
    """The evidence one answer is scoped to: its gap's excerpt and its citations.

    Keeping the scope at the gap is what keeps a merge honest: a reading found in
    one refused table can never be read as a conflict with a fact that lives
    somewhere else in the document.
    """
    gap = next((item for item in gaps if item.gap_id == answer.gap_id), None)
    ids = set(gap.evidence_ids) if gap is not None else set()
    for item in (*answer.items, *answer.assay_methods):
        ids.update(item.evidence_ids)
    return ids


def _answer_fact_scope(
    answer: PatentGapAnswer, gaps: Collection[PatentGap]
) -> set[str]:
    """The rule facts this gap named: what its answer may be compared against.

    A gap that names one measurement must not be answered against a neighbour
    that merely shares its slot, so the named fact is the comparison scope.
    """
    gap = next((item for item in gaps if item.gap_id == answer.gap_id), None)
    if gap is None:
        return set()
    fact_id = str(gap.rule_context.get("related_fact_id") or "")
    return {fact_id} if fact_id else set()


def _recorded_items(
    answer: PatentGapAnswer,
    gap: PatentGap | None,
    rule_measurements: Sequence[Mapping[str, Any]],
) -> list[DraftMeasurement]:
    """The reading a method-only answer leaves implicit, rebuilt from the rule fact.

    An ``assay_attribution`` gap is a reading whose assay the rules could not name:
    the reading itself is already extracted, published and verbatim. When the model
    answers such a gap with the assay method alone, Python binds the recorded reading
    to it. The value is *copied* from the rule fact, never re-typed by the model, so
    an answer that omits the readings cannot drift from them.

    A gap that names no recorded fact yields nothing: binding an unnamed reading
    would attach the method to whatever happens to share its evidence.

    ponytail: one fact per gap, so a refused 15-row table still binds one reading;
    widen to the gap's whole fact set if that table shape starts to matter.
    """
    if answer.items or not answer.assay_methods or gap is None:
        return []
    fact_id = str(gap.rule_context.get("related_fact_id") or "")
    if not fact_id:
        return []
    method_key = answer.assay_methods[0].local_key
    items: list[DraftMeasurement] = []
    for measurement in rule_measurements:
        if str(measurement.get("measurement_id") or "") != fact_id:
            continue
        value = measurement.get("value") or {}
        provenance = measurement.get("provenance") or {}
        raw_text = str(value.get("raw_text") or "")
        if not raw_text:
            continue
        items.append(
            DraftMeasurement(
                local_key=f"recorded-{fact_id}"[:64],
                metric=str(measurement.get("metric") or ""),
                value=DraftValue(
                    raw_text=raw_text,
                    operator=str(value.get("operator") or "="),
                    value=value.get("original_value"),
                    unit=str(value.get("original_unit") or ""),
                    qualitative=str(value.get("qualitative_value") or ""),
                ),
                compound_label_raw=str(provenance.get("reference_raw") or ""),
                row_label_raw=str(provenance.get("reference_raw") or ""),
                compound_label_key=str(provenance.get("reference_key") or ""),
                molecule_ref=str(measurement.get("mol_id") or ""),
                assay_local_key=method_key,
                evidence_ids=list(measurement.get("evidence_ids") or [])[:50],
            )
        )
    return items


def _answer_submission(
    answer: PatentGapAnswer,
    scope: PatentTaskScope,
    recorded: Sequence[DraftMeasurement] | None = None,
) -> PatentDraft:
    """Express one answered gap as a draft the merge already understands.

    A gap answer carries the same item models, so the bridge is identity plus
    the attempt's identity triple. Coverage stays Python's (the answer has no
    page authority); associations live on the measurements themselves.

    ``recorded`` carries the readings Python rebuilt from rule facts for a
    method-only answer; it replaces the items the model did not resend.
    """
    return PatentDraft(
        doc_id=scope.doc_id,
        attempt_id=scope.attempt_id,
        evidence_signature=scope.evidence_signature,
        assay_methods=list(answer.assay_methods),
        measurements=list(answer.items if recorded is None else recorded),
        coverage=DraftCoverage(
            pages_viewed=sorted(
                {item.page for item in answer.items if item.page is not None}
            ),
            pages_uncovered=[],
            notes=f"gap {answer.gap_id} ({answer.gap_kind})",
        ),
    )


def _progress_emitter(ctx: PipelineContext) -> Callable[[Any], None] | None:
    """Map runtime events onto the stage's progress channel (None = no channel)."""
    progress = ctx.progress
    if progress is None:
        return None

    def _emit(event: Any) -> None:
        data: dict[str, Any] = {"message": event.message or event.phase or event.kind}
        if event.phase:
            data["phase"] = event.phase
        if event.turn:
            data["turn"] = event.turn
        if event.tool:
            data["tool"] = event.tool
        if event.ok is not None:
            data["ok"] = event.ok
        progress(f"llm_{event.kind}", data)

    return _emit


def _combine_merges(results: list[MergeResult]) -> MergeResult:
    """Union several submissions' merges; a later submission supersedes a slot.

    Every submission is validated against the same attempt scope, so the unions
    are safe: measurements, review candidates and conflicts keep one entry per
    identity (the last submission wins, which is what a correction means), and
    the counters stay counts of dispositions.
    """
    if len(results) == 1:
        return results[0]
    measurements: dict[str, dict[str, Any]] = {}
    candidates: dict[str, dict[str, Any]] = {}
    conflicts: dict[str, Any] = {}
    stats: dict[str, int] = {}
    for result in results:
        for item in result.measurements:
            measurements[str(item.get("measurement_id"))] = item
        for item in result.candidates:
            key = str(
                item.get("review_item_id")
                or item.get("slot_id")
                or item.get("measurement_id")
                or item.get("reason")
            )
            candidates[key] = item
        for conflict in result.conflicts:
            conflicts[conflict.conflict_id] = conflict
        for name, value in result.stats.items():
            if name == "deterministic":
                stats[name] = max(stats.get(name, 0), value)
            else:
                stats[name] = stats.get(name, 0) + value
    return MergeResult(
        measurements=list(measurements.values()),
        conflicts=list(conflicts.values()),
        candidates=list(candidates.values()),
        stats=stats,
    )


def _fallback(
    reason: str, error_code: str, *, meta: dict[str, Any] | None = None
) -> LlmAnalysis:
    """Deterministic-only result that records why the LLM pass stopped."""
    payload: dict[str, Any] = dict(meta or {})
    payload.setdefault("error_code", error_code)
    payload.setdefault("error", reason)
    return LlmAnalysis(
        status="fallback",
        mode="deterministic",
        llm=payload,
        issues=[
            {
                "code": "llm_analysis_fallback",
                "message": (
                    f"LLM analysis fell back to the deterministic path: {reason}"
                ),
                "severity": "warning",
                "evidence_ids": [],
                "related_fact_id": None,
            }
        ],
    )


@register(after="markdown")
class PatentStage:
    name = "patent"

    def execute(self, ctx: PipelineContext) -> StageResult:
        if ctx.run_id is None:
            return StageResult(
                stage=self.name,
                status="error",
                message="Missing run context",
                error_code=PipelineErrorCode.MISSING_CONTEXT,
                recoverable=False,
            )

        from mbforge.service.pipeline.cancellation import (
            default_registry,
            make_cancel_check,
        )

        cancel_check = make_cancel_check(default_registry, ctx.task_id)

        analysis = LlmAnalysis()
        try:
            outcome = self._extract(ctx, cancel_check)
            signature = evidence_signature(
                (item.evidence_id, item.page, item.kind, item.raw_text)
                for item in outcome.evidence
            )
            analysis = self._llm_analysis(ctx, outcome, cancel_check, signature)
            measurements = (
                analysis.merge.measurements
                if analysis.merge is not None
                else list(outcome.measurements)
            )
            issues = [*outcome.issues, *analysis.issues]
            # The model's associations land on the designations they name — the one
            # place its judgement is consumed, and it can only name a structure this
            # document already recognized. They are applied before the artifact is
            # built, because a resolved designation changes what its readings join to.
            linked = apply_gap_links(
                outcome.entries,
                analysis.links,
                doc_id=ctx.doc_id,
                sections=outcome.sections,
                candidates=ctx.candidates,
                measurements=measurements,
                attributions=[
                    *outcome.names,
                    *outcome.characterizations,
                    *outcome.routes,
                ],
            )
            if analysis.links:
                # The same association also decides which printed passages now have an
                # owner, so their reports are re-derived from the state it produced —
                # a passage it attributed must not keep saying it names nothing.
                issues[:] = [
                    issue for issue in issues if issue["code"] not in FAMILY_ISSUE_CODES
                ] + _family_issues(
                    outcome.characterizations, outcome.names, outcome.routes
                )
            if linked:
                # A designation the model resolved after the rule pass had run is a
                # declared entry now, so the association runs again: the readings
                # that cite it bind in this run instead of waiting for a re-run, and
                # what stays unowned is reported rather than left silent.
                associate_facts(
                    outcome.sections,
                    outcome.entries,
                    outcome.assay_methods,
                    measurements,
                    ctx.candidates,
                    {item.evidence_id for item in outcome.evidence},
                    issues,
                )
            artifact = PatentFactsArtifact(
                doc_id=ctx.doc_id,
                run_id=ctx.run_id,
                sections=[
                    PatentSectionModel(
                        section_id=section.section_id,
                        title=section.title,
                        kind=section.kind,
                        page_start=section.page_start,
                        page_end=section.page_end,
                        evidence_ids=list(section.evidence_ids),
                    )
                    for section in outcome.sections
                ],
                entries=outcome.entries,
                assay_methods=outcome.assay_methods,
                examples=outcome.examples,
                measurements=measurements,
                structure_activity=outcome.structure_activity,
                synthesis_steps=outcome.routes,
                names=outcome.names,
                characterizations=outcome.characterizations,
                issues=issues,
                analysis_status=analysis.status,
                extraction_mode=analysis.mode,
                conflicts=(
                    [conflict.model_dump() for conflict in analysis.merge.conflicts]
                    if analysis.merge is not None
                    else []
                ),
                review_candidates=(
                    [
                        _candidate_payload(candidate)
                        for candidate in analysis.merge.candidates
                    ]
                    if analysis.merge is not None
                    else []
                ),
                llm=analysis.llm,
                coverage=analysis.coverage,
                stats={
                    "section_count": len(outcome.sections),
                    "entry_count": len(outcome.entries),
                    "example_count": len(outcome.examples),
                    "assay_method_count": len(outcome.assay_methods),
                    "measurement_count": len(measurements),
                    "route_count": len(outcome.routes),
                    "synthesis_step_count": sum(
                        int(route.get("step_count") or 0) for route in outcome.routes
                    ),
                    "name_count": len(outcome.names),
                    "characterization_count": len(outcome.characterizations),
                    "unattributed_count": sum(
                        1
                        for item in (
                            *outcome.characterizations,
                            *outcome.names,
                            *outcome.routes,
                        )
                        if item["attribution"] == "unresolved"
                    ),
                    "issue_count": len(issues),
                    "llm_links_applied": linked,
                    "analysis_status": analysis.status,
                    "extraction_mode": analysis.mode,
                    "llm_merge": (
                        analysis.merge.stats if analysis.merge is not None else {}
                    ),
                },
            )
            publication = patent_facts.publish_document_facts(
                ctx.library_root,
                doc_id=ctx.doc_id,
                artifact=artifact,
                evidence_signature=signature,
                candidates=ctx.candidates,
            )
        except Exception as exc:
            from mbforge.service.pipeline.cancellation import TaskCancelledError

            if isinstance(exc, TaskCancelledError):
                raise
            logger.exception("Patent fact extraction failed for %s", ctx.doc_id)
            return StageResult(
                stage=self.name,
                status="error",
                message=f"Patent fact extraction failed: {exc}",
                error_code=PipelineErrorCode.PATENT_EXTRACTION_FAILED,
                recoverable=False,
            )

        logger.info(
            "Patent facts committed for %s (revision %d): %d sections, %d entries, "
            "%d examples, %d assay methods, %d measurements, %d issues, analysis=%s "
            "(run %s, projection_ok=%s)",
            ctx.doc_id,
            publication.revision,
            len(outcome.sections),
            len(outcome.entries),
            len(outcome.examples),
            len(outcome.assay_methods),
            len(measurements),
            len(issues),
            analysis.status,
            ctx.run_id,
            publication.projection_ok,
        )
        message = (
            f"Extracted {len(outcome.sections)} sections, "
            f"{len(outcome.entries)} entries, "
            f"{len(outcome.examples)} examples, "
            f"{len(outcome.assay_methods)} assay methods, "
            f"{len(measurements)} measurements, "
            f"committed revision {publication.revision} with "
            f"{publication.molecule_count} activity-backed molecules"
        )
        if analysis.merge is not None:
            message += (
                f"; LLM merge: {analysis.merge.stats['conflict']} conflicts, "
                f"{len(analysis.merge.candidates)} review candidates"
            )
        elif analysis.status == "fallback":
            message += "; LLM analysis fell back to the deterministic path"
        status = "success"
        recoverable = False
        if not publication.projection_ok:
            # The facts are committed (SQL is authoritative); only the file needs
            # rebuilding, so the stage warns instead of failing the run.
            status = "warning"
            recoverable = True
            message += "; the facts are committed but the file projection needs repair"
        return StageResult(
            stage=self.name,
            status=status,
            recoverable=recoverable,
            message=message,
            context={
                "section_count": len(outcome.sections),
                "entry_count": len(outcome.entries),
                "example_count": len(outcome.examples),
                "assay_method_count": len(outcome.assay_methods),
                "measurement_count": len(measurements),
                "molecule_count": publication.molecule_count,
                "issue_count": len(issues),
                "revision": publication.revision,
                "projection_ok": publication.projection_ok,
                "analysis_status": analysis.status,
                "extraction_mode": analysis.mode,
                "conflict_count": (
                    len(analysis.merge.conflicts) if analysis.merge is not None else 0
                ),
                "review_candidate_count": (
                    len(analysis.merge.candidates) if analysis.merge is not None else 0
                ),
                "run_id": ctx.run_id,
                "artifact_path": str(publication.projection_path),
            },
        )

    def _llm_analysis(
        self,
        ctx: PipelineContext,
        outcome: ExtractionOutcome,
        cancel_check: Any,
        signature: str,
    ) -> LlmAnalysis:
        """Run the optional LLM pass over the rule draft and merge the result.

        Every failure here is a *fallback*, not a stage failure: the rule facts
        are already complete and remain publishable. Only a user cancellation is
        propagated, so the queue records a cancelled task instead of a fallback.
        """
        from mbforge.foundation.config import load_global_config
        from mbforge.service.pipeline.cancellation import TaskCancelledError

        config = load_global_config().patent_analysis
        if not config.enabled:
            return LlmAnalysis()

        try:
            runtime = get_patent_analysis_runtime()
        except RuntimeError as exc:
            return _fallback(str(exc), "runtime_unconfigured")

        not_ready = runtime.ensure_ready()
        if not_ready:
            return _fallback(not_ready, "sidecar_not_ready")
        if not ctx.run_id:
            return _fallback("the run id is missing", "missing_run_id")

        evidence = outcome.evidence
        pages = {item.evidence_id: item.page for item in evidence}
        scope = PatentTaskScope(
            library_root=str(ctx.library_root),
            doc_id=ctx.doc_id,
            run_id=ctx.run_id,
            attempt_id=short_id(),
            evidence_signature=signature,
            budget=PatentAnalysisBudget(
                max_model_turns=config.max_model_turns,
                wall_clock_seconds=config.wall_clock_seconds,
                max_total_tokens=config.max_total_tokens,
                digest_char_budget=config.digest_char_budget,
                request_timeout_seconds=config.request_timeout_seconds,
            ),
        )
        gaps, skipped_gaps = build_gaps(
            issues=outcome.issues,
            evidence=evidence,
            structures=ctx.candidates,
            entries=outcome.entries,
            # One run does what its turns can answer and reports what it left: a list
            # longer than the budget cannot finish, and an unfinished list leaves a
            # ``partial`` that says nothing about the document (measured: 40 gaps,
            # 24 turns, 39 never processed).
            max_gaps=min(
                DEFAULT_MAX_GAPS, max(1, config.max_model_turns // TURNS_PER_GAP)
            ),
            excerpt_char_budget=config.digest_char_budget,
        )

        cancel_state = {"cancelled": False}

        def should_cancel() -> bool:
            if cancel_state["cancelled"]:
                return True
            try:
                cancel_check()
            except TaskCancelledError:
                cancel_state["cancelled"] = True
                return True
            return False

        if not gaps:
            # Nothing to model: the rules named no gap, so no provider call is
            # needed at all. The document stays deterministic and says why.
            if should_cancel():
                raise TaskCancelledError(ctx.task_id)
            return LlmAnalysis(
                status="succeeded",
                mode="deterministic",
                merge=None,
                llm={
                    "ok": True,
                    "status": "succeeded",
                    "turns": 0,
                    "tool_calls": 0,
                    "tokens": None,
                    "duration_ms": 0,
                    "model": "",
                    "prompt_version": "",
                    "error_code": None,
                    "error": None,
                    "gaps": {
                        "total": 0,
                        "answered": 0,
                        "unanswerable": 0,
                        "not_processed": 0,
                    },
                    "submissions": 0,
                },
                coverage=None,
                issues=[],
            )

        try:
            result = runtime.run(
                scope,
                gaps=gaps,
                should_cancel=should_cancel,
                on_event=_progress_emitter(ctx),
            )
        except TaskCancelledError:
            raise
        except Exception as exc:  # noqa: BLE001 — a fallback, not a stage failure
            logger.warning("Patent LLM analysis failed for %s: %s", ctx.doc_id, exc)
            return _fallback(str(exc), "analysis_failed")

        meta = result.outcome.model_dump()
        by_page: dict[int, list[str]] = {}
        for item in evidence:
            by_page.setdefault(item.page, []).append(item.evidence_id)
        reads = result.evidence_reads
        complete_pages = [
            page for page, ids in by_page.items() if all(reads.get(id) for id in ids)
        ]
        unread_pages = [
            page for page, ids in by_page.items() if not any(id in reads for id in ids)
        ]
        document = get_repositories(ctx.library_root).documents.get(ctx.doc_id)
        page_count = int((document or {}).get("page_count") or 0)
        coverage = EvidenceReadCoverage(
            total_evidence=len(evidence),
            complete_evidence=sum(
                reads.get(item.evidence_id, False) for item in evidence
            ),
            partial_evidence=sum(
                item.evidence_id in reads and not reads[item.evidence_id]
                for item in evidence
            ),
            complete_pages=sorted(complete_pages),
            partial_pages=sorted(
                set(by_page) - set(complete_pages) - set(unread_pages)
            ),
            unread_pages=sorted(unread_pages),
            no_evidence_pages=sorted(set(range(1, page_count + 1)) - set(by_page)),
        )
        answers = [
            answer for answer in result.gap_answers if answer.status == "answered"
        ]
        unanswerable = [
            answer for answer in result.gap_answers if answer.status == "unanswerable"
        ]
        links = [
            link.model_dump()
            for answer in result.gap_answers
            for link in (getattr(answer, "links", None) or [])
        ]
        meta["gaps"] = {
            "total": len(gaps),
            "answered": len(answers),
            "unanswerable": len(unanswerable),
            "not_processed": len(gaps) - len(result.gap_answers),
            "skipped": dict(skipped_gaps),
        }
        meta["submissions"] = len(result.gap_answers)
        if result.outcome.status == "cancelled" or cancel_state["cancelled"]:
            raise TaskCancelledError(ctx.task_id)
        if not answers:
            fallback = _fallback(
                result.outcome.error or "the analysis answered no gap",
                result.outcome.error_code or "no_submission",
                meta=meta,
            )
            fallback.coverage = coverage
            return fallback

        # A run that stops early (budget, timeout, disconnect) still hands over
        # every gap answer it validated, so those facts are merged rather than
        # thrown away; the status records that the run did not finish.
        # A method-only answer for an attribution gap omits the readings by design:
        # Python rebuilds them from the rule facts, so the model never retypes a value.
        gap_by_id = {gap.gap_id: gap for gap in gaps}
        merge = _combine_merges(
            [
                merge_submission(
                    doc_id=ctx.doc_id,
                    rule_measurements=outcome.measurements,
                    rule_assay_methods=outcome.assay_methods,
                    submission=_answer_submission(
                        answer,
                        scope,
                        _recorded_items(
                            answer, gap_by_id.get(answer.gap_id), outcome.measurements
                        )
                        or None,
                    ),
                    evidence_pages=pages,
                    scope_evidence_ids=_answer_scope(answer, gaps),
                    scope_fact_ids=_answer_fact_scope(answer, gaps),
                )
                for answer in answers
            ]
        )
        finished = result.outcome.ok and result.outcome.complete
        issues: list[dict[str, Any]] = []
        if not finished:
            reason = result.outcome.error or "the run stopped before finishing"
            issues.append(
                {
                    "code": "llm_analysis_incomplete",
                    "message": (
                        "LLM analysis stopped early; the gaps it answered are "
                        f"published, the rest stays deterministic: {reason}"
                    ),
                    "severity": "warning",
                    "evidence_ids": [],
                    "related_fact_id": None,
                }
            )
        for answer in unanswerable:
            issues.append(
                {
                    "code": "llm_gap_unanswerable",
                    "message": (
                        f"gap {answer.gap_id} was left unresolved "
                        f"({answer.unanswerable_reason or 'no reason given'})"
                    ),
                    "severity": "info",
                    "evidence_ids": list(answer.evidence_ids),
                    "related_fact_id": None,
                }
            )
        dropped = int(merge.stats.get("unattributed", 0) or 0)
        if dropped:
            issues.append(
                {
                    "code": "llm_item_unattributed",
                    "message": (
                        f"{dropped} LLM reading(s) named no compound and no "
                        "structure and were dropped instead of queued for review"
                    ),
                    "severity": "info",
                    "evidence_ids": [],
                    "related_fact_id": None,
                }
            )
        return LlmAnalysis(
            status="succeeded" if finished else "partial",
            mode="hybrid",
            merge=merge,
            links=links,
            llm=meta,
            coverage=coverage,
            issues=issues,
        )

    def _extract(self, ctx: PipelineContext, cancel_check) -> ExtractionOutcome:
        """Read SQL evidence once and project all Patent facts."""
        from mbforge.service.pipeline.activity.extraction import (
            extract_activity_measurements_from_evidence,
        )
        from mbforge.service.pipeline.artifacts.evidence_join import (
            load_document_evidence,
        )
        from mbforge.service.pipeline.artifacts.hydration import load_detections

        source_evidence = load_document_evidence(ctx.library_root, ctx.doc_id)
        sections = parse_source_evidence_sections(source_evidence, ctx.doc_id)

        all_entries: list[dict] = []
        seen_entry_ids: set[str] = set()
        all_assay_methods: list[dict] = []
        seen_assay_method_ids: set[str] = set()
        blocks_by_id = {item.evidence_id: item for item in source_evidence}
        for section in sections:
            cancel_check()
            if section.page_start is None or section.page_end is None:
                raise ValueError("section page range is unavailable")
            source_ids = section.title_evidence_ids
            declared_here = 0

            for entry_dict in extract_entries_from_title(
                section.title,
                ctx.doc_id,
                section.section_id,
                section.page_start,
                evidence_ids=source_ids,
            ):
                if entry_dict["entry_id"] in seen_entry_ids:
                    continue
                seen_entry_ids.add(entry_dict["entry_id"])
                all_entries.append(entry_dict)
                declared_here += 1

            for entry_dict in extract_entries_from_body(
                [
                    (evidence_id, blocks_by_id[evidence_id].raw_text)
                    for evidence_id in section.evidence_ids
                    if evidence_id in blocks_by_id
                ],
                ctx.doc_id,
                section.section_id,
                _entry_role(section.kind),
            ):
                if entry_dict["entry_id"] in seen_entry_ids:
                    continue
                seen_entry_ids.add(entry_dict["entry_id"])
                all_entries.append(entry_dict)
                declared_here += 1

            if declared_here == 0:
                identity = _example_identity_entry(section, ctx.doc_id)
                if identity is not None and identity["entry_id"] not in seen_entry_ids:
                    seen_entry_ids.add(identity["entry_id"])
                    all_entries.append(identity)

            method_dict = extract_assay_method_from_title(
                section.title,
                ctx.doc_id,
                section.section_id,
                section.page_start,
                section.page_end,
                evidence_ids=source_ids,
            )
            if (
                method_dict is not None
                and method_dict["assay_method_id"] not in seen_assay_method_ids
            ):
                seen_assay_method_ids.add(method_dict["assay_method_id"])
                all_assay_methods.append(method_dict)

        measurements, issues = extract_activity_measurements_from_evidence(
            source_evidence, ctx.doc_id
        )
        candidates = list(ctx.candidates)
        if not candidates:
            detection_result = load_detections(ctx.library_root, ctx.doc_id)
            if detection_result is not None:
                candidates = detection_result[0]
        ctx.candidates = candidates
        characterizations = extract_characterization(source_evidence, ctx.doc_id)
        # A printed mass that disagrees with the structure claiming that label is
        # evidence for a correction, not a correction: it becomes a review item and
        # only a human's confirm rewrites the SMILES. It runs after the printed
        # passages are read, because that is what it compares against.
        for mismatch in find_mass_mismatches(characterizations, candidates):
            issues.append(
                {
                    "code": "smiles_mass_mismatch",
                    "message": (
                        f"{mismatch['label_key']}: printed m/z "
                        f"{mismatch['printed_mz']} [{mismatch['adduct']}] vs "
                        f"calculated {mismatch['calculated_mass']} "
                        f"(Δ {mismatch['delta']:+.3f} Da)"
                    ),
                    "severity": "warning",
                    "evidence_ids": list(mismatch["evidence_ids"][:50]),
                    "related_fact_id": mismatch["mol_id"],
                    "mol_id": mismatch["mol_id"],
                    "printed_mz": mismatch["printed_mz"],
                    "calculated_mass": mismatch["calculated_mass"],
                    "delta": mismatch["delta"],
                    "adduct": mismatch["adduct"],
                    "structure_smiles": mismatch["structure_smiles"],
                    "raw_text": mismatch["raw_text"],
                }
            )
        associate_facts(
            sections,
            all_entries,
            all_assay_methods,
            measurements,
            candidates,
            {item.evidence_id for item in source_evidence},
            issues,
        )

        routes = extract_synthesis_routes(sections, blocks_by_id, ctx.doc_id)
        names = extract_compound_names(sections, blocks_by_id, ctx.doc_id)
        # A patent also names products mid-paragraph; without this the only
        # names recorded are the ones a heading happened to state.
        names.extend(extract_prose_compound_names(source_evidence, ctx.doc_id))
        _backfill_entry_names(all_entries, names)
        characterizations = extract_characterization(source_evidence, ctx.doc_id)
        issues.extend(_family_issues(characterizations, names, routes))
        # The document declares its own structure-activity mapping in each example
        # heading; joining through that declaration is what turns a reading into
        # (structure, value) without guessing at a detected label.
        structure_activity = _declared_structure_activity(
            source_evidence, measurements, candidates, ctx.doc_id, ctx.library_root
        )

        return ExtractionOutcome(
            sections=sections,
            entries=all_entries,
            assay_methods=all_assay_methods,
            examples=_example_facts(sections),
            measurements=measurements,
            issues=issues,
            routes=routes,
            names=names,
            characterizations=characterizations,
            structure_activity=structure_activity,
            evidence=list(source_evidence),
        )


def _candidate_designations(candidate: Any) -> set[str]:
    """The designations a recognised structure answers to.

    A crop's printed label lives on the candidate's ``name`` and on its OCR label
    properties; the designation an example heading declares (``化合物8`` -> ``8``)
    has to match one of them.
    """
    from mbforge.service.pipeline.patent.association import _candidate_label_keys

    keys = set(_candidate_label_keys(candidate))
    name = getattr(candidate, "name", "")
    if isinstance(name, str) and name.strip():
        keys.add(name.strip())
    return keys


def _declared_structure_activity(
    evidence: Sequence[SourceEvidence],
    measurements: Sequence[dict],
    candidates: Sequence[Any],
    doc_id: str,
    library_root: str,
) -> list[dict]:
    """Pair each reading with the structure its example heading declares.

    Returns artifact-shaped dicts. A reading with no declared structure is simply
    absent: the document named the compound but drew nothing, and reporting a
    pair there would mean inventing a structure.

    The structures are read from the library's ``molecules`` table, not from
    *candidates*: the candidates this stage receives are the raw recognition
    results (Markush scaffolds included, labelled ``I-A``/``II-A``), while the
    concrete compound the pipeline stored — ``name='8'`` with a plain SMILES — is
    the one an example heading's designation points at.
    """
    from mbforge.service.pipeline.patent.declared_pairs import (
        extract_declared_examples,
        pair_structure_activity,
        recover_by_product_mass,
    )

    structures = _stored_structures_by_designation(library_root, doc_id)
    examples = extract_declared_examples(evidence, doc_id)
    if not examples:
        return []
    pairs = (
        pair_structure_activity(examples, measurements, structures)
        if structures
        else []
    )
    # A drawing whose label OCR missed is still in the library, unnamed. The
    # example's printed product mass identifies it when exactly one structure
    # reproduces that mass.
    unnamed = _stored_unnamed_structures(library_root, doc_id)
    if unnamed:
        paired_keys = {pair.declared_key for pair in pairs}
        pairs.extend(recover_by_product_mass(examples, paired_keys, unnamed))
    return [
        {
            "declared_key": pair.declared_key,
            "measurement_id": pair.measurement_id,
            "smiles": pair.smiles,
            "metric": pair.metric,
            "value": pair.value,
            "unit": pair.unit,
            "verified_by_mass": pair.verified_by_mass,
            "printed_mz": pair.printed_mz,
            "calculated_mz": pair.calculated_mz,
        }
        for pair in pairs
    ]


def _stored_unnamed_structures(library_root: str, doc_id: str) -> list[str]:
    """Concrete structures of this document that carry no printed designation.

    These are the drawings whose crop-label OCR missed. They are the reserve a
    product mass can identify.
    """
    from mbforge.service.ports import get_repositories

    rows = get_repositories(library_root).molecules.designated_structures(doc_id)
    out: list[str] = []
    for row in rows:
        name = str(row.get("name") or "").strip()
        smiles = str(row.get("canonical_smiles") or "").strip()
        if not name and smiles and "*" not in smiles:
            out.append(smiles)
    return out


def _stored_structures_by_designation(library_root: str, doc_id: str) -> dict[str, str]:
    """``{printed designation: canonical SMILES}`` for this document's structures.

    Only concrete compounds are included: a Markush scaffold's ``name`` is a
    scheme label (``I-A``), never the designation an activity table prints for a
    finished compound.
    """
    from mbforge.service.ports import get_repositories

    rows = get_repositories(library_root).molecules.designated_structures(doc_id)
    structures: dict[str, str] = {}
    for row in rows:
        key = str(row.get("name") or "").strip()
        smiles = str(row.get("canonical_smiles") or "").strip()
        if key and smiles and "*" not in smiles:
            structures.setdefault(key, smiles)
    return structures
