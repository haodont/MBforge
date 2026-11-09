"""Turn the rule issues into a bounded gap worklist.

A rule issue is how the deterministic path says *where* it stopped: the code
says what it could not read, ``evidence_ids`` say where. This module is the one
place that maps an issue to a bounded unit of work — a :class:`PatentGap` —
that carries the verbatim excerpt an answer is judged against.

The worklist is derived, never searched: enumeration stays Python's job, so the
model never has to rebuild the list by reading the document again.
"""

from __future__ import annotations

import re
from collections.abc import Callable, Mapping, Sequence
from typing import Any

from mbforge.contracts.patent import _MAX_TEXT, GapKind, PatentGap
from mbforge.domain.evidence import SourceEvidence
from mbforge.domain.evidence_kind import category_of
from mbforge.domain.molecule import Molecule
from mbforge.domain.patent import designation_key
from mbforge.service.pipeline.activity.normalization import find_activity_metrics
from mbforge.service.pipeline.activity.parsing.tables import activity_table_excerpts
from mbforge.service.pipeline.persist.molecules import filter_persistable_candidates

#: Issue code -> the kind of gap it describes. An issue code outside this map
#: is not a modelling gap (budget, coverage, transport) and produces no work.
GAP_KINDS: dict[str, GapKind] = {
    "complex_activity_table": "table",
    "unsupported_table_format": "table",
    "activity_value_unparsed": "prose_measurement",
    "activity_reference_missing": "prose_measurement",
    "compound_reference_unresolved": "prose_measurement",
    "assay_method_unresolved": "assay_attribution",
    # Association is where rules stop and the model earns its place: the passage
    # is already read, only its owner is unknown. These five codes existed as
    # reports for a long time while never reaching a gap, so the association work
    # the deterministic pass cannot do was never handed to anyone.
    "characterization_attribution": "prose_measurement",
    "synthesis_route_unresolved": "assay_attribution",
    "compound_name_unresolved": "prose_measurement",
    "molecule_label_unresolved": "prose_measurement",
    "molecule_candidate_ambiguous": "prose_measurement",
}

#: Draw-down order: the refused tables hold the most readings per excerpt, then
#: attribution (a measurement already exists), then single prose readings.
KIND_ORDER: tuple[GapKind, ...] = (
    "table",
    "assay_attribution",
    "assay_method",
    "prose_measurement",
)

#: Marker appended when an excerpt had to be clipped. A clipped excerpt must
#: never read as a complete one; the model can ask for the rest by page.
TRUNCATION_MARK = "\n[…excerpt truncated; the gap's pages are listed above…]"

DEFAULT_MAX_GAPS = 40
#: Turns one gap is expected to need: read the excerpt, at most one tool call, submit.
#: The live v3 run took 3 turns for an accepted table answer (including the retry a
#: contract rejection cost) and 2 turns for each gap it could not answer, so a
#: worklist longer than ``max_model_turns // TURNS_PER_GAP`` guarantees a run that
#: dies mid-list — 40 gaps, 24 turns, 39 never processed, and ``partial`` for an
#: outcome that was never in doubt. Sizing the list to the budget lets the run finish
#: and report the work it left, which ``skipped`` already carries.
TURNS_PER_GAP = 3
DEFAULT_EXCERPT_CHARS = 8000
#: The contract's own cap on ``excerpt``. A budget above it (or a single evidence row
#: that is itself longer: a structure payload stored as raw_text) would build a gap
#: the contract rejects, and one invalid gap fails the whole stage. The contract wins.
MAX_EXCERPT_CHARS = _MAX_TEXT

