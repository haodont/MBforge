"""Unit tests for chemistry endpoints."""

from __future__ import annotations

import asyncio

import pytest

from mbforge.application.dto.chem import (
    FingerprintPairRequest,
    GesimAtomMappingRequest,
    SimilaritySearchRequest,
    SmilesImageRequest,
    SmilesRequest,
    SubstructureSearchRequest,
    ValidateSmilesRequest,
)
from mbforge.application.use_cases.chem.chem import (
    canonicalize_sync as _canonicalize_sync,
)
from mbforge.application.use_cases.chem.chem import (
    draw_smiles_sync as _draw_smiles_sync,
)
from mbforge.application.use_cases.chem.chem import (
    fingerprint_sync as _fingerprint_sync,
)
from mbforge.application.use_cases.chem.chem import (
    properties_sync as _properties_sync,
)
from mbforge.application.use_cases.chem.chem import (
    similarity_search_sync as _similarity_search_sync,
)
from mbforge.application.use_cases.chem.chem import (
    substructure_search_sync as _substructure_search_sync,
)
from mbforge.application.use_cases.chem.chem import (
    tanimoto_sync as _tanimoto_sync,
)
from mbforge.application.use_cases.chem.chem import (
    validate_smiles_sync as _validate_smiles_sync,
)
from mbforge.interfaces.http.molecule.chem import (
    canonicalize,
    fingerprint,
    gesim_atom_mapping,
    properties,
    similarity_search,
    smiles_to_image,
    substructure_search,
    tanimoto,
    validate_smiles,
)


def _capture_to_thread(monkeypatch: pytest.MonkeyPatch):
    """Patch asyncio.to_thread so callers can inspect what was offloaded."""
    calls: list[tuple[object, tuple, dict]] = []

    async def _fake_to_thread(func, *args, **kwargs):
        calls.append((func, args, kwargs))
        return {"_fake": True}

    monkeypatch.setattr(asyncio, "to_thread", _fake_to_thread)
    return calls


@pytest.mark.parametrize(
    "handler, sync_func, body",
    [
        (validate_smiles, _validate_smiles_sync, ValidateSmilesRequest(smiles="CCO")),
        (fingerprint, _fingerprint_sync, SmilesRequest(smiles="CCO")),
        (properties, _properties_sync, SmilesRequest(smiles="CCO")),
        (canonicalize, _canonicalize_sync, SmilesRequest(smiles="CCO")),
        (
            tanimoto,
            _tanimoto_sync,
            FingerprintPairRequest(fingerprint_a=[1, 0, 1], fingerprint_b=[1, 1, 0]),
        ),
        (
            substructure_search,
            _substructure_search_sync,
            SubstructureSearchRequest(query="CCO", candidates=[{"smiles": "CCCO"}]),
        ),
        (
            similarity_search,
            _similarity_search_sync,
            SimilaritySearchRequest(query="CCO", candidates=[{"smiles": "CCCO"}]),
        ),
    ],
)
def test_chem_routes_offload_to_thread(
    monkeypatch: pytest.MonkeyPatch,
    handler,
    sync_func,
    body,
) -> None:
    """Async chemistry routes delegate blocking RDKit work to asyncio.to_thread."""
    calls = _capture_to_thread(monkeypatch)

    result = asyncio.run(handler(body))

    assert result == {"_fake": True}
    assert len(calls) == 1
    assert calls[0][0] is sync_func


def test_draw_smiles_renders_markush_wildcards_as_svg() -> None:
    result = _draw_smiles_sync("*c1ccc(*)nc1", 360, 240)

    assert result.success is True
    assert "<svg" in result.svg


def test_smiles_to_image_rejects_invalid_smiles() -> None:
    result = asyncio.run(smiles_to_image(SmilesImageRequest(smiles="not-smiles")))

    assert result.success is False
    assert result.error == "invalid SMILES"


def test_validate_smiles_batch_and_legacy() -> None:
    """Batch validation accepts both ``list`` and legacy ``smiles``."""
    batch = asyncio.run(
        validate_smiles(ValidateSmilesRequest(list=["CCO", "not-smiles"]))
    )
    assert len(batch) == 2
    assert batch[0].valid is True
    assert batch[0].input == "CCO"
    assert batch[1].valid is False

    single = asyncio.run(validate_smiles(ValidateSmilesRequest(smiles="CCO")))
    assert len(single) == 1
    assert single[0].valid is True


def test_validate_smiles_request_requires_smiles_or_list() -> None:
    with pytest.raises(ValueError):
        ValidateSmilesRequest()


def test_gesim_not_implemented_returns_envelope() -> None:
    """The gesim atom-mapping endpoint returns a stable not-implemented envelope."""
    mapping = asyncio.run(
        gesim_atom_mapping(GesimAtomMappingRequest(smiles_a="CCO", smiles_b="CCO"))
    )
    assert mapping.success is False
    assert "not implemented" in mapping.error


def test_substructure_search_with_candidates() -> None:
    result = _substructure_search_sync(
        SubstructureSearchRequest(
            query="c1ccccc1",
            candidates=[{"smiles": "c1ccccc1C"}, {"smiles": "CCO"}],
            top_k=10,
        )
    )
    assert result.success is True
    assert len(result.results) == 1
    assert result.results[0]["smiles"] == "c1ccccc1C"


def test_substructure_search_rejects_invalid_query() -> None:
    result = _substructure_search_sync(
        SubstructureSearchRequest(query="not-a-smiles", candidates=[])
    )
    assert result.success is False
    assert "invalid query SMILES" in result.error


def test_similarity_search_with_candidates() -> None:
    result = _similarity_search_sync(
        SimilaritySearchRequest(
            query="CCO",
            candidates=[{"smiles": "CCO"}, {"smiles": "c1ccccc1"}],
            top_k=10,
            threshold=0.0,
        )
    )
    assert result.success is True
    assert len(result.results) >= 1
    top = result.results[0]
    assert top["smiles"] == "CCO"
    assert top["similarity"] == 1.0


def test_similarity_search_rejects_invalid_query() -> None:
    result = _similarity_search_sync(
        SimilaritySearchRequest(query="not-a-smiles", candidates=[])
    )
    assert result.success is False
    assert "invalid query SMILES" in result.error


@pytest.mark.parametrize(
    "request_obj,expected",
    [
        (SmilesRequest(input="CCO"), {"smiles": "CCO"}),
        (
            GesimAtomMappingRequest(a="CCO", b="CCO"),
            {"smiles_a": "CCO", "smiles_b": "CCO"},
        ),
    ],
)
def test_chem_requests_accept_frontend_aliases(request_obj, expected) -> None:
    """Chem request models accept the frontend camelCase/short aliases."""
    for field, value in expected.items():
        assert getattr(request_obj, field) == value


def test_validate_one_smiles_response_has_frontend_fields() -> None:
    """Validation response exposes both legacy and frontend field names."""
    result = _validate_smiles_sync(["CCO"])[0]
    assert result.valid is True
    assert result.input == "CCO"
    assert result.smiles == "CCO"
    assert result.canonical_smiles is not None

    invalid = _validate_smiles_sync(["not-smiles"])[0]
    assert invalid.valid is False
    assert invalid.canonical_smiles is None
