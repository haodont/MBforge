"""Unit tests for the Markush attachment-site service (Phase 4).

Covers ``services.use_cases.markush.sites`` (``create_site`` / ``update_site`` /
``create_option`` / ``create_mount`` / ``decide_mount`` and their listings):
validation gates, idempotency, listing order and the decision audit trail.
"""

from __future__ import annotations

import json

import pytest

from mbforge.db.sqlite.database import DatabaseManager
from mbforge.domain.markush import MarkushSiteError
from mbforge.service.ports import get_repositories
from mbforge.service.use_cases.markush.sites import (
    create_mount,
    create_option,
    create_site,
    decide_mount,
    list_mounts,
    list_options,
    list_sites,
    update_site,
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
    database, *, scaffold_id: str = "sc-1", smiles: str = "*c1ccc(*)cc1"
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


def test_create_site_validates_scaffold_state_and_attachment_points(
    database, repo
) -> None:
    """An explicit in-range atom map is required, and only a confirmed
    scaffold may carry sites."""
    _seed_scaffold(database)
    _seed_scaffold_pending(database)

    with pytest.raises(MarkushSiteError, match="atom_map_num is required"):
        create_site(repo, scaffold_id="sc-1", site_label="R1", atom_map_num=None)
    with pytest.raises(MarkushSiteError, match="out of range"):
        # scaffold has 2 attachment points; atom_map_num=5 is invalid.
        create_site(
            repo,
            scaffold_id="sc-1",
            site_label="R1",
            atom_map_num=5,
            attachment_count=1,
        )
    with pytest.raises(MarkushSiteError, match="scaffold is not confirmed"):
        create_site(repo, scaffold_id="sc-p", site_label="R1", atom_map_num=1)


def test_sites_list_in_order_mounts_filter_by_scaffold_and_update_applies(
    database, repo
) -> None:
    """Sites keep their creation order, mounts are scoped to their scaffold,
    and ``update_site`` persists the new attachment count."""
    _seed_scaffold(database, scaffold_id="sc-1")
    _seed_scaffold(database, scaffold_id="sc-2")
    _seed_fragment(database)

    s1 = create_site(repo, scaffold_id="sc-1", site_label="R1", atom_map_num=1)
    create_site(repo, scaffold_id="sc-1", site_label="R2", atom_map_num=2)
    sites = list_sites(repo, "sc-1")
    assert [s.site_label for s in sites] == ["R1", "R2"]
    assert [s.atom_map_num for s in sites] == [1, 2]

    other = create_site(repo, scaffold_id="sc-2", site_label="R2", atom_map_num=1)
    create_mount(repo, site_id=s1.site_id, fragment_id="fr-1")
    create_mount(repo, site_id=other.site_id, fragment_id="fr-1")
    mounts = list_mounts(repo, scaffold_id="sc-1")
    assert len(mounts) == 1
    assert mounts[0].site_id == s1.site_id

    updated = update_site(repo, site_id=s1.site_id, attachment_count=2)
    assert updated.attachment_count == 2


def test_create_option_requires_definition_or_confirmed_fragment(
    database, repo
) -> None:
    """An option needs a fragment or free-text definition, and a presented
    fragment must already be confirmed."""
    _seed_scaffold(database)
    _seed_fragment_pending(database)
    site = create_site(repo, scaffold_id="sc-1", site_label="R1", atom_map_num=1)

    with pytest.raises(MarkushSiteError, match="requires"):
        create_option(repo, site_id=site.site_id)
    with pytest.raises(MarkushSiteError, match="fragment is not confirmed"):
        create_option(repo, site_id=site.site_id, fragment_id="fr-p")

    option = create_option(repo, site_id=site.site_id, definition_text="C1-6 alkyl")
    options = list_options(repo, site.site_id)
    assert option.definition_text == "C1-6 alkyl"
    assert len(options) == 1


def test_create_mount_checks_attachment_count_confirmation_and_idempotency(
    database, repo
) -> None:
    """Mounts are idempotent per (site, fragment), reject unconfirmed
    fragments and refuse a fragment whose attachment count mismatches."""
    _seed_scaffold(database)
    _seed_fragment(database, smiles="*C")  # 1 attachment point
    _seed_fragment_pending(database)
    site = create_site(repo, scaffold_id="sc-1", site_label="R1", atom_map_num=1)

    first = create_mount(repo, site_id=site.site_id, fragment_id="fr-1")
    second = create_mount(repo, site_id=site.site_id, fragment_id="fr-1")
    assert first.mount_id == second.mount_id

    with pytest.raises(MarkushSiteError, match="fragment is not confirmed"):
        create_mount(repo, site_id=site.site_id, fragment_id="fr-p")

    two_point_site = create_site(
        repo,
        scaffold_id="sc-1",
        site_label="R2",
        atom_map_num=2,
        attachment_count=2,  # site expects 2
    )
    with pytest.raises(MarkushSiteError, match="attachment mismatch"):
        create_mount(repo, site_id=two_point_site.site_id, fragment_id="fr-1")


def test_decide_mount_records_audit_and_rejects_repeat(database, repo) -> None:
    """A confirmed mount is audited exactly once; re-confirming it is refused."""
    _seed_scaffold(database)
    _seed_fragment(database)
    site = create_site(repo, scaffold_id="sc-1", site_label="R1", atom_map_num=1)
    mount = create_mount(repo, site_id=site.site_id, fragment_id="fr-1")

    decided = decide_mount(repo, mount_id=mount.mount_id, action="confirm", reason="ok")
    with database.mol_conn() as conn:
        audit = conn.execute(
            "SELECT action, new_state, snapshot FROM markush_decisions "
            "WHERE entity_id = ?",
            (mount.mount_id,),
        ).fetchone()
    assert decided.status == "confirmed"
    assert audit["action"] == "mount_confirm"
    assert audit["new_state"] == "confirmed"
    assert json.loads(audit["snapshot"])["site_id"] == site.site_id

    with pytest.raises(MarkushSiteError, match="mount is already"):
        decide_mount(repo, mount_id=mount.mount_id, action="confirm", reason="again")
    with database.mol_conn() as conn:
        decisions = conn.execute(
            "SELECT COUNT(*) FROM markush_decisions WHERE entity_id = ?",
            (mount.mount_id,),
        ).fetchone()[0]
    assert decisions == 1