#: A qualitative bin is meaningless without the bound it stands for
#: (``"++++" 1nM<IC50<20nM``, ``注 "+"：IC50>1μM``). Those definition lines are
#: selected as nearby, citable context, never a document-wide assay default.
_LEGEND_LINE_RE = re.compile(
    r"(?:注|Note)?\s*[“\"'(\[]?\s*(?:\+{1,4}|[十]{1,4})\s*[”\"')\]]?\s*[:：]?\s*"
    r".{0,40}?(?:IC|EC)\s*_?\s*\d+",
    re.IGNORECASE,
)
#: How a row prints an owned designation: ``化合物77``, ``实施例1``, ``Compound 7``.
_DESIGNATION_MARKER = (
    r"(?:化合物|实施例|实例|化合物号|第|Compound|Example|Ex\.?|No\.?)\s*"
)
MAX_GAP_STRUCTURES = 20
#: Passages one grouped gap may carry. A document prints hundreds of spectra, names
#: and routes; the page is the unit one answer can cover, and the contract's own
#: limit is what the model can cite back.
MAX_GAP_PASSAGES = 20

#: Reports for a passage whose owner the rules could not read. They are emitted
#: by ``patent.rules.characterization._family_issues`` one per passage, and
#: grouped here: attributing them one gap per row would cost a model turn for
#: every printed spectrum.
FAMILY_ISSUE_CODES: tuple[str, ...] = (
    "characterization_attribution",
    "compound_name_unresolved",
    "synthesis_route_unresolved",
)

#: Reports about a *designation* no structure claims. Also grouped by page: one
#: document prints dozens of them (34 in one corpus document) and an answer may cite
#: up to 50 links, so one gap can settle a whole page.
DESIGNATION_ISSUE_CODES: tuple[str, ...] = (
    "molecule_label_unresolved",
    "molecule_candidate_ambiguous",
)

#: Codes whose issues on one page become a single work item.
GROUPED_WORK_CODES: tuple[str, ...] = FAMILY_ISSUE_CODES + DESIGNATION_ISSUE_CODES

#: Evidence categories a gap may be built on. A ``molecule`` row is a detection
#: payload — a JSON blob, not a printed passage — and handing it over as an excerpt
#: produced a live run that read it and answered ``no_attribution``: correct, and
#: pure waste. A designation located only on a payload is reported, not sent.
_PRINTED_CATEGORIES = ("text", "table")


