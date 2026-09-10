"""Unit tests for the :class:`mbforge.core.entities.molecule.Molecule` value object."""

from __future__ import annotations

from mbforge.core.entities.molecule import Molecule

# ---------------------------------------------------------------------------
# Construction
# ---------------------------------------------------------------------------


def test_to_dict_round_trip() -> None:
    """to_dict -> from_dict preserves all fields (except fingerprint)."""
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
    assert restored._fingerprint is None  # fingerprint excluded from to_dict


def test_from_dict_handles_json_string_columns() -> None:
    """from_dict parses JSON-encoded strings for annotation columns."""
    data = {
        "mol_id": "m1",
        "canonical_smiles": "CCO",
        "properties": '{"a": 1}',
        "labels": '["x", "y"]',
        "semantic_tags": '["tag"]',
    }
    m = Molecule.from_dict(data)
    assert m.properties == {"a": 1}
    assert m.labels == ["x", "y"]
    assert m.semantic_tags == ["tag"]


def test_from_dict_handles_malformed_json_gracefully() -> None:
    """Malformed JSON strings fall back to defaults."""
    data = {
        "mol_id": "m1",
        "canonical_smiles": "CCO",
        "properties": "not-json",
        "labels": "not-json",
        "semantic_tags": "not-json",
    }
    m = Molecule.from_dict(data)
    assert m.properties == {}
    assert m.labels == []
    assert m.semantic_tags == []


def test_from_dict_ignores_unknown_keys() -> None:
    """Extra keys in the input dict are silently ignored."""
    data = {"mol_id": "m1", "canonical_smiles": "CCO", "unknown_field": 42}
    m = Molecule.from_dict(data)
    assert m.mol_id == "m1"


def test_from_dict_missing_keys_use_defaults() -> None:
    """Missing keys fall back to defaults."""
    m = Molecule.from_dict({"mol_id": "m1"})
    assert m.canonical_smiles == ""
    assert m.status == "active"
    assert m.review_status == "pending"
    assert m.properties == {}


# ---------------------------------------------------------------------------
# Serialization: JSON
# ---------------------------------------------------------------------------


def test_to_json_from_json_round_trip() -> None:
    """to_json -> from_json preserves all serializable fields."""
    original = Molecule(
        mol_id="m1",
        canonical_smiles="CCO",
        name="ethanol",
        properties={"k": "v"},
        labels=["a"],
    )
    restored = Molecule.from_json(original.to_json())
    assert restored.mol_id == original.mol_id
    assert restored.name == original.name
    assert restored.properties == original.properties
    assert restored.labels == original.labels


# ---------------------------------------------------------------------------
# DB row bridge
# ---------------------------------------------------------------------------


def test_from_row_with_sqlite_row_shape() -> None:
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


# ---------------------------------------------------------------------------
# Derived chemical operations
# ---------------------------------------------------------------------------


def test_is_valid_true_for_parseable_smiles() -> None:
    """is_valid returns True for a SMILES RDKit can parse."""
    m = Molecule(mol_id="m1", canonical_smiles="CCO")
    assert m.is_valid() is True


def test_is_valid_false_for_garbage() -> None:
    """is_valid returns False for an unparseable SMILES."""
    m = Molecule(mol_id="m1", canonical_smiles="not-a-smiles")
    assert m.is_valid() is False


def test_is_valid_false_for_empty() -> None:
    """is_valid returns False for empty SMILES."""
    m = Molecule(mol_id="m1", canonical_smiles="")
    assert m.is_valid() is False


def test_fingerprint_lazy_computation() -> None:
    """fingerprint property computes lazily on first access."""
    m = Molecule(mol_id="m1", canonical_smiles="CCO")
    assert m._fingerprint is None  # not yet computed
    fp = m.fingerprint
    assert isinstance(fp, bytes)
    assert len(fp) == 256  # 2048 bits packed
    assert m._fingerprint == fp  # cached


def test_fingerprint_lazy_returns_none_for_invalid() -> None:
    """fingerprint property returns None for unparseable SMILES."""
    m = Molecule(mol_id="m1", canonical_smiles="not-a-smiles")
    assert m.fingerprint is None


def test_fingerprint_setter_bypasses_lazy() -> None:
    """Setting fingerprint via setter prevents lazy computation."""
    m = Molecule(mol_id="m1", canonical_smiles="CCO")
    custom = b"\xab" * 256
    m.fingerprint = custom
    assert m.fingerprint == custom


def test_tanimoto_bytes_self_similarity() -> None:
    """Tanimoto similarity of a fingerprint with itself is 1.0."""
    m = Molecule(mol_id="m1", canonical_smiles="CCO")
    fp = m.fingerprint
    assert fp is not None
    assert Molecule.tanimoto_bytes(fp, fp) == 1.0


def test_tanimoto_bytes_different_molecules() -> None:
    """Tanimoto similarity between different molecules is in [0, 1)."""
    a = Molecule(mol_id="m1", canonical_smiles="CCO").fingerprint
    b = Molecule(mol_id="m2", canonical_smiles="c1ccccc1").fingerprint
    assert a is not None
    assert b is not None
    sim = Molecule.tanimoto_bytes(a, b)
    assert 0.0 <= sim < 1.0
