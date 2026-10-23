"""Unit tests for the chemistry endpoints in ``mbforge.api.http.molecule.chem``.

Protects: every async route offloads its blocking RDKit work to
``asyncio.to_thread``, the request models accept the frontend
camelCase/short aliases, batch/legacy SMILES validation exposes both the
legacy and the frontend field names, and substructure/similarity search
reject an invalid query SMILES instead of returning matches.
"""

from __future__ import annotations

import asyncio

import pytest

from mbforge.api.http.molecule.chem import (
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
from mbforge.service.dto.chem import (
    FingerprintPairRequest,
    GesimAtomMappingRequest,
    SimilaritySearchRequest,
    SmilesImageRequest,
    SmilesRequest,
    SubstructureSearchRequest,
    ValidateSmilesRequest,
)
from mbforge.service.use_cases.chem.chem import (
    canonicalize_sync as _canonicalize_sync,
)
from mbforge.service.use_cases.chem.chem import (
    draw_smiles_sync as _draw_smiles_sync,
)
from mbforge.service.use_cases.chem.chem import (
    fingerprint_sync as _fingerprint_sync,
)
from mbforge.service.use_cases.chem.chem import (
    properties_sync as _properties_sync,
)
from mbforge.service.use_cases.chem.chem import (
    similarity_search_sync as _similarity_search_sync,
)
from mbforge.service.use_cases.chem.chem import (
    substructure_search_sync as _substructure_search_sync,
)
from mbforge.service.use_cases.chem.chem import (
    tanimoto_sync as _tanimoto_sync,
)
from mbforge.service.use_cases.chem.chem import (
    validate_smiles_sync as _validate_smiles_sync,
)


def _capture_to_thread(monkeypatch: pytest.MonkeyPatch):
    """Patch asyncio.to_thread so callers can inspect what was offloaded."""
    calls: list[tuple[object, tuple, dict]] = []

    async def _fake_to_thread(func, *args, **kwargs):
        calls.append((func, args, kwargs))
        return {"_fake": True}

    monkeypatch.setattr(asyncio, "to_thread", _fake_to_thread)
    return calls


def test_chem_routes_offload_to_thread(monkeypatch: pytest.MonkeyPatch) -> None:
    """Async chemistry routes delegate blocking RDKit work to asyncio.to_thread."""
    cases = [
        (
            "validate_smiles",
            validate_smiles,
            _validate_smiles_sync,
            ValidateSmilesRequest(smiles="CCO"),
        ),
        ("fingerprint", fingerprint, _fingerprint_sync, SmilesRequest(smiles="CCO")),
        ("properties", properties, _properties_sync, SmilesRequest(smiles="CCO")),
        ("canonicalize", canonicalize, _canonicalize_sync, SmilesRequest(smiles="CCO")),
        (
            "tanimoto",
            tanimoto,
            _tanimoto_sync,
            FingerprintPairRequest(fingerprint_a=[1, 0, 1], fingerprint_b=[1, 1, 0]),
        ),
        (
            "substructure_search",
            substructure_search,
            _substructure_search_sync,
            SubstructureSearchRequest(query="CCO", candidates=[{"smiles": "CCCO"}]),
        ),
        (
            "similarity_search",
            similarity_search,
            _similarity_search_sync,
            SimilaritySearchRequest(query="CCO", candidates=[{"smiles": "CCCO"}]),
        ),
    ]
    calls = _capture_to_thread(monkeypatch)

    for index, (name, handler, sync_func, body) in enumerate(cases):
        result = asyncio.run(handler(body))

        assert result == {"_fake": True}, name
        assert len(calls) == index + 1, name
        assert calls[-1][0] is sync_func, name


def test_draw_smiles_renders_markush_wildcards_as_svg() -> None:
    result = _draw_smiles_sync("*c1ccc(*)nc1", 360, 240)

    assert result.success is True
    assert "<svg" in result.svg


def test_smiles_to_image_rejects_invalid_smiles() -> None:
    result = asyncio.run(smiles_to_image(SmilesImageRequest(smiles="not-smiles")))

    assert result.success is False
    assert result.error == "invalid SMILES"


def test_validate_smiles_batch_and_legacy_expose_frontend_fields() -> None:
    """Batch validation accepts both ``list`` and legacy ``smiles``.

    An empty request is a ``ValueError``; each response carries the legacy
    (``input``/``valid``) and frontend (``smiles``/``canonical_smiles``) names.
    """
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

    valid = _validate_smiles_sync(["CCO"])[0]
    assert valid.valid is True
    assert valid.input == "CCO"
    assert valid.smiles == "CCO"
    assert valid.canonical_smiles is not None

    invalid = _validate_smiles_sync(["not-smiles"])[0]
    assert invalid.valid is False
    assert invalid.canonical_smiles is None

    with pytest.raises(ValueError):
        ValidateSmilesRequest()


def test_gesim_not_implemented_returns_envelope() -> None:
    """The gesim atom-mapping endpoint returns a stable not-implemented envelope."""
    mapping = asyncio.run(
        gesim_atom_mapping(GesimAtomMappingRequest(smiles_a="CCO", smiles_b="CCO"))
    )
    assert mapping.success is False
    assert "not implemented" in mapping.error


def test_substructure_search_matches_candidates_and_rejects_invalid_query() -> None:
    """Substructure search filters by the query and refuses an invalid query SMILES."""
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

    invalid = _substructure_search_sync(
        SubstructureSearchRequest(query="not-a-smiles", candidates=[])
    )
    assert invalid.success is False
    assert "invalid query SMILES" in invalid.error


def test_similarity_search_ranks_candidates_and_rejects_invalid_query() -> None:
    """Similarity search returns scored candidates and refuses an invalid query SMILES."""
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

    invalid = _similarity_search_sync(
        SimilaritySearchRequest(query="not-a-smiles", candidates=[])
    )
    assert invalid.success is False
    assert "invalid query SMILES" in invalid.error


def test_chem_requests_accept_frontend_aliases() -> None:
    """Chem request models accept the frontend camelCase/short aliases."""
    cases = [
        ("SmilesRequest", SmilesRequest(input="CCO"), {"smiles": "CCO"}),
        (
            "GesimAtomMappingRequest",
            GesimAtomMappingRequest(a="CCO", b="CCO"),
            {"smiles_a": "CCO", "smiles_b": "CCO"},
        ),
    ]

    for name, request_obj, expected in cases:
        for field, value in expected.items():
            assert getattr(request_obj, field) == value, f"{name}.{field}"
