# MBForge TODO index

This directory records active architecture and implementation plans.

## Current pipeline

`Extract → Markdown → Patent` is the registered pipeline. Extract is the single
producer — the layout/text/table producer and the molecule pass
(MolDet + MolParser) both run inside it — and mints and persists the canonical
`SourceEvidence` rows to SQLite itself. SQL is the only evidence store (there is
no branch artifact); Markdown assembles the readable document from that
evidence, and Patent publishes the unified facts artifact. Link and Persist are
removed from the active path.

## Known gaps

- `report.json` and `storage/{doc_id}/pages/` have no writer in the active
  path: the removed Persist stage produced them, while the document report and
  page readers still consume them.
- `markush_scaffolds` and `markush_fragments` also have no writer — their only
  producer module was removed with the Persist stage — yet the Markush
  enumeration/review readers still read them.
- The molecule↔evidence association is now persisted in `evidence.evidence_id`
  (pointing at the canonical `source_evidence` row); the legacy
  `text_molecule_links` table was dropped.

## Active plans

- [Source layout reorganization](../docs/plan-source-layout-reorganization.md)
- [SLANet-1M as table parser on the Hiro-Layout path](../docs/plan-slanet-1m-table-parser.md)
- [Backend architecture](../docs/wiki/architecture.md)
- [Pipeline contract](../docs/wiki/pipeline.md)

## Conventions

- Treat `docs/wiki/pipeline.md` as the per-stage contract.
- Keep SQL source evidence separate from the shared `domain.molecule.Molecule`
  entity and inferred facts.
- `Molecule` is the only structure-bearing molecule domain object across
  detection normalization, correction, Markush handling, hydration, query,
  and future persistence. `ExtractionResult`/`DetectionSource` remain raw
  observations; `CompoundEntry` remains a document-level patent record.
- Cross-business-package imports use absolute `mbforge...` paths; relative
  imports are for a package and its immediate local modules.
