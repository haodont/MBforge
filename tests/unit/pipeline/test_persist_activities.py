"""Unit tests for ``mbforge.application.pipeline.persist.activities``.

Since ``125a63d6`` the persist path writes the ``activities.json``
artifact instead of SQLite rows, so the per-row persistence contract
(matched rows, idempotent re-ingest, deterministic activity_id, stale
review-item cleanup) is no longer exercised here — those tests were
removed as stale contracts (see TODO/src-naming-migration.md) and await
equivalents against the finalized artifact contract. What remains locks
the no-op/skip edges and the schema:

1. Schema bootstrap creates the ``activities`` table on greenfield.
2. Records that fail to match any candidate are skipped (no orphans).
3. Records with no candidates at all are a no-op.
4. Records with all-null position fields are skipped.
"""

from __future__ import annotations

import sqlite3
from pathlib import Path
from unittest.mock import MagicMock

from mbforge.adapters.persistence.sqlite.database import DatabaseManager
from mbforge.application.pipeline.activity.extraction import ActivityRecord
from mbforge.application.pipeline.persist.activities import (
    persist_activities,
)


def _candidate(
    canonical_smiles: str = "CCO",
    name: str = "",
    esmiles: str | None = None,
) -> MagicMock:
    cand = MagicMock()
    cand.status = "pending"
    cand.canonical_smiles = canonical_smiles
    cand.esmiles = esmiles or canonical_smiles
    cand.name = name
    return cand


def _activity(
    *,
    target: str = "STAT6",
    assay: str = "hSTAT6 TR-FRET",
    value: float = 4.0,
    page_num: int = 1,
    table_idx: int = 0,
    row_idx: int = 1,
    col_idx: int | None = 1,
    row_label: str | None = None,
    row_smiles: str | None = None,
    confidence: float = 0.9,
) -> ActivityRecord:
    return ActivityRecord(
        activity_type="IC50",
        value=value,
        value_original=value,
        unit="nM",
        operator="=",
        target=target,
        assay_type=assay,
        raw_text=f"IC50 {target} = {value} nM",
        confidence=confidence,
        page_num=page_num,
        evidence_kind="table",
        evidence_bbox=None,
        table_idx=table_idx,
        row_idx=row_idx,
        col_idx=col_idx,
        row_label=row_label,
        row_smiles=row_smiles,
    )


def _init_db(tmp_library: Path) -> DatabaseManager:
    db = DatabaseManager.get(str(tmp_library))
    db.initialize()
    return db


def _seed_molecule(
    db: DatabaseManager,
    doc_id: str = "doc-1",
    mol_id: str = "CCO",
    name: str = "cmpd-1",
) -> None:
    """Insert a minimal molecules row so the FK from activities is satisfied."""
    with db.mol_conn() as conn:
        conn.execute(
            """
            INSERT INTO molecules (mol_id, smiles, esmiles, name, source_doc,
                                    source_type, status, canonical_smiles)
            VALUES (?, ?, ?, ?, ?, 'image', 'pending', ?)
            """,
            (mol_id, mol_id, mol_id, name, doc_id, mol_id),
        )


def _fetch_activities(db: DatabaseManager) -> list[sqlite3.Row]:
    with db.mol_conn() as conn:
        return conn.execute(
            "SELECT * FROM activities ORDER BY page_num, table_idx, row_idx, col_idx"
        ).fetchall()


def test_activities_table_created_on_greenfield(tmp_library: Path) -> None:
    """Greenfield initialization creates the activities table."""
    db = _init_db(tmp_library)

    with db.mol_conn() as conn:
        tables = {
            r[0]
            for r in conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table' AND name='activities'"
            )
        }
        assert "activities" in tables
        cols = {row[1] for row in conn.execute("PRAGMA table_info(activities)")}
        for required in (
            "activity_id",
            "mol_id",
            "doc_id",
            "activity_type",
            "value",
            "target",
            "assay_description",
            "row_label",
            "table_idx",
            "row_idx",
        ):
            assert required in cols, f"missing column: {required}"


def test_persist_activities_skips_unmatched_records(tmp_library: Path) -> None:
    """Records that match no candidate are not inserted (no orphan activities)."""
    db = _init_db(tmp_library)
    _seed_molecule(db, doc_id="doc-1", mol_id="CCO", name="cmpd-1")

    cand = _candidate(canonical_smiles="CCO", name="cmpd-1")
    # Rec has row_label 'cmpd-99' which doesn't match anything.
    rec = _activity(row_label="cmpd-99")

    written = persist_activities(str(tmp_library), "doc-1", [rec], candidates=[cand])
    assert written == 0
    assert _fetch_activities(db) == []


def test_persist_activities_no_candidates_is_noop(tmp_library: Path) -> None:
    """When no candidates are passed, persist is a no-op even with records."""
    db = _init_db(tmp_library)
    rec = _activity()

    written = persist_activities(str(tmp_library), "doc-1", [rec], candidates=None)
    assert written == 0
    assert _fetch_activities(db) == []


def test_records_with_all_null_position_fields_are_skipped(
    tmp_library: Path,
) -> None:
    """Orphan records (no page/table/row coords) are not written.

    Locks the contract that a record with no positional anchors is treated
    as an orphan and skipped — never written with NULL coordinates that
    would later confuse SAR queries that filter by page or table_idx.
    """
    db = _init_db(tmp_library)
    _seed_molecule(db, doc_id="doc-1", mol_id="CCO", name="cmpd-1")

    cand = _candidate(canonical_smiles="CCO", name="cmpd-1")
    rec = ActivityRecord(
        activity_type="IC50",
        value=4.0,
        value_original=4.0,
        unit="nM",
        operator="=",
        target="STAT6",
        assay_type="hSTAT6 TR-FRET",
        raw_text="orphan",
        confidence=0.5,
        page_num=None,
        evidence_kind="text",
        evidence_bbox=None,
        table_idx=None,
        row_idx=None,
        col_idx=None,
        row_label=None,
        row_smiles=None,
    )

    written = persist_activities(str(tmp_library), "doc-1", [rec], candidates=[cand])
    assert written == 0
    assert _fetch_activities(db) == []