def build_gaps(
    *,
    issues: Sequence[Mapping[str, Any]],
    evidence: Sequence[SourceEvidence],
    structures: Sequence[Molecule] | None = None,
    entries: Sequence[Mapping[str, Any]] = (),
    max_gaps: int = DEFAULT_MAX_GAPS,
    excerpt_char_budget: int = DEFAULT_EXCERPT_CHARS,
) -> tuple[list[PatentGap], dict[str, int]]:
    """Return ``(gaps, skipped)`` for one attempt.

    ``skipped`` counts, per code, the work left over — either because the issue
    names no location (nothing to hand over) or because *max_gaps* was reached.
    Leftover work is reported, never silently dropped.

    ``structures`` are the document's recognized molecules. A gap whose excerpt
    prints labels those structures own carries them, so the answer can be tied to
    a concrete structure without another round trip. Nearby method/legend
    passages carry their own IDs as candidate context, never global defaults.
    """
    by_id = {row.evidence_id: row for row in evidence if row.evidence_id}
    catalogue = _structure_catalogue(structures or [], entries)
    entries_by_id = {str(entry.get("entry_id") or ""): entry for entry in entries}

    def _issue_rows(issue: Mapping[str, Any]) -> list[SourceEvidence]:
        """The printed rows a gap may be built on for one issue.

        An association issue about a *designation* cites the candidates it could not
        choose between, and a candidate's evidence is a detection payload — JSON, not
        a passage. The passage the designation printed in is named by the *entry* the
        issue points at, so that is what travels; a payload is never an excerpt.
        """
        rows = _rows(issue, by_id)
        entry = entries_by_id.get(str(issue.get("related_fact_id") or ""))
        if entry:
            declared = [
                by_id[evidence_id]
                for evidence_id in (entry.get("evidence_ids") or [])
                if isinstance(evidence_id, str) and evidence_id in by_id
            ]
            known = {row.evidence_id for row in declared}
            rows = declared + [row for row in rows if row.evidence_id not in known]
        return [row for row in rows if _is_printed(row)]

    skipped: dict[str, int] = {}
    built: list[PatentGap] = []
    seen_ids: dict[str, int] = {}
    seen_work: set[tuple[str, tuple[str, ...]]] = set()

    for kind in KIND_ORDER:
        consumed: set[int] = set()
        for index, issue in enumerate(issues):
            code = str(issue.get("code", ""))
            if GAP_KINDS.get(code) != kind or index in consumed:
                continue
            if not _rows(issue, by_id):
                _bump(skipped, f"{code}:no_location")
                consumed.add(index)
                continue
            rows = _issue_rows(issue)
            if not rows:
                # A detection payload is not a passage: there is nothing for a
                # reader to read, so the report stands and the model stays out of it.
                _bump(skipped, f"{code}:no_text_location")
                consumed.add(index)
                continue
            passages: list[dict[str, Any]] = []
            designations: list[dict[str, Any]] = []
            if code in GROUPED_WORK_CODES:
                # One passage, or one designation, per gap costs a turn each and a
                # document has hundreds of both, so one code's work is filled into a
                # single item up to the passage budget: an answer may cite 50 links.
                issue, rows, related = _grouped_work(
                    issues, _issue_rows, index, code, consumed
                )
                if not rows:
                    _bump(skipped, f"{code}:no_location")
                    continue
                passages = [
                    {
                        "evidence_id": row.evidence_id,
                        "page": row.page,
                        "raw_text": (row.raw_text or "")[:400],
                    }
                    for row in rows[:MAX_GAP_PASSAGES]
                ]
                if code in DESIGNATION_ISSUE_CODES:
                    entries_by_id = {
                        str(entry.get("entry_id") or ""): entry for entry in entries
                    }
                    designations = [
                        {
                            "label_raw": str(
                                entries_by_id[fact_id].get("label_raw") or ""
                            ),
                            "label_key": str(
                                entries_by_id[fact_id].get("label_key") or ""
                            ),
                        }
                        for fact_id in related
                        if fact_id in entries_by_id
                    ][:MAX_GAP_PASSAGES]
            else:
                consumed.add(index)
            # One table that raises the same issue once per row is one work item,
            # not fifteen: identical excerpts would be paid for fifteen times.
            work = (code, tuple(row.evidence_id for row in rows))
            if work in seen_work:
                _bump(skipped, f"{code}:same_location")
                continue
            seen_work.add(work)
            excerpts = (
                activity_table_excerpts(rows[0].raw_text)
                if kind == "table" and len(rows) == 1
                else [(None, [])]
            )
            for index in range(len(excerpts)):
                excerpt, row_labels = excerpts[index]
                if len(built) >= max_gaps:
                    _bump(skipped, f"{code}:over_cap")
                    continue
                gap = _gap(
                    issue=issue,
                    kind=kind,
                    rows=rows,
                    seen_ids=seen_ids,
                    excerpt_char_budget=excerpt_char_budget,
                    context_rows=_context_rows(rows, evidence),
                    catalogue=catalogue,
                    excerpt=excerpt,
                    row_labels=row_labels,
                    passages=passages,
                    designations=designations,
                )
                if len(excerpts) > 1:
                    gap.rule_context["table_chunk"] = index + 1
                    gap.rule_context["table_chunks"] = len(excerpts)
                built.append(gap)
    return built, skipped


