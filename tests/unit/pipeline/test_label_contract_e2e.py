"""End-to-end test for the coreference-label persistence contract.

Reproduces the Phase-0 bug fixed by :mod:`mbforge.pipeline.detection.label_normalization`:

- An ``ExtractionResult`` carrying a ``formula_label`` of ``"R₁"`` used to
  land in :class:`NormalizedMolecule.properties` only as a list entry
  under ``role_contexts``.
- :func:`persist_markush_scaffolds` then read ``properties["formula_label"]``
  directly and stored ``""`` in the database.
- The downstream review/audit pipeline had no way to link a scaffold back
  to its human-readable label.

After the fix, the same input must round-trip through normalization and
emerge as ``"R1"`` in the ``markush_scaffolds.formula_label`` column,
with ``raw_coref_label`` / ``normalized_label`` / ``label_kind`` written
to ``properties`` for downstream consumers.
"""

from __future__ import annotations

from mbforge.pipeline.detection.normalization import normalize_molecules
from mbforge.pipeline.detection.types import ExtractionResult
from mbforge.pipeline.persist.markush import persist_markush_scaffolds
from mbforge.storage.sqlite.database import DatabaseManager


def _extraction(*, esmiles: str, formula_label: str | None) -> ExtractionResult:
    return ExtractionResult(
        esmiles=esmiles,
        smiles=esmiles,
        source="image",
        page_idx=1,
        bbox_pdf=(0.0, 0.0, 10.0, 10.0),
        mol_img_path="crop.png",
        moldet_conf=0.9,
        properties={"formula_label": formula_label} if formula_label else {},
    )


def test_formula_label_round_trips_into_markush_scaffold(tmp_path) -> None:
    db = DatabaseManager.get(str(tmp_path))
    db.initialize()

    # Two distinct scaffolds with different labels — keep them separate
    # so we exercise both ``r_group`` and ``formula`` kinds in a single
    # persist transaction.
    results = [
        _extraction(esmiles="*c1ccc(*)cc1", formula_label="R₁"),
        _extraction(esmiles="*c1ccc(*)c(*)c1", formula_label="Formula I"),
    ]

    normalized = normalize_molecules(results)
    assert len(normalized) == 2, "two distinct SMILES must remain distinct"

    # Every normalized molecule must carry the canonical triple from the
    # normalizer; the legacy ``formula_label`` key must also remain for
    # back-compat readers.
    for molecule in normalized:
        assert molecule.properties["raw_coref_label"]
        assert molecule.properties["normalized_label"]
        assert molecule.properties["label_kind"] in {
            "formula",
            "r_group",
            "ring",
            "compound",
            "example",
            "unknown",
        }
        assert molecule.properties["formula_label"]

    for molecule in normalized:
        molecule.properties["structure_role"] = "scaffold"

    with db.mol_conn() as conn:
        persist_markush_scaffolds("doc-1", normalized, conn=conn)
        rows = conn.execute(
            "SELECT formula_label, smiles, properties "
            "FROM markush_scaffolds ORDER BY formula_label"
        ).fetchall()

    labels = {row["formula_label"] for row in rows}
    assert labels == {"R1", "Formula I"}, (
        f"Expected the canonical labels to land in the DB, got {labels}"
    )

    # The stored properties blob must include the canonical triple so
    # downstream consumers can index by ``normalized_label`` without
    # needing the column itself.
    for row in rows:
        import json

        props = json.loads(row["properties"])
        assert props["normalized_label"] == row["formula_label"]
        assert props["label_kind"] in {"formula", "r_group"}
