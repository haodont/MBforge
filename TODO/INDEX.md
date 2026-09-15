# MBForge TODO index

This directory records active architecture and implementation plans.

## Current pipeline

`Extract ∥ Detection → Markdown → Patent` is the registered pipeline. Extract
and Detection publish independent run-scoped branch artifacts; Join validates
them and writes canonical `SourceEvidence` rows to SQLite. Link is removed from
the active path, and Persist remains unregistered pending redesign.

## Active plans

- [Source layout reorganization](../docs/plan-source-layout-reorganization.md)

## Conventions

- Treat `docs/wiki/pipeline.md` as the per-stage contract.
- Keep raw branch data and SQL source evidence separate from the shared
  `core.entities.molecule.Molecule` entity and inferred facts.
- `Molecule` is the only structure-bearing molecule domain object across
  detection normalization, correction, Markush handling, hydration, query,
  and future persistence. `ExtractionResult`/`DetectionSource` remain raw
  observations; `CompoundEntry` remains a document-level patent record.
- Cross-business-package imports use absolute `mbforge...` paths; relative
  imports are for a package and its immediate local modules.
