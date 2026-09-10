"""Tests for the document-scoped molecule submission tool."""

from __future__ import annotations

import json

import pytest

from mbforge.pipeline.detection.document_registration import (
    MoleculeRegistrationError,
    MoleculeRegistrationSession,
    collect_molecule_candidates_with_tool,
    create_molecule_registration_tool,
)


def test_registration_session_reuses_normalize_and_merges_observations() -> None:
    session = MoleculeRegistrationSession("doc-1")

    first = session.submit(
        esmiles="CCO",
        name="Compound E001",
        page_num=7,
        context_text="E001 was tested in the assay.",
        confidence=0.9,
    )
    second = session.submit(
        esmiles="OCC",
        name="E001",
        page_num=7,
        confidence=0.8,
    )

    assert first["accepted"] is True
    assert first["structure_role"] == "complete"
    assert second["canonical_smiles"] == "CCO"
    candidates = session.finalize()
    assert len(candidates) == 1
    assert candidates[0].canonical_smiles == "CCO"
    assert len(candidates[0].detections) == 2


def test_registration_session_keeps_markush_as_review_candidate() -> None:
    session = MoleculeRegistrationSession("doc-1")
    result = session.submit(
        esmiles="CCO",
        name="Formula I",
        page_num=3,
        context_text="General formula I, wherein R1 is optionally substituted.",
        role_hint="complete",
    )

    assert result["accepted"] is True
    assert result["structure_role"] == "review_required"
    assert "context_formula_label" in result["review_reasons"]
    assert session.finalize()[0].properties["structure_role"] == "review_required"


def test_registration_session_rejects_bad_contract_values() -> None:
    session = MoleculeRegistrationSession("doc-1")

    with pytest.raises(MoleculeRegistrationError, match="page_num"):
        session.submit(esmiles="CCO", page_num=0)
    with pytest.raises(MoleculeRegistrationError, match="bbox"):
        session.submit(esmiles="CCO", bbox=[0, 1])
    with pytest.raises(MoleculeRegistrationError, match="confidence"):
        session.submit(esmiles="CCO", confidence=1.1)


@pytest.mark.asyncio
async def test_registration_tool_returns_structured_result() -> None:
    session = MoleculeRegistrationSession("doc-1")
    registration_tool = create_molecule_registration_tool(session)

    result = await registration_tool.ainvoke(
        {
            "esmiles": "CCO",
            "name": "E001",
            "page_num": 2,
            "confidence": 0.75,
        }
    )

    payload = json.loads(result)
    assert payload["accepted"] is True
    assert payload["canonical_smiles"] == "CCO"
    assert session.submission_count == 1


@pytest.mark.asyncio
async def test_cloud_tool_adapter_collects_calls_without_database_access() -> None:
    class _Response:
        tool_calls = [
            {
                "name": "submit_molecule_candidate",
                "args": {
                    "esmiles": "CCO",
                    "name": "E001",
                    "page_num": 4,
                    "confidence": 0.8,
                },
            }
        ]

    class _Bound:
        async def ainvoke(self, _prompt: str) -> _Response:
            return _Response()

    class _LLM:
        def bind_tools(self, tools, tool_choice=None):
            assert len(tools) == 1
            assert tools[0].name == "submit_molecule_candidate"
            assert tool_choice == "required"
            return _Bound()

    session = MoleculeRegistrationSession("doc-1")
    candidates, stats = await collect_molecule_candidates_with_tool(
        _LLM(), session, "Compound E001: CCO"
    )

    assert stats == {
        "tool_calls": 1,
        "accepted_submissions": 1,
        "rejected_submissions": 0,
        "coerced_source_submissions": 0,
        "buffered_submissions": 1,
    }
    assert candidates[0].canonical_smiles == "CCO"
    assert candidates[0].detections[0].page == 3


