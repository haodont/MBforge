# Settings Schema Audit & Normalization Design

**Date:** 2026-07-11  
**Scope:** Python backend `AppConfig` / `LLMConfig` and downstream consumers; frontend type alignment as secondary concern.  
**Approach:** Medium audit (方案 B) — list missing/hardcoded configuration items and recommend turning the seven loose `dict[str, Any]` fields into typed Pydantic sub-models.

---

## 1. Background

`mbforge.utils.config.AppConfig` is the single source of truth for global settings. It is persisted as `{GLOBAL_APP_DIR}/settings.json` and exposed through `PUT /api/v1/settings`. Currently only three models are strongly typed:

- `RecentProject`
- `LLMConfig`
- `AppConfig` itself

The remaining subsystem settings are stored as untyped `dict[str, Any]`:

```python
vlm: dict[str, Any]
ocr: dict[str, Any]
model_server: dict[str, Any]
pdf_parse: dict[str, Any]
moldet: dict[str, Any]
ingest: dict[str, Any]
popo: dict[str, Any]
```

This causes three maintainability problems:

1. **No server-side validation.** A typo or wrong type written by the frontend is silently accepted.
2. **Default values are scattered.** Each consumer calls `.get("key", default)` independently; the same key can have different defaults in different files.
3. **Frontend/backend drift.** `frontend/src/api/http/settings.ts` maintains its own interfaces, which can diverge from the backend schema.

This design documents the recommended typed schema and the concrete fields to add.

---

## 2. Guiding Principles

1. **Backward compatibility.** All new sub-models use `ConfigDict(extra="ignore")`. Existing `settings.json` files deserialize without migration.
2. **Sane defaults.** Every new field has a default value equal to the current hard-coded fallback so behavior does not change on upgrade.
3. **Centralize defaults.** Once a field is typed in a Pydantic model, consumers should access it directly (`cfg.ocr.upload_batch_size`) instead of using `.get(...)`.
4. **No new runtime capabilities.** This audit intentionally does not propose new features; it only exposes parameters that are already tunable in code.

---

## 3. Proposed Schema

### 3.1 `LLMConfig` additions

Current fields: `provider`, `model`, `api_key`, `base_url`, `temperature`, `max_tokens`, `pageindex_threshold`, `language`, `reorganize_model`.

Add:

| Field | Type | Default | Rationale |
|-------|------|---------|-----------|
| `top_p` | `float` | `1.0` | Already declared in frontend `LlmConfig` but missing on backend. |
| `request_timeout` | `int` | `60` | Already declared in frontend; `create_llm` ignores timeout today. |

Notes:

- `reorganize_model` already exists but should keep its documented fallback to `model`.
- Consider moving the fallback logic (`getattr(cfg.llm, "reorganize_model", None) or cfg.llm.model`) into a helper or validator so callers do not repeat it.

### 3.2 New `OCRConfig`

Replaces `ocr: dict[str, Any]`.

| Field | Type | Default | Consumer |
|-------|------|---------|----------|
| `mineru_api_key` | `str` | `""` | `routers/ocr.py::test_mineru`, `backends/ocr/chain.py` |
| `paddleocr_api_key` | `str` | `""` | `routers/ocr.py::test_paddleocr`, `backends/ocr/chain.py` |
| `paddleocr_host` | `str` | `"https://aistudio.baidu.com"` | `routers/ocr.py::test_paddleocr`, `backends/ocr/chain.py` |
| `paddleocr_model` | `str` | `"PaddleOCR-VL-1.6"` | `routers/ocr.py::test_paddleocr`, `backends/ocr/chain.py` |
| `glmocr_api_key` | `str` | `""` | `routers/ocr.py::test_glmocr`, `backends/ocr/chain.py` |
| `glmocr_model` | `str` | `"glm-ocr"` | `backends/ocr/chain.py` |
| `upload_batch_size` | `int` | `1` | `pipeline/extract_text.py` (MinerU batch path) |

Notes:

- `glmocr_base_url` is read in `backends/ocr/chain.py` but only as a fallback alias; decide whether to keep it or collapse to `base_url`.
- Keep `extra="ignore"` so users can still pass backend-specific keys not in this list.

### 3.3 New `MoldetConfig`

Replaces `moldet: dict[str, Any]`.

| Field | Type | Default | Consumer |
|-------|------|---------|----------|
| `device` | `str` | `"auto"` | `parsers/molecule/molscribe_inference/download.py` |
| `molscribe_dir` | `str` | `""` | `parsers/molecule/molscribe_inference/download.py` |
| `auto_moldet_on_import` | `bool` | `True` | Settings UI control for automatic molecule detection on import. |
| `detection_dpi` | `float` | `200.0` | `pipeline/extract_molecules.py` |
| `detection_batch_size` | `int` | `0` | `pipeline/extract_molecules.py` |
| `text_page_char_threshold` | `int` | `500` | `pipeline/extract_molecules.py` (currently hard-coded) |
| `max_pages_per_doc` | `int \| None` | `None` | `pipeline/extract_molecules.py` (currently passed via `max_pages` arg) |

Notes:

- `device` should accept `"auto"`, `"cpu"`, `"cuda"`, or a specific CUDA device string.
- `max_pages_per_doc` is currently a function argument; exposing it in settings allows UI-level ingestion limits.

