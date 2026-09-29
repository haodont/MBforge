# HTTP API

FastAPI routes live under `src/mbforge/api/http/` and are mounted by
`src/mbforge/server/app.py`. Request and response models live in
`src/mbforge/service/dto/`.

Routes resolve `library_root` through the service use cases. They do not
construct SQLite managers or access storage modules directly. The running
OpenAPI document remains available from the local FastAPI server at
`/docs`.