def test_registration_session_rejects_missing_esmiles_and_unknown_source() -> None:
    session = MoleculeRegistrationSession("doc-1")

    with pytest.raises(MoleculeRegistrationError, match="esmiles"):
        session.submit(esmiles="")
    with pytest.raises(MoleculeRegistrationError, match="source"):
        session.submit(esmiles="CCO", source="invalid")


@pytest.mark.asyncio
async def test_cloud_tool_adapter_requires_tool_call_support() -> None:
    class _LLM:
        pass

    session = MoleculeRegistrationSession("doc-1")
    with pytest.raises(MoleculeRegistrationError, match="tool calls"):
        await collect_molecule_candidates_with_tool(_LLM(), session, "text")


@pytest.mark.asyncio
async def test_cloud_tool_adapter_skips_non_candidate_calls() -> None:
    class _Response:
        tool_calls = [
            "not-a-tool-call",
            {"name": "unrelated_tool", "args": {"esmiles": "CCO"}},
            {
                "function": {
                    "name": "submit_molecule_candidate",
                    "arguments": "{not-json",
                }
            },
            {"name": "submit_molecule_candidate", "args": "CCO"},
        ]

    class _Bound:
        async def ainvoke(self, _prompt: str) -> _Response:
            return _Response()

    class _LLM:
        def bind_tools(self, tools, tool_choice=None):
            return _Bound()

    session = MoleculeRegistrationSession("doc-1")
    candidates, stats = await collect_molecule_candidates_with_tool(
        _LLM(), session, "Compound E001: CCO"
    )

    assert stats == {
        "tool_calls": 0,
        "accepted_submissions": 0,
        "rejected_submissions": 0,
        "coerced_source_submissions": 0,
        "buffered_submissions": 0,
    }
    assert candidates == []


@pytest.mark.asyncio
async def test_cloud_tool_adapter_counts_rejected_submissions_as_unaccepted() -> None:
    class _Response:
        tool_calls = [
            {
                "name": "submit_molecule_candidate",
                "args": {"esmiles": "C1CC"},
            }
        ]

    class _Bound:
        async def ainvoke(self, _prompt: str) -> _Response:
            return _Response()

    class _LLM:
        def bind_tools(self, tools, tool_choice=None):
            return _Bound()

    session = MoleculeRegistrationSession("doc-1")
    candidates, stats = await collect_molecule_candidates_with_tool(
        _LLM(), session, "unclosed ring SMILES"
    )

    assert stats == {
        "tool_calls": 1,
        "accepted_submissions": 0,
        "rejected_submissions": 1,
        "coerced_source_submissions": 0,
        "buffered_submissions": 1,
    }
    assert candidates[0].status == "rejected"


@pytest.mark.asyncio
async def test_cloud_tool_adapter_coerces_image_source_to_text() -> None:
    """The text-only fallback must never claim image provenance."""

    class _Response:
        tool_calls = [
            {
                "name": "submit_molecule_candidate",
                "args": {
                    "esmiles": "CCO",
                    "name": "E001",
                    "page_num": 2,
                    "source": "image",
                    "confidence": 0.8,
                },
            }
        ]

    class _Bound:
        async def ainvoke(self, _prompt: str) -> _Response:
            return _Response()

    class _LLM:
        def bind_tools(self, tools, tool_choice=None):
            return _Bound()

    session = MoleculeRegistrationSession("doc-1")
    candidates, stats = await collect_molecule_candidates_with_tool(
        _LLM(), session, "Compound E001: CCO"
    )

    assert stats["coerced_source_submissions"] == 1
    assert candidates[0].sources == ["text"]


