"""Scope-bound tool operations for one Patent-analysis attempt.

Every operation resolves its credential to the attempt's bound scope first, so a
tool call can only ever read the document that attempt was bound to: the model
supplies evidence ids, filters and page windows — never a path, a library root
or another document id.

The unit of work is one gap: Python enumerates what the rules refused to read,
hands over a bounded excerpt, and accepts one validated answer per gap. Business
failures (a foreign evidence id, an answer that violates the contract) come back
as ``success=False`` plus a message the model can act on; an unknown or expired
credential is a real request error.
"""

from __future__ import annotations

import re
from typing import Any

from pydantic import ValidationError as PydanticValidationError

from mbforge.contracts.patent import PatentGap, PatentGapAnswer
from mbforge.contracts.patent_runtime import PatentTaskScope
from mbforge.domain.evidence import SourceEvidence
from mbforge.domain.evidence_kind import category_of
from mbforge.foundation.errors import ValidationError
from mbforge.foundation.logger import get_logger
from mbforge.service.pipeline.activity.normalization import find_activity_metrics
from mbforge.service.pipeline.activity.parsing.tables import table_cell_matches
from mbforge.service.pipeline.artifacts.hydration import load_detections
from mbforge.service.pipeline.persist.molecules import filter_persistable_candidates
from mbforge.service.ports.patent_analysis import get_patent_task_registry
from mbforge.service.use_cases.documents.source_evidence import (
    list_evidence,
    resolve,
)

#: Per-call bounds: the session gets pagination signals, never the whole document.
MAX_TEXT_CHARS = 2000
MAX_EVIDENCE_IDS = 50
MAX_READ_ROWS = 200
MAX_PAGE_SPAN = 20
MAX_PAGE_SIZE = 50

logger = get_logger(__name__)


def list_molecules(
    credential: str, *, page: int = 1, page_size: int = 50, label: str = ""
) -> dict[str, Any]:
    """List the bound document's recognized structures (never creates one).

    ``label`` narrows the answer to the structures that carry one printed
    designation. The comparison runs in the same key space the association itself
    uses, so ``化合物77``, ``77`` and ``实施例7`` all find the structures labelled
    ``77`` — including the several that make the designation ambiguous — instead of
    leaving the model to page through the whole catalogue blind.
    """
    scope = _scope(credential)
    invalid = _invalid_paging(page, page_size)
    if invalid:
        return _failure(invalid)
    loaded = load_detections(scope.library_root, scope.doc_id)
    candidates = filter_persistable_candidates(
        scope.doc_id, list(loaded[0]) if loaded else [], warn=False
    )
    asked = _label_tokens(label) if label.strip() else set()
    if asked:
        candidates = [
            item for item in candidates if asked & _molecule_label_tokens(item)
        ]
    candidates.sort(
        key=lambda item: (
            item.name or "",
            item.canonical_smiles or "",
            item.mol_id or "",
        )
    )
    start = (page - 1) * page_size
    window = candidates[start : start + page_size]
    return {
        "success": True,
        "tool": "list_molecules",
        "label": label,
        "items": [_molecule_payload(molecule) for molecule in window],
        "total": len(candidates),
        "page": page,
        "page_size": page_size,
        "has_more": start + page_size < len(candidates),
    }


def get_gap(credential: str, *, gap_id: str = "") -> dict[str, Any]:
    """Return one bounded gap, or the next unanswered one.

    The gap is the unit of work: what the rules refused to read, where it is,
    and the verbatim excerpt an answer is judged against. Enumeration belongs
    to Python, so the session never rebuilds this list by reading the document.

    The attempt's identity travels with the gap for the host to bind submissions.
    """
    scope = _scope(credential)  # authorization: unknown credentials are rejected
    registry = get_patent_task_registry()
    gap = registry.gap(credential, gap_id) if gap_id else registry.next_gap(credential)
    if gap is None:
        return _failure(
            "unknown gap for this attempt" if gap_id else "all gaps are answered"
        )
    answered = {answer.gap_id for answer in registry.gap_answers(credential)}
    return {
        "success": True,
        "tool": "get_gap",
        "doc_id": scope.doc_id,
        "attempt_id": scope.attempt_id,
        "evidence_signature": scope.evidence_signature,
        "gap": {
            "gap_id": gap.gap_id,
            "gap_kind": gap.gap_kind,
            "code": gap.code,
            "message": gap.message,
            "page_start": gap.page_start,
            "page_end": gap.page_end,
            "evidence_ids": list(gap.evidence_ids),
            "excerpt": gap.excerpt,
            "rule_context": dict(gap.rule_context),
        },
        "answered": len(answered),
        "remaining": len(registry.gaps(credential)) - len(answered),
    }


