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

from dataclasses import dataclass, field

from mbforge.domain.evidence import SourceEvidence
from mbforge.domain.patent_analysis import evidence_signature
from mbforge.foundation.logger import get_logger
from mbforge.service.pipeline.patent.artifact import (
    PatentFactsArtifact,
    PatentSectionModel,
)
from mbforge.service.pipeline.patent.association import associate_facts
from mbforge.service.pipeline.patent.rules.assay import section_assay_methods
from mbforge.service.pipeline.patent.rules.characterization import (
    _family_issues,
    extract_characterization,
    extract_synthesis_routes,
    find_mass_mismatches,
)
from mbforge.service.pipeline.patent.rules.entries import (
    _backfill_entry_names,
    _declared_structure_activity,
    _entry_role,
    _example_facts,
    _example_identity_entry,
    extract_entries_from_body,
    extract_entries_from_title,
)
from mbforge.service.pipeline.patent.rules.names import (
    extract_compound_names,
    extract_prose_compound_names,
)
from mbforge.service.pipeline.patent.sections import (
    _HEADING_RE,
    parse_source_evidence_sections,
)
from mbforge.service.pipeline.patent.sections import (
    ParsedSection as DocumentSection,
)
from mbforge.service.pipeline.run.context import PipelineContext
from mbforge.service.pipeline.stage import PipelineErrorCode, StageResult, register
from mbforge.service.use_cases.documents import patent_facts

logger = get_logger("mbforge.service.pipeline.stages.patent")

__all__ = [
    "DocumentSection",
    "PatentStage",
    "_HEADING_RE",
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

        try:
            outcome = self._extract(ctx, cancel_check)
            signature = evidence_signature(
                (item.evidence_id, item.page, item.kind, item.raw_text)
                for item in outcome.evidence
            )
            measurements = list(outcome.measurements)
            issues = list(outcome.issues)
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
                analysis_status="disabled",
                extraction_mode="deterministic",
                conflicts=[],
                review_candidates=[],
                llm={},
                coverage=None,
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
                    "llm_links_applied": 0,
                    "analysis_status": "disabled",
                    "extraction_mode": "deterministic",
                    "llm_merge": {},
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
            "%d examples, %d assay methods, %d measurements, %d issues "
            "(run %s, projection_ok=%s)",
            ctx.doc_id,
            publication.revision,
            len(outcome.sections),
            len(outcome.entries),
            len(outcome.examples),
            len(outcome.assay_methods),
            len(measurements),
            len(issues),
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
                "analysis_status": "disabled",
                "extraction_mode": "deterministic",
                "conflict_count": 0,
                "review_candidate_count": 0,
                "run_id": ctx.run_id,
                "artifact_path": str(publication.projection_path),
            },
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
            title_declared = 0

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
                title_declared += 1

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

            # Body designations may name starting materials or intermediates.
            if title_declared == 0:
                identity = _example_identity_entry(section, ctx.doc_id)
                if identity is not None and identity["entry_id"] not in seen_entry_ids:
                    seen_entry_ids.add(identity["entry_id"])
                    all_entries.append(identity)

            for method_dict in section_assay_methods(ctx.doc_id, section, blocks_by_id):
                if method_dict["assay_method_id"] in seen_assay_method_ids:
                    continue
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
            source_evidence, measurements, ctx.doc_id, ctx.library_root, issues
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
