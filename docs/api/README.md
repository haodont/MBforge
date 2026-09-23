# HTTP API

FastAPI routes live under `src/mbforge/interfaces/http/` and are mounted by
`src/mbforge/app.py`. Request and response models live in
`src/mbforge/application/dto/`.

Routes resolve `library_root` through the application use cases. They do not
construct SQLite managers or access storage modules directly. The running
OpenAPI document remains available from the local FastAPI server at
`/docs`.
