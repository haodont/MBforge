"""Per-molecule entity: a molecule as a typed value object.

A :class:`Molecule` is the canonical in-memory representation of a
molecule record. It holds the flat fields of the ``molecules`` table as
typed attributes, with JSON columns (``properties``, ``labels``,
``semantic_tags``) parsed into native Python types.

This class is a *pure value object* — it does not touch the database
itself. Persistence is handled by a separate repository / service layer
(e.g. :mod:`mbforge.services.molecule.queries`). The class only knows
how to round-trip to/from a dict or JSON string, so it can be backed by
either SQLite rows or JSON files without changing the entity itself.

Scope guard: related tables (``molecule_detections``, ``evidence``,
``molecule_images``, ``molecule_relations``) are NOT part of the
molecule entity. They are traversed by the service layer.

Relationship to :class:`NormalizedMolecule` (in
:mod:`mbforge.core.detection.types`): ``NormalizedMolecule`` is the
transient pipeline processing record (pre-persistence, carries
``detections[]``). ``Molecule`` is the persisted shape (has ``mol_id``).
The bridge between them lives in the persistence layer.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any


@dataclass
class Molecule:
    """A molecule as a typed value object.

    Fields mirror the ``molecules`` SQLite table. JSON columns are
    exposed as native Python types (``dict`` / ``list``). The binary
    ``fingerprint`` field is preserved in-memory but excluded from
    :meth:`to_dict` / :meth:`to_json` (not JSON-friendly and
    recomputable from ``canonical_smiles``).
    """

    # ── Identity ────────────────────────────────────────────────
    mol_id: str
    canonical_smiles: str

    # ── Chemical core ───────────────────────────────────────────
    smiles: str = ""
    esmiles: str = ""
    name: str = ""
    _fingerprint: bytes | None = field(
        default=None, init=False, repr=False, compare=False
    )

    # ── Activity ────────────────────────────────────────────────
    activity: float | None = None
    activity_type: str = ""
    units: str = ""

    # ── Provenance ──────────────────────────────────────────────
    source_doc: str = ""
    source_type: str = ""
    created_at: str = ""

    # ── Lifecycle ───────────────────────────────────────────────
    status: str = "active"
    review_status: str = "pending"
    reviewed_at: str | None = None

    # ── Annotations (typed; JSON columns in DB) ─────────────────
    properties: dict[str, Any] = field(default_factory=dict)
    labels: list[str] = field(default_factory=list)
    semantic_tags: list[str] = field(default_factory=list)
    notes: str = ""

    # ── Fingerprint property (lazy computation) ─────────────────

    @property
    def fingerprint(self) -> bytes | None:
        """Morgan fingerprint, computed lazily from canonical_smiles."""
        if self._fingerprint is None and self.canonical_smiles:
            self._fingerprint = self._compute_fingerprint()
        return self._fingerprint

    @fingerprint.setter
    def fingerprint(self, value: bytes | None) -> None:
        self._fingerprint = value

    def _compute_fingerprint(self) -> bytes | None:
        """Compute Morgan fingerprint (ECFP4, 2048 bits)."""
        import numpy as np
        from rdkit import Chem
        from rdkit.Chem import AllChem

        try:
            mol = Chem.MolFromSmiles(self.canonical_smiles.strip())
            if mol is None:
                return None
            fp = AllChem.GetMorganFingerprintAsBitVect(mol, 2, nBits=2048)
            arr = np.array(fp, dtype=np.uint8)
            return np.packbits(arr).tobytes()
        except Exception:
            return None

    # ── Derived chemical operations ─────────────────────────────

    def is_valid(self) -> bool:
        """Return True if the canonical SMILES is parseable by RDKit."""
        from rdkit import Chem

        if not self.canonical_smiles or not self.canonical_smiles.strip():
            return False
        try:
            return Chem.MolFromSmiles(self.canonical_smiles.strip()) is not None
        except Exception:
            return False

    def similarity(self, other: Molecule) -> float:
        """Compute Tanimoto similarity with another molecule."""
        import numpy as np

        fp1 = self.fingerprint
        fp2 = other.fingerprint
        if fp1 is None or fp2 is None:
            return 0.0
        arr1 = np.unpackbits(np.frombuffer(fp1, dtype=np.uint8))[:2048]
        arr2 = np.unpackbits(np.frombuffer(fp2, dtype=np.uint8))[:2048]
        intersection = int(np.count_nonzero(arr1 & arr2))
        union = int(np.count_nonzero(arr1 | arr2))
        if union == 0:
            return 1.0 if intersection == 0 else 0.0
        return intersection / union

    @staticmethod
    def tanimoto_bytes(a: bytes, b: bytes) -> float:
        """Compute Tanimoto similarity between two packed fingerprint blobs."""
        import numpy as np

        av = np.unpackbits(np.frombuffer(a, dtype=np.uint8))[:2048]
        bv = np.unpackbits(np.frombuffer(b, dtype=np.uint8))[:2048]
        intersection = int(np.count_nonzero(av & bv))
        union = int(np.count_nonzero(av | bv))
        if union == 0:
            return 1.0 if intersection == 0 else 0.0
        return intersection / union

    # ── Serialization ───────────────────────────────────────────

    def to_dict(self) -> dict[str, Any]:
        """Return the record as a plain dict suitable for JSON serialization.

        The binary ``fingerprint`` field is excluded (not JSON-friendly
        and recomputable from ``canonical_smiles``).
        """
        return {
            "mol_id": self.mol_id,
            "canonical_smiles": self.canonical_smiles,
            "smiles": self.smiles,
            "esmiles": self.esmiles,
            "name": self.name,
            "activity": self.activity,
            "activity_type": self.activity_type,
            "units": self.units,
            "source_doc": self.source_doc,
            "source_type": self.source_type,
            "created_at": self.created_at,
            "status": self.status,
            "review_status": self.review_status,
            "reviewed_at": self.reviewed_at,
            "properties": self.properties,
            "labels": self.labels,
            "semantic_tags": self.semantic_tags,
            "notes": self.notes,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> Molecule:
        """Construct a Molecule from a dict (e.g. loaded from JSON).

        JSON columns (``properties``, ``labels``, ``semantic_tags``)
        accept either already-parsed native types or JSON-encoded
        strings, so the same constructor handles both JSON-file input
        and raw SQLite rows. Unknown keys are ignored; missing keys
        fall back to defaults.
        """

        def _json_col(key: str, default: Any) -> Any:
            v = data.get(key, default)
            if isinstance(v, str):
                try:
                    return json.loads(v)
                except (json.JSONDecodeError, TypeError):
                    return default
            if v is None:
                return default
            return v

        mol = cls(
            mol_id=data.get("mol_id", ""),
            canonical_smiles=data.get("canonical_smiles", ""),
            smiles=data.get("smiles", ""),
            esmiles=data.get("esmiles", ""),
            name=data.get("name", ""),
            activity=data.get("activity"),
            activity_type=data.get("activity_type", ""),
            units=data.get("units", ""),
            source_doc=data.get("source_doc", ""),
            source_type=data.get("source_type", ""),
            created_at=data.get("created_at", ""),
            status=data.get("status", "active"),
            review_status=data.get("review_status", "pending"),
            reviewed_at=data.get("reviewed_at"),
            properties=_json_col("properties", {}),
            labels=_json_col("labels", []),
            semantic_tags=_json_col("semantic_tags", []),
            notes=data.get("notes", ""),
        )
        # Set fingerprint via setter (it's a property, not a constructor param)
        if "fingerprint" in data:
            mol.fingerprint = data["fingerprint"]
        return mol

    def to_json(self) -> str:
        """Return the record as a JSON string."""
        return json.dumps(self.to_dict(), ensure_ascii=False, indent=2)

    @classmethod
    def from_json(cls, json_str: str) -> Molecule:
        """Construct a Molecule from a JSON string."""
        return cls.from_dict(json.loads(json_str))

    # ── DB row bridge ───────────────────────────────────────────

    @classmethod
    def from_row(cls, row: dict) -> Molecule:
        """Construct a Molecule from a DB row (``dict`` or ``sqlite3.Row``).

        Thin wrapper around :meth:`from_dict` that accepts any
        dict-like row. JSON columns are parsed the same way.
        """
        return cls.from_dict(dict(row))


@dataclass
class MarkushScaffold:
    """A Markush scaffold as a typed value object.

    Fields mirror the ``markush_scaffolds`` SQLite table. A scaffold is
    the core structure of a Markush pattern — it carries explicit
    attachment sites (``[*:N]``) where R-groups can be mounted. JSON
    columns (``properties``) are parsed into native Python types.

    This class is a *pure value object* — it does not touch the database.
    Persistence is handled by the service layer
    (:mod:`mbforge.storage.markush_candidates`).
    """

    # ── Identity ────────────────────────────────────────────────
    scaffold_id: str
    doc_id: str
    smiles: str

    # ── Chemical core ───────────────────────────────────────────
    esmiles: str = ""
    formula_label: str = ""

    # ── Provenance (page + bbox of the source image) ────────────
    page: int | None = None
    bbox_x0: float | None = None
    bbox_y0: float | None = None
    bbox_x1: float | None = None
    bbox_y1: float | None = None
    crop_relpath: str | None = None

    # ── Confidence & lifecycle ──────────────────────────────────
    confidence: float | None = None
    status: str = "pending"

    # ── Annotations (JSON column in DB) ─────────────────────────
    properties: dict[str, Any] = field(default_factory=dict)

    # ── Timestamps ──────────────────────────────────────────────
    created_at: str = ""
    updated_at: str = ""

    # ── Derived chemical operations ─────────────────────────────

    @property
    def attachment_count(self) -> int:
        """Number of explicit attachment sites (``*`` atoms) in the SMILES."""
        return self.smiles.count("*") if self.smiles else 0

    def is_valid(self) -> bool:
        """Return True if the SMILES is parseable by RDKit."""
        from rdkit import Chem

        if not self.smiles or not self.smiles.strip():
            return False
        try:
            return Chem.MolFromSmiles(self.smiles.strip()) is not None
        except Exception:
            return False

    # ── Serialization ───────────────────────────────────────────

    def to_dict(self) -> dict[str, Any]:
        """Return the record as a plain dict suitable for JSON serialization."""
        return {
            "scaffold_id": self.scaffold_id,
            "doc_id": self.doc_id,
            "smiles": self.smiles,
            "esmiles": self.esmiles,
            "formula_label": self.formula_label,
            "page": self.page,
            "bbox_x0": self.bbox_x0,
            "bbox_y0": self.bbox_y0,
            "bbox_x1": self.bbox_x1,
            "bbox_y1": self.bbox_y1,
            "crop_relpath": self.crop_relpath,
            "confidence": self.confidence,
            "status": self.status,
            "properties": self.properties,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> MarkushScaffold:
        """Construct a MarkushScaffold from a dict.

        The ``properties`` column accepts either an already-parsed dict
        or a JSON-encoded string. Unknown keys are ignored; missing
        keys fall back to defaults.
        """

        def _json_col(key: str, default: Any) -> Any:
            v = data.get(key, default)
            if isinstance(v, str):
                try:
                    return json.loads(v)
                except (json.JSONDecodeError, TypeError):
                    return default
            if v is None:
                return default
            return v

        return cls(
            scaffold_id=data.get("scaffold_id", ""),
            doc_id=data.get("doc_id", ""),
            smiles=data.get("smiles", ""),
            esmiles=data.get("esmiles", ""),
            formula_label=data.get("formula_label", ""),
            page=data.get("page"),
            bbox_x0=data.get("bbox_x0"),
            bbox_y0=data.get("bbox_y0"),
            bbox_x1=data.get("bbox_x1"),
            bbox_y1=data.get("bbox_y1"),
            crop_relpath=data.get("crop_relpath"),
            confidence=data.get("confidence"),
            status=data.get("status", "pending"),
            properties=_json_col("properties", {}),
            created_at=data.get("created_at", ""),
            updated_at=data.get("updated_at", ""),
        )

    def to_json(self) -> str:
        """Return the record as a JSON string."""
        return json.dumps(self.to_dict(), ensure_ascii=False, indent=2)

    @classmethod
    def from_json(cls, json_str: str) -> MarkushScaffold:
        """Construct a MarkushScaffold from a JSON string."""
        return cls.from_dict(json.loads(json_str))

    @classmethod
    def from_row(cls, row: dict) -> MarkushScaffold:
        """Construct a MarkushScaffold from a DB row."""
        return cls.from_dict(dict(row))


@dataclass
class MarkushFragment:
    """A Markush fragment as a typed value object.

    Fields mirror the ``markush_fragments`` SQLite table. A fragment is
    an R-group substituent that can be mounted on a scaffold's
    attachment sites. Optionally linked to a parent ``scaffold_id``.

    This class is a *pure value object* — it does not touch the database.
    Persistence is handled by the service layer.
    """

    # ── Identity ────────────────────────────────────────────────
    fragment_id: str
    doc_id: str
    smiles: str

    # ── Parent scaffold (optional) ──────────────────────────────
    scaffold_id: str | None = None

    # ── Chemical core ───────────────────────────────────────────
    esmiles: str = ""
    label: str = ""

    # ── Provenance (page + bbox of the source image) ────────────
    page: int | None = None
    bbox_x0: float | None = None
    bbox_y0: float | None = None
    bbox_x1: float | None = None
    bbox_y1: float | None = None
    crop_relpath: str | None = None

    # ── Confidence & lifecycle ──────────────────────────────────
    confidence: float | None = None
    status: str = "pending"

    # ── Annotations (JSON column in DB) ─────────────────────────
    properties: dict[str, Any] = field(default_factory=dict)

    # ── Timestamps ──────────────────────────────────────────────
    created_at: str = ""
    updated_at: str = ""

    # ── Derived chemical operations ─────────────────────────────

    @property
    def attachment_count(self) -> int:
        """Number of attachment points (``*`` atoms) in the SMILES."""
        return self.smiles.count("*") if self.smiles else 0

    def is_valid(self) -> bool:
        """Return True if the SMILES is parseable by RDKit."""
        from rdkit import Chem

        if not self.smiles or not self.smiles.strip():
            return False
        try:
            return Chem.MolFromSmiles(self.smiles.strip()) is not None
        except Exception:
            return False

    # ── Serialization ───────────────────────────────────────────

    def to_dict(self) -> dict[str, Any]:
        """Return the record as a plain dict suitable for JSON serialization."""
        return {
            "fragment_id": self.fragment_id,
            "doc_id": self.doc_id,
            "scaffold_id": self.scaffold_id,
            "smiles": self.smiles,
            "esmiles": self.esmiles,
            "label": self.label,
            "page": self.page,
            "bbox_x0": self.bbox_x0,
            "bbox_y0": self.bbox_y0,
            "bbox_x1": self.bbox_x1,
            "bbox_y1": self.bbox_y1,
            "crop_relpath": self.crop_relpath,
            "confidence": self.confidence,
            "status": self.status,
            "properties": self.properties,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> MarkushFragment:
        """Construct a MarkushFragment from a dict.

        The ``properties`` column accepts either an already-parsed dict
        or a JSON-encoded string. Unknown keys are ignored; missing
        keys fall back to defaults.
        """

        def _json_col(key: str, default: Any) -> Any:
            v = data.get(key, default)
            if isinstance(v, str):
                try:
                    return json.loads(v)
                except (json.JSONDecodeError, TypeError):
                    return default
            if v is None:
                return default
            return v

        return cls(
            fragment_id=data.get("fragment_id", ""),
            doc_id=data.get("doc_id", ""),
            scaffold_id=data.get("scaffold_id"),
            smiles=data.get("smiles", ""),
            esmiles=data.get("esmiles", ""),
            label=data.get("label", ""),
            page=data.get("page"),
            bbox_x0=data.get("bbox_x0"),
            bbox_y0=data.get("bbox_y0"),
            bbox_x1=data.get("bbox_x1"),
            bbox_y1=data.get("bbox_y1"),
            crop_relpath=data.get("crop_relpath"),
            confidence=data.get("confidence"),
            status=data.get("status", "pending"),
            properties=_json_col("properties", {}),
            created_at=data.get("created_at", ""),
            updated_at=data.get("updated_at", ""),
        )

    def to_json(self) -> str:
        """Return the record as a JSON string."""
        return json.dumps(self.to_dict(), ensure_ascii=False, indent=2)

    @classmethod
    def from_json(cls, json_str: str) -> MarkushFragment:
        """Construct a MarkushFragment from a JSON string."""
        return cls.from_dict(json.loads(json_str))

    @classmethod
    def from_row(cls, row: dict) -> MarkushFragment:
        """Construct a MarkushFragment from a DB row."""
        return cls.from_dict(dict(row))


__all__ = ["Molecule", "MarkushScaffold", "MarkushFragment"]