def request_excerpt(
    credential: str,
    *,
    gap_id: str,
    evidence_ids: list[str] | None = None,
    page_from: int | None = None,
    page_to: int | None = None,
) -> dict[str, Any]:
    """Fetch the one bounded follow-up excerpt a gap may ask for.

    The excerpt boundary is chosen before its content is seen, so a gap whose
    header, caption or legend falls just outside it needs a bounded second look.
    One per gap, capped like a normal read: this is an escape hatch, not a
    search tool.
    """
    scope = _scope(credential)
    registry = get_patent_task_registry()
    gap = registry.gap(credential, gap_id)
    if gap is None:
        return _failure("unknown gap for this attempt")
    if gap_id in {answer.gap_id for answer in registry.gap_answers(credential)}:
        return _failure("this gap is already answered")
    items = _excerpt_items(
        scope,
        evidence_ids=evidence_ids,
        page_from=page_from,
        page_to=page_to,
    )
    if isinstance(items, str):
        return _failure(items)
    refusal = registry.record_gap_excerpt(
        credential, gap_id, [item["evidence_id"] for item in items]
    )
    if refusal:
        return _failure(refusal)
    if gap.rule_context.get("evidence"):
        gap.rule_context["evidence"] = [
            *gap.rule_context["evidence"],
            *({**item, "role": "context"} for item in items),
        ]
    registry.record_evidence_reads(credential, items)
    return {
        "success": True,
        "tool": "request_excerpt",
        "items": items,
        "note": "this was the one follow-up excerpt for this gap; answer with it.",
    }


