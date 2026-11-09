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
from mbforge.domain.patent_analysis import evidence_signature
from mbforge.foundation.ids import short_id
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
from mbforge.service.ports import get_patent_analysis_runtime, get_repositories
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
                    scope_work_evidence_ids=(
                        gap_by_id[answer.gap_id].rule_context.get("work_evidence_ids")
                        if answer.gap_id in gap_by_id
                        else None
                    ),
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
