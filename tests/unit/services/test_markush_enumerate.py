"""Unit tests for the Markush bounded enumeration service (Phase 6)."""

from __future__ import annotations

import json

import pytest

from mbforge.core.enumeration import (
    SiteSelection,
    preview,
    theoretical_count,
)
from mbforge.services.markush.enumeration import (
    apply_generated_decision,
    list_run_results,
    run_enumeration,
)
from mbforge.storage.sqlite.database import DatabaseManager


@pytest.fixture
def database(tmp_path):
    db = DatabaseManager.get(str(tmp_path))
    db.initialize()
    return db


def _seed_scaffold(
    database, *, scaffold_id: str = "sc-1", smiles: str = "[*:1]C1CCCCC1"
):
    with database.mol_conn() as conn:
        conn.execute(
            """
            INSERT INTO markush_scaffolds
                (scaffold_id, doc_id, smiles, status)
            VALUES (?, 'doc-1', ?, 'confirmed')
            """,
            (scaffold_id, smiles),
        )
        conn.commit()


def _seed_confirmed_relations(
    database,
    *,
    scaffold_id: str = "sc-1",
    scaffold_smiles: str = "[*:1]C1CCCCC1",
    sites: dict[int, list[tuple[str, str]]] | None = None,
):
    """Seed a confirmed scaffold, one confirmed site per atom-map number, and
    a confirmed fragment + option for every entry.

    ``sites`` maps ``atom_map_num -> [(fragment_id, smiles), ...]``.
    """
    _seed_scaffold(database, scaffold_id=scaffold_id, smiles=scaffold_smiles)
    sites = sites or {1: [("frag-1", "F")]}
    with database.mol_conn() as conn:
        for map_num, fragments in sites.items():
            site_id = f"site-{map_num}"
            conn.execute(
                """
                INSERT INTO markush_sites
                    (site_id, scaffold_id, site_label, atom_map_num, status)
                VALUES (?, ?, ?, ?, 'confirmed')
                """,
                (site_id, scaffold_id, f"R{map_num}", map_num),
            )
            for i, (fragment_id, smiles) in enumerate(fragments):
                conn.execute(
                    """
                    INSERT INTO markush_fragments
                        (fragment_id, doc_id, label, smiles, status)
                    VALUES (?, 'doc-1', ?, ?, 'confirmed')
                    """,
                    (fragment_id, fragment_id, smiles),
                )
                conn.execute(
                    """
                    INSERT INTO markush_options
                        (option_id, site_id, fragment_id, status)
                    VALUES (?, ?, ?, 'confirmed')
                    """,
                    (f"opt-{map_num}-{i}", site_id, fragment_id),
                )
        conn.commit()


def test_run_resolves_fragment_id_from_database(database):
    _seed_confirmed_relations(database)
    with database.mol_conn() as conn:
        result = run_enumeration(
            conn,
            scaffold_id="sc-1",
            selection=[SiteSelection("R1", 1, ["frag-1"])],
            requested_limit=10,
        )
        items = list_run_results(conn, result.run_id)
    assert result.status == "completed"
    assert items
    assert items[0]["assignments"][0]["fragment_id"] == "frag-1"


def test_theoretical_count_is_cross_product(database):
    selections = [
        SiteSelection(site_label="R1", atom_map_num=1, fragments=["F", "Cl"]),
        SiteSelection(site_label="R2", atom_map_num=2, fragments=["A", "B", "C"]),
    ]
    assert theoretical_count(selections) == 6


@pytest.mark.parametrize(
    "selections,requested_limit,expected_count,truncated",
    [
        (
            [
                SiteSelection(site_label="R1", atom_map_num=1, fragments=["A", "B"]),
                SiteSelection(site_label="R2", atom_map_num=2, fragments=["A", "B"]),
            ],
            3,
            4,
            True,
        ),
        (
            [SiteSelection(site_label="R1", atom_map_num=1, fragments=["A", "B"])],
            10,
            2,
            False,
        ),
    ],
)
def test_preview_reports_truncation(
    selections, requested_limit, expected_count, truncated
):
    info = preview(selections, requested_limit=requested_limit)
    assert info["theoretical_count"] == expected_count
    assert info["truncated"] is truncated


