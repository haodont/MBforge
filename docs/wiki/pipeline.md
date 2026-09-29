# Pipeline contract

The registered pipeline is:

```text
Extract ─> Markdown ─> Patent
```

Extract is the single producer: the layout/text/table producer and the molecule
pass (MolDet + MolParser) both run inside it, and it mints and persists the
canonical `SourceEvidence` rows in `{library_root}/.mbforge/library.db` itself.
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

Model loading is lazy. Tests use mocked or unavailable model capabilities and
must not download weights or require a GPU.