def submit_gap_answer(credential: str, answer: dict[str, Any]) -> dict[str, Any]:
    """Validate one gap answer against its gap and stage it.

    Check shape, bound identity and evidence membership. Packet-backed tables
    also require literal row/cell/metric support; semantic attribution and
    adoption still need the merge and review.
    """
    scope = _scope(credential)
    registry = get_patent_task_registry()
    try:
        parsed = PatentGapAnswer.model_validate(answer)
    except PydanticValidationError as exc:
        # A rejection has to teach the shape. A run that submitted four correct
        # readings lost two turns guessing the key that holds the number, so the
        # failure names the reading shapes instead of only the offending path.
        return _failure(
            "answer does not satisfy the contract",
            errors=_contract_errors(exc),
            expected_reading={
                "numeric": {
                    "metric": "CYP3A4抑制率",
                    "value": {
                        "raw_text": "26.3",
                        "operator": "=",
                        "value": 26.3,
                        "unit": "%",
                    },
                    "compound_label_raw": "化合物77",
                    "row_label_raw": "化合物77",
                    "compound_label_key": "77",
                    "molecule_ref": "<a mol_id from this gap's rule_context.structures>",
                },
                "qualitative": {
                    "metric": "IC50",
                    "value": {"raw_text": "++", "qualitative": "++"},
                    "row_label_raw": "实施例1",
                    "compound_label_key": "1",
                },
            },
        )
    gap = registry.gap(credential, parsed.gap_id)
    if gap is None:
        return _failure("answer names a gap that is not part of this attempt")
    if parsed.gap_kind != gap.gap_kind:
        return _failure(
            f"answer kind {parsed.gap_kind!r} does not match the gap's {gap.gap_kind!r}"
        )
    if parsed.doc_id != scope.doc_id:
        return _failure("answer is bound to a different document")
    if parsed.attempt_id != scope.attempt_id:
        return _failure("answer belongs to a stale attempt")
    if parsed.evidence_signature != scope.evidence_signature:
        return _failure(
            "answer was computed from a stale evidence set; re-read the gap and "
            "resubmit"
        )
    row_labels = gap.rule_context.get("row_labels") or []
    if row_labels:
        from mbforge.domain.patent import designation_key

        example_rows = gap.rule_context.get("row_label_type") == "example"

        def normalize(value: str) -> str:
            key = designation_key(value) or _LABEL_PREFIX_RE.sub("", value)
            if example_rows and not key.startswith("@example:"):
                key = designation_key(f"Example {key}") or key
            return key.strip(_LABEL_TRIM).casefold()

        allowed_labels = {normalize(label) for label in row_labels}
        if any(
            normalize(item.row_label_raw or item.compound_label_raw)
            not in allowed_labels
            for item in parsed.items
        ):
            return _failure("answer contains a row outside the assigned table chunk")
    allowed = registry.gap_evidence_ids(credential, parsed.gap_id)
    outside = sorted(_cited_evidence_ids(parsed) - allowed)
    if outside:
        return _failure(
            "answer cites evidence outside this gap's excerpt",
            outside_evidence_ids=outside[:10],
            outside_count=len(outside),
        )
    foreign = _foreign_ids(scope, sorted(_cited_evidence_ids(parsed)))
    if foreign:
        return _failure(
            "answer cites evidence outside the bound document",
            foreign_evidence_ids=foreign[:10],
            foreign_count=len(foreign),
        )
    support_errors = _table_support_errors(parsed, gap)
    if support_errors:
        return _failure(
            "table readings must quote a supplied data row, not a context definition",
            errors=support_errors,
        )
    # The model reads the number; the label-to-structure link is deterministic
    # and belongs here. A live run was handed ``77 -> mol_id`` and still
    # submitted an empty molecule_ref, so the gap's own list settles it instead
    # of the prompt.
    parsed, attached, conflicts = _attach_gap_structures(parsed, gap)
    if conflicts:
        return _failure(
            "structure choice is ambiguous or contradicts the printed row; leave molecule_ref empty",
            conflicting_rows=conflicts,
        )
    parsed = _normalise_links(parsed)
    unknown_refs = _unknown_molecule_refs(scope, parsed, gap)
    if unknown_refs:
        return _failure(
            "molecule_ref must be a label key or mol_id returned by list_molecules",
            unknown_molecule_refs=unknown_refs[:10],
            unknown_count=len(unknown_refs),
        )
    unknown_links = _unknown_link_structures(scope, parsed, gap)
    if unknown_links:
        return _failure(
            "a linked structure must be one this document recognized",
            unknown_link_structures=unknown_links[:10],
            unknown_link_count=len(unknown_links),
        )
    if registry.is_cancelled(credential):
        return _failure("attempt was cancelled")
    registry.stage_gap_answer(credential, parsed)
    pending = registry.next_gap(credential)
    return {
        "success": True,
        "tool": "submit_gap_answer",
        "staged": True,
        "status": parsed.status,
        "counts": {
            "items": len(parsed.items),
            "assay_methods": len(parsed.assay_methods),
        },
        "structures_attached": attached,
        "next_gap_id": pending.gap_id if pending is not None else None,
    }


def _table_support_errors(answer: PatentGapAnswer, gap: PatentGap) -> list[str]:
    """Check literal cell ownership; assay semantics still need review."""
    packet = gap.rule_context.get("evidence") or []
    if gap.gap_kind != "table" or not packet:
        return []
    work = {
        row["evidence_id"]: row["raw_text"]
        for row in packet
        if row.get("role") == "work"
    }
    visible = {row["evidence_id"]: row["raw_text"] for row in packet}

    def compact(text: str) -> str:
        return re.sub(r"\s+", "", text)

    errors: list[str] = []
    for item in answer.items:
        quote = compact(item.source_quote)
        sources = [work[eid] for eid in item.evidence_ids if eid in work]
        label = compact(item.row_label_raw or item.compound_label_raw)
        value_text = compact(item.value.raw_text)
        if value_text.upper() in {"ND", "NA", "NT"}:
            errors.append(f"{item.local_key}: a no-data marker is not a reading")
        if (
            not quote
            or not any(quote in compact(text) for text in sources)
            or (label and label not in quote)
            or value_text not in quote
        ):
            errors.append(
                f"{item.local_key}: source_quote must contain the printed row label and value and occur in cited work evidence"
            )
        pipe_sources = [text for text in sources if text.lstrip().startswith("|")]
        if pipe_sources and (
            item.source_column is None
            or not any(
                table_cell_matches(
                    text,
                    item.source_quote,
                    row_label=item.row_label_raw or item.compound_label_raw,
                    raw_value=item.value.raw_text,
                    column=item.source_column,
                )
                for text in pipe_sources
            )
        ):
            errors.append(
                f"{item.local_key}: source_column must select the exact value cell paired with this printed label; quote one complete data row and never borrow a sibling pair's value"
            )
        if item.value.value is not None:
            number = re.search(r"[-+]?\d*\.?\d+(?:[eE][-+]?\d+)?", item.value.raw_text)
            if number is None or float(number[0]) != item.value.value:
                errors.append(
                    f"{item.local_key}: value.value must equal the number in value.raw_text"
                )
            printed_operator = re.match(
                r"\s*(<=|>=|<|>|≤|≥|~|≈|=)", item.value.raw_text
            )
            aliases = {"≤": "<=", "≥": ">=", "≈": "~"}
            source_operator = printed_operator[1] if printed_operator else "="
            if aliases.get(source_operator, source_operator) != aliases.get(
                item.value.operator, item.value.operator
            ):
                errors.append(
                    f"{item.local_key}: operator must preserve the printed comparison"
                )
        cited_text = "\n".join(visible.get(eid, "") for eid in item.evidence_ids)
        if not set(find_activity_metrics(item.metric)) & set(
            find_activity_metrics(cited_text)
        ):
            errors.append(
                f"{item.local_key}: metric must be explicitly stated in cited work or context evidence; request the missing definition or leave unanswerable"
            )
    return errors


