"""The Patent-analysis contract, from sample to sidecar (P0/P1).

One file, one test per boundary:

* the strict draft shape and its refusal rules (``PatentDraft``);
* slot / candidate-set / evidence signatures that retire a decision when values
  or evidence change, and the conflict + decision + snapshot round trip;
* the committed gap JSON schema bundle the Node sidecar consumes;
* the gap and gap-answer shapes pinned on strings read from the real corpus;
* the runtime boundary: the wire request carries no library path, unknown token
  usage stays unknown, a credential binds exactly one immutable scope for the
  duration of an attempt and stops working when revoked;
* the transport boundary: progress/tool events reach the caller, the staged
  answer comes back with the outcome, and a rejected, dropped or truncated
  stream is a failure — never a success.

Functions under test: ``mbforge.contracts.patent`` /
``mbforge.contracts.patent_runtime``, ``mbforge.domain.patent_analysis``,
``mbforge.contracts.schema_export.build_gap_bundle``,
``mbforge.server.patent_analysis.InMemoryPatentTaskRegistry`` /
``SidecarPatentAnalysisRuntime``, ``mbforge.service.pipeline.run.events``.
"""

from __future__ import annotations

import json
from typing import Any

import httpx
import pytest
from pydantic import ValidationError

from mbforge.contracts.patent import (
    PatentAnalysisSnapshot,
    PatentConflict,
    PatentDecision,
    PatentDraft,
    PatentGap,
    PatentGapAnswer,
)
from mbforge.contracts.patent_runtime import (
    PatentAnalysisBudget,
    PatentAnalysisEvent,
    PatentTaskScope,
)
from mbforge.contracts.schema_export import build_gap_bundle, default_gap_output_path
from mbforge.domain.patent_analysis import (
    candidate_set_signature,
    candidate_signature,
    conflict_id,
    evidence_signature,
    measurement_slot_id,
)
from mbforge.server.patent_analysis import SidecarPatentAnalysisRuntime
from mbforge.service.pipeline.run.events import PipelineEventSink
from mbforge.service.ports.patent_analysis import get_patent_task_registry

_DOC = "d" * 64
_ATTEMPT = "attempt-1"
_EVIDENCE_SIGNATURE = "sig-evidence-1"

_TEN = {"metric": "IC50", "value": 10.0, "unit": "nM", "operator": "="}
_HUNDRED = {"metric": "IC50", "value": 100.0, "unit": "nM", "operator": "="}


# ── the draft shape ─────────────────────────────────────────────────


def _draft_payload(**overrides: Any) -> dict[str, Any]:
    """A minimal valid draft: one prose assay method, two measurements."""
    payload: dict[str, Any] = {
        "protocol_version": "1",
        "doc_id": _DOC,
        "attempt_id": _ATTEMPT,
        "evidence_signature": _EVIDENCE_SIGNATURE,
        "assay_methods": [
            {
                "local_key": "assay-prose-1",
                "target": "MRGPRX2",
                "system": "human",
                "endpoint": "calcium flux",
                "evidence_ids": ["ev-assay"],
            }
        ],
        "measurements": [
            {
                "local_key": "measurement-1",
                "metric": "IC50",
                "value": {
                    "raw_text": "< 100 nM",
                    "operator": "<",
                    "value": 100.0,
                    "unit": "nM",
                },
                "compound_label_raw": "Compound 12",
                "compound_label_key": "12",
                "assay_local_key": "assay-prose-1",
                "page": 7,
                "evidence_ids": ["ev-cell"],
            },
            {
                "local_key": "measurement-2",
                "metric": "inhibition_pct",
                "value": {
                    "raw_text": "72% inhibition at 1 uM",
                    "value": 72.0,
                    "unit": "%",
                },
                "compound_label_raw": "Compound 12",
                "compound_label_key": "12",
                "assay_local_key": "assay-prose-1",
                "page": 7,
                "evidence_ids": ["ev-cell"],
            },
        ],
        "coverage": {"pages_viewed": [7], "pages_uncovered": [1, 2, 3, 4, 5, 6, 8]},
    }
    payload.update(overrides)
    return payload


