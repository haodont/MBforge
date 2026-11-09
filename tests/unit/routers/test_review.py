from __future__ import annotations

from fastapi.testclient import TestClient

from mbforge.db.sqlite.database import DatabaseManager
from mbforge.service.ports import get_repositories


def test_an_ai_proposal_enters_the_queue_and_freezes_after_a_decision(
    app_client: TestClient, tmp_library
) -> None:
    """The assistant may propose, revise and then lose the target to a human."""
    from mbforge.db.source_evidence import persist_source_evidence
    from mbforge.domain.evidence import SourceEvidence

    root = str(tmp_library)
    evidence = SourceEvidence.create(
        doc_id="doc-1",
        page=1,
        bbox=(10.0, 10.0, 200.0, 30.0),
        raw_text="ICs0 = 64.6 nM",
    )
    persist_source_evidence(tmp_library, [evidence])
    body = {
        "library_root": root,
        "items": [
            {
                "doc_id": "doc-1",
                "target_kind": "evidence",
                "target_id": evidence.evidence_id,
                "field": "raw_text",
                "before": "ICs0 = 64.6 nM",
                "after": "IC50 = 64.6 nM",
                "rationale": "glyph damage: ICs0 is the OCR reading of IC50",
                "evidence_ids": [evidence.evidence_id],
            }
        ],
    }

    created = app_client.post("/api/v1/review/propose", json=body)
    assert created.status_code == 200
    item = created.json()["items"][0]
    assert item["action"] == "created" and item["status"] == "pending"

    queue = app_client.get(
        "/api/v1/review/queue",
        params={"library_root": root, "kind": "ai_review"},
    )
    assert queue.status_code == 200 and queue.json()["total"] == 1
    assert queue.json()["items"][0]["payload"]["proposal"]["after"] == "IC50 = 64.6 nM"

    decision = app_client.post(
        "/api/v1/review/decide",
        json={
            "library_root": root,
            "items": [{"kind": "ai_review", "id": item["item_id"]}],
            "action": "confirm",
            "reason": "the reading should be IC50",
        },
    )
    assert decision.status_code == 200 and decision.json()["updated"] == 1

    again = app_client.post("/api/v1/review/propose", json=body)
    assert again.status_code == 200
    assert again.json()["items"][0]["action"] == "refused"
    assert "human already decided" in again.json()["items"][0]["error"]


def test_a_filtered_batch_confirms_every_text_proposal_of_one_document(
    app_client: TestClient, tmp_library
) -> None:
    """One click approves the whole patent (or all text) without a selection list."""
    from mbforge.db.source_evidence import persist_source_evidence
    from mbforge.domain.evidence import SourceEvidence

    root = str(tmp_library)
    evidence = [
        SourceEvidence.create(
            doc_id="doc-1",
            page=1,
            bbox=(10.0, 10.0 + index * 40.0, 200.0, 30.0 + index * 40.0),
            raw_text=f"reading {index}",
        )
        for index in range(2)
    ]
    persist_source_evidence(tmp_library, evidence)
    proposals = [
        {
            "doc_id": "doc-1",
            "target_kind": "evidence",
            "target_id": item.evidence_id,
            "field": "raw_text",
            "after": f"corrected {index}",
        }
        for index, item in enumerate(evidence)
    ]
    created = app_client.post(
        "/api/v1/review/propose", json={"library_root": root, "items": proposals}
    )
    assert created.status_code == 200
    assert [entry["action"] for entry in created.json()["items"]] == [
        "created",
        "created",
    ]

    batch = app_client.post(
        "/api/v1/review/decide-filtered",
        json={
            "library_root": root,
            "kind": "ai_review",
            "doc_id": "doc-1",
            "target_kind": "evidence",
            "action": "confirm",
            "reason": "approved all text",
        },
    )
    assert batch.status_code == 200
    assert batch.json()["updated"] == 2

    pending = app_client.get(
        "/api/v1/review/queue",
        params={"library_root": root, "kind": "ai_review", "status": "pending"},
    )
    assert pending.json()["total"] == 0


