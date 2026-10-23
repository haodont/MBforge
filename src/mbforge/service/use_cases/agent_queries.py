"""Read-side queries backing the assistant's library tools.

These are the structured, safe queries the agent sidecar exposes as tools
(``library_stats``, ``search_library``, ``query_documents``, ``query_activities``,
``query_evidence``) plus the guarded read-only SQL escape hatch
(``library_sql``). They read the library database through the repository /
database ports, so no tool reaches the concrete SQLite adapter directly.
"""

from __future__ import annotations

from typing import Any

from mbforge.domain.evidence_kind import category_of
from mbforge.foundation.errors import ValidationError
from mbforge.service.ports import get_database, get_repositories
from mbforge.service.use_cases.documents.activity_queries import list_activity_records
from mbforge.service.use_cases.documents.source_evidence import find_text, list_evidence

#: Long free text (evidence, context) is truncated before crossing the tool boundary.
MAX_TEXT_CHARS = 2000


def search_library(
    library_root: str, *, query: str, doc_id: str = "", limit: int = 20, offset: int = 0
) -> dict[str, Any]:
    """Search all extracted source text with literal, AND-combined keywords."""
    query = query.strip()
    if not query or len(query) > 400 or len(query.split()) > 10:
        raise ValidationError("Use 1-10 keywords, at most 400 characters")
    if not 1 <= limit <= 50 or not 0 <= offset <= 10000:
        raise ValidationError("Invalid search pagination")
    rows = get_repositories(library_root).evidence.search(
        query, doc_id=doc_id, limit=limit + 1, offset=offset
    )
    return {
        "results": rows[:limit],
        "has_more": len(rows) > limit,
        "next_offset": offset + limit if len(rows) > limit else None,
        "scope": "extracted_source_evidence",
        "query": query,
    }


def library_stats(library_root: str) -> dict[str, Any]:
    """Return coarse counts across the library's main tables."""
    db = get_database(library_root)
    totals: dict[str, Any] = dict(db.table_counts())
    totals["documents"] = {
        "total": totals["documents"],
        "by_status": db.document_status_counts(),
    }
    return totals


def query_documents(
    library_root: str,
    *,
    status: str = "",
    name: str = "",
    limit: int = 50,
) -> list[dict[str, Any]]:
    """List/filter documents. *name* is a case-insensitive substring match."""
    statuses = [status] if status else None
    rows = get_repositories(library_root).documents.list_rows(statuses=statuses)
    needle = name.strip().lower()
    results: list[dict[str, Any]] = []
    for row in rows:
        if (
            needle
            and needle not in str(row.get("title", "")).lower()
            and needle not in str(row.get("file_name", "")).lower()
        ):
            continue
        results.append(
            {
                "doc_id": row.get("doc_id"),
                "title": row.get("title"),
                "file_name": row.get("file_name"),
                "page_count": row.get("page_count"),
                "status": row.get("status"),
                "created_at": row.get("created_at"),
            }
        )
        if len(results) >= limit:
            break
    return results


def query_activities(
    library_root: str,
    *,
    doc_id: str,
    target: str = "",
    assay_description: str = "",
    limit: int = 50,
) -> list[dict[str, Any]]:
    """Return a document's activity records (the Patent-stage measurements)."""
    if not doc_id:
        raise ValidationError("doc_id is required")
    return list_activity_records(
        library_root,
        doc_id,
        target=target,
        assay_description=assay_description,
        limit=limit,
    )


def query_evidence(
    library_root: str,
    *,
    doc_id: str,
    page: int | None = None,
    kind: str = "",
    text: str = "",
    limit: int = 50,
) -> list[dict[str, Any]]:
    """Return a document's source-evidence rows, optionally filtered."""
    if not doc_id:
        raise ValidationError("doc_id is required")
    if text.strip():
        entries = find_text(library_root, doc_id, text)
    else:
        entries = list_evidence(library_root, doc_id, page=page, kind=kind or None)
    results: list[dict[str, Any]] = []
    for entry in entries:
        if page is not None and entry.page != page:
            continue
        if kind and entry.kind != kind:
            continue
        item = entry.to_dict()
        item["category"] = category_of(entry.kind)
        raw = item.get("raw_text")
        if isinstance(raw, str) and len(raw) > MAX_TEXT_CHARS:
            item["raw_text"] = raw[:MAX_TEXT_CHARS] + "…"
        item["truncated"] = isinstance(raw, str) and len(raw) > MAX_TEXT_CHARS
        results.append(item)
        if len(results) >= limit:
            break
    return results


def library_schema(library_root: str) -> list[dict[str, Any]]:
    """Return the queryable table/column listing for the SQL escape hatch."""
    return get_database(library_root).readonly_schema()


def run_library_sql(library_root: str, sql: str, *, max_rows: int) -> dict[str, Any]:
    """Run one guarded read-only SELECT against the library database."""
    return get_database(library_root).readonly_query(sql, max_rows=max_rows)


__all__ = [
    "library_schema",
    "library_stats",
    "query_activities",
    "query_documents",
    "query_evidence",
    "run_library_sql",
    "search_library",
]