def _context_rows(
    rows: Sequence[SourceEvidence], evidence: Sequence[SourceEvidence]
) -> list[SourceEvidence]:
    """Nearby assay/legend passages are candidates for scope, not global defaults."""
    pages = {row.page for row in rows}
    owned = {row.evidence_id for row in rows}
    positions = {row.evidence_id: index for index, row in enumerate(evidence)}
    anchor = positions.get(rows[0].evidence_id, 0)
    candidates = [
        row
        for row in evidence
        if row.evidence_id not in owned
        and row.doc_id == rows[0].doc_id
        and category_of(row.kind) == "text"
        and row.raw_text.strip()
        and min(abs(row.page - page) for page in pages) <= 1
        and (
            find_activity_metrics(row.raw_text)
            or _LEGEND_LINE_RE.search(row.raw_text)
            or re.search(r"\b(?:assay|FLIPR|HTRF)\b|测定|试验", row.raw_text, re.I)
        )
    ]
    candidates.sort(
        key=lambda row: (
            min(abs(row.page - page) for page in pages),
            abs(positions[row.evidence_id] - anchor),
        )
    )
    # shortcut: adjacent pages only; use request_excerpt for a distant definition.
    return candidates[:6]


def _normalise(text: str) -> str:
    return re.sub(r"\s+", "", str(text or "")).casefold()


def _structure_catalogue(
    structures: Sequence[Molecule], entries: Sequence[Mapping[str, Any]]
) -> list[dict[str, Any]]:
    """``{label, mol_id, name, page}`` per recognized structure, label-indexed."""
    catalogue: list[dict[str, Any]] = []
    for structure in filter_persistable_candidates("", list(structures), warn=False):
        properties = dict(getattr(structure, "properties", {}) or {})
        labels: list[str] = []
        for key in (
            "ocr_labels_primary",
            "ocr_labels",
            "raw_coref_label",
            "normalized_label",
            "label",
            "formula_label",
        ):
            value = properties.get(key)
            if isinstance(value, str):
                labels.append(value)
            elif isinstance(value, (list, tuple)):
                labels.extend(item for item in value if isinstance(item, str))
        if getattr(structure, "name", None):
            labels.append(str(structure.name))
        identity = structure.mol_id or structure.canonical_smiles
        labels.extend(
            str(entry["label_raw"])
            for entry in entries
            if entry.get("entity_id") in {identity, structure.canonical_smiles}
            and entry.get("label_raw")
            and entry.get("structure_status") == "resolved"
        )
        detections = list(getattr(structure, "detections", []) or [])
        catalogue.append(
            {
                "labels": labels,
                # Hydrated candidates keep their identity in canonical_smiles and
                # leave mol_id empty; the service's own payload takes the same
                # fallback, because an empty id here is an unusable reference.
                "mol_id": (
                    getattr(structure, "mol_id", "")
                    or getattr(structure, "canonical_smiles", "")
                    or ""
                ),
                "name": getattr(structure, "name", "") or "",
                "page": detections[0].page + 1 if detections else None,
            }
        )
    return catalogue


def _structures_for(text: str, catalogue: Sequence[Mapping[str, Any]]) -> list[dict]:
    """The structures whose printed label this text actually designates.

    Two passes, because a bare number in a table cell is ambiguous by itself:
    ``| 化合物77 | 37 |`` prints the designation 77 and the reading 37, so a
    token match alone hands the model the structure labelled 37. A label counts
    when it follows a designation marker (``化合物``, ``实施例``, ``Compound``…)
    anywhere in the text; only when this text uses no marker at all does a plain
    token match apply (``| 1 | ++++ |``). Matching is boundary-aware on the
    whitespace-stripped text: a substring test would match the label ``3`` inside
    ``26.3`` and the ``1`` inside ``1nM``.
    """
    haystack = _normalise(text)
    marked: list[dict] = []
    plain: list[dict] = []
    for entry in catalogue:
        for label in entry.get("labels") or []:
            needle = _normalise(label)
            if not needle:
                continue
            escaped = re.escape(needle)
            tail = r"(?![0-9a-z.\-%])"
            if re.search(_DESIGNATION_MARKER + escaped + tail, haystack):
                marked.append(_structure_entry(entry, label))
            elif re.search(r"(?<![0-9a-z.\-%])" + escaped + tail, haystack):
                plain.append(_structure_entry(entry, label))
    found = marked or plain
    return list({(item["label"], item["mol_id"]): item for item in found}.values())[
        :MAX_GAP_STRUCTURES
    ]


