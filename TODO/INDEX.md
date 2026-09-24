# MBForge TODO index

This directory records active architecture and implementation plans.

## Current pipeline

`Extract → Join → Markdown → Patent` is the registered pipeline. Extract is the
single producer — the layout/text/table producer and the molecule pass
(MolDet + MolParser) both run inside it — and publishes one run-scoped branch
artifact; Join validates it and writes canonical `SourceEvidence` rows to
SQLite. Link is removed from the active path, and Persist remains unregistered
pending redesign.

## Known gaps

- `patent/sections.py:parse_source_evidence_sections` treats only
  `kind in {"text_span", "table_span"}` as heading-eligible, but the local
  Hiro-Layout producer mints every region under its own label (`text`, `sec`,
  `head`, `tab`, …). A scanned document therefore reports 0 sections / 0
  entries even though its `source_evidence` rows hold the full text. Either the
  parser must classify through `evidence_kind.category_of`, or the join must
  mint the producer's labels into the text category.

## Active plans

- [Source layout reorganization](../docs/plan-source-layout-reorganization.md)
- [SLANet-1M as table parser on the Hiro-Layout path](../docs/plan-slanet-1m-table-parser.md)
- [Backend architecture](../docs/wiki/architecture.md)
- [Pipeline contract](../docs/wiki/pipeline.md)

## Conventions

- Treat `docs/wiki/pipeline.md` as the per-stage contract.
- Keep raw branch data and SQL source evidence separate from the shared
  `domain.molecule.Molecule` entity and inferred facts.
- `Molecule` is the only structure-bearing molecule domain object across
  detection normalization, correction, Markush handling, hydration, query,
  and future persistence. `ExtractionResult`/`DetectionSource` remain raw
  observations; `CompoundEntry` remains a document-level patent record.
- Cross-business-package imports use absolute `mbforge...` paths; relative
  imports are for a package and its immediate local modules.
