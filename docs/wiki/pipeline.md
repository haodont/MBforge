# Pipeline contract

The registered pipeline is:

```text
Extract ─┐
         ├─> Join ─> Markdown ─> Patent
Detection┘
```

Extract and Detection are parallel producers. Each writes a raw branch
artifact under the run staging directory. Join validates the two branches,
deduplicates evidence, and persists canonical `SourceEvidence` rows in
`{library_root}/.mbforge/library.db`; downstream artifacts retain
`evidence_ids` rather than duplicating evidence payloads.

Markdown enriches the readable document representation. Patent extracts
document-local facts and associations from the joined evidence and publishes
the unified facts artifact. Link is not registered. Persist is retained as a
future redesign and is not part of the active runner.

Stage names, dependencies, results, and machine-readable error codes are
defined in `src/mbforge/application/pipeline/stage.py`. Queue terminal states
are defined once in `src/mbforge/foundation/queue_contract.py`.

Model loading is lazy. Tests use mocked or unavailable model capabilities and
must not download weights or require a GPU.