def _structure_entry(entry: Mapping[str, Any], label: Any) -> dict:
    return {
        "label": str(label),
        "mol_id": entry.get("mol_id") or "",
        "name": entry.get("name") or "",
        "page": entry.get("page"),
    }


def _rows(
    issue: Mapping[str, Any], by_id: Mapping[str, SourceEvidence]
) -> list[SourceEvidence]:
    return [
        by_id[evidence_id]
        for evidence_id in (issue.get("evidence_ids") or [])
        if isinstance(evidence_id, str) and evidence_id in by_id
    ]


def _is_printed(row: SourceEvidence) -> bool:
    """Whether a row is something a reader can read (a passage or a table)."""
    return category_of(row.kind) in _PRINTED_CATEGORIES


def _grouped_work(
    issues: Sequence[Mapping[str, Any]],
    rows_of: Callable[[Mapping[str, Any]], list[SourceEvidence]],
    index: int,
    code: str,
    consumed: set[int],
) -> tuple[Mapping[str, Any], list[SourceEvidence], list[str]]:
    """Merge one code's issues into single work items, filled to the passage budget.

    Returns the merged issue, its printed rows, and the fact ids it names (the
    entries whose designations the group is about, when it is about designations).
    The group is filled to ``MAX_GAP_PASSAGES`` rows, because an answer may cite up
    to fifty links while a document prints hundreds of passages. ``rule_context``
    carries each passage's page and the candidates' pages, so the same-page decider
    the prompt asks for has what it needs without one gap per page (measured: that
    page bound tripled the corpus worklist, 142 → 503 gaps, for no evidence).
    """
    grouped: list[int] = []
    collected: dict[str, SourceEvidence] = {}
    related: list[str] = []
    for other, candidate in enumerate(issues):
        if other in consumed or str(candidate.get("code", "")) != code:
            continue
        located = rows_of(candidate)
        if not located:
            continue
        grouped.append(other)
        for row in located:
            collected.setdefault(row.evidence_id, row)
        fact_id = str(candidate.get("related_fact_id") or "")
        if fact_id:
            related.append(fact_id)
        if len(collected) >= MAX_GAP_PASSAGES:
            break
    consumed.update(grouped)
    rows = list(collected.values())
    pages = sorted({int(row.page) for row in rows if row.page})
    span = f"page {pages[0]}" if len(pages) <= 1 else f"pages {pages[0]}-{pages[-1]}"
    merged = {
        "code": code,
        "message": (
            f"{code}: {len(rows)} printed passage(s) on {span} name a designation this "
            "document does not resolve"
        ),
        "related_fact_id": None,
    }
    return merged, rows, list(dict.fromkeys(related))


