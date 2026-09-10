# API Reference

This is the starting point for the long-term HTTP API reference. The running
FastAPI application exposes interactive OpenAPI at `/docs` and the schema at
`/openapi.json`. Route definitions and Pydantic models remain the executable
source of truth.

## Common contract

- Base path: `/api/v1`.
- Local development backend: `http://127.0.0.1:18792`.
- Frontend requests go through `frontend/src/api/http/` and use the Vite
  `/api` proxy in development.
- Python request fields use `library_root`; TypeScript and wire payloads use
  `libraryRoot`.
- Document artifacts are addressed through `storage/{doc_id}/`; callers do
  not construct filesystem paths.

Expected failures use the shared error envelope:

```json
{
  "success": false,
  "error": "human-readable message",
  "error_code": "machine_readable_code",
  "severity": "warning",
  "category": "module.category"
}
```

See [operations.md](../wiki/operations.md) for diagnostics and logging.

## Route groups

| Group | Prefix | Source |
|---|---|---|
| Libraries and documents | `/api/v1/library`, `/api/v1/documents` | `routers/documents/library.py`, `documents.py` |
| Pipeline and events | `/api/v1/pipeline`, `/api/v1/events` | `routers/pipeline/pipeline.py`, `system/events.py` |
| Activities | `/api/v1/activities` | `routers/documents/activity.py` |
| Knowledge and molecules | `/api/v1/kb`, `/api/v1/molecule`, `/api/v1/chem` | `routers/molecule/molecule.py`, `chem.py` |
| Notes | `/api/v1/notes` | `routers/documents/notes.py` |
| PDF, OCR, and text | `/api/v1/pdf`, `/api/v1/ocr`, `/api/v1/text` | `routers/documents/pdf.py`, `system/ocr.py` |
| Detection and rendering | `/api/v1/moldet`, `/api/v1/molparser`, `/api/v1/models` | `routers/molecule/moldet.py`, `molparser.py`, `system/models.py` |
| Settings and diagnostics | `/api/v1/settings`, `/api/v1/diagnostics`, `/api/v1/review` | `routers/system/settings.py`, `readiness.py`, `review.py` |
| Project Docs | `/api/v1/docs/pages` | `routers/documents/project_docs.py` |

Use the generated OpenAPI schema for the complete endpoint and parameter list;
do not maintain a second hand-written list here.

`GET /api/v1/activities/documents/{doc_id}` returns the document's persisted
activity rows together with activity matches still in `review_items`. The
response uses `source=activities` and `status=persisted` for stored rows, and
`source=review_items` with the review status for pending or resolved matches.
Optional `target`, `assay_description`, and `limit` query parameters apply to
both sources.

The model management routes under `/api/v1/models` include
`GET /loaded-status` and `POST /clear-cache`. “Clear cache” means unloading
in-process MolDet/MolParser models; it deliberately does not delete downloaded
weights. OCR fallback order is saved under `settings.ocr.priority`.

## Adding or changing an endpoint

1. Define or update the Pydantic schema and route test.
2. Register the router in `src/mbforge/app.py` with the correct prefix.
3. Update the frontend HTTP client and React Query hook when applicable.
4. Record compatibility, migration, and rollback impact in the PR.
5. Refresh the generated OpenAPI schema and this page only when the contract
   grouping or convention changes.
