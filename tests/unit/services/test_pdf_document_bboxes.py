"""Tests for the molecule side of the document overlay.

Molecule bboxes come from the same ``source_evidence`` index as the layout
blocks — ``kind='molecule'`` rows — so these tests seed that table directly
and assert the per-kind split of the single overlay read.
"""

from __future__ import annotations

from pathlib import Path

from mbforge.core.molecule import Molecule
from mbforge.core.types import DetectionSource
from mbforge.pipeline.extract.text import ExtractedDocument, PageContent, TextSpan
from mbforge.services.documents.pdf_layout import build_document_overlay
from mbforge.storage.sqlite.database import DatabaseManager
from tests.unit.v2_artifact_helpers import publish_v2_run

DOC = "doc-1"
CROP = "storage/doc-1/crops/page_0001_mol_0001.png"


def _insert_evidence_row(
    tmp_path: Path,
    page: int,
    box: tuple[float, float, float, float],
    *,
    kind: str = "molecule",
    coref: str = CROP,
    raw_text: str = "",
    doc_id: str = DOC,
) -> None:
    """Seed one ``source_evidence`` row (the overlay's only read source)."""
    db = DatabaseManager.get(str(tmp_path))
    db.initialize()
    with db.mol_conn() as conn:
        conn.execute(
            """
            INSERT INTO source_evidence
                (evidence_id, doc_id, page,
                 bbox_x0, bbox_y0, bbox_x1, bbox_y1,
                 raw_text, coref, kind)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                f"{doc_id}-{page}-{box[0]}-{box[1]}-{kind}",
                doc_id,
                page,
                *box,
                raw_text,
                coref,
                kind,
            ),
        )


def _overlay(tmp_path: Path, doc_id: str = DOC) -> dict:
    return build_document_overlay(str(tmp_path), doc_id, "/p.pdf")


def test_overlay_groups_molecule_pages_in_one_read(tmp_path: Path) -> None:
    _insert_evidence_row(tmp_path, 1, (10.0, 20.0, 110.0, 120.0))
    _insert_evidence_row(tmp_path, 2, (1.0, 2.0, 3.0, 4.0))

    result = _overlay(tmp_path)

    assert result["success"] is True
    assert result["source"] == "source_evidence"
    assert result["count"] == 2
    assert sorted(result["pages"].keys()) == ["1", "2"]  # 1-based visual pages
    page1 = result["pages"]["1"]
    assert page1[0]["bbox_pdf"] == [10.0, 20.0, 110.0, 120.0]
    assert page1[0]["page_idx"] == 0  # entries stay 0-based
    assert page1[0]["page"] == 0
    assert result["pages"]["2"][0]["bbox_pdf"] == [1.0, 2.0, 3.0, 4.0]


def test_overlay_molecule_entries_carry_crop_or_context(tmp_path: Path) -> None:
    _insert_evidence_row(tmp_path, 1, (10.0, 20.0, 110.0, 120.0))
    _insert_evidence_row(
        tmp_path, 1, (50.0, 60.0, 90.0, 99.0), coref="", raw_text="Compound 7"
    )

    entries = _overlay(tmp_path)["pages"]["1"]

    cropped = next(e for e in entries if e["crop_relpath"])
    assert cropped["source"] == "image"
    assert cropped["mol_img_path"] == CROP
    # Image evidence without structured metadata remains displayable.
    assert cropped["smiles"] == ""

    textual = next(e for e in entries if not e["crop_relpath"])
    assert textual["source"] == "text"
    assert textual["mol_img_path"] is None
    assert textual["context_text"] == "Compound 7"


def test_overlay_molecule_pages_exclude_layout_rows(tmp_path: Path) -> None:
    _insert_evidence_row(tmp_path, 1, (10.0, 20.0, 110.0, 120.0))
    _insert_evidence_row(
        tmp_path, 1, (1.0, 1.0, 9.0, 9.0), kind="text_span", coref="", raw_text="text"
    )
    _insert_evidence_row(
        tmp_path, 1, (2.0, 2.0, 8.0, 8.0), kind="table_span", coref="", raw_text="cell"
    )
    _insert_evidence_row(tmp_path, 1, (3.0, 3.0, 7.0, 7.0), kind="image_region")

    result = _overlay(tmp_path)

    assert result["count"] == 1
    assert len(result["pages"]["1"]) == 1
    # The same rows still feed the block side of the payload.
    assert {b["block_type"] for b in result["blocks"]} == {"text", "table", "image"}


def test_overlay_empty_document_reports_empty(tmp_path: Path) -> None:
    result = _overlay(tmp_path, "nope")

    assert result["pages"] == {}
    assert result["count"] == 0
    assert result["source"] == "empty"
    assert result["blocks"] == []


def test_overlay_serves_blocks_and_molecules_from_one_read(tmp_path: Path) -> None:
    """A joined run populates both sides of the payload."""
    extracted = ExtractedDocument(
        raw_text="text",
        page_count=1,
        pages=[
            PageContent(
                page_num=1,
                text="text",
                text_spans=[TextSpan("text", (10.0, 20.0, 30.0, 50.0))],
            )
        ],
    )
    publish_v2_run(
        tmp_path,
        DOC,
        "run-1",
        extracted,
        [
            Molecule(
                canonical_smiles="CCO",
                esmiles="CCO<sep>",
                name="EtOH",
                sources=["image"],
                detections=[
                    DetectionSource(
                        source="image",
                        page=0,
                        bbox=(100.0, 200.0, 200.0, 300.0),
                        image_path="crops/etoh.png",
                        confidence=0.81,
                        conf_moldet=0.9,
                    )
                ],
            )
        ],
        {"molecule_count": 1},
        width=200.0,
        height=300.0,
    )

    result = _overlay(tmp_path)

    assert [b["block_type"] for b in result["blocks"]] == ["text"]
    assert result["pages"]["1"][0]["bbox_pdf"] == [100.0, 200.0, 200.0, 300.0]
    assert result["source"] == "source_evidence"
