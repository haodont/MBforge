"""Unit tests for the Markush attachment-site service (Phase 4)."""

from __future__ import annotations

import json

import pytest

from mbforge.core.markush import MarkushSiteError
from mbforge.services.markush.sites import (
    create_mount,
    create_option,
    create_site,
    decide_mount,
    list_mounts,
    list_options,
    list_sites,
    update_site,
)
from mbforge.storage.sqlite.database import DatabaseManager


@pytest.fixture
def database(tmp_path):
    db = DatabaseManager.get(str(tmp_path))
    db.initialize()
    return db


def _seed_scaffold(
    database, *, scaffold_id: str = "sc-1", smiles: str = "*c1ccc(*)cc1"
):
    database.mol_conn()
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


def _seed_fragment(database, *, fragment_id: str = "fr-1", smiles: str = "*C"):
    with database.mol_conn() as conn:
        conn.execute(
            """
            INSERT INTO markush_fragments
                (fragment_id, doc_id, smiles, status)
            VALUES (?, 'doc-1', ?, 'confirmed')
            """,
            (fragment_id, smiles),
        )
        conn.commit()


def _seed_scaffold_pending(
    database, *, scaffold_id: str = "sc-p", smiles: str = "*c1ccc(*)cc1"
):
    with database.mol_conn() as conn:
        conn.execute(
            """
            INSERT INTO markush_scaffolds
                (scaffold_id, doc_id, smiles, status)
            VALUES (?, 'doc-1', ?, 'pending')
            """,
            (scaffold_id, smiles),
        )
        conn.commit()


def _seed_fragment_pending(database, *, fragment_id: str = "fr-p", smiles: str = "*C"):
    with database.mol_conn() as conn:
        conn.execute(
            """
            INSERT INTO markush_fragments
                (fragment_id, doc_id, smiles, status)
            VALUES (?, 'doc-1', ?, 'pending')
            """,
            (fragment_id, smiles),
        )
        conn.commit()


def test_create_site_requires_explicit_atom_map(database) -> None:
    _seed_scaffold(database)
    with (
        database.mol_conn() as conn,
        pytest.raises(MarkushSiteError, match="atom_map_num is required"),
    ):
        create_site(conn, scaffold_id="sc-1", site_label="R1", atom_map_num=None)


def test_create_site_rejects_out_of_range_atom_map(database) -> None:
    _seed_scaffold(database)
    with (
        database.mol_conn() as conn,
        pytest.raises(MarkushSiteError, match="out of range"),
    ):
        # scaffold has 2 attachment points; atom_map_num=5 is invalid.
        create_site(
            conn,
            scaffold_id="sc-1",
            site_label="R1",
            atom_map_num=5,
            attachment_count=1,
        )


def test_create_and_list_sites(database) -> None:
    _seed_scaffold(database)
    with database.mol_conn() as conn:
        create_site(
            conn,
            scaffold_id="sc-1",
            site_label="R1",
            atom_map_num=1,
        )
        create_site(
            conn,
            scaffold_id="sc-1",
            site_label="R2",
            atom_map_num=2,
        )
        sites = list_sites(conn, "sc-1")
    assert [s.site_label for s in sites] == ["R1", "R2"]
    assert [s.atom_map_num for s in sites] == [1, 2]


def test_update_site_changes_attachment_count(database) -> None:
    _seed_scaffold(database)
    with database.mol_conn() as conn:
        site = create_site(
            conn,
            scaffold_id="sc-1",
            site_label="R1",
            atom_map_num=1,
        )
        updated = update_site(conn, site_id=site.site_id, attachment_count=2)
    assert updated.attachment_count == 2


def test_create_option_requires_fragment_or_definition(database) -> None:
    _seed_scaffold(database)
    with database.mol_conn() as conn:
        site = create_site(
            conn,
            scaffold_id="sc-1",
            site_label="R1",
            atom_map_num=1,
        )
        with pytest.raises(MarkushSiteError, match="requires"):
            create_option(conn, site_id=site.site_id)


def test_create_option_with_definition(database) -> None:
    _seed_scaffold(database)
    with database.mol_conn() as conn:
        site = create_site(
            conn,
            scaffold_id="sc-1",
            site_label="R1",
            atom_map_num=1,
        )
        option = create_option(
            conn,
            site_id=site.site_id,
            definition_text="C1-6 alkyl",
        )
        options = list_options(conn, site.site_id)
    assert option.definition_text == "C1-6 alkyl"
    assert len(options) == 1


