"""Contract tests for the capability registry."""

from __future__ import annotations

import asyncio
import base64
from pathlib import Path

import pytest

from mbforge.foundation.errors import CapabilityForbiddenError, ValidationError
from mbforge.service.capabilities import (
    CapabilityContext,
    all_capabilities,
    invoke,
)
from mbforge.service.capabilities import read_patent as read_patent_capabilities
from mbforge.service.capabilities.read_visual import VisualInput
from mbforge.service.pipeline.layout.labels import kind_vocab
from mbforge.service.pipeline.patent.artifact import (
    PatentFactsArtifact,
    PatentSectionModel,
)
from mbforge.service.pipeline.patent.sections import SECTION_KINDS
from mbforge.service.use_cases.documents.library import LibraryStore

_CONTEXT = CapabilityContext(library_root="/tmp/library", mode="readonly")


def _facts_artifact() -> PatentFactsArtifact:
    return PatentFactsArtifact(
        doc_id="doc-1",
        run_id="20261110000000",
        stats={"issue_count": 1},
        sections=[
            PatentSectionModel(
                section_id=f"section-{index}",
                title=f"Example {index}",
                kind="example",
                page_start=1,
                page_end=2,
                evidence_ids=[f"ev-{index}-a", f"ev-{index}-b"],
            )
            for index in (1, 2)
        ],
        entries=[
            {"entry_id": f"entry-{index}", "label_key": str(index)}
            for index in (1, 2, 3)
        ],
        issues=[
            {
                "code": "unbound_reading",
                "message": "no structure owns this reading",
                "evidence_ids": ["ev-issue-a"],
            }
        ],
    )


def test_capability_names_are_unique_and_schemas_generate() -> None:
    capabilities = all_capabilities()
    names = [capability.name for capability in capabilities]
    assert len(names) == len(set(names))
    assert {
        "resolve_document",
        "submit_extraction",
        "submit_patent_analysis",
        "search_evidence",
        "get_patent_result",
        "query_activities",
    } <= set(names)
    for capability in capabilities:
        assert capability.input_model.model_json_schema()
        assert capability.output_model.model_json_schema()


def test_readonly_mode_rejects_mutating_capability() -> None:
    with pytest.raises(CapabilityForbiddenError):
        asyncio.run(
            invoke(
                "submit_extraction",
                CapabilityContext(library_root="/tmp/library", mode="readonly"),
                {"doc_id": "missing"},
            )
        )


def test_inspect_visual_molecule_image_returns_png_for_valid_smiles() -> None:
    result = asyncio.run(
        invoke(
            "inspect_visual",
            CapabilityContext(library_root="/tmp/library", mode="readonly"),
            {"action": "molecule_image", "smiles": "CC(=O)Oc1ccccc1C(=O)O"},
        )
    )
    assert result.data.mime_type == "image/png"
    assert base64.b64decode(result.data.image_base64).startswith(b"\x89PNG")


def test_inspect_visual_rejects_invalid_smiles() -> None:
    with pytest.raises(ValidationError):
        asyncio.run(
            invoke(
                "inspect_visual",
                CapabilityContext(library_root="/tmp/library", mode="readonly"),
                {"action": "molecule_image", "smiles": "not-a-molecule-@@"},
            )
        )