def _gap(
    *,
    issue: Mapping[str, Any],
    kind: GapKind,
    rows: list[SourceEvidence],
    seen_ids: dict[str, int],
    excerpt_char_budget: int,
    context_rows: Sequence[SourceEvidence],
    catalogue: Sequence[Mapping[str, Any]],
    excerpt: str | None = None,
    row_labels: Sequence[str] = (),
    passages: Sequence[Mapping[str, Any]] = (),
    designations: Sequence[Mapping[str, Any]] = (),
) -> PatentGap:
    code = str(issue.get("code", ""))
    evidence_ids = [row.evidence_id for row in rows]
    pages = sorted({int(row.page) for row in rows if row.page})
    if excerpt is None:
        excerpt = "\n\n".join(row.raw_text for row in rows if row.raw_text)

    if excerpt_char_budget > 0 and len(excerpt) > excerpt_char_budget:
        excerpt = excerpt[:excerpt_char_budget] + TRUNCATION_MARK
    if len(excerpt) > MAX_EXCERPT_CHARS:
        excerpt = excerpt[: MAX_EXCERPT_CHARS - len(TRUNCATION_MARK)] + TRUNCATION_MARK

    context: dict[str, Any] = {}
    # IDs accompany the visible text, so context can be cited without a tool turn.
    context["evidence"] = []
    work_budget = min(max(0, excerpt_char_budget), MAX_EXCERPT_CHARS)
    for row in rows:
        if work_budget <= 0:
            break
        full_text = excerpt if len(rows) == 1 else row.raw_text
        text = full_text[:work_budget]
        context["evidence"].append(
            {
                "evidence_id": row.evidence_id,
                "page": row.page,
                "role": "work",
                "raw_text": text,
                "truncated": len(text) < len(full_text) or TRUNCATION_MARK in text,
            }
        )
        work_budget -= len(text)
    context["work_evidence_ids"] = list(evidence_ids)
    context_budget = max(0, min(excerpt_char_budget, MAX_EXCERPT_CHARS))
    for row in context_rows:
        if context_budget <= 0:
            break
        text = row.raw_text[:context_budget]
        context["evidence"].append(
            {
                "evidence_id": row.evidence_id,
                "page": row.page,
                "role": "context",
                "raw_text": text,
                "truncated": len(text) < len(row.raw_text),
            }
        )
        evidence_ids.append(row.evidence_id)
        context_budget -= len(text)
    messages = [str(issue.get("message", ""))[:400]]
    if messages[0]:
        context["rule_reason"] = messages[0]
    related = issue.get("related_fact_id")
    if isinstance(related, str) and related:
        context["related_fact_id"] = related[:128]
    if passages:
        # Grouped work: every passage names its own evidence row, so the answer can
        # cite one link per passage and Python matches it by that row.
        context["passages"] = [dict(item) for item in passages][:MAX_GAP_PASSAGES]
    if designations:
        # The merged report names the labels, so a grouped gap tells the model which
        # designations it is settling rather than only which rows it is reading.
        context["designations"] = [dict(item) for item in designations][
            :MAX_GAP_PASSAGES
        ]
    # Structures whose printed label appears here: the answer can name one of
    # them, so the reading lands on a concrete structure instead of a string.
    # Legends contain thresholds, not additional compound designations.
    structure_text = excerpt
    if row_labels:
        structure_text = " | ".join(row_labels)
        context["row_labels"] = list(row_labels)
    if row_labels and re.search(
        r"实施例|実施例|example", excerpt.splitlines()[0], re.I
    ):
        context["row_label_type"] = "example"
        keys = {designation_key(f"Example {label}").casefold() for label in row_labels}
        keys.discard("")
        structures = [
            _structure_entry(entry, label)
            for entry in catalogue
            for label in dict.fromkeys(entry["labels"])
            if designation_key(label).casefold() in keys
        ][:MAX_GAP_STRUCTURES]
    else:
        structures = _structures_for(structure_text, catalogue)
    if structures:
        context["structures"] = structures
    return PatentGap(
        gap_id=_gap_id(code, evidence_ids[0], seen_ids),
        gap_kind=kind,
        code=code,
        message=str(issue.get("message", ""))[:400],
        page_start=pages[0] if pages else None,
        page_end=pages[-1] if pages else None,
        evidence_ids=evidence_ids[:50],
        excerpt=excerpt,
        rule_context=context,
    )


def _gap_id(code: str, first_evidence_id: str, seen_ids: dict[str, int]) -> str:
    """Anchor the id to the issue's first evidence row so it survives re-runs."""
    base = f"{code}:{first_evidence_id}"
    seen_ids[base] = seen_ids.get(base, 0) + 1
    return base if seen_ids[base] == 1 else f"{base}:{seen_ids[base]}"


def _bump(counter: dict[str, int], key: str) -> None:
    counter[key] = counter.get(key, 0) + 1


__all__ = [
    "DEFAULT_EXCERPT_CHARS",
    "DEFAULT_MAX_GAPS",
    "DESIGNATION_ISSUE_CODES",
    "FAMILY_ISSUE_CODES",
    "GAP_KINDS",
    "GROUPED_WORK_CODES",
    "KIND_ORDER",
    "MAX_GAP_PASSAGES",
    "TURNS_PER_GAP",
    "build_gaps",
]