### 3.4 New `IngestConfig`

Replaces `ingest: dict[str, Any]`.

| Field | Type | Default | Consumer |
|-------|------|---------|----------|
| `auto_enqueue_on_import` | `bool` | `True` | Frontend declares it; backend consumer should be added or the frontend field deprecated. |
| `default_priority` | `int` | `0` | New; pipeline runner queue ordering. |
| `stage_timeout_seconds` | `dict[str, int]` | `{...}` | Optional; per-stage timeouts instead of hard-coded defaults. |
| `max_retries` | `int` | `1` | Optional; recoverable stage retries. |

Notes:

- `auto_enqueue_on_import` is declared in the frontend but no backend code reads it today. Either wire it up or remove it from the frontend type.
- `stage_timeout_seconds` and `max_retries` are reserved for future pipeline hardening.

### 3.5 New `PdfParseConfig`

Replaces `pdf_parse: dict[str, Any]`.

| Field | Type | Default | Consumer |
|-------|------|---------|----------|
| `chunk_size` | `int` | `1000` | Frontend declares it; backend should consume or deprecate. |
| `chunk_overlap` | `int` | `200` | Frontend declares it; backend should consume or deprecate. |

Notes:

- These fields are currently frontend-only. If the backend has no chunking strategy that uses them, they should be removed from the frontend interface rather than kept as dead weight.

### 3.6 New `PopoConfig`

Replaces `popo: dict[str, Any]`.

| Field | Type | Default | Consumer |
|-------|------|---------|----------|
| `enabled` | `bool` | `False` | `pipeline/stages/reorganize_stage.py` |

Notes:

- Keep minimal. Additional Popo parameters (model path, batch size) can be added later under this model.

### 3.7 New `VLMConfig`

Replaces `vlm: dict[str, Any]`.

| Field | Type | Default | Consumer |
|-------|------|---------|----------|
| `provider` | `str` | `"openai_compatible"` | Reserved for future Popo / visual pipeline use. |
| `model` | `str` | `""` | Reserved. |
| `api_key` | `str` | `""` | Reserved. |
| `base_url` | `str` | `""` | Reserved. |

Notes:

- Mark these as `reserved` in the docstring until a concrete consumer exists, to avoid the appearance of dead code.

### 3.8 New `ModelServerConfig`

Replaces `model_server: dict[str, Any]`.

| Field | Type | Default | Consumer |
|-------|------|---------|----------|
| `host` | `str` | `"127.0.0.1"` | Reserved / future local model server. |
| `port` | `int` | `18793` | Reserved. |
| `auto_start` | `bool` | `False` | Reserved. |
| `startup_timeout` | `int` | `30` | Reserved. |
| `health_check_interval` | `int` | `5` | Reserved. |

Notes:

- The backend currently has no model-server process. These fields are reserved; if no plan exists to implement the server, consider removing the `model_server` frontend type instead.

### 3.9 Secrets redaction

`_redact_secrets` in `routers/settings.py` currently redacts keys containing `api_key` or `secret`. Extend the heuristic to also match:

- `token`
- `password`
- `key` (when it appears as a suffix, e.g., `glmocr_api_key` already matches `api_key`, but generic `hf_key` would not)

This is a small, safe improvement that prevents leaking credentials in `GET /api/v1/settings` responses.

---

## 4. Migration & Compatibility

1. Change `AppConfig` field types from `dict[str, Any]` to the new Pydantic models with `Field(default_factory=Model)`.
2. Keep `SettingsConfigDict(extra="ignore")` on `AppConfig` and `ConfigDict(extra="ignore")` on every sub-model.
3. `update_settings` deep-merges dicts and calls `AppConfig.model_validate(current)`. Because the new sub-models accept dict input during validation, existing `settings.json` files continue to work.
4. Update consumers to access typed attributes directly. Remove per-module `.get("key", default)` fallbacks once the model owns the default.

---

## 5. Frontend Alignment

1. Update `frontend/src/api/http/settings.ts` interfaces to match the backend schema exactly.
2. Rename the frontend internal `moldet_batch_size` setting to `detection_batch_size` to align with the backend schema; update `PdfParseSection.tsx` accordingly.
3. Add `auto_moldet_on_import` to both backend `MoldetConfig` and the frontend type to preserve the existing Settings UI toggle.
4. For fields marked `reserved` above, keep them in the type but do not add UI controls until a consumer exists.
5. If a field is declared on the frontend but never consumed on the backend (`pdf_parse.chunk_size`, `pdf_parse.chunk_overlap`, `ingest.auto_enqueue_on_import`, `model_server.*`), decide whether to:
   - Implement the consumer, or
   - Remove the field from both sides.

---

## 6. Out of Scope

- Implementing the changes. This document is an audit and design only.
- Changing the physical storage path or migration logic in `utils/config.py`.
- Adding new pipeline stages or runtime capabilities.
- Implementing `/cache-size` and `/cache-clear` endpoints (currently stubs in `routers/settings.py`).

---

## 7. Acceptance Criteria

- All fields listed above have explicit types and defaults in `AppConfig` or a nested Pydantic model.
- Every hard-coded default currently living in a consumer module is represented in the corresponding Pydantic model.
- Existing `settings.json` files deserialize without error.
- `GET /api/v1/settings` continues to redact sensitive values.
- Frontend settings types match the backend schema.