def test_draft_preserves_bounded_readings_and_refuses_misdescriptions() -> None:
    """A bounded operator, a qualitative metric — and every shape that would
    misdescribe a reading is a contract violation.

    Unknown fields, an out-of-range confidence, a dangling local key, a
    duplicated key and an undeclared missing unit are all refused.
    """
    draft = PatentDraft.model_validate(_draft_payload())
    bounded = draft.measurements[0].value
    assert bounded.raw_text == "< 100 nM"
    assert bounded.operator == "<"
    # A fixed-concentration inhibition reading stays an inhibition metric.
    assert draft.measurements[1].metric == "inhibition_pct"
    assert draft.measurements[1].value.unit == "%"
    assert draft.coverage.pages_uncovered

    payload = _draft_payload()
    payload["measurements"][0]["model_confidence"] = 1.5
    with pytest.raises(ValidationError):
        PatentDraft.model_validate(payload)

    payload = _draft_payload()
    payload["unexpected_field"] = True
    with pytest.raises(ValidationError):
        PatentDraft.model_validate(payload)

    payload = _draft_payload()
    payload["measurements"][0]["assay_local_key"] = "assay-missing"
    with pytest.raises(ValidationError):
        PatentDraft.model_validate(payload)

    # A concentration without a unit must explicitly declare it missing.
    payload = _draft_payload()
    payload["measurements"][0]["value"] = {"raw_text": "8.3", "value": 8.3}
    with pytest.raises(ValidationError):
        PatentDraft.model_validate(payload)

    payload["measurements"][0]["value"]["missing_fields"] = ["unit"]
    assert PatentDraft.model_validate(payload).measurements[0].value.value == 8.3

    # US20260027089A1 p63: pIC50 6.9 is dimensionless, not missing a unit.
    payload = _draft_payload()
    payload["measurements"][0].update(
        metric="pIC50", value={"raw_text": "6.9", "value": 6.9}
    )
    logarithmic = PatentDraft.model_validate(payload).measurements[0].value
    assert logarithmic.unit == ""
    assert logarithmic.missing_fields == []
    assert logarithmic.value == 6.9

    payload["measurements"][0]["value"]["unit"] = "nM"
    with pytest.raises(ValidationError, match="dimensionless"):
        PatentDraft.model_validate(payload)


# ── identity signatures ─────────────────────────────────────────────


def test_slots_signatures_and_conflict_identity_stay_distinct() -> None:
    """Species/assays/repeats stay apart, a candidate set is order-independent,
    and the evidence signature is order-independent but content-sensitive.

    A changed candidate set is a different review item / decision slot, so a
    stale decision is retired when values or evidence change.
    """
    base = {
        "doc_id": _DOC,
        "anchor_evidence_id": "ev-cell",
        "compound_key": "12",
        "metric": "IC50",
    }
    human = measurement_slot_id(**base, assay_key="mrgprx2-human")
    mouse = measurement_slot_id(**base, assay_key="mrgprb2-mouse")
    repeated = measurement_slot_id(**{**base, "anchor_evidence_id": "ev-cell-2"})
    assert len({human, mouse, repeated}) == 3
    assert measurement_slot_id(**base, assay_key="mrgprx2-human") == human

    ten = candidate_signature(_TEN)
    hundred = candidate_signature(_HUNDRED)
    assert ten != hundred

    candidate_set = candidate_set_signature([ten, hundred])
    assert candidate_set == candidate_set_signature([hundred, ten])
    review_item = conflict_id(human, candidate_set)
    assert review_item == conflict_id(human, candidate_set_signature([hundred, ten]))
    # A changed candidate set is a different review item / decision slot.
    assert conflict_id(human, candidate_set_signature([ten])) != review_item

    rows = [
        ("ev-1", 1, "text", "Compound 12 IC50 10 nM"),
        ("ev-2", 1, "tab", "| 12 | 100 |"),
    ]
    baseline = evidence_signature(rows)
    assert baseline == evidence_signature(list(reversed(rows)))

    changed = [rows[0], ("ev-2", 1, "tab", "| 12 | 1000 |")]
    assert evidence_signature(changed) != baseline


