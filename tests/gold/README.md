# Gold relation-pair set

This directory holds the machine-readable side of the
[gold-standard protocol](../../docs/plan-gold-standard.md). The protocol is the
authority; the files here are its executable form.

| File | Purpose |
|---|---|
| `schema.json` | JSON Schema for one gold record |
| `manifest.json` | Development corpus metadata, rendering class and strata |
| `validate.py` | Structural + semantic validator (stdlib only) |
| `annotations/*.jsonl` | Annotation records, one per line; pilot records are assistant drafts until adjudicated |
| [Pilot report](../../docs/qa/gold-pilot-cn121270515a-20261023.md) | First annotation pass, findings and open adjudications |

## Rules

- The page image is the source of truth. OCR text is evidence, not truth.
- A record identifies its document by `doc_id` (SHA-256 of the file bytes).
  PDFs are never committed to this repository.
- `gold_status` is `present`, `absent` or `insufficient_evidence`. `absent`
  records are only valid on pages marked `page_annotation: "exhaustive"`.
- Precision is computed only on exhaustively annotated pages. Unmatched commits
  on targeted pages are `unjudged`, never false positives.
- `present` records require a subject or object, at least one evidence id and
  `geometry_complete: true`.
- Corrections append a new record with `annotation.version` and
  `annotation.supersedes`; they never edit the old record.

## Validate

```bash
uv run python tests/gold/validate.py --check-manifest
uv run python tests/gold/validate.py --self-test
uv run python tests/gold/validate.py tests/gold/annotations/dev.jsonl
```

Exit code 0 means every record passed. The validator checks the JSON Schema's
core constraints plus the cross-field rules JSON Schema cannot express: bbox
ordering, key-space consistency, gold-status requirements, document metadata
agreement and unique ids.

## Current state

The manifest is a **development** corpus: all 13 documents were read while the
parsers were written, so they cannot also be the held-out proof. The held-out
split needs at least six new documents, including a granted `B`, a utility
model, an EP document and a Markush-heavy document. `family` is unassigned in
the manifest and must be assigned before the split.

Five pilot annotations are checked in (36 records):

| File | Records | Layout |
|---|---:|---|
| `annotations/cn121270515a.pilot.jsonl` | 22 | Markush claims, claim 4 list, examples, activity table |
| `annotations/us20250206734a1.pilot.jsonl` | 6 | two-column examples, table split across pages |
| `annotations/il292693a.pilot.jsonl` | 4 | structure-column synthesis table |
| `annotations/cn120943813a.pilot.jsonl` | 3 | repeated (label, value) table, label-in-table/structure-below |
| `annotations/jp2023544789a.pilot.jsonl` | 1 | cross-page example, native Japanese text |

They are one annotator's drafts: every present record carries
`human_confirm: not_run`. The first-document findings are in the
[pilot report](../../docs/qa/gold-pilot-cn121270515a-20261023.md); the
cross-document layout rules are in
[patent layout rules](../../docs/wiki/patent-layout-rules.md). Human
adjudication, the pair-level evaluator and the held-out split are pending.
