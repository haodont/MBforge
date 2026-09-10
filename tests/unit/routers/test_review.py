from __future__ import annotations

from fastapi.testclient import TestClient

from mbforge.services.review_queue import insert_review_item
from mbforge.storage.sqlite.database import DatabaseManager


def test_review_queue_stats_and_batch_decision(
    app_client: TestClient, tmp_library
) -> None:
    root = str(tmp_library)
    db = DatabaseManager.get(root)
    db.initialize()
    with db.mol_conn() as conn:
        insert_review_item(
            conn,
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