#: Compound prefixes may be removed; example identities keep their own namespace.
_LABEL_PREFIX_RE = re.compile(
    r"^\s*(?:化合物号|化合物|Compound|No\.?)\s*",
    re.IGNORECASE,
)
_LABEL_TRIM = " 　:：-、,，()（）[]【】"


def _label_key(item: Any) -> str:
    """Prefer the printed designation over a model-supplied normalized key."""
    from mbforge.domain.patent import designation_key

    for candidate in (
        item.row_label_raw,
        item.compound_label_raw,
        item.compound_label_key,
    ):
        raw = str(candidate or "").strip()
        text = designation_key(raw) or _LABEL_PREFIX_RE.sub("", raw)
        text = text.strip(_LABEL_TRIM)
        if text:
            return text.casefold()
    return ""


def _attach_gap_structures(
    answer: PatentGapAnswer, gap: Any
) -> tuple[PatentGapAnswer, int, list[str]]:
    """Fill ``molecule_ref`` from the structures the gap itself identified.

    Deterministic, so it is not the model's task: ``化合物77`` is the structure
    labelled ``77``, and the gap already carries that link. Returns the answer
    with its references filled and how many readings were attached.
    """
    structures = (getattr(gap, "rule_context", None) or {}).get("structures") or []
    by_label: dict[str, set[str]] = {}
    from mbforge.domain.patent import designation_key

    for entry in structures:
        raw = str(entry.get("label", "")).strip()
        label = (designation_key(raw) or _LABEL_PREFIX_RE.sub("", raw)).casefold()
        if label and entry.get("mol_id"):
            by_label.setdefault(label, set()).add(str(entry["mol_id"]))
    attached = 0
    items = []
    conflicts: list[str] = []
    for item in answer.items:
        label_key = _label_key(item)
        if gap.rule_context.get(
            "row_label_type"
        ) == "example" and not label_key.startswith("@example:"):
            label_key = (
                designation_key(f"Example {label_key}") or label_key
            ).casefold()
        if gap.rule_context.get("row_label_type") == "example":
            item = item.model_copy(update={"compound_label_key": label_key})
        references = by_label.get(label_key, set())
        if item.molecule_ref and (
            (
                references
                and (len(references) != 1 or item.molecule_ref not in references)
            )
            or (gap.rule_context.get("row_labels") and not references)
        ):
            conflicts.append(item.row_label_raw or item.compound_label_raw)
        # A shared label is evidence of ambiguity, never a last-writer choice.
        if not item.molecule_ref and len(references) == 1:
            item = item.model_copy(update={"molecule_ref": next(iter(references))})
            attached += 1
        items.append(item)
    return answer.model_copy(update={"items": items}), attached, conflicts