def test_get_patent_result_pages_one_collection_without_evidence_refs(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A summary call carries no rows and no collection floods the context."""
    monkeypatch.setattr(
        read_patent_capabilities,
        "load_patent_facts",
        lambda _root, _doc: _facts_artifact(),
    )

    summary = asyncio.run(invoke("get_patent_result", _CONTEXT, {"doc_id": "doc-1"}))
    assert summary.data.collection == "summary"
    assert summary.data.items == []
    assert summary.data.counts is not None
    assert summary.data.counts.sections == 2

    sections = asyncio.run(
        invoke(
            "get_patent_result",
            _CONTEXT,
            {"doc_id": "doc-1", "collection": "sections", "limit": 1},
        )
    )
    assert sections.data.total == 2
    assert [item["section_id"] for item in sections.data.items] == ["section-1"]
    assert "evidence_ids" not in sections.data.items[0]
    assert sections.data.counts is None
    assert sections.truncated is True
    assert sections.next_offset == 1

    with_refs = asyncio.run(
        invoke(
            "get_patent_result",
            _CONTEXT,
            {
                "doc_id": "doc-1",
                "collection": "sections",
                "limit": 1,
                "include_evidence_ids": True,
            },
        )
    )
    assert with_refs.data.items[0]["evidence_ids"] == ["ev-1-a", "ev-1-b"]

    issues = asyncio.run(
        invoke(
            "get_patent_result", _CONTEXT, {"doc_id": "doc-1", "collection": "issues"}
        )
    )
    assert [item["code"] for item in issues.data.items] == ["unbound_reading"]


def test_inspect_visual_branches_declare_their_required_parameters() -> None:
    schema = VisualInput.model_json_schema()
    assert schema["type"] == "object"
    assert schema["discriminator"]["propertyName"] == "action"
    assert set(schema["$defs"]["PageImageAction"]["required"]) == {
        "action",
        "doc_id",
        "page",
    }
    assert set(schema["$defs"]["MoleculeImageAction"]["required"]) == {
        "action",
        "smiles",
    }

    for payload in (
        {"action": "page_image"},
        {"action": "page_molecules", "doc_id": "doc-1"},
        {"action": "molecule_image", "doc_id": "doc-1", "page": 2},
        {"action": "recognize_structure"},
    ):
        with pytest.raises(ValidationError):
            asyncio.run(invoke("inspect_visual", _CONTEXT, payload))


def test_search_molecules_echoes_the_decision_it_made(tmp_library: Path) -> None:
    context = CapabilityContext(library_root=str(tmp_library), mode="readonly")

    structure = asyncio.run(
        invoke(
            "search_molecules",
            context,
            {"query": "CC(=O)Oc1ccccc1C(=O)O", "mode": "auto"},
        )
    )
    assert structure.data.resolved_mode == "substructure"
    assert structure.data.requested_mode == "auto"
    assert structure.data.threshold_applied is False

    text = asyncio.run(invoke("search_molecules", context, {"query": "aspirin"}))
    assert text.data.resolved_mode == "text"

    scored = asyncio.run(
        invoke(
            "search_molecules",
            context,
            {"query": "CCO", "mode": "similarity", "similarity_threshold": 0.5},
        )
    )
    assert scored.data.threshold_applied is True
    zeroed = asyncio.run(
        invoke(
            "search_molecules",
            context,
            {"query": "CCO", "mode": "similarity", "similarity_threshold": 0.0},
        )
    )
    assert zeroed.data.threshold_applied is False


def test_list_evidence_rejects_an_unregistered_kind_and_vocabulary_publishes_it() -> (
    None
):
    with pytest.raises(ValidationError):
        asyncio.run(
            invoke("list_evidence", _CONTEXT, {"doc_id": "doc-1", "kind": "fact"})
        )

    vocabulary = asyncio.run(invoke("get_vocabulary", _CONTEXT, {})).data
    assert vocabulary.evidence_kinds == dict(sorted(kind_vocab().items()))
    assert vocabulary.evidence_kinds["molecule"] == "molecule"
    assert vocabulary.evidence_kinds["bib"] == "text"
    assert vocabulary.section_kinds == list(SECTION_KINDS)
    assert "pending" in vocabulary.molecule_review_statuses
    assert "superseded" not in vocabulary.measurement_review_statuses
    assert "designation_unbound" in vocabulary.review_kinds


def _register(tmp_library: Path, file_name: str, title: str) -> str:
    """Register a document in *tmp_library* and return its canonical doc_id."""
    source = tmp_library / file_name
    source.write_bytes(f"pdf content {file_name}".encode())
    return LibraryStore.get(tmp_library).add_document(source, title=title).doc_id


def test_document_reference_resolves_to_the_canonical_doc_id(tmp_library: Path) -> None:
    """A capability accepts the title, file name, short id, or hash prefix."""
    doc_id = _register(tmp_library, "CN119504738A.pdf", "CN119504738A")
    context = CapabilityContext(library_root=str(tmp_library), mode="readonly")

    resolved = asyncio.run(
        invoke("resolve_document", context, {"query": "CN119504738A"})
    )
    match = resolved.data.matches[0]
    assert match.short_id == doc_id[:12]
    assert len(match.short_id) == 12

    document = asyncio.run(invoke("get_document", context, {"doc_id": match.short_id}))
    assert document.data.doc_id == doc_id
    assert document.data.short_id == match.short_id

    for reference in ("CN119504738A", "CN119504738A.pdf", doc_id[:8], doc_id):
        result = asyncio.run(invoke("get_document", context, {"doc_id": reference}))
        assert result.data.doc_id == doc_id

    evidence = asyncio.run(invoke("list_evidence", context, {"doc_id": match.short_id}))
    assert evidence.data.doc_id == doc_id
    assert evidence.data.short_id == match.short_id


def test_ambiguous_document_reference_is_rejected(tmp_library: Path) -> None:
    """Two documents share a title: the reference must not pick one."""
    _register(tmp_library, "CN119504738A.pdf", "Shared Title")
    _register(tmp_library, "CN119504739A.pdf", "Shared Title")
    context = CapabilityContext(library_root=str(tmp_library), mode="readonly")

    with pytest.raises(ValidationError) as excinfo:
        asyncio.run(invoke("get_document", context, {"doc_id": "Shared Title"}))
    assert len(excinfo.value.context["candidates"]) == 2


def test_import_pdf_auto_enqueues_and_survives_a_failed_enqueue(
    tmp_library: Path,
    monkeypatch: pytest.MonkeyPatch,
    patch_config,
) -> None:
    """Import queues Extract -> Markdown by default; a disabled or failing
    enqueue leaves the stored document pending instead of failing the import."""
    from mbforge.service.use_cases.pipeline import ingest

    enabled = {"value": True}
    patch_config(
        lambda cfg: setattr(cfg.ingest, "auto_enqueue_on_import", enabled["value"])
    )
    context = CapabilityContext(library_root=str(tmp_library), mode="edit")
    queued: list[str] = []

    async def _enqueue(_root: str, doc_id: str) -> str:
        queued.append(doc_id)
        return "run-1"

    monkeypatch.setattr(ingest, "enqueue", _enqueue)

    (tmp_library / "first.pdf").write_bytes(b"%PDF-1.4 first")
    first = asyncio.run(invoke("import_pdf", context, {"path": "first.pdf"}))
    assert first.data.run_id == "run-1"
    assert queued == [first.data.doc_id]

    enabled["value"] = False
    (tmp_library / "second.pdf").write_bytes(b"%PDF-1.4 second")
    second = asyncio.run(invoke("import_pdf", context, {"path": "second.pdf"}))
    assert second.data.run_id is None
    assert queued == [first.data.doc_id]

    async def _fail(_root: str, doc_id: str) -> str:
        raise RuntimeError("queue unavailable")

    monkeypatch.setattr(ingest, "enqueue", _fail)
    enabled["value"] = True
    (tmp_library / "third.pdf").write_bytes(b"%PDF-1.4 third")
    third = asyncio.run(invoke("import_pdf", context, {"path": "third.pdf"}))
    assert third.data.run_id is None
    assert third.data.status == "pending"
