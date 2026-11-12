"""AI review proposals: propose, revise while pending, frozen after a decision.

Functions under test: ``propose_items`` / ``apply_proposal_payload`` through
``review_queue.decide``.

The rule the product asked for: the assistant may file a correction at any time
into the review center; it may revise its own *pending* proposal; once a human
confirms or rejects it, the target is frozen against further AI changes. A
proposal never writes a value by itself — the human decision does.
"""

from __future__ import annotations

from pathlib import Path

from mbforge.contracts.review_proposal import AI_REVIEW_KIND, ReviewProposal
from mbforge.db.source_evidence import persist_source_evidence
from mbforge.db.sqlite.database import DatabaseManager
from mbforge.domain.evidence import SourceEvidence
from mbforge.service.ports import get_repositories
from mbforge.service.use_cases import review_proposals
from mbforge.service.use_cases.review_queue import decide_items

DOC = "doc1"


class _Decision:
    """Request-shaped decision row (what ``decide_items`` consumes)."""

    def __init__(self, item_id: str) -> None:
        self.kind = AI_REVIEW_KIND
        self.id = item_id
        self.choice = None
        self.expected_revision = None


def _seed_molecule(root: Path, name: str = "6") -> None:
    db = DatabaseManager.get(str(root))
    db.initialize()
    with db.connection() as conn:
        conn.execute(
            "INSERT INTO molecules (mol_id, smiles, canonical_smiles, name, source_doc) "
            "VALUES (?, ?, ?, ?, ?)",
            ("mol-1", "CCO", "CCO", name, DOC),
        )
        conn.commit()


def _item(root: Path, item_id: str) -> dict:
    return get_repositories(str(root)).review.get_item(AI_REVIEW_KIND, item_id)


def _propose(root: Path, after: str) -> ReviewProposal:
    return ReviewProposal(
        doc_id=DOC,
        target_kind="molecule",
        target_id="mol-1",
        field="name",
        before="6",
        after=after,
        rationale="the printed designation beside the drawing reads 7",
        evidence_ids=["ev-label"],
    )


def test_a_proposal_enters_the_queue_pending_and_revises_in_place(
    tmp_path: Path,
) -> None:
    _seed_molecule(tmp_path)

    [created] = review_proposals.propose_items(str(tmp_path), [_propose(tmp_path, "7")])

    assert created.action == "created"
    assert created.status == "pending"
    item = _item(tmp_path, created.item_id)
    assert item["kind"] == AI_REVIEW_KIND and item["status"] == "pending"
    assert item["payload"]["proposal"]["after"] == "7"
    # The store value is recorded beside the model claim: a hallucinated
    # "before" becomes visible instead of trusted.
    assert item["payload"]["before_actual"] == "6"

    [revised] = review_proposals.propose_items(str(tmp_path), [_propose(tmp_path, "8")])

    assert revised.action == "updated" and revised.item_id == created.item_id
    payload = _item(tmp_path, created.item_id)["payload"]
    assert payload["proposal"]["after"] == "8"
    assert payload["revision"] == 2
    assert len(payload["history"]) == 1


def test_a_human_decision_applies_once_and_then_freezes_the_target(
    tmp_path: Path, patch_config_root
) -> None:
    patch_config_root(tmp_path)  # decide_items resolves the configured library
    _seed_molecule(tmp_path)
    [created] = review_proposals.propose_items(str(tmp_path), [_propose(tmp_path, "7")])

    decided = decide_items(str(tmp_path), "confirm", "", [_Decision(created.item_id)])

    assert decided.updated == 1
    assert decided.results[0]["applied"] is True
    stored = get_repositories(str(tmp_path)).molecules.identity_fields(["mol-1"])
    assert stored["mol-1"]["name"] == "7"

    [refused] = review_proposals.propose_items(str(tmp_path), [_propose(tmp_path, "9")])

    assert refused.action == "refused"
    assert "human already decided" in refused.error
    payload = _item(tmp_path, created.item_id)["payload"]
    assert payload["proposal"]["after"] == "7"  # the frozen proposal is untouched


def test_an_evidence_target_is_recorded_and_never_rewritten(
    tmp_path: Path, patch_config_root
) -> None:
    patch_config_root(tmp_path)
    evidence = SourceEvidence.create(
        doc_id=DOC,
        page=1,
        bbox=(10.0, 10.0, 200.0, 30.0),
        raw_text="ICs0 = 64.6 nM",
    )
    persist_source_evidence(tmp_path, [evidence])
    proposal = ReviewProposal(
        doc_id=DOC,
        target_kind="evidence",
        target_id=evidence.evidence_id,
        field="raw_text",
        before="ICs0 = 64.6 nM",
        after="IC50 = 64.6 nM",
        rationale="glyph damage: ICs0 is the OCR reading of IC50",
        evidence_ids=[evidence.evidence_id],
    )

    [created] = review_proposals.propose_items(str(tmp_path), [proposal])
    payload = _item(tmp_path, created.item_id)["payload"]

    assert payload["before_actual"] == "ICs0 = 64.6 nM"
    decided = decide_items(str(tmp_path), "confirm", "", [_Decision(created.item_id)])
    assert decided.results[0]["applied"] is False  # record-only by design
    assert (
        get_repositories(str(tmp_path)).evidence.get(evidence.evidence_id).raw_text
        == "ICs0 = 64.6 nM"
    )


def test_a_filtered_batch_confirms_only_the_matching_proposals(
    tmp_path: Path, patch_config_root
) -> None:
    """``target_kind=evidence`` approves text-level proposals and nothing else."""
    from mbforge.service.use_cases.review_queue import decide_filtered

    patch_config_root(tmp_path)
    _seed_molecule(tmp_path)
    evidence = SourceEvidence.create(
        doc_id=DOC,
        page=1,
        bbox=(10.0, 10.0, 200.0, 30.0),
        raw_text="ICs0 = 64.6 nM",
    )
    persist_source_evidence(tmp_path, [evidence])
    review_proposals.propose_items(
        str(tmp_path),
        [
            ReviewProposal(
                doc_id=DOC,
                target_kind="evidence",
                target_id=evidence.evidence_id,
                field="raw_text",
                after="IC50 = 64.6 nM",
            ),
            _propose(tmp_path, "7"),
        ],
    )

    decided = decide_filtered(
        str(tmp_path),
        kind=AI_REVIEW_KIND,
        doc_id=DOC,
        target_kind="evidence",
        action="confirm",
        reason="approved all text",
        limit=50,
    )

    assert decided.updated == 1
    evidence_item = _item(
        tmp_path,
        review_proposals.proposal_item_id(
            doc_id=DOC,
            target_kind="evidence",
            target_id=evidence.evidence_id,
            field="raw_text",
        ),
    )
    molecule_item = _item(
        tmp_path,
        review_proposals.proposal_item_id(
            doc_id=DOC, target_kind="molecule", target_id="mol-1", field="name"
        ),
    )
    assert evidence_item["status"] == "confirmed"
    # The molecule proposal was untouched by the evidence-only batch.
    assert molecule_item["status"] == "pending"


def test_a_proposal_against_an_invented_target_is_refused(tmp_path: Path) -> None:
    [refused] = review_proposals.propose_items(
        str(tmp_path),
        [
            ReviewProposal(
                doc_id=DOC,
                target_kind="evidence",
                target_id="does-not-exist",
                field="raw_text",
                after="IC50 = 64.6 nM",
            )
        ],
    )

    assert refused.action == "refused" and "unknown evidence target" in refused.error
