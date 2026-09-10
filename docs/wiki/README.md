# MBForge Development Wiki

This directory contains the current, long-lived engineering knowledge base.
Keep pages short, link to code instead of copying implementation, and update a
page in the same change that changes its contract. API contracts live in
[`../api/`](../api/); immutable decisions live in [`../adr/`](../adr/).

## Core pages

| Topic | Page |
|---|---|
| Architecture, paths, code style | [architecture.md](architecture.md) |
| PDF pipeline | [pipeline.md](pipeline.md) |
| Runtime, errors, diagnostics | [operations.md](operations.md) |
| Work, branches, releases | [workflow.md](workflow.md) |
| Open Knowledge Format adaptation | [okf.md](okf.md) |

## Maintenance rules

- Code and tests are authoritative; dated numbers and snapshots do not belong
  in current pages unless they have a clear verification source.
- Public endpoint, schema, or field changes update [`../api/`](../api/) and the
  relevant code tests.
- Storage, module-boundary, compatibility, and security changes update the
  relevant wiki page and an ADR.
- Audits, research, and completed plans belong in [`../archive/`](../archive/)
  or remain explicitly marked as drafts.
