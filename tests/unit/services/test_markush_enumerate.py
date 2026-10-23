"""Unit tests for the Markush bounded enumeration service (Phase 6).

Covers ``services.use_cases.markush.enumeration`` (``run_enumeration``,
``apply_generated_decision``, ``list_run_results``) plus the counting helpers
``domain.enumeration.theoretical_count`` / ``preview``.
"""

from __future__ import annotations

import json

import pytest

from mbforge.db.sqlite.database import DatabaseManager
from mbforge.domain.enumeration import (
    SiteSelection,
    preview,
    theoretical_count,
)
from mbforge.service.ports import get_repositories
from mbforge.service.use_cases.markush.enumeration import (
    apply_generated_decision,
    list_run_results,
    run_enumeration,
)


@pytest.fixture
def database(tmp_path):
    db = DatabaseManager.get(str(tmp_path))
    db.initialize()
    return db


@pytest.fixture
def repo(tmp_path):
    return get_repositories(str(tmp_path)).markush


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


def test_theoretical_count_and_preview_truncation(database) -> None:
    """The theoretical count is the fragment cross-product, and preview flags
    truncation against the requested limit."""
    assert (
        theoretical_count(
            [
                SiteSelection(site_label="R1", atom_map_num=1, fragments=["F", "Cl"]),
                SiteSelection(
                    site_label="R2", atom_map_num=2, fragments=["A", "B", "C"]
                ),
            ]
        )
        == 6
    )

    cases = [
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
    ]
    for selections, requested_limit, expected_count, truncated in cases:
        info = preview(selections, requested_limit=requested_limit)
        assert info["theoretical_count"] == expected_count, f"{selections!r}"
        assert info["truncated"] is truncated, f"{selections!r}"


def test_run_enumeration_resolves_fragments_deterministically_and_handles_empty(
    database, repo
) -> None:
    """A run resolves seeded fragment ids, repeats byte-identical canonical
    sets for the same selection, and reports an empty selection as ``empty``."""
    _seed_confirmed_relations(
        database,
        scaffold_id="sc-1",
        scaffold_smiles="[*:1]C1CCCCC1",
        sites={1: [("f-1", "F"), ("f-2", "Cl"), ("f-3", "Br")]},
    )

    single = run_enumeration(
        repo,
        scaffold_id="sc-1",
        selection=[SiteSelection("R1", 1, ["f-1"])],
        requested_limit=10,
    )
    single_items = list_run_results(repo, single.run_id)
    assert single.status == "completed"
    assert single_items
    assert single_items[0]["assignments"][0]["fragment_id"] == "f-1"

    selections = [
        SiteSelection(site_label="R1", atom_map_num=1, fragments=["f-1", "f-2", "f-3"]),
    ]
    first = run_enumeration(
        repo,
        scaffold_id="sc-1",
        selection=selections,
        requested_limit=50,
    )
    second = run_enumeration(
        repo,
        scaffold_id="sc-1",
        selection=selections,
        requested_limit=50,
    )
    first_canon = sorted(
        item["canonical_smiles"] for item in list_run_results(repo, first.run_id)
    )
    second_canon = sorted(
        item["canonical_smiles"] for item in list_run_results(repo, second.run_id)
    )
    assert first_canon == second_canon
    assert len(first_canon) == 3  # F, Cl, Br all canonicalize

    empty = run_enumeration(
        repo,
        scaffold_id="sc-1",
        selection=[SiteSelection(site_label="R1", atom_map_num=1, fragments=[])],
        requested_limit=10,
    )
    assert empty.status == "empty"
    assert empty.written_count == 0


def test_run_enumeration_rejects_when_theoretical_exceeds_limit(database, repo) -> None:
    """An over-limit cross-product is rejected up front and writes no rows."""
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
    result = run_enumeration(
        repo,
        scaffold_id="sc-1",
        selection=selections,
        requested_limit=5,
    )
    assert result.status == "rejected"
    assert result.theoretical_count == 27
    assert result.written_count == 0


def test_generated_decision_mints_on_confirm_and_writes_nothing_on_reject(
    database, repo
) -> None:
    """Confirming a generated row mints a molecule carrying generation
    provenance; rejecting one leaves no molecule behind."""
    _seed_confirmed_relations(database)
    selection = [SiteSelection("R1", 1, ["frag-1"])]

    run = run_enumeration(
        repo,
        scaffold_id="sc-1",
        selection=selection,
        requested_limit=10,
    )
    generated_id = list_run_results(repo, run.run_id)[0]["generated_id"]
    decision = apply_generated_decision(
        repo,
        entity_id=generated_id,
        action="confirm",
        reason="verified",
    )
    with database.mol_conn() as conn:
        mol = conn.execute(
            "SELECT properties, review_status, source_doc FROM molecules "
            "WHERE mol_id = ?",
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

    rejected_run = run_enumeration(
        repo,
        scaffold_id="sc-1",
        selection=selection,
        requested_limit=10,
    )
    rejected_id = list_run_results(repo, rejected_run.run_id)[0]["generated_id"]
    rejected = apply_generated_decision(
        repo,
        entity_id=rejected_id,
        action="reject",
        reason="not useful",
    )
    with database.mol_conn() as conn:
        rejected_mol = conn.execute(
            "SELECT mol_id FROM molecules WHERE mol_id = ?", (rejected_id,)
        ).fetchone()
    assert rejected["review_status"] == "rejected"
    assert rejected_mol is None
