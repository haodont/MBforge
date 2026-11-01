# HTTP API

FastAPI routes live under `src/mbforge/api/http/` and are mounted by
`src/mbforge/server/app.py`. Request and response models live in
`src/mbforge/service/dto/`.

Routes resolve `library_root` through the service use cases. They do not
construct SQLite managers or access storage modules directly. The running
OpenAPI document remains available from the local FastAPI server at
`/docs`.

`POST /api/v1/activities/export` accepts
`{"doc_ids": ["<document SHA-256>"], "library_root": "<library directory>"}`
(`library_root` is optional). It returns `application/zip` as
`structure-activity.zip`. The archive contains matched readings pending review,
all unresolved readings with reasons, and exact committed facts/source evidence.
Unanalysed or stale documents return 409 and must run Patent analysis first.
The entire selection fails explicitly if one document is unavailable or stale;
it never silently omits that document. See the
[export contract](../qa/structure-activity-export-20261030.md).
