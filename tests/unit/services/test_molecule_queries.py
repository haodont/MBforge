"""Unit tests for services.molecule.queries read paths.

Focus: ``molecules_by_location`` reading the v2 run branches restored with
SQL source evidence — page-basis conversion, the persistable-candidate
filter, the interactive cache union and the SQL fallback for legacy
documents without artifacts.
"""

from __future__ import annotations

from pathlib import Path

from mbforge.core.detection.types import DetectionSource, NormalizedMolecule
from mbforge.pipeline.extract_text import ExtractedDocument, PageContent
from mbforge.services.molecule.queries import molecules_by_location
from mbforge.storage.sqlite.database import DatabaseManager
from tests.unit.v2_artifact_helpers import publish_v2_run

# Router-order bbox tuple (x0, x1, y0, y1); values are PDF points.
QUERY = (15.0, 35.0, 25.0, 55.0)
STORED_BOX = (10.0, 20.0, 40.0, 60.0)  # contains QUERY on both axes


def _candidate(
    page: int | None = 2,
    bbox: tuple[float, float, float, float] | None = STORED_BOX,
    canonical: str = "CCO",
    status: str = "pending",
    properties: dict | None = None,
) -> NormalizedMolecule:
    return NormalizedMolecule(
        canonical_smiles=canonical,
        esmiles=f"{canonical}<sep>",
        name="EtOH",
        sources=["image"],
        detections=[
            DetectionSource(
                source="image",
                page=page,
                bbox=bbox,
                image_path="crops/etoh.png",
                confidence=0.9,
                conf_moldet=0.9,
            )
        ],
        status=status,
        properties={"structure_role": "complete"} if properties is None else properties,
    )


def _save_index(
    tmp_path: Path, doc_id: str, candidates: list[NormalizedMolecule]
) -> None:
    extracted = ExtractedDocument(
        raw_text="...",
        page_count=4,
        parser="pymupdf+ocr",
        pages=[PageContent(page_num=3, text="page text")],
    )
    publish_v2_run(
        tmp_path,
        doc_id,
        "run-1",
        extracted,
        candidates,
        {"molecule_count": len(candidates)},
        width=200.0,
        height=100.0,
    )


def _insert_cache_row(
    conn, mol_id: str | None, page: int, box: tuple[float, float, float, float]
) -> None:
    conn.execute(
        """
        INSERT INTO molecule_detections
            (mol_id, doc_id, page, bbox_x0, bbox_y0, bbox_x1, bbox_y1,
             crop_relpath, conf_moldet, conf_molscribe, vlm_verified_esmiles)
        VALUES (?, 'doc-1', ?, ?, ?, ?, ?, 'crops/cache.png', ?, ?, 'CCO')
        """,
        (mol_id, page, *box, 0.9, 0.9),
    )


def test_by_location_matches_index_and_dedupes_cache_mirror(tmp_path: Path) -> None:
    root = str(tmp_path)
    _save_index(tmp_path, "doc-1", [_candidate()])

    db = DatabaseManager.get(root)
    db.initialize()
    with db.mol_conn() as conn:
        conn.execute(
            "INSERT INTO molecules (mol_id, smiles, name, canonical_smiles) "
            "VALUES ('CCO', 'CCO', 'ethanol', 'CCO')"
        )
        # Persist-time mirror of the primary detection — must dedupe away.
        _insert_cache_row(conn, "CCO", 2, STORED_BOX)
        # Interactive recognition row on the same page — different stored box
        # that still contains the query box.
        _insert_cache_row(conn, None, 2, (12.0, 18.0, 45.0, 65.0))

    matches = molecules_by_location(root, "doc-1", 3, QUERY)

    assert len(matches) == 2
    index_match = next(m for m in matches if m["mol_id"] == "CCO")
    # 0-based artifact page → 1-based public page; identity follows persist.
    assert index_match["page"] == 3
    assert index_match["canonical_smiles"] == "CCO"
    assert index_match["name"] == "ethanol"  # refreshed from the molecules row
    assert index_match["confidence"] == 0.9
    assert index_match["bbox"] == {
        "x0": 10.0,
        "y0": 20.0,
        "x1": 40.0,
        "y1": 60.0,
    }
    assert index_match["crop_url"] and "etoh.png" in index_match["crop_url"]

    cache_match = next(m for m in matches if m["mol_id"] is None)
    assert cache_match["canonical_smiles"] == "CCO"  # from vlm_verified_esmiles
    assert cache_match["name"] == ""  # no molecules row, no mol_id fallback
    assert cache_match["confidence"] == 0.9
    assert cache_match["crop_url"] and "cache.png" in cache_match["crop_url"]


def test_by_location_applies_persistable_candidate_filter(tmp_path: Path) -> None:
    root = str(tmp_path)
    _save_index(
        tmp_path,
        "doc-1",
        [
            _candidate(),  # persistable: appears
            _candidate(
                canonical="CCC", status="rejected", bbox=(100.0, 70.0, 120.0, 90.0)
            ),  # dropped
            _candidate(
                canonical="CCN",
                bbox=(130.0, 70.0, 150.0, 90.0),
                properties={"structure_role": "fragment"},
            ),  # dropped
            _candidate(canonical="CCF", page=None),  # dropped: no page
            _candidate(canonical="CCCl", bbox=None),  # dropped: no bbox
        ],
    )

    matches = molecules_by_location(root, "doc-1", 3, QUERY)

    assert [m["mol_id"] for m in matches] == ["CCO"]
    # Pre-persist candidates have no molecules row: name falls back to mol_id.
    assert matches[0]["name"] == "CCO"
    assert matches[0]["crop_url"] and "etoh.png" in matches[0]["crop_url"]


def test_by_location_requires_containment(tmp_path: Path) -> None:
    root = str(tmp_path)
    _save_index(tmp_path, "doc-1", [_candidate()])

    # Partially overlapping query box: the stored box must CONTAIN the query
    # (same predicate as the legacy SQL path), so this misses.
    assert molecules_by_location(root, "doc-1", 3, (15.0, 35.0, 25.0, 61.0)) == []
    # Right page required: stored detection page is 0-based 2 → public 3.
    assert molecules_by_location(root, "doc-1", 2, QUERY) == []


def test_by_location_ignores_legacy_sql_evidence_without_artifacts(
    tmp_path: Path,
) -> None:
    root = str(tmp_path)
    db = DatabaseManager.get(root)
    db.initialize()
    with db.mol_conn() as conn:
        conn.execute(
            "INSERT INTO molecules (mol_id, smiles, name, canonical_smiles) "
            "VALUES ('m1', 'CCO', 'ethanol', 'CCO')"
        )
        conn.execute(
            """
            INSERT INTO evidence
                (canonical_smiles, mol_id, doc_id, page, bbox_x0, bbox_y0,
                 bbox_x1, bbox_y1, kind, confidence, crop_relpath)
            VALUES ('CCO', 'm1', 'doc-1', 3, 10, 20, 40, 60, 'figure', 0.91,
                    'crop.png')
            """
        )

    matches = molecules_by_location(root, "doc-1", 3, QUERY)

    assert matches == []