def test_conflict_decision_and_snapshot_round_trip() -> None:
    slot = measurement_slot_id(
        doc_id=_DOC,
        anchor_evidence_id="ev-cell",
        compound_key="12",
        assay_key="mrgprx2-human",
        metric="IC50",
    )
    ten = candidate_signature(_TEN)
    hundred = candidate_signature(_HUNDRED)
    candidate_set = candidate_set_signature([ten, hundred])

    conflict_payload = {
        "conflict_id": conflict_id(slot, candidate_set),
        "slot_id": slot,
        "kind": "measurement",
        "doc_id": _DOC,
        "page": 7,
        "evidence_ids": ["ev-cell"],
        "candidates": [
            {
                "source": "deterministic",
                "fields": _TEN,
                "signature": ten,
                "evidence_ids": ["ev-cell"],
            },
            {
                "source": "llm",
                "fields": _HUNDRED,
                "signature": hundred,
                "evidence_ids": ["ev-cell"],
            },
        ],
    }
    conflict = PatentConflict.model_validate(conflict_payload)
    assert [item.source for item in conflict.candidates] == ["deterministic", "llm"]

    duplicated = dict(conflict_payload)
    duplicated["candidates"] = [conflict_payload["candidates"][0]] * 2
    with pytest.raises(ValidationError):
        PatentConflict.model_validate(duplicated)

    decision = PatentDecision.model_validate(
        {
            "slot_id": slot,
            "choice": "deterministic",
            "candidate_set_signature": candidate_set,
            "evidence_signature": _EVIDENCE_SIGNATURE,
            "decided_at": "2026-10-13 00:00:00",
        }
    )
    with pytest.raises(ValidationError):
        PatentDecision.model_validate(
            {
                "slot_id": slot,
                "choice": "use the 100 nM value",
                "candidate_set_signature": candidate_set,
                "evidence_signature": _EVIDENCE_SIGNATURE,
                "decided_at": "2026-10-13 00:00:00",
            }
        )

    snapshot = PatentAnalysisSnapshot.model_validate(
        {
            "doc_id": _DOC,
            "revision": 1,
            "evidence_signature": _EVIDENCE_SIGNATURE,
            "analysis_status": "succeeded",
            "extraction_mode": "hybrid",
            "payload": {"measurements": []},
            "decisions": {slot: decision.model_dump()},
            "updated_at": "2026-10-13 00:00:00",
        }
    )
    assert snapshot.decisions[slot].choice == "deterministic"
    # Stale decisions are retained in the map, not silently dropped.
    stale = snapshot.model_copy(update={"evidence_signature": "sig-evidence-2"})
    assert stale.decisions[slot].evidence_signature == _EVIDENCE_SIGNATURE

    with pytest.raises(ValidationError):
        PatentAnalysisSnapshot.model_validate(
            {
                "doc_id": _DOC,
                "revision": 0,
                "evidence_signature": _EVIDENCE_SIGNATURE,
                "analysis_status": "succeeded",
                "extraction_mode": "hybrid",
                "payload": {},
                "updated_at": "2026-10-13 00:00:00",
            }
        )


def test_committed_gap_schema_bundle_matches_contracts() -> None:
    """The Node-facing gap bundle must be regenerated with the contracts."""
    path = default_gap_output_path()
    assert path.is_file(), f"missing exported schema: {path}"
    committed = json.loads(path.read_text(encoding="utf-8"))
    assert committed == build_gap_bundle()


# ── the gap-answer contract (corpus strings) ────────────────────────
#
# Every excerpt below is a verbatim string observed in one of the 13 analysed
# patents (see ``docs/wiki/patent-extraction-forms.md``). The contract has to
# accept the answer a reader would give and refuse the shapes that would let a
# definition pass as a measurement.

_CORPUS_DOC = "cn-121270515a"
_CORPUS_ATTEMPT = "attempt-1"
_CORPUS_SIGNATURE = "sig-1"


def _gap_answer(**overrides: object) -> dict[str, object]:
    base: dict[str, object] = {
        "gap_id": "gap-1",
        "gap_kind": "table",
        "doc_id": _CORPUS_DOC,
        "attempt_id": _CORPUS_ATTEMPT,
        "evidence_signature": _CORPUS_SIGNATURE,
        "status": "unanswerable",
        "unanswerable_reason": "not_a_fact",
        "evidence_ids": ["ev-table"],
    }
    base.update(overrides)
    return base


