"""Stage 4: the single SQL-backed patent-facts parser.

Patent consumes the SourceEvidence rows written by the Extract/Detection
Join. Sections, entries, examples, assay methods, and activity measurements
are assembled once and published as ``patent_facts.json``.

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
from dataclasses import dataclass
from typing import Any

from mbforge.core.stage import PipelineErrorCode, StageResult, register
from mbforge.pipeline.patent.artifact import PatentFactsArtifact, PatentSectionModel
from mbforge.pipeline.patent.association import associate_facts
from mbforge.pipeline.patent.sections import _HEADING_RE, parse_source_evidence_sections
from mbforge.pipeline.patent.sections import ParsedSection as DocumentSection
from mbforge.pipeline.run.context import PipelineContext
from mbforge.utils.logger import get_logger

logger = get_logger("mbforge.pipeline.stages.patent")

#: Target compounds declared in a section title, e.g. ``化合物13和14``.
_COMPOUND_LABEL = r"\d{1,4}[A-Za-z]?(?:-[A-Za-z])?"
_COMPOUND_TOKEN_RE = re.compile(
    rf"(?:化合物\s*(?P<zh>{_COMPOUND_LABEL}(?:\s*和\s*{_COMPOUND_LABEL})*)|"
    rf"compound\s+(?P<en>{_COMPOUND_LABEL}(?:\s+and\s+{_COMPOUND_LABEL})*))",
    re.IGNORECASE,
)

#: Internal compound codes in parentheses, e.g. ``(IGP-20024-01)``.
_CODE_RE = re.compile(r"[（(]([A-Za-z][A-Za-z0-9\-]{2,})[)）]")

#: Assay-declaring titles; Latin potency tokens match case-insensitively.
_ASSAY_HINT_RE = re.compile(
    r"抑制活性|激动活性|拮抗活性|结合活性|抑制率|(?i:IC50|EC50|Ki)"
    r"|活性测定|生物活性|药理|活性测试"
)

#: Target named after ``对`` in a title, e.g. ``对MRGPRX2受体抑制活性``.
_ASSAY_TARGET_RE = re.compile(r"对\s*(?P<target>[A-Za-z][A-Za-z0-9\-]*)")

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


def extract_entries_from_title(
    title: str,
    doc_id: str,
    section_id: str,
    page_num: int,
    *,
    evidence_ids: list[str] | None = None,
) -> list[dict]:
    """Extract title-declared compound entries (spec §5.1 decision 3).

    Returns ``CompoundEntry.to_dict()``-shaped dicts.
    """
    from mbforge.core.patent import (
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
    for match in _COMPOUND_TOKEN_RE.finditer(title):
        labels = match.group("zh") or match.group("en") or ""
        for label in re.split(r"\s*(?:和|and)\s*", labels, flags=re.I):
            label = label.strip()
            if not label:
                continue
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


def extract_assay_method_from_title(
    title: str,
    doc_id: str,
    section_id: str,
    page_num: int,
    page_end: int,
    *,
    evidence_ids: list[str] | None = None,
) -> dict | None:
    """Extract the assay method declared by a section title (spec §5.3).

    Returns ``AssayMethod.to_dict()`` or ``None`` when the title carries
    no assay hint. ``comparison_key`` stays ``None`` — never
    auto-generated (spec §5.5).
    """
    from mbforge.core.activity import AssayMethod, assay_method_id

    if not _ASSAY_HINT_RE.search(title):
        return None

    target = None
    target_match = _ASSAY_TARGET_RE.search(title)
    if target_match:
        target = target_match.group("target")
    endpoint = next(
        (mapped for kw, mapped in _ASSAY_ENDPOINT_MAP.items() if kw in title), None
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


def _measurement_has_activity(measurement: dict[str, Any]) -> bool:
    """Return whether an entry-linked Patent measurement has an actual reading."""
    entry_id = measurement.get("compound_entry_id")
    if not isinstance(entry_id, str) or not entry_id.strip():
        return False
    value = measurement.get("value")
    if not isinstance(value, dict):
        return False
    return any(
        value.get(key) not in (None, "")
        for key in (
            "canonical_value",
            "original_value",
            "qualitative_value",
            "raw_text",
        )
    )


def _persist_activity_backed_molecules(
    ctx: PipelineContext, outcome: ExtractionOutcome
) -> int:
    """Persist only concrete candidates with a linked Patent measurement."""
    from mbforge.pipeline.persist.molecules import (
        delete_document_molecule_rows,
        filter_persistable_candidates,
        persist_molecule_candidates,
    )
    from mbforge.storage.sqlite.database import DatabaseManager

    candidates_by_smiles = {
        candidate.canonical_smiles.strip(): candidate
        for candidate in ctx.candidates
        if isinstance(getattr(candidate, "canonical_smiles", None), str)
        and candidate.canonical_smiles.strip()
    }
    measurements_by_smiles: dict[str, list[dict[str, Any]]] = {}
    for measurement in outcome.measurements:
        if not isinstance(measurement, dict) or not _measurement_has_activity(
            measurement
        ):
            continue
        entry_id = measurement.get("compound_entry_id")
        entry = next(
            (item for item in outcome.entries if item.get("entry_id") == entry_id),
            None,
        )
        smiles = entry.get("entity_id") if isinstance(entry, dict) else None
        if isinstance(smiles, str) and smiles.strip() in candidates_by_smiles:
            measurements_by_smiles.setdefault(smiles.strip(), []).append(measurement)

    eligible = [
        candidates_by_smiles[smiles]
        for smiles in measurements_by_smiles
        if smiles in candidates_by_smiles
    ]
    eligible = filter_persistable_candidates(ctx.doc_id, eligible, warn=False)
    if not eligible:
        return 0

    db = DatabaseManager.get(str(ctx.library_root))
    with db.transaction() as (_kb_conn, mol_conn):
        # Refresh document-scoped derived rows so a Patent retry does not
        # duplicate detections/evidence for the same document.
        delete_document_molecule_rows(mol_conn, ctx.doc_id)
        persist_molecule_candidates(
            str(ctx.library_root),
            ctx.doc_id,
            eligible,
            conn=mol_conn,
        )
        for candidate in eligible:
            measurement = measurements_by_smiles[candidate.canonical_smiles.strip()][0]
            value = measurement.get("value") or {}
            canonical_value = value.get("canonical_value")
            if canonical_value is None:
                canonical_value = value.get("original_value")
            units = value.get("canonical_unit") or value.get("original_unit") or ""
            mol_conn.execute(
                """
                UPDATE molecules
                SET activity = ?, activity_type = ?, units = ?
                WHERE mol_id = ?
                """,
                (
                    canonical_value,
                    measurement.get("metric") or "activity",
                    units,
                    candidate.canonical_smiles,
                ),
            )

    return len(eligible)


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

        from mbforge.pipeline.cancellation import default_registry, make_cancel_check

        cancel_check = make_cancel_check(default_registry, ctx.task_id)

        try:
            outcome = self._extract(ctx, cancel_check)
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
                measurements=outcome.measurements,
                issues=outcome.issues,
                stats={
                    "section_count": len(outcome.sections),
                    "entry_count": len(outcome.entries),
                    "example_count": len(outcome.examples),
                    "assay_method_count": len(outcome.assay_methods),
                    "measurement_count": len(outcome.measurements),
                    "issue_count": len(outcome.issues),
                },
            )
            molecule_count = _persist_activity_backed_molecules(ctx, outcome)
            from mbforge.pipeline.artifacts.staging import publish_run

            artifact_path = publish_run(
                ctx.library_root, ctx.doc_id, ctx.run_id, patent_facts=artifact
            )
        except Exception as exc:
            from mbforge.pipeline.cancellation import TaskCancelledError

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
            "Patent facts published for %s: %d sections, %d entries, "
            "%d examples, %d assay methods, %d measurements, %d issues (run %s)",
            ctx.doc_id,
            len(outcome.sections),
            len(outcome.entries),
            len(outcome.examples),
            len(outcome.assay_methods),
            len(outcome.measurements),
            len(outcome.issues),
            ctx.run_id,
        )
        message = (
            f"Extracted {len(outcome.sections)} sections, "
            f"{len(outcome.entries)} entries, "
            f"{len(outcome.examples)} examples, "
            f"{len(outcome.assay_methods)} assay methods, "
            f"{len(outcome.measurements)} measurements, "
            f"persisted {molecule_count} activity-backed molecules"
        )
        return StageResult(
            stage=self.name,
            status="success",
            message=message,
            context={
                "section_count": len(outcome.sections),
                "entry_count": len(outcome.entries),
                "example_count": len(outcome.examples),
                "assay_method_count": len(outcome.assay_methods),
                "measurement_count": len(outcome.measurements),
                "molecule_count": molecule_count,
                "issue_count": len(outcome.issues),
                "run_id": ctx.run_id,
                "artifact_path": str(artifact_path),
            },
        )

    def _extract(self, ctx: PipelineContext, cancel_check) -> ExtractionOutcome:
        """Read SQL evidence once and project all Patent facts."""
        from mbforge.pipeline.activity.extraction import (
            extract_activity_measurements_from_evidence,
        )
        from mbforge.pipeline.artifacts.evidence_join import load_document_evidence
        from mbforge.pipeline.artifacts.hydration import load_detections

        source_evidence = load_document_evidence(ctx.library_root, ctx.doc_id)
        sections = parse_source_evidence_sections(source_evidence, ctx.doc_id)

        all_entries: list[dict] = []
        seen_entry_ids: set[str] = set()
        all_assay_methods: list[dict] = []
        seen_assay_method_ids: set[str] = set()
        for section in sections:
            cancel_check()
            if section.page_start is None or section.page_end is None:
                raise ValueError("section page range is unavailable")
            source_ids = section.title_evidence_ids

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
        associate_facts(
            sections,
            all_entries,
            all_assay_methods,
            measurements,
            candidates,
            {item.evidence_id for item in source_evidence},
            issues,
        )

        return ExtractionOutcome(
            sections=sections,
            entries=all_entries,
            assay_methods=all_assay_methods,
            examples=_example_facts(sections),
            measurements=measurements,
            issues=issues,
        )
