"""One-call research briefing: the server-known state of a library.

A resumed or fresh agent session otherwise re-discovers its context one tool
call at a time (documents, then runs, then the review queue, then the worker).
This aggregates the durable server state into a single read so the agent starts
grounded. It deliberately does NOT carry the agent's active goal — that is
session state the CLI owns, not a server fact — and it stores nothing: every
field is projected from the same stores the individual capabilities read.
"""

from __future__ import annotations

import asyncio
from typing import Any

from mbforge.service.ports import get_repositories
from mbforge.service.use_cases.documents.document_refs import short_doc_id
from mbforge.service.use_cases.pipeline import ingest
from mbforge.service.use_cases.review_queue import stats_summary

#: Active runs shown in the briefing; the agent pages ``runs`` for the rest.
_RUN_LIMIT = 10


async def library_briefing(library_root: str, doc_id: str = "") -> dict[str, Any]:
    """Aggregate documents, active runs, worker, review queue and anchor coverage.

    ``doc_id`` scopes the runs, review queue and anchor coverage to one
    document; the document overview stays library-wide.
    """
    repositories = get_repositories(library_root)
    by_status, runs, worker, review, anchors = await asyncio.gather(
        asyncio.to_thread(repositories.database.document_status_counts),
        ingest.list_runs(
            library_root, doc_id=doc_id, active_only=True, limit=_RUN_LIMIT
        ),
        ingest.worker_health_payload(library_root),
        asyncio.to_thread(stats_summary, library_root, doc_id or None),
        asyncio.to_thread(repositories.anchors.coverage, doc_id or None),
    )

    pending_by_kind: dict[str, int] = {}
    for row in review.get("items") or []:
        if row.get("status") == "pending":
            pending_by_kind[str(row["kind"])] = int(row["count"])

    return {
        "documents": {
            "total": sum(by_status.values()),
            "by_status": dict(by_status),
        },
        "active_runs": [
            {
                "run_id": str(row["run_id"]),
                "doc_id": row.get("doc_id"),
                "short_id": (
                    short_doc_id(str(row["doc_id"])) if row.get("doc_id") else None
                ),
                "status": str(row.get("status") or "unknown"),
                "stages": [
                    f"{node.get('stage')}={node.get('status')}"
                    for node in row.get("nodes") or []
                ],
            }
            for row in runs
        ],
        "worker": {
            "status": str(worker["status"]),
            "locked": bool(worker["locked"]),
            "active": int(worker["active"]),
            "backlog": int(worker["backlog"]),
            "model_gate": worker.get("model_gate"),
        },
        "review": {
            "pending": int(review.get("pending") or 0),
            "by_kind": pending_by_kind,
        },
        "anchors": anchors,
    }


__all__ = ["library_briefing"]
