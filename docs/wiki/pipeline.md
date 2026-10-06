# Pipeline contract

The registered pipeline is:

```text
Extract ─> Markdown ─> Patent
```

Extract is the single producer: the layout/text/table producer and the molecule
pass (MolDet + MolParser) both run inside it, and it mints and persists the
canonical `SourceEvidence` rows in `{library_root}/library.db` itself.
SQL is the only evidence store — there is no branch artifact — and crops are
staged in `storage/{doc_id}/.staging/` then promoted into
`storage/{doc_id}/crops/` only after every stage succeeds. Downstream artifacts
retain `evidence_ids` rather than duplicating evidence payloads.

Markdown enriches the readable document representation from the SQL evidence.
Patent extracts document-local facts and associations from the same evidence and
publishes the unified facts artifact. Link and Persist are not registered and
are not part of the active runner.

Stage names, dependencies, results, and machine-readable error codes are
defined in `src/mbforge/service/pipeline/stage.py`. Queue terminal states
are defined once in `src/mbforge/foundation/queue_contract.py`.

## Document lifecycle and workspace visibility

`documents.status` records where a document stands relative to processing, and
the workspace listing is gated on it:

| status | meaning | shown in workspace |
| --- | --- | --- |
| `pending` | bytes registered, no run has produced an outcome | no |
| `ready` | every stage succeeded and the run published its output | yes |
| `error` | a stage failed, or finalization could not publish the output | yes |

`POST /api/v1/library/import` registers the document and enqueues its run in
the same request (unless `ingest.auto_enqueue_on_import` is false), returning
the `run_id`. The workspace therefore hides a document between import and the
end of processing, and the queue page is the place to watch progress, read
logs, and retry.

The worker writes the status — not the per-stage event sink, whose `complete`
event fires once per stage and would mark a document ready early:

- run finalization (`all_stages_done` + `claim_finalize`) → `ready` when the
  run includes the `patent` stage, otherwise `extracted`
- stage failure, or a finalization that cannot publish → `error`
- cancellation → `pending` (no outcome exists; the document stays visible as
  "待处理")

Import runs the pipeline through Extract + Markdown only: the document is listed
as soon as it is imported (resting at `pending`, shown as "待处理") and becomes
`extracted` once it is readable; Patent analysis is triggered separately (per
document or in batch) with a `patent`-only run. A `patent`-only run rebuilds its
context from the SQL `source_evidence` rows Extract wrote.

`VISIBLE_DOCUMENT_STATUSES` in `src/mbforge/domain/document.py` names the
visible statuses (`pending`, `extracted`, `ready`, `error`); the document
listing, `doc_count`, and collection counts all filter on it so no count
advertises a document the user cannot see. Deleting a queue task discards that
run's results and returns the document to `pending`; only deleting the document
itself removes its source PDF.

Model loading is lazy. Tests use mocked or unavailable model capabilities and
must not download weights or require a GPU.