def test_review_assist_pulls_one_suggestion_and_serves_it_back(
    app_client: TestClient, tmp_library, patch_config
) -> None:
    """The route refuses when disabled, then stores and serves one suggestion.

    The suggestion is data, never a decision: the item stays pending and the
    queue carries the answer in its payload for the reviewer to read.
    """
    root = str(tmp_library)
    DatabaseManager.get(root).initialize()
    repo = get_repositories(root).review
    repo.insert_review_item(
        item_id="assist-1",
        kind="missing_evidence",
        doc_id="doc-1",
        reasons=["missing_crop"],
        name="17",
    )

    # Assistance is opt-in: the default configuration refuses the request.
    disabled = app_client.post("/api/v1/review/assist", json={"library_root": root})
    assert disabled.status_code == 422

    from mbforge.contracts.review_assist import AssistSuggestion
    from mbforge.service.ports.review_assist import configure_review_assist_runtime

    class _Runtime:
        calls = 0

        def run(self, packet, *, timeout_seconds: float = 120.0) -> AssistSuggestion:
            _Runtime.calls += 1
            return AssistSuggestion(
                status="answered", model="fake-vlm", vision=False, answer="answer=m-1"
            )

    configure_review_assist_runtime(_Runtime())
    try:
        patch_config(lambda cfg: setattr(cfg.review, "enabled", True))
        answer = app_client.post(
            "/api/v1/review/assist",
            json={
                "library_root": root,
                "items": [{"kind": "missing_evidence", "id": "assist-1"}],
            },
        )
        assert answer.status_code == 200
        assert answer.json()["items"][0]["status"] == "answered"

        stored = app_client.get(
            "/api/v1/review/assist/missing_evidence/assist-1",
            params={"library_root": root},
        )
        assert stored.status_code == 200
        assert stored.json()["answer"] == "answer=m-1"

        queue = app_client.get(
            "/api/v1/review/queue",
            params={"library_root": root, "status": "pending"},
        )
        item = next(row for row in queue.json()["items"] if row["id"] == "assist-1")
        assert item["status"] == "pending"  # a suggestion never decides
        assert item["payload"]["ai_assist"]["answer"] == "answer=m-1"
    finally:
        configure_review_assist_runtime(None)


def test_review_queue_stats_and_batch_decision(
    app_client: TestClient, tmp_library
) -> None:
    root = str(tmp_library)
    db = DatabaseManager.get(root)
    db.initialize()
    repo = get_repositories(root).review
    repo.insert_review_item(
        item_id="native-1",
        kind="missing_evidence",
        doc_id="doc-1",
        reasons=["missing_crop"],
    )

    queue = app_client.get(
        "/api/v1/review/queue",
        params={"library_root": root, "status": "pending"},
    )
    assert queue.status_code == 200
    assert queue.json()["total"] == 1
    assert queue.json()["items"][0]["kind"] == "missing_evidence"

    decision = app_client.post(
        "/api/v1/review/decide",
        json={
            "library_root": root,
            "items": [
                {"kind": "missing_evidence", "id": "native-1"},
                {"kind": "missing_evidence", "id": "missing"},
            ],
            "action": "reject",
            "reason": "confirmed not actionable",
        },
    )
    assert decision.status_code == 200
    assert decision.json()["updated"] == 1
    assert decision.json()["skipped"] == 1

    stats = app_client.get("/api/v1/review/stats", params={"library_root": root})
    assert stats.status_code == 200
    assert stats.json()["pending"] == 0
    assert {row["status"] for row in stats.json()["items"]} == {"rejected"}

    history = app_client.get(
        "/api/v1/review/history",
        params={"library_root": root, "entity_id": "native-1"},
    )
    assert history.status_code == 200
    assert history.json()["history"][0]["action"] == "reject"
