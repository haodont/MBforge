"""Unit tests for the :class:`mbforge.domain.molecule.Molecule` value object.

Covers ``to_dict``/``from_dict``/``to_json``/``from_json``/``from_row`` bridges
plus the derived ``is_valid`` / ``fingerprint`` / ``tanimoto_bytes`` operations.
"""

from __future__ import annotations

from mbforge.domain.molecule import Molecule


def test_dict_and_json_round_trips_preserve_fields() -> None:
    """to_dict -> from_dict and to_json -> from_json keep every serializable
    field; the cacheable fingerprint is excluded from the dict form."""
    original = Molecule(
        mol_id="m1",
        canonical_smiles="CCO",
        smiles="CCO",
        esmiles="CCO",
        name="ethanol",
        activity=1.5,
        activity_type="IC50",
        units="nM",
        source_doc="doc-1",
        source_type="image",
        created_at="2026-01-01T00:00:00Z",
        status="active",
        review_status="approved",
        reviewed_at="2026-01-02T00:00:00Z",
        properties={"key": "value"},
        labels=["tag1"],
        semantic_tags=["organic"],
        notes="a note",
    )
    restored = Molecule.from_dict(original.to_dict())
    assert restored.mol_id == original.mol_id
    assert restored.canonical_smiles == original.canonical_smiles
    assert restored.name == original.name
    assert restored.activity == original.activity
    assert restored.properties == original.properties
    assert restored.labels == original.labels
    assert restored.semantic_tags == original.semantic_tags
    assert restored.notes == original.notes
    # fingerprint is excluded from to_dict
    assert "fingerprint" not in original.to_dict()
    assert restored._fingerprint is None

    json_original = Molecule(
        mol_id="m1",
        canonical_smiles="CCO",
        name="ethanol",
        properties={"k": "v"},
        labels=["a"],
    )
    json_restored = Molecule.from_json(json_original.to_json())
    assert json_restored.mol_id == json_original.mol_id
    assert json_restored.name == json_original.name
    assert json_restored.properties == json_original.properties
    assert json_restored.labels == json_original.labels


def test_from_dict_parses_json_columns_and_falls_back_on_bad_input() -> None:
    """from_dict parses JSON-encoded annotation columns, defaults malformed or
    missing values, and silently ignores unknown keys."""
    parsed = Molecule.from_dict(
        {
            "mol_id": "m1",
            "canonical_smiles": "CCO",
            "properties": '{"a": 1}',
            "labels": '["x", "y"]',
            "semantic_tags": '["tag"]',
        }
    )
    assert parsed.properties == {"a": 1}
    assert parsed.labels == ["x", "y"]
    assert parsed.semantic_tags == ["tag"]

    malformed = Molecule.from_dict(
        {
            "mol_id": "m1",
            "canonical_smiles": "CCO",
            "properties": "not-json",
            "labels": "not-json",
            "semantic_tags": "not-json",
        }
    )
    assert malformed.properties == {}
    assert malformed.labels == []
    assert malformed.semantic_tags == []

    assert (
        Molecule.from_dict(
            {"mol_id": "m1", "canonical_smiles": "CCO", "unknown_field": 42}
        ).mol_id
        == "m1"
    )

    defaults = Molecule.from_dict({"mol_id": "m1"})
    assert defaults.canonical_smiles == ""
    assert defaults.status == "active"
    assert defaults.review_status == "pending"
    assert defaults.properties == {}


def test_from_row_bridges_the_sqlite_row_shape() -> None:
    """from_row accepts a dict mirroring the molecules table schema."""
    row = {
        "mol_id": "m1",
        "smiles": "CCO",
        "esmiles": "CCO",
        "name": "ethanol",
        "source_doc": "doc-1",
        "activity": 1.5,
        "activity_type": "IC50",
        "units": "nM",
        "source_type": "image",
        "status": "active",
        "properties": '{"k": "v"}',
        "labels": '["a"]',
        "semantic_tags": '["t"]',
        "notes": "note",
        "fingerprint": b"\x00",
        "canonical_smiles": "CCO",
        "review_status": "pending",
        "reviewed_at": None,
        "created_at": "2026-01-01T00:00:00Z",
    }
    m = Molecule.from_row(row)
    assert m.mol_id == "m1"
    assert m.properties == {"k": "v"}
    assert m.labels == ["a"]
    assert m.fingerprint == b"\x00"


def test_is_valid_only_for_parseable_smiles() -> None:
    """is_valid is True for a parseable SMILES, False for garbage or empty."""
    for smiles, expected in (("CCO", True), ("not-a-smiles", False), ("", False)):
        m = Molecule(mol_id="m1", canonical_smiles=smiles)
        assert m.is_valid() is expected, f"{smiles!r}"


def test_fingerprint_is_lazily_cached_and_overridable() -> None:
    """fingerprint computes lazily and caches, returns None for an unparseable
    SMILES, and the setter bypasses lazy computation."""
    m = Molecule(mol_id="m1", canonical_smiles="CCO")
    assert m._fingerprint is None  # not yet computed
    fp = m.fingerprint
    assert isinstance(fp, bytes)
    assert len(fp) == 256  # 2048 bits packed
    assert m._fingerprint == fp  # cached

    assert Molecule(mol_id="m1", canonical_smiles="not-a-smiles").fingerprint is None

    custom = b"\xab" * 256
    m.fingerprint = custom
    assert m.fingerprint == custom


def test_tanimoto_bytes_bounds() -> None:
    """Self-similarity is 1.0; different molecules score in [0, 1)."""
    m = Molecule(mol_id="m1", canonical_smiles="CCO")
    fp = m.fingerprint
    assert fp is not None
    assert Molecule.tanimoto_bytes(fp, fp) == 1.0

    a = Molecule(mol_id="m1", canonical_smiles="CCO").fingerprint
    b = Molecule(mol_id="m2", canonical_smiles="c1ccccc1").fingerprint
    assert a is not None
    assert b is not None
    sim = Molecule.tanimoto_bytes(a, b)
    assert 0.0 <= sim < 1.0
