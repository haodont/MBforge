# Documentation Index

The repository has three documentation layers:

| Layer | Purpose | Update policy |
|---|---|---|
| [`wiki/`](wiki/README.md) | Long-term engineering knowledge | Keep current with code |
| [`api/`](api/README.md) | HTTP contracts and API conventions | Update with schema/route changes |
| [`plans/`](plans/) | Active implementation designs | Update until completed; then archive |
| [`adr/`](adr/) | Architecture decisions | Preserve history; add status notes |

Historical audits, research, reviews, and implementation plans are in
[`archive/`](archive/README.md). They are context, not current API or product
requirements.

## Entry points

| Need | Document |
|---|---|
| Product and installation | [../README.md](../README.md) |
| AI coding rules | [../AGENTS.md](../AGENTS.md) |
| Session architecture notes | [../CLAUDE.md](../CLAUDE.md) |
| Contribution workflow | [../CONTRIBUTING.md](../CONTRIBUTING.md) |
| Current priorities | [../TODO/INDEX.md](../TODO/INDEX.md) |
| Third-party attribution | [REFERENCES.md](REFERENCES.md) |

## Canonical technical pages

- [Architecture and engineering rules](wiki/architecture.md)
- [Pipeline](wiki/pipeline.md)
- [Real scanned-PDF benchmark](wiki/real-pdf-benchmark.md)
- [Operations, errors, and diagnostics](wiki/operations.md)
- [Development workflow](wiki/workflow.md)
- [API reference](api/README.md)
- [Open Knowledge Format adaptation](wiki/okf.md)

The old `docs/specs/`, `docs/architecture/`, `PROJECT_MANAGEMENT.md`, and
`VERSION_CONTROL.md` paths are compatibility pages only. New links should use
`wiki/` and `api/`.