def _gap_item(**overrides: object) -> dict[str, object]:
    base: dict[str, object] = {
        "local_key": "m-1",
        "metric": "IC50",
        "value": {"raw_text": "++", "qualitative": "++"},
        "compound_label_raw": "实施例1",
        "row_label_raw": "实施例1",
        "compound_label_key": "1",
        "page": 21,
        "evidence_ids": ["ev-table"],
    }
    base.update(overrides)
    return base


def test_a_gap_carries_the_rule_location_and_a_give_up_is_countable() -> None:
    """A gap refuses a page span that runs backwards, and one question is
    answerable in exactly one shape.

    Every non-reading the corpus shows is a give-up with a counted reason:
    ``H3C``/``N. HN S`` are structure-column noise (no attribution exists);
    ``注：“+”：IC50>1μM`` defines a bin, so it is not a fact; the JP full-width
    ``ρIC50`` digits are glyph-damaged. Each status has exactly one legal shape.
    """
    with pytest.raises(ValidationError):
        PatentGap(
            gap_id="gap-2",
            gap_kind="table",
            code="complex_activity_table",
            page_start=22,
            page_end=21,
            evidence_ids=["ev-table"],
        )

    for reason in ("no_attribution", "not_a_fact", "glyph_damaged"):
        answer = PatentGapAnswer.model_validate(
            _gap_answer(status="unanswerable", unanswerable_reason=reason)
        )
        assert answer.status == "unanswerable"
        assert answer.unanswerable_reason == reason
        assert answer.items == []

    with pytest.raises(ValidationError):
        PatentGapAnswer.model_validate(
            _gap_answer(status="answered", unanswerable_reason=None)
        )

    with pytest.raises(ValidationError):
        PatentGapAnswer.model_validate(
            _gap_answer(
                status="unanswerable", unanswerable_reason=None, items=[_gap_item()]
            )
        )

    with pytest.raises(ValidationError):
        PatentGapAnswer.model_validate(
            _gap_answer(status="needs_excerpt", unanswerable_reason="glyph_damaged")
        )

    pending = PatentGapAnswer.model_validate(
        _gap_answer(status="needs_excerpt", unanswerable_reason=None)
    )
    assert pending.items == []


def test_an_answer_splits_a_row_or_a_reference_into_readings() -> None:
    """``十`` is OCR for ``+`` (one reading per column, label verbatim), and
    ``Examples 4, 25, 28 and 30 exhibited a pIC50 ≥ 8.0.`` is four readings.

    An assay-attribution answer may name the assay it references; the decision
    to adopt stays with a human, and a dangling assay key is refused.
    """
    bins = PatentGapAnswer.model_validate(
        _gap_answer(
            status="answered",
            unanswerable_reason=None,
            items=[
                _gap_item(
                    local_key="m-1",
                    value={"raw_text": "+", "qualitative": "+"},
                    row_label_raw="实施例1",
                ),
                _gap_item(
                    local_key="m-2",
                    value={"raw_text": "++++", "qualitative": "++++"},
                    row_label_raw="实施例1",
                ),
            ],
        )
    )

    assert [item.value.qualitative for item in bins.items] == ["+", "++++"]
    assert [item.row_label_raw for item in bins.items] == ["实施例1", "实施例1"]

    excerpt = "Examples 4, 25, 28 and 30 exhibited a pIC50 ≥ 8.0."
    plural = PatentGapAnswer.model_validate(
        _gap_answer(
            gap_id="gap-wo-56",
            gap_kind="prose_measurement",
            status="answered",
            unanswerable_reason=None,
            evidence_ids=["ev-wo-line"],
            items=[
                _gap_item(
                    local_key=f"m-{index}",
                    metric="pIC50",
                    value={
                        "raw_text": "≥ 8.0",
                        "operator": ">=",
                        "value": 8.0,
                        "missing_fields": ["unit"],
                    },
                    compound_label_raw=f"Example {index}",
                    row_label_raw=f"Example {index}",
                    compound_label_key=str(index),
                    evidence_ids=["ev-wo-line"],
                )
                for index in (4, 25, 28, 30)
            ],
        )
    )

    assert len(plural.items) == 4
    assert {item.compound_label_key for item in plural.items} == {"4", "25", "28", "30"}
    assert excerpt.endswith("8.0.")

    attribution = PatentGapAnswer.model_validate(
        _gap_answer(
            gap_id="gap-cn-110",
            gap_kind="assay_attribution",
            status="answered",
            unanswerable_reason=None,
            evidence_ids=["ev-assay-section"],
            assay_methods=[
                {
                    "local_key": "a-1",
                    "target": "MRGPRX2",
                    "endpoint": "抑制活性",
                    "raw_text": "生物活性研究(一)本发明化合物对MRGPRX2的抑制活性",
                    "page_start": 19,
                    "page_end": 20,
                    "evidence_ids": ["ev-assay-section"],
                }
            ],
            items=[
                _gap_item(
                    local_key="m-24",
                    assay_local_key="a-1",
                    evidence_ids=["ev-assay-table"],
                )
            ],
        )
    )

    assert attribution.assay_methods[0].target == "MRGPRX2"
    assert attribution.items[0].assay_local_key == "a-1"

    with pytest.raises(ValidationError):
        PatentGapAnswer.model_validate(
            _gap_answer(
                gap_id="gap-bad",
                gap_kind="assay_attribution",
                status="answered",
                unanswerable_reason=None,
                items=[_gap_item(assay_local_key="a-missing")],
            )
        )