@pytest.mark.asyncio
async def test_cloud_tool_adapter_continues_after_malformed_call(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A malformed per-call ainvoke/json.loads must not discard previously
    buffered candidates; the bad call is counted as a rejected submission
    and the loop continues to the next tool call."""

    import json as json_mod

    import mbforge.pipeline.detection.document_registration as reg_mod

    real_loads = reg_mod.json.loads
    counter = {"n": 0}

    def _flaky_loads(*args, **kwargs):
        counter["n"] += 1
        if counter["n"] == 1:
            raise json_mod.JSONDecodeError("flaky", "not-json", 0)
        return real_loads(*args, **kwargs)

    monkeypatch.setattr(reg_mod.json, "loads", _flaky_loads)

    class _Response:
        tool_calls = [
            {
                "name": "submit_molecule_candidate",
                "args": {
                    "esmiles": "CCO",
                    "name": "E001",
                    "page_num": 1,
                    "confidence": 0.8,
                },
            },
            {
                "name": "submit_molecule_candidate",
                "args": {
                    "esmiles": "CCC",
                    "name": "E002",
                    "page_num": 1,
                    "confidence": 0.8,
                },
            },
        ]

    class _Bound:
        async def ainvoke(self, _prompt: str) -> _Response:
            return _Response()

    class _LLM:
        def bind_tools(self, tools, tool_choice=None):
            return _Bound()

    session = MoleculeRegistrationSession("doc-1")
    candidates, stats = await collect_molecule_candidates_with_tool(
        _LLM(), session, "Compound E001: CCO; Compound E002: CCC"
    )

    assert counter["n"] == 2
    assert stats["tool_calls"] == 2
    assert stats["accepted_submissions"] == 1
    assert stats["rejected_submissions"] == 1
    # The flaky first call still buffered its candidate inside the tool
    # (session.submit ran before json.loads failed); the loop simply
    # counted it as a rejection and moved on.  The well-formed second
    # call survives end-to-end, proving the malformed call did not
    # discard its candidate.
    assert stats["buffered_submissions"] == 2
    canonicals = sorted(c.canonical_smiles for c in candidates)
    assert canonicals == ["CCC", "CCO"]


@pytest.mark.asyncio
async def test_cloud_tool_adapter_propagates_cancellation_in_loop() -> None:
    """The cancel_check must be polled inside the tool-call loop so a
    user-initiated cancel aborts the cloud pass without waiting for the
    LLM provider."""

    from mbforge.pipeline.cancellation import (
        CancellationRegistry,
        TaskCancelledError,
    )

    registry = CancellationRegistry()
    registry.cancel("doc-1")

    class _Response:
        tool_calls = [
            {
                "name": "submit_molecule_candidate",
                "args": {"esmiles": "CCO", "page_num": 1},
            }
        ]

    class _Bound:
        async def ainvoke(self, _prompt: str) -> _Response:
            return _Response()

    class _LLM:
        def bind_tools(self, tools, tool_choice=None):
            return _Bound()

    session = MoleculeRegistrationSession("doc-1")

    def _cancel() -> None:
        if registry.is_cancelled("doc-1"):
            raise TaskCancelledError("doc-1")

    with pytest.raises(TaskCancelledError):
        await collect_molecule_candidates_with_tool(
            _LLM(),
            session,
            "Compound E001: CCO",
            cancel_check=_cancel,
        )


@pytest.mark.asyncio
async def test_cloud_tool_adapter_polls_cancel_before_ainvoke() -> None:
    """cancel_check is called once before the LLM and again before each
    per-call ainvoke, so even a single LLM call cannot bypass cancellation."""

    from mbforge.pipeline.cancellation import (
        CancellationRegistry,
        TaskCancelledError,
    )

    registry = CancellationRegistry()
    counter = {"n": 0}

    def _check() -> None:
        counter["n"] += 1
        if registry.is_cancelled("doc-1"):
            raise TaskCancelledError("doc-1")

    class _Bound:
        async def ainvoke(self, _prompt: str) -> object:
            # The LLM should never be reached because the registry was
            # cancelled before the call was even made.
            raise AssertionError("LLM invoked despite cancel")

    class _LLM:
        def bind_tools(self, tools, tool_choice=None):
            return _Bound()

    session = MoleculeRegistrationSession("doc-1")
    registry.cancel("doc-1")
    with pytest.raises(TaskCancelledError):
        await collect_molecule_candidates_with_tool(
            _LLM(), session, "text", cancel_check=_check
        )
    assert counter["n"] >= 1
