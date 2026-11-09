"""Dual-path behaviour of the Patent stage (rule draft + optional LLM merge).

Protects: the stage keeps working with the analysis disabled or with no gap to
answer, a merge is only advertised as ``hybrid`` when a submission was actually
accepted, an LLM failure or an unready sidecar falls back to the deterministic
artifact instead of failing the stage, a timeout keeps the validated answers as
a partial result, and a cancellation stays a cancellation.

Functions under test: ``PatentStage.execute``
(``mbforge.service.pipeline.stages.patent_stage``).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import pytest

from mbforge.contracts.patent import PatentGapAnswer
from mbforge.contracts.patent_runtime import (
    PatentAnalysisEvent,
    PatentAnalysisOutcome,
    PatentAnalysisResult,
    PatentTaskScope,
)
from mbforge.db.source_evidence import persist_source_evidence
from mbforge.db.sqlite.database import DatabaseManager
from mbforge.domain.evidence import SourceEvidence
from mbforge.service.pipeline.cancellation import TaskCancelledError
from mbforge.service.pipeline.extract.text import ExtractedDocument, PageContent
from mbforge.service.pipeline.run.context import PipelineContext
from mbforge.service.pipeline.stages.patent_stage import PatentStage
from mbforge.service.ports.patent_analysis import configure_patent_analysis_runtime
from mbforge.service.use_cases.documents.patent_facts import load_patent_facts

DOC = "doc1"
#: Two prose rows, then a refused activity table: the table is what makes the
#: stage produce a gap, and a document with no gap must never call the model.
LINES = ("实施例1：化合物1的制备", "将原料溶于溶剂。")
TABLE = "| 化合物编号 | IC50 (nM) |\n| --- | --- |\n| 1 | unreadable |"
READING = "化合物1的IC50值为< 100 nM。"


@dataclass
class _FakeRuntime:
    """Records how the stage called it and answers the gaps it was handed.

    A real session answers the gaps it receives, so the fake derives its answers
    from ``gaps``: the identity triple and the evidence ids come from the gap and
    the scope, exactly as the wire contract requires.
    """

    ready_reason: str | None = None
    outcome: PatentAnalysisOutcome | None = None
    answer_status: str = "answered"
    with_answer: bool = True
    #: Answer with an assay method only, the way a session settles an
    #: ``assay_attribution`` gap (the readings stay Python's).
    assay_only: bool = False
    #: Hand the same answer back twice, as a session correcting itself does.
    repeat_answer: bool = False
    evidence_reads: dict[str, bool] = field(default_factory=dict)
    #: Associations the model made, shaped as ``PatentGapLink`` payloads.
    links: list[dict[str, Any]] = field(default_factory=list)
    calls: dict[str, Any] = field(default_factory=dict)

    def ensure_ready(self) -> str | None:
        return self.ready_reason

    def _answer(self, scope: PatentTaskScope, gap: Any) -> PatentGapAnswer:
        answered = self.answer_status == "answered"
        items: list[dict[str, Any]] = []
        if answered and not self.assay_only:
            items = [
                {
                    "local_key": "measurement-1",
                    "metric": "IC50",
                    "value": {
                        "raw_text": "IC50 = 42 nM",
                        "operator": "=",
                        "value": 42.0,
                        "unit": "nM",
                    },
                    "compound_label_raw": "化合物1",
                    "compound_label_key": "1",
                    "page": 1,
                    "evidence_ids": list(gap.evidence_ids),
                }
            ]
        return PatentGapAnswer.model_validate(
            {
                "gap_id": gap.gap_id,
                "gap_kind": gap.gap_kind,
                "doc_id": scope.doc_id,
                "attempt_id": scope.attempt_id,
                "evidence_signature": scope.evidence_signature,
                "status": self.answer_status,
                "evidence_ids": list(gap.evidence_ids),
                "links": list(self.links) if answered else [],
                "unanswerable_reason": (
                    "not_a_fact" if self.answer_status == "unanswerable" else None
                ),
                "assay_methods": (
                    [
                        {
                            "local_key": "assay-1",
                            "target": "CYP3A4",
                            "endpoint": "IC50",
                            "evidence_ids": list(gap.evidence_ids),
                        }
                    ]
                    if answered and self.assay_only
                    else []
                ),
                "items": items,
            }
        )

    def run(
        self,
        scope: PatentTaskScope,
        *,
        gaps: list[Any],
        deterministic_draft: dict[str, Any] | None = None,
        should_cancel: Any = None,
        on_event: Any = None,
    ) -> PatentAnalysisResult:
        self.calls["run"] = self.calls.get("run", 0) + 1
        self.calls["scope"] = scope
        self.calls["gaps"] = gaps
        self.calls["draft"] = deterministic_draft
        if on_event is not None:
            on_event(
                PatentAnalysisEvent(
                    kind="progress", phase="turn", turn=1, message="model turn 1"
                )
            )
        answers = []
        if self.with_answer and gaps:
            answer = self._answer(scope, gaps[0])
            answers = [answer, answer] if self.repeat_answer else [answer]
        return PatentAnalysisResult(
            outcome=self.outcome or PatentAnalysisOutcome(ok=True, status="succeeded"),
            gap_answers=answers,
            evidence_reads=self.evidence_reads,
        )

    def cancel(self, attempt_id: str) -> bool:
        return False


def _ctx(
    tmp_path: Path,
    run_id: str = "run-1",
    lines: tuple[str, ...] = LINES,
    table: str | None = TABLE,
) -> tuple[PipelineContext, list[Any]]:
    """A parsed document with seeded evidence rows and a refused activity table."""
    ctx = PipelineContext(
        pdf_path=tmp_path / "source.pdf",
        library_root=tmp_path,
        doc_id=DOC,
        run_id=run_id,
        task_id="task-1",
    )
    ctx.extracted = ExtractedDocument(
        raw_text="\n".join(lines),
        page_count=1,
        pages=[PageContent(page_num=1, text="")],
    )
    blocks = [
        SourceEvidence.create(
            doc_id=DOC,
            page=1,
            bbox=(10.0, 1000.0 - index * 40.0, 200.0, 1020.0 - index * 40.0),
            raw_text=line,
        )
        for index, line in enumerate(lines)
    ]
    if table is not None:
        blocks.append(
            SourceEvidence.create(
                doc_id=DOC,
                page=1,
                bbox=(10.0, 800.0, 200.0, 900.0),
                raw_text=table,
                kind="tab",
            )
        )
    persist_source_evidence(tmp_path, blocks)
    return ctx, blocks


def _enable_analysis(patch_config: Any) -> None:
    patch_config(lambda cfg: setattr(cfg.patent_analysis, "enabled", True))


def test_the_llm_pass_is_opt_in_and_never_called_without_a_gap(
    tmp_path: Path, patch_config: Any
) -> None:
    """Disabled: deterministic. Enabled but no gap: deterministic, no model call."""
    disabled_ctx, _ = _ctx(tmp_path)

    result = PatentStage().execute(disabled_ctx)

    assert result.status == "success"
    assert result.context["analysis_status"] == "disabled"
    assert result.context["extraction_mode"] == "deterministic"
    facts = load_patent_facts(tmp_path, DOC)
    assert facts is not None
    assert facts.analysis_status == "disabled"
    assert facts.extraction_mode == "deterministic"
    assert facts.conflicts == []
    assert facts.review_candidates == []
    assert facts.llm == {}

    _enable_analysis(patch_config)
    no_gap_root = tmp_path / "no-gaps"
    no_gap_ctx, _ = _ctx(no_gap_root)
    no_gap_ctx.doc_id = "doc-no-gaps"
    runtime = _FakeRuntime()
    configure_patent_analysis_runtime(runtime)

    no_gap_result = PatentStage().execute(no_gap_ctx)

    assert runtime.calls.get("run", 0) == 0
    assert no_gap_result.context["analysis_status"] == "succeeded"
    assert no_gap_result.context["extraction_mode"] == "deterministic"


def test_the_worklist_is_sized_to_the_turn_budget(
    tmp_path: Path, patch_config: Any
) -> None:
    """A run hands over only what its turns can answer, and reports the rest.

    The live v3 run was handed 40 gaps for a 24-turn budget: it answered one, never
    processed 39, and the artifact read ``partial`` for an outcome that was never in
    doubt. The budget decides the worklist instead, so the run can finish — and the
    work it left is already counted in ``skipped``.
    """
    _enable_analysis(patch_config)
    patch_config(lambda cfg: setattr(cfg.patent_analysis, "max_model_turns", 3))
    ctx, _ = _ctx(tmp_path)
    runtime = _FakeRuntime()
    configure_patent_analysis_runtime(runtime)

    result = PatentStage().execute(ctx)

    assert result.status == "success"
    assert len(runtime.calls["gaps"]) == 1  # 3 turns at 3 turns per gap
    facts = load_patent_facts(tmp_path, DOC)
    assert facts is not None
    assert facts.llm["gaps"]["total"] == 1
    assert facts.llm["gaps"]["skipped"], "the work left behind is reported, not hidden"


def test_an_accepted_submission_is_merged_into_a_hybrid_artifact(
    tmp_path: Path, patch_config: Any
) -> None:
    _enable_analysis(patch_config)
    ctx, blocks = _ctx(tmp_path)
    from mbforge.domain.molecule import Molecule
    from mbforge.domain.types import DetectionSource

    ctx.candidates = [
        Molecule(
            canonical_smiles="CC",
            name="1",
            properties={"ocr_labels_primary": "1"},
            detections=[
                DetectionSource(
                    source="image", page=0, evidence_id=blocks[2].evidence_id
                )
            ],
        )
    ]
    runtime = _FakeRuntime(evidence_reads={blocks[2].evidence_id: False})
    configure_patent_analysis_runtime(runtime)

    result = PatentStage().execute(ctx)

    assert result.status == "success"
    assert runtime.calls["run"] == 1
    assert result.context["analysis_status"] == "succeeded"
    assert result.context["extraction_mode"] == "hybrid"
    assert result.context["review_candidate_count"] == 1

    facts = load_patent_facts(tmp_path, DOC)
    assert facts is not None
    assert facts.extraction_mode == "hybrid"
    # The unproven LLM reading is a review candidate, never a valid measurement.
    assert facts.measurements == []
    assert facts.review_candidates[0]["reason"] == "llm_only"
    assert facts.review_candidates[0]["review_item_id"]
    assert facts.coverage is not None
    assert facts.coverage.total_evidence == 3
    assert facts.coverage.complete_evidence == 0
    assert facts.coverage.partial_evidence == 1
    assert facts.coverage.complete_pages == []
    assert facts.coverage.partial_pages == [1]

    # The session got the bound scope, the gap worklist and the rule draft.
    scope = runtime.calls["scope"]
    assert scope.doc_id == DOC
    assert scope.run_id == "run-1"
    assert scope.evidence_signature
    gap = runtime.calls["gaps"][0]
    assert gap.gap_kind == "table"
    assert gap.evidence_ids == [blocks[2].evidence_id]
    assert "IC50" in gap.excerpt
    assert gap.rule_context["structures"][0]["mol_id"] == "CC"

    # A method-only answer leaves the reading to Python: the recorded rule value is
    # published unchanged and agrees with the answer, never retyped by the model.
    recorded_root = tmp_path / "recorded"
    recorded_ctx, _ = _ctx(recorded_root, lines=(*LINES, READING), table=None)
    recorded_runtime = _FakeRuntime(assay_only=True)
    configure_patent_analysis_runtime(recorded_runtime)

    recorded_result = PatentStage().execute(recorded_ctx)

    assert recorded_result.status == "success"
    assert recorded_runtime.calls["gaps"][0].gap_kind == "assay_attribution"
    recorded = load_patent_facts(recorded_root, DOC)
    assert recorded is not None
    assert recorded.measurements[0]["value"]["raw_text"] == "< 100 nM"
    bound = [
        item
        for item in recorded.review_candidates
        if item["reason"] == "llm_only" and item["llm"]["value_text"] == "< 100 nM"
    ]
    assert len(bound) == 1
    assert bound[0]["llm"]["measurement"]["assay_local_key"] == "assay-1"

    # Two submissions in one run reach the artifact as one set: the later answer
    # supersedes the same slot instead of forking a duplicate.
    union_root = tmp_path / "union"
    union_ctx, _ = _ctx(union_root)
    union_runtime = _FakeRuntime(repeat_answer=True)
    configure_patent_analysis_runtime(union_runtime)

    PatentStage().execute(union_ctx)

    union = load_patent_facts(union_root, DOC)
    assert union is not None
    assert union.llm["gaps"]["answered"] == 2
    assert union.stats["llm_merge"]["llm_only"] == 2
    assert len(union.review_candidates) == 1


def test_an_association_reaches_the_persisted_activity(
    tmp_path: Path, patch_config: Any
) -> None:
    """The designation the rules could not bind, from the gap to the SQL row.

    The document prints a reading for ``化合物77`` and a spectrum line, and declares
    the designation nowhere — so the rule pass declares it from the print itself,
    pending review (no molecule, no SQL activity), and leaves the spectrum
    unattributed.
    One association names the structure, and everything that hung on that label
    follows in the same run: the entry it declared, the reading that joins it, the
    spectrum it attributes, the persisted activity. The failures the model answered
    are gone instead of standing as reports the run has already disproved.
    """
    _enable_analysis(patch_config)
    reading = "化合物77的IC50为4 nM。"
    spectrum = "MS (ESI) m/z: 456.2 [M+H]+"
    # No section declares ``化合物77``: the reading cites a designation the rules
    # have no entry for, so nothing in the document can own it — nor the spectrum
    # printed beside it — until a reader says which structure it is.
    ctx, blocks = _ctx(tmp_path, lines=(reading, spectrum), table=None)
    from mbforge.domain.molecule import Molecule
    from mbforge.domain.types import DetectionSource

    ctx.candidates = [
        Molecule(
            mol_id="MOL-77",
            canonical_smiles="CCOC",
            esmiles="CCOC",
            name="",
            sources=["image"],
            detections=[
                DetectionSource(
                    source="image", page=0, evidence_id=blocks[0].evidence_id
                )
            ],
            # The crop was labelled differently from the print, so no rule can match
            # the designation to it: only a reader can.
            properties={"ocr_labels": ["77A"]},
        )
    ]
    runtime = _FakeRuntime(
        links=[
            {
                "label_raw": "化合物77",
                "mol_id": "MOL-77",
                # The row the model read the designation from: the spectrum, which
                # names no owner in its own text.
                "evidence_ids": [blocks[1].evidence_id],
            }
        ]
    )
    configure_patent_analysis_runtime(runtime)

    result = PatentStage().execute(ctx)

    assert result.status == "success"
    # The rule pass cannot attach a structure to the designation, so it hands that
    # over rather than leaving the reading unowned in silence: the label is declared
    # from the print, and the structure it names is the gap.
    assert "molecule_label_unresolved" in {gap.code for gap in runtime.calls["gaps"]}
    assert "characterization_attribution" in {gap.code for gap in runtime.calls["gaps"]}
    facts = load_patent_facts(tmp_path, DOC)
    assert facts is not None
    assert facts.stats["llm_links_applied"] == 1
    # The designation the rules could not place exists as a declared entry...
    declared = [entry for entry in facts.entries if entry["label_key"] == "77"]
    assert len(declared) == 1
    assert declared[0]["entity_id"] == "CCOC"
    assert declared[0]["review_status"] == "pending"
    # ...the reading that cites it joined it...
    bound = [
        item
        for item in facts.measurements
        if (item.get("provenance") or {}).get("reference_key") == "77"
    ]
    assert len(bound) == 1
    assert bound[0]["compound_entry_id"] == declared[0]["entry_id"]
    assert bound[0]["mol_id"] == "CCOC"
    # ...the spectrum that named no owner carries the label now...
    assert len(facts.characterizations) == 1
    assert facts.characterizations[0]["label_key"] == "77"
    assert facts.characterizations[0]["attribution"] == "resolved"
    # ...and the association reached the persisted activity.
    with DatabaseManager.get(str(tmp_path)).mol_conn() as conn:
        row = conn.execute(
            "SELECT mol_id, smiles, activity, activity_type, units FROM molecules"
        ).fetchone()
    assert row is not None
    assert tuple(row) == ("CCOC", "CCOC", 4.0, "IC50", "nM")
    # The failures the model answered are not left standing.
    assert not any(
        issue["code"] in {"molecule_label_unresolved", "characterization_attribution"}
        for issue in facts.issues
    )


def test_a_degraded_analysis_publishes_partial_or_falls_back(
    tmp_path: Path, patch_config: Any
) -> None:
    """A timeout keeps the validated answers; a failure leaves the rule artifact.

    An unready sidecar never even starts an attempt, and a cancellation is raised
    rather than silently degraded.
    """
    _enable_analysis(patch_config)

    partial_root = tmp_path / "partial"
    ctx, _ = _ctx(partial_root)
    configure_patent_analysis_runtime(
        _FakeRuntime(
            outcome=PatentAnalysisOutcome(
                ok=True,
                status="succeeded",
                complete=False,
                error_code="timeout",
                error="Request timed out.",
            ),
        )
    )

    result = PatentStage().execute(ctx)

    assert result.status == "success"
    assert result.context["analysis_status"] == "partial"
    assert result.context["extraction_mode"] == "hybrid"
    facts = load_patent_facts(partial_root, DOC)
    assert facts is not None
    assert facts.analysis_status == "partial"
    assert facts.llm["submissions"] == 1
    assert facts.llm["gaps"]["answered"] == 1
    assert facts.review_candidates[0]["reason"] == "llm_only"
    assert any(issue["code"] == "llm_analysis_incomplete" for issue in facts.issues)

    # A transport failure is allowed to have spent an attempt.
    failed_root = tmp_path / "failed"
    failed_ctx, _ = _ctx(failed_root)
    configure_patent_analysis_runtime(
        _FakeRuntime(
            with_answer=False,
            outcome=PatentAnalysisOutcome(
                ok=False,
                status="failed",
                error_code="sidecar_unavailable",
                error="ConnectError: no sidecar",
            ),
        )
    )

    failed_result = PatentStage().execute(failed_ctx)

    assert failed_result.status == "success"
    assert failed_result.context["analysis_status"] == "fallback"
    assert failed_result.context["extraction_mode"] == "deterministic"
    failed_facts = load_patent_facts(failed_root, DOC)
    assert failed_facts is not None
    assert failed_facts.llm["error_code"] == "sidecar_unavailable"
    assert any(
        issue["code"] == "llm_analysis_fallback" for issue in failed_facts.issues
    )

    # An unready sidecar never even starts an attempt.
    unready_root = tmp_path / "unready"
    unready_ctx, _ = _ctx(unready_root)
    unready = _FakeRuntime(
        ready_reason="MBFORGE_AGENT_AUTOSTART=0 and no agent is listening"
    )
    configure_patent_analysis_runtime(unready)

    unready_result = PatentStage().execute(unready_ctx)

    assert unready_result.context["analysis_status"] == "fallback"
    assert unready.calls.get("run", 0) == 0
    unready_facts = load_patent_facts(unready_root, DOC)
    assert unready_facts is not None
    assert unready_facts.llm["error_code"] == "sidecar_not_ready"

    cancelled_root = tmp_path / "cancelled"
    cancelled_ctx, _ = _ctx(cancelled_root)
    configure_patent_analysis_runtime(
        _FakeRuntime(
            with_answer=False,
            outcome=PatentAnalysisOutcome(ok=False, status="cancelled"),
        )
    )

    with pytest.raises(TaskCancelledError):
        PatentStage().execute(cancelled_ctx)