def _excerpt_items(
    scope: PatentTaskScope,
    *,
    evidence_ids: list[str] | None,
    page_from: int | None,
    page_to: int | None,
) -> list[dict[str, Any]] | str:
    """Return the follow-up excerpt rows, or a message saying why not."""
    ids = [item.strip() for item in (evidence_ids or []) if item.strip()]
    if ids:
        if len(ids) > MAX_EVIDENCE_IDS:
            return f"at most {MAX_EVIDENCE_IDS} evidence ids per call"
        items: list[dict[str, Any]] = []
        for evidence_id in ids:
            row = resolve(scope.library_root, evidence_id)
            if row is None or row.doc_id != scope.doc_id:
                return "evidence ids outside the bound document"
            items.append(_evidence_payload(row))
        return items
    if page_from is None and page_to is None:
        return "provide evidence_ids or a page window"
    start = page_from or 1
    end = page_to or start
    if end < start:
        return "page_to must not be before page_from"
    if end - start + 1 > MAX_PAGE_SPAN:
        return f"a page window is limited to {MAX_PAGE_SPAN} pages"
    items = []
    for page in range(start, end + 1):
        for row in list_evidence(scope.library_root, scope.doc_id, page=page):
            if len(items) >= MAX_READ_ROWS:
                return items
            items.append(_evidence_payload(row))
    return items


def _cited_evidence_ids(answer: PatentGapAnswer) -> set[str]:
    cited: set[str] = set()
    for item in (*answer.items, *answer.assay_methods, *answer.links):
        cited.update(item.evidence_ids)
    cited.update(answer.evidence_ids)
    return cited


def _normalise_links(answer: PatentGapAnswer) -> PatentGapAnswer:
    """Recompute each link's key space from its printed label.

    The model says which structure owns ``化合物77``; the key is derived here, so a
    link can only ever meet an entry in the space Python owns.
    """
    from mbforge.domain.patent import designation_key

    if not answer.links:
        return answer
    links = [
        link.model_copy(update={"label_key": designation_key(link.label_raw)})
        for link in answer.links
    ]
    return answer.model_copy(update={"links": links})


def _unknown_link_structures(
    scope: PatentTaskScope, answer: PatentGapAnswer, gap: Any = None
) -> list[str]:
    """Linked structures that this document did not recognize."""
    if not answer.links:
        return []
    recognized = _recognized_refs(
        list((load_detections(scope.library_root, scope.doc_id) or ([], {}))[0])
    )
    for entry in (getattr(gap, "rule_context", None) or {}).get("structures") or []:
        recognized.add(str(entry.get("mol_id", "")))
        recognized.add(str(entry.get("label", "")))
    recognized.discard("")
    return [link.mol_id for link in answer.links if link.mol_id not in recognized]


def _unknown_molecule_refs(
    scope: PatentTaskScope, answer: PatentGapAnswer, gap: Any = None
) -> list[str]:
    """Refs that are not a recognized structure of this document.

    A reading may only be attached to a structure the pipeline already found — by
    label key or mol_id. A SMILES the model wrote is not a reference and never
    becomes one here. The gap's own list counts as recognized: the gap builder
    takes it from this document's structures.
    """
    refs = sorted({item.molecule_ref for item in answer.items if item.molecule_ref})
    if not refs:
        return []
    loaded = load_detections(scope.library_root, scope.doc_id)
    candidates = list(loaded[0]) if loaded else []
    known = _recognized_refs(candidates)
    for entry in (getattr(gap, "rule_context", None) or {}).get("structures") or []:
        known.add(str(entry.get("mol_id", "")))
        known.add(str(entry.get("label", "")))
    known.discard("")
    return [ref for ref in refs if ref not in known]


def _recognized_refs(candidates: Any) -> set[str]:
    known: set[str] = set()
    for molecule in filter_persistable_candidates("", list(candidates), warn=False):
        known.add(str(molecule.mol_id or ""))
        known.add(str(getattr(molecule, "canonical_smiles", "") or ""))
        known.add(str(molecule.name or ""))
        properties = dict(getattr(molecule, "properties", {}) or {})
        for key in (
            "ocr_labels_primary",
            "ocr_labels",
            "raw_coref_label",
            "normalized_label",
            "label",
        ):
            value = properties.get(key)
            if isinstance(value, str):
                known.add(value)
            elif isinstance(value, (list, tuple)):
                known.update(str(item) for item in value)
    known.discard("")
    return known