def test_create_mount_rejects_attachment_count_mismatch(database) -> None:
    _seed_scaffold(database)
    _seed_fragment(database, smiles="*C")  # 1 attachment point
    with database.mol_conn() as conn:
        site = create_site(
            conn,
            scaffold_id="sc-1",
            site_label="R1",
            atom_map_num=1,
            attachment_count=2,  # site expects 2
        )
        with pytest.raises(MarkushSiteError, match="attachment mismatch"):
            create_mount(conn, site_id=site.site_id, fragment_id="fr-1")


def test_create_mount_is_idempotent(database) -> None:
    _seed_scaffold(database)
    _seed_fragment(database)
    with database.mol_conn() as conn:
        site = create_site(
            conn,
            scaffold_id="sc-1",
            site_label="R1",
            atom_map_num=1,
        )
        first = create_mount(conn, site_id=site.site_id, fragment_id="fr-1")
        second = create_mount(conn, site_id=site.site_id, fragment_id="fr-1")
    assert first.mount_id == second.mount_id


def test_decide_mount_records_audit_row(database) -> None:
    _seed_scaffold(database)
    _seed_fragment(database)
    with database.mol_conn() as conn:
        site = create_site(
            conn,
            scaffold_id="sc-1",
            site_label="R1",
            atom_map_num=1,
        )
        mount = create_mount(conn, site_id=site.site_id, fragment_id="fr-1")
        decided = decide_mount(
            conn, mount_id=mount.mount_id, action="confirm", reason="ok"
        )
        audit = conn.execute(
            "SELECT action, new_state, snapshot FROM markush_decisions "
            "WHERE entity_id = ?",
            (mount.mount_id,),
        ).fetchone()
    assert decided.status == "confirmed"
    assert audit["action"] == "mount_confirm"
    assert audit["new_state"] == "confirmed"
    assert json.loads(audit["snapshot"])["site_id"] == site.site_id


def test_list_mounts_filters_by_scaffold(database) -> None:
    _seed_scaffold(database, scaffold_id="sc-1")
    _seed_scaffold(database, scaffold_id="sc-2")
    _seed_fragment(database)
    with database.mol_conn() as conn:
        s1 = create_site(
            conn,
            scaffold_id="sc-1",
            site_label="R1",
            atom_map_num=1,
        )
        s2 = create_site(
            conn,
            scaffold_id="sc-2",
            site_label="R2",
            atom_map_num=1,
        )
        create_mount(conn, site_id=s1.site_id, fragment_id="fr-1")
        create_mount(conn, site_id=s2.site_id, fragment_id="fr-1")
        mounts = list_mounts(conn, scaffold_id="sc-1")
    assert len(mounts) == 1
    assert mounts[0].site_id == s1.site_id


def test_create_site_requires_confirmed_scaffold(database) -> None:
    _seed_scaffold_pending(database)
    with (
        database.mol_conn() as conn,
        pytest.raises(MarkushSiteError, match="scaffold is not confirmed"),
    ):
        create_site(
            conn,
            scaffold_id="sc-p",
            site_label="R1",
            atom_map_num=1,
        )


def test_create_option_rejects_unconfirmed_fragment(database) -> None:
    _seed_scaffold(database)
    _seed_fragment_pending(database)
    with database.mol_conn() as conn:
        site = create_site(
            conn,
            scaffold_id="sc-1",
            site_label="R1",
            atom_map_num=1,
        )
        with pytest.raises(MarkushSiteError, match="fragment is not confirmed"):
            create_option(conn, site_id=site.site_id, fragment_id="fr-p")


def test_create_mount_requires_confirmed_site_and_fragment(database) -> None:
    _seed_scaffold(database)
    _seed_fragment_pending(database)
    with database.mol_conn() as conn:
        site = create_site(
            conn,
            scaffold_id="sc-1",
            site_label="R1",
            atom_map_num=1,
        )
        with pytest.raises(MarkushSiteError, match="fragment is not confirmed"):
            create_mount(conn, site_id=site.site_id, fragment_id="fr-p")


def test_decide_mount_rejects_repeated_confirmed(database) -> None:
    _seed_scaffold(database)
    _seed_fragment(database)
    with database.mol_conn() as conn:
        site = create_site(
            conn,
            scaffold_id="sc-1",
            site_label="R1",
            atom_map_num=1,
        )
        mount = create_mount(conn, site_id=site.site_id, fragment_id="fr-1")
        decided = decide_mount(
            conn, mount_id=mount.mount_id, action="confirm", reason="ok"
        )
        assert decided.status == "confirmed"
        with pytest.raises(MarkushSiteError, match="mount is already"):
            decide_mount(
                conn, mount_id=mount.mount_id, action="confirm", reason="again"
            )
        audit = conn.execute(
            "SELECT COUNT(*) FROM markush_decisions WHERE entity_id = ?",
            (mount.mount_id,),
        ).fetchone()[0]
    assert audit == 1