def test_run_rejects_when_theoretical_exceeds_limit(database):
    _seed_confirmed_relations(
        database,
        scaffold_id="sc-1",
        scaffold_smiles="[*:1]C1CC([*:2])C([*:3])CC1",
        sites={
            1: [("f-1", "F"), ("f-2", "Cl"), ("f-3", "Br")],
            2: [("f-4", "F"), ("f-5", "Cl"), ("f-6", "Br")],
            3: [("f-7", "F"), ("f-8", "Cl"), ("f-9", "Br")],
        },
    )
    selections = [
        SiteSelection(site_label="R1", atom_map_num=1, fragments=["f-1", "f-2", "f-3"]),
        SiteSelection(site_label="R2", atom_map_num=2, fragments=["f-4", "f-5", "f-6"]),
        SiteSelection(site_label="R3", atom_map_num=3, fragments=["f-7", "f-8", "f-9"]),
    ]
    with database.mol_conn() as conn:
        result = run_enumeration(
            conn,
            scaffold_id="sc-1",
            selection=selections,
            requested_limit=5,
        )
    assert result.status == "rejected"
    assert result.theoretical_count == 27
    assert result.written_count == 0


def test_run_writes_deterministic_canonical_smiles(database):
    """Two runs against the same selection produce identical canonical sets."""
    _seed_confirmed_relations(
        database,
        scaffold_id="sc-1",
        scaffold_smiles="[*:1]C1CCCCC1",
        sites={1: [("f-1", "F"), ("f-2", "Cl"), ("f-3", "Br")]},
    )
    selections = [
        SiteSelection(site_label="R1", atom_map_num=1, fragments=["f-1", "f-2", "f-3"]),
    ]
    with database.mol_conn() as conn:
        first = run_enumeration(
            conn,
            scaffold_id="sc-1",
            selection=selections,
            requested_limit=50,
        )
        second = run_enumeration(
            conn,
            scaffold_id="sc-1",
            selection=selections,
            requested_limit=50,
        )
        first_items = list_run_results(conn, first.run_id)
        second_items = list_run_results(conn, second.run_id)
    first_canon = sorted(item["canonical_smiles"] for item in first_items)
    second_canon = sorted(item["canonical_smiles"] for item in second_items)
    assert first_canon == second_canon
    assert len(first_canon) == 3  # F, Cl, Br all canonicalize


def test_run_empty_selection_writes_zero_rows(database):
    _seed_confirmed_relations(
        database,
        scaffold_id="sc-1",
        scaffold_smiles="[*:1]C1CCCCC1",
        sites={1: [("frag-1", "F")]},
    )
    selections = [
        SiteSelection(site_label="R1", atom_map_num=1, fragments=[]),
    ]
    with database.mol_conn() as conn:
        result = run_enumeration(
            conn,
            scaffold_id="sc-1",
            selection=selections,
            requested_limit=10,
        )
    assert result.status == "empty"
    assert result.written_count == 0


def test_generated_confirm_writes_molecule_with_provenance(database):
    _seed_confirmed_relations(database)
    with database.mol_conn() as conn:
        result = run_enumeration(
            conn,
            scaffold_id="sc-1",
            selection=[SiteSelection("R1", 1, ["frag-1"])],
            requested_limit=10,
        )
        generated_id = list_run_results(conn, result.run_id)[0]["generated_id"]
        decision = apply_generated_decision(
            conn,
            entity_id=generated_id,
            action="confirm",
            reason="verified",
        )
        mol = conn.execute(
            "SELECT properties, review_status, source_doc FROM molecules WHERE mol_id = ?",
            (generated_id,),
        ).fetchone()
    assert decision["review_status"] == "confirmed"
    assert mol is not None
    assert mol["source_doc"] == "markush_generation"
    assert mol["review_status"] == "confirmed"
    provenance = json.loads(mol["properties"])["markush_generation"]
    assert provenance["generated_id"] == generated_id
    assert provenance["scaffold_id"] == "sc-1"
    assert provenance["combination_key"]
    assert provenance["assignments"][0]["fragment_id"] == "frag-1"


def test_generated_reject_writes_no_molecule(database):
    _seed_confirmed_relations(database)
    with database.mol_conn() as conn:
        result = run_enumeration(
            conn,
            scaffold_id="sc-1",
            selection=[SiteSelection("R1", 1, ["frag-1"])],
            requested_limit=10,
        )
        generated_id = list_run_results(conn, result.run_id)[0]["generated_id"]
        decision = apply_generated_decision(
            conn,
            entity_id=generated_id,
            action="reject",
            reason="not useful",
        )
        mol = conn.execute(
            "SELECT mol_id FROM molecules WHERE mol_id = ?", (generated_id,)
        ).fetchone()
    assert decision["review_status"] == "rejected"
    assert mol is None