def _scope(credential: str) -> PatentTaskScope:
    scope = get_patent_task_registry().resolve((credential or "").strip())
    if scope is None:
        raise ValidationError("unknown or expired patent analysis credential")
    return scope


def _invalid_paging(page: int, page_size: int) -> str | None:
    if page < 1:
        return "page must be >= 1"
    if not 1 <= page_size <= MAX_PAGE_SIZE:
        return f"page_size must be within 1..{MAX_PAGE_SIZE}"
    return None


def _failure(message: str, **extra: Any) -> dict[str, Any]:
    """Refuse one submission, and leave a trace: a run that submits nothing is
    otherwise indistinguishable from a run whose every submission was rejected."""
    logger.warning("Rejected a gap answer: %s%s", message, f" {extra}" if extra else "")
    return {"success": False, "error": message, **extra}


def _text(value: str) -> tuple[str, bool]:
    if len(value) <= MAX_TEXT_CHARS:
        return value, False
    return value[:MAX_TEXT_CHARS] + "…", True


def _evidence_payload(evidence: SourceEvidence) -> dict[str, Any]:
    text, truncated = _text(evidence.raw_text or "")
    return {
        "evidence_id": evidence.evidence_id,
        "page": evidence.page,
        "bbox": list(evidence.bbox),
        "kind": evidence.kind,
        "category": category_of(evidence.kind),
        "raw_text": text,
        "truncated": truncated,
    }


def _label_tokens(value: str) -> set[str]:
    """The token a designation carries, whichever key space it was printed in.

    ``化合物77``, ``77``, ``Example 77`` and ``@example:77`` all yield ``77``. The
    association keeps the example space separate for *identity* — ``实施例7`` is not
    ``化合物7`` — but a lookup by a printed label must still find the structure the
    reader means, and the candidate catalogue stores either spelling.
    """
    from mbforge.domain.patent import EXAMPLE_KEY_PREFIX, designation_key

    text = designation_key(str(value or "")) or str(value or "").strip()
    token = text.removeprefix(EXAMPLE_KEY_PREFIX).strip()
    token = re.sub(r"(?i)^example\s*", "", token).strip()
    return {token.casefold()} if token else set()


def _molecule_label_tokens(molecule: Any) -> set[str]:
    """Every designation token this recognized structure answers to."""
    from mbforge.service.pipeline.patent.candidate_labels import candidate_label_keys

    tokens: set[str] = set()
    for key in candidate_label_keys(molecule):
        tokens |= _label_tokens(key)
    return tokens


def _molecule_payload(molecule: Any) -> dict[str, Any]:
    """A compact identity: enough to name a structure, nothing to re-emit.

    Full records (SMILES + E-SMILES + every label + evidence ids) run to ~800
    characters each and stay in the conversation for every later turn — 33 of
    them cost more tokens than the whole rest of the run. The model needs a
    reference, not a structure: mol_id, labels and page are enough.
    """
    detections = list(getattr(molecule, "detections", []) or [])
    properties = dict(getattr(molecule, "properties", {}) or {})
    labels = [
        str(properties[key])
        for key in (
            "ocr_labels_primary",
            "ocr_labels",
            "raw_coref_label",
            "normalized_label",
            "label",
            "formula_label",
        )
        if properties.get(key)
    ]
    return {
        "mol_id": molecule.mol_id or molecule.canonical_smiles,
        "name": molecule.name,
        "labels": labels[:3],
        "structure_role": properties.get("structure_role"),
        "page": detections[0].page if detections else None,
    }


def _contract_errors(exc: PydanticValidationError) -> list[dict[str, str]]:
    return [
        {
            "location": ".".join(str(part) for part in error.get("loc", ())),
            "message": str(error.get("msg", "")),
        }
        for error in exc.errors()[:20]
    ]


def _foreign_ids(scope: PatentTaskScope, evidence_ids: list[str]) -> list[str]:
    foreign: list[str] = []
    for evidence_id in evidence_ids:
        row = resolve(scope.library_root, evidence_id)
        if row is None or row.doc_id != scope.doc_id:
            foreign.append(evidence_id)
    return foreign


__all__ = [
    "MAX_EVIDENCE_IDS",
    "MAX_PAGE_SIZE",
    "get_gap",
    "list_molecules",
    "request_excerpt",
    "submit_gap_answer",
]