# ── the runtime boundary ────────────────────────────────────────────


def _runtime_gap(gap_id: str = "complex_activity_table:ev-21") -> PatentGap:
    return PatentGap(
        gap_id=gap_id,
        gap_kind="table",
        code="complex_activity_table",
        page_start=21,
        page_end=21,
        evidence_ids=["ev-21"],
        excerpt="| 化合物编号 | IC50(nM) |",
    )


def _runtime_answer(gap_id: str, status: str) -> PatentGapAnswer:
    base: dict[str, object] = {
        "gap_id": gap_id,
        "gap_kind": _runtime_gap(gap_id).gap_kind,
        "doc_id": "doc-1",
        "attempt_id": "attempt-1",
        "evidence_signature": "sig-1",
        "status": status,
        "evidence_ids": ["ev-21"],
    }
    if status == "answered":
        base["items"] = [
            {
                "local_key": "item-1",
                "metric": "IC50",
                "value": {"raw_text": "+", "qualitative": "+"},
                "row_label_raw": "实施例1",
                "page": 21,
                "evidence_ids": ["ev-21"],
            }
        ]
    else:
        base["unanswerable_reason"] = "no_attribution"
    return PatentGapAnswer.model_validate(base)


def test_stage_progress_reaches_the_event_sink_with_the_callback_phase() -> None:
    """A stage reports without importing the sink; a payload that names its own
    phase does not override the callback's, so a sidecar event cannot relabel it."""
    events: list[PatentAnalysisEvent] = []
    sink = PipelineEventSink(
        lambda event: events.append(event),
        task_id=None,
        library_root="/library",
        doc_id="doc-1",
    )

    sink.progress("patent")("digest", {"message": "digest built", "chars": 1234})

    assert len(events) == 1
    event = events[0]
    assert event.stage == "patent"
    assert event.event == "info"
    assert event.message == "digest built"
    assert event.data == {"phase": "digest", "chars": 1234}

    sink.progress("patent")("llm_tool", {"phase": "tool", "tool": "read_evidence"})

    assert len(events) == 2
    assert events[1].data == {"phase": "llm_tool", "tool": "read_evidence"}


# ── the Python -> sidecar transport ─────────────────────────────────


def _sidecar_scope(attempt_id: str = "attempt-1") -> PatentTaskScope:
    return PatentTaskScope(
        library_root="/library",
        doc_id="doc-1",
        run_id="run-1",
        attempt_id=attempt_id,
        evidence_signature="sig-1",
        budget=PatentAnalysisBudget(
            max_model_turns=4,
            wall_clock_seconds=30,
            max_total_tokens=10_000,
            digest_char_budget=5_000,
        ),
    )


def _sse(name: str, payload: dict[str, Any]) -> bytes:
    return f"event: {name}\ndata: {json.dumps(payload)}\n\n".encode()


def _sidecar_runtime(handler: Any) -> SidecarPatentAnalysisRuntime:
    return SidecarPatentAnalysisRuntime(
        base_url="http://agent.test", transport=httpx.MockTransport(handler)
    )


def _done(**overrides: Any) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "ok": True,
        "status": "succeeded",
        "turns": 3,
        "tool_calls": 2,
        "tokens": None,
        "duration_ms": 1200,
        "model": "test-model",
        "prompt_version": "patent-v1",
    }
    payload.update(overrides)
    return payload


def test_a_streamed_attempt_binds_the_credential_and_returns_its_outcome() -> None:
    seen: dict[str, Any] = {}
    answer = _runtime_answer("complex_activity_table:ev-21", "unanswerable")

    def handler(request: httpx.Request) -> httpx.Response:
        payload = json.loads(request.content)
        seen["credential"] = payload["credential"]
        seen["has_library_root"] = "library_root" in payload
        seen["resolved_during_run"] = (
            get_patent_task_registry().resolve(payload["credential"]) is not None
        )
        # Exactly what the scope-limited submit-gap-answer endpoint does.
        get_patent_task_registry().stage_gap_answer(payload["credential"], answer)
        body = (
            _sse(
                "progress",
                {"kind": "progress", "phase": "turn", "turn": 1, "message": "turn 1"},
            )
            + _sse("tool", {"kind": "tool", "tool": "read_evidence", "ok": True})
            + _sse("done", _done())
        )
        return httpx.Response(
            200, content=body, headers={"content-type": "text/event-stream"}
        )

    events: list[Any] = []
    result = _sidecar_runtime(handler).run(
        _sidecar_scope(), gaps=[_runtime_gap()], on_event=events.append
    )
    outcome = result.outcome

    assert outcome.ok is True
    assert outcome.status == "succeeded"
    assert outcome.turns == 3
    assert outcome.tokens is None
    assert [event.kind for event in events] == ["progress", "tool"]
    assert seen["has_library_root"] is False
    assert seen["resolved_during_run"] is True
    assert len(result.gap_answers) == 1
    assert result.gap_answers[0].gap_id == "complex_activity_table:ev-21"
    assert result.gap_answers[0].unanswerable_reason == "no_attribution"
    # The credential stops working the moment the attempt ends.
    assert get_patent_task_registry().resolve(seen["credential"]) is None


def test_sidecar_failures_and_cancellation_are_never_a_success() -> None:
    """A dropped stream, a rejected request and an unreachable sidecar all fail;
    a caller cancellation stops the stream and tells the sidecar."""

    def truncated(request: httpx.Request) -> httpx.Response:
        body = _sse("progress", {"kind": "progress", "message": "turn 1"})
        return httpx.Response(
            200, content=body, headers={"content-type": "text/event-stream"}
        )

    truncated_outcome = (
        _sidecar_runtime(truncated).run(_sidecar_scope(), gaps=[_runtime_gap()]).outcome
    )

    assert truncated_outcome.ok is False
    assert truncated_outcome.status == "failed"
    assert truncated_outcome.error_code == "transport_truncated"

    def rejected(request: httpx.Request) -> httpx.Response:
        return httpx.Response(422, json={"error": "unsupported protocol_version"})

    rejected_outcome = (
        _sidecar_runtime(rejected).run(_sidecar_scope(), gaps=[_runtime_gap()]).outcome
    )

    assert rejected_outcome.ok is False
    assert rejected_outcome.error_code == "sidecar_rejected"
    assert "protocol_version" in str(rejected_outcome.error)

    def unreachable(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("no sidecar", request=request)

    unreachable_outcome = (
        _sidecar_runtime(unreachable)
        .run(_sidecar_scope(), gaps=[_runtime_gap()])
        .outcome
    )

    assert unreachable_outcome.ok is False
    assert unreachable_outcome.error_code == "sidecar_unavailable"

    calls: list[str] = []

    def cancellable(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/cancel"):
            calls.append("cancel")
            return httpx.Response(200, json={"success": True, "cancelled": True})
        calls.append("stream")
        body = _sse("progress", {"kind": "progress", "message": "turn 1"}) + _sse(
            "done", _done()
        )
        return httpx.Response(
            200, content=body, headers={"content-type": "text/event-stream"}
        )

    checks = {"count": 0}

    def should_cancel() -> bool:
        checks["count"] += 1
        return checks["count"] > 1

    cancelled = (
        _sidecar_runtime(cancellable)
        .run(_sidecar_scope(), gaps=[_runtime_gap()], should_cancel=should_cancel)
        .outcome
    )

    assert cancelled.status == "cancelled"
    assert cancelled.ok is False
    assert calls == ["stream", "cancel"]
