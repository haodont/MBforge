# Repo Restructure Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Restructure the MBForge repository into three top-level zones (`code/`, `plans/`, `docs/`) plus `reference/`, `configs/`, and `setup/`, per the approved design spec `docs/superpowers/specs/2026-06-24-repo-restructure-design.md`.

**Architecture:** Pure `git mv` reorganization — no behavior change. Every move preserves history. Files are grouped by destination zone; each commit is a logical zone. Archive (never delete) for plans ≥1 week untouched or visibly orphaned assets.

**Tech Stack:** `git`, `bash`, `uv`, `npm`, `cargo`. Verification: `cargo check`, `tsc --noEmit`, `ruff check`, `pytest`, `skills/doc-audit/scripts/scan_dead_refs.py`.

**Constraints (carry from spec):**
- All file moves use `git mv` to preserve history.
- Archive is append-only; never `rm -rf` archived content.
- `docs/superpowers/` path is preserved (auto-generated).
- `docs/specs/` keeps its 6 canonical specs + README (one file moves out).
- `AGENTS.md`, `CLAUDE.md`, `README.md`, `LICENSE`, `pyproject.toml`, `uv.lock`, `.env.template`, `.gitignore`, `.editorconfig` stay at root.

---

## Task 1: Scaffold target directories

**Files:** Create new empty directories (no source moves yet).

- [ ] **Step 1: Verify current state**

Run: `rtk git status --short`
Expected: clean tree or only pre-existing untracked/modified items; no moves done yet.

- [ ] **Step 2: Create target directories**

```bash
mkdir -p plans/archived
mkdir -p docs/research
mkdir -p docs/references/external
mkdir -p docs/plans
mkdir -p docs/audit
mkdir -p docs/diagrams
mkdir -p docs/archive
mkdir -p reference
mkdir -p configs
```

- [ ] **Step 3: Verify directories**

Run: `ls -d plans/archived docs/research docs/references/external docs/plans docs/audit docs/diagrams docs/archive reference configs`
Expected: all 9 paths printed.

- [ ] **Step 4: Commit scaffolding**

```bash
rtk git add plans/archived docs/research docs/references/external docs/plans docs/audit docs/diagrams docs/archive reference configs
rtk git commit -m "chore(struct): scaffold top-level dirs for 3-zone restructure"
```

---

## Task 2: Move `TODO/` files into `plans/` (active ones)

**Files:** Move 3 active items from `TODO/` to `plans/`.

- [ ] **Step 1: Move INDEX.md**

```bash
rtk git mv TODO/INDEX.md plans/INDEX.md
```

- [ ] **Step 2: Move 2026-06-22 plan**

```bash
rtk git mv TODO/2026-06-22-llm-extraction-paper-research.md plans/2026-06-22-llm-extraction-paper-research.md
```

- [ ] **Step 3: Move 2026-06-24 plan**

```bash
rtk git mv TODO/2026-06-24-zvec-python-sidecar-plan.md plans/2026-06-24-zvec-python-sidecar-plan.md
```

- [ ] **Step 4: Verify TODO/ has 2 files left (the ≥1-week ones)**

Run: `ls TODO/`
Expected: `2026-06-12-processing-queue-ux.md`, `project-scope-and-queue-plan.md`.

- [ ] **Step 5: Commit**

```bash
rtk git add -u
rtk git commit -m "refactor(struct): move active TODO/ items to plans/"
```

---

## Task 3: Archive ≥1-week untouched plans into `plans/archived/`

**Files:** Move 2 stale plans (12 days untouched).

- [ ] **Step 1: Archive 2026-06-12 plan**

```bash
rtk git mv TODO/2026-06-12-processing-queue-ux.md plans/archived/2026-06-12-processing-queue-ux.md
```

- [ ] **Step 2: Archive project-scope plan**

```bash
rtk git mv TODO/project-scope-and-queue-plan.md plans/archived/project-scope-and-queue-plan.md
```

- [ ] **Step 3: Verify TODO/ is empty**

Run: `ls -A TODO/`
Expected: empty output.

- [ ] **Step 4: Remove empty TODO/ dir**

```bash
rmdir TODO
```

- [ ] **Step 5: Verify plans/archived/ has 2 files**

Run: `ls plans/archived/`
Expected: 2 markdown files.

- [ ] **Step 6: Commit**

```bash
rtk git add -A
rtk git commit -m "chore(struct): archive 2 ≥1-week plans into plans/archived/"
```

---

## Task 4: Move `docs/` plans into `docs/plans/` and `plans/archived/`

**Files:** 2 plan files from `docs/` root.

- [ ] **Step 1: Move recent plan to docs/plans/**

```bash
rtk git mv docs/moldet-v2-optimization-plan.md docs/plans/moldet-v2-optimization.md
```

- [ ] **Step 2: Archive stale REFACTORING-PLAN (superseded by Phase 6) and pipeline-redesign (33d)**

```bash
rtk git mv docs/REFACTORING-PLAN.md plans/archived/refactoring-plan.md
rtk git mv docs/pipeline-redesign.md plans/archived/pipeline-redesign.md
```

- [ ] **Step 3: Verify docs/plans/ has 1 file**

Run: `ls docs/plans/`
Expected: `moldet-v2-optimization.md`.

- [ ] **Step 4: Verify plans/archived/ has 4 files total**

Run: `ls plans/archived/`
Expected: 4 markdown files.

- [ ] **Step 5: Commit**

```bash
rtk git add -A
rtk git commit -m "refactor(struct): split docs/ plans into docs/plans/ and plans/archived/"
```

---

## Task 5: Move `docs/` reference files into `docs/references/`

**Files:** 3 reference files from `docs/` root.

- [ ] **Step 1: Move TECH_STACK.md**

```bash
rtk git mv docs/TECH_STACK.md docs/references/tech-stack.md
```

- [ ] **Step 2: Move REFERENCES.md (becomes README index)**

```bash
rtk git mv docs/REFERENCES.md docs/references/README.md
```

- [ ] **Step 3: Move rig_api_surface.md**

```bash
rtk git mv docs/rig_api_surface.md docs/references/rig-api-surface.md
```

- [ ] **Step 4: Verify docs/references/ has 3 files (no external/ yet)**

Run: `ls docs/references/`
Expected: `README.md`, `rig-api-surface.md`, `tech-stack.md`.

- [ ] **Step 5: Commit**

```bash
rtk git add -A
rtk git commit -m "refactor(struct): move docs/ references into docs/references/"
```

---

## Task 6: Move `docs/` research files into `docs/research/`

**Files:** 2 research files.

- [ ] **Step 1: Move pageindex-research.md**

```bash
rtk git mv docs/pageindex-research.md docs/research/pageindex-research.md
```

- [ ] **Step 2: Move llm-chemical-extraction-reference.md (research, not canonical spec)**

```bash
rtk git mv docs/specs/llm-chemical-extraction-reference.md docs/research/llm-chemical-extraction-reference.md
```

- [ ] **Step 3: Move pdf-pipeline-test/ (research test fixtures)**

```bash
rtk git mv docs/pdf-pipeline-test docs/research/pdf-pipeline-test
```

- [ ] **Step 4: Verify docs/research/ has 2 files + 1 dir**

Run: `ls docs/research/`
Expected: `pageindex-research.md`, `llm-chemical-extraction-reference.md`, `pdf-pipeline-test/`.

- [ ] **Step 5: Verify docs/specs/ no longer has llm-chemical-extraction-reference.md**

Run: `ls docs/specs/`
Expected: 6 spec files + README (no llm-chemical-extraction-reference.md).

- [ ] **Step 6: Commit**

```bash
rtk git add -A
rtk git commit -m "refactor(struct): move research notes into docs/research/"
```

---

## Task 7: Move `docs/` diagrams into `docs/diagrams/` and archive HTML

**Files:** 2 drawio files + 1 HTML.

- [ ] **Step 1: Move structure.drawio**

```bash
rtk git mv docs/structure.drawio docs/diagrams/structure.drawio
```

- [ ] **Step 2: Move pdfIO.drawio**

```bash
rtk git mv docs/pdfIO.drawio docs/diagrams/pdfio.drawio
```

- [ ] **Step 3: Archive mbforge_introduction_v2.html (82K, 20d, no inbound links)**

```bash
rtk git mv docs/mbforge_introduction_v2.html docs/archive/intro-v2.html
```

- [ ] **Step 4: Verify docs/diagrams/ has 2 files**

Run: `ls docs/diagrams/`
Expected: `structure.drawio`, `pdfio.drawio`.

- [ ] **Step 5: Verify docs/archive/ has 1 file**

Run: `ls docs/archive/`
Expected: `intro-v2.html`.

- [ ] **Step 6: Commit**

```bash
rtk git add -A
rtk git commit -m "refactor(struct): move diagrams to docs/diagrams/, archive intro HTML"
```

---

## Task 8: Move `PDF_FRONTEND_API.md` into `docs/specs/`

**Files:** 1 root-level spec doc.

- [ ] **Step 1: Move PDF_FRONTEND_API.md**

```bash
rtk git mv PDF_FRONTEND_API.md docs/specs/pdf-frontend-api.md
```

- [ ] **Step 2: Verify root no longer has PDF_FRONTEND_API.md**

Run: `ls PDF_FRONTEND_API.md 2>&1`
Expected: "No such file or directory" error.

- [ ] **Step 3: Verify docs/specs/ has the file**

Run: `ls docs/specs/pdf-frontend-api.md`
Expected: file exists.

- [ ] **Step 4: Commit**

```bash
rtk git add -A
rtk git commit -m "refactor(struct): move PDF_FRONTEND_API.md to docs/specs/"
```

---

## Task 9: Move `CODE_REVIEW_REPORT.md` into `docs/audit/`

**Files:** 1 root-level audit report.

- [ ] **Step 1: Move CODE_REVIEW_REPORT.md**

```bash
rtk git mv CODE_REVIEW_REPORT.md docs/audit/code-review-report.md
```

- [ ] **Step 2: Verify**

Run: `ls docs/audit/`
Expected: `code-review-report.md`.

- [ ] **Step 3: Commit**

```bash
rtk git add -A
rtk git commit -m "refactor(struct): move CODE_REVIEW_REPORT.md to docs/audit/"
```

---

## Task 10: Move `constants.yaml` to `configs/` and update generator

**Files:** Move constants source-of-truth, update `scripts/generate_constants.py` if it hardcodes path.

- [ ] **Step 1: Check generator script for constants.yaml reference**

Run: `rtk grep -n "constants.yaml" scripts/generate_constants.py`
Expected: line(s) showing how the script locates the YAML.

- [ ] **Step 2: Move constants.yaml**

```bash
rtk git mv constants.yaml configs/constants.yaml
```

- [ ] **Step 3: Update generator script if it hardcodes root path**

If Step 1 found a hardcoded reference (e.g. `Path("constants.yaml")`), edit `scripts/generate_constants.py` to use `Path(__file__).parent.parent / "configs" / "constants.yaml"`. Otherwise skip.

Run: `rtk grep -n "constants.yaml" scripts/generate_constants.py`
Expected: reference now points to `configs/constants.yaml`.

- [ ] **Step 4: Verify configs/ has the file**

Run: `ls configs/constants.yaml`
Expected: file exists.

- [ ] **Step 5: Commit**

```bash
rtk git add -A
rtk git commit -m "refactor(struct): move constants.yaml to configs/, update generator path"
```

---

## Task 11: Move `ref/` scripts into `scripts/`

**Files:** 4 code helpers from `ref/`.

- [ ] **Step 1: Move migrate_to_rig.py**

```bash
rtk git mv ref/migrate_to_rig.py scripts/migrate_to_rig.py
```

- [ ] **Step 2: Move gen_closure_tools.py**

```bash
rtk git mv ref/gen_closure_tools.py scripts/gen_closure_tools.py
```

- [ ] **Step 3: Move pull-all.py**

```bash
rtk git mv ref/pull-all.py scripts/pull-all.py
```

- [ ] **Step 4: Move pull-all.ps1**

```bash
rtk git mv ref/pull-all.ps1 scripts/pull-all.ps1
```

- [ ] **Step 5: Verify scripts/ count**

Run: `ls scripts/`
Expected: 8 files (4 existing + 4 moved).

- [ ] **Step 6: Commit**

```bash
rtk git add -A
rtk git commit -m "refactor(struct): migrate ref/ code helpers into scripts/"
```

---

## Task 12: Move `ref/` external notes into `docs/references/external/`

**Files:** 1 index + 7 markdown notes.

- [ ] **Step 1: Move INDEX.md**

```bash
rtk git mv ref/INDEX.md docs/references/external-index.md
```

- [ ] **Step 2: Move 7 external notes**

```bash
rtk git mv ref/mineru-popo.md docs/references/external/mineru-popo.md
rtk git mv ref/molecode.md docs/references/external/molecode.md
rtk git mv ref/harness-systems.md docs/references/external/harness-systems.md
rtk git mv ref/harness-engineering.md docs/references/external/harness-engineering.md
rtk git mv ref/wiki-app-notes.md docs/references/external/wiki-app-notes.md
rtk git mv ref/chematic.md docs/references/external/chematic.md
rtk git mv ref/memvid.md docs/references/external/memvid.md
```

- [ ] **Step 3: Verify docs/references/external/ has 7 files**

Run: `ls docs/references/external/`
Expected: 7 markdown files.

- [ ] **Step 4: Verify docs/references/ has 4 root files + external/**

Run: `ls docs/references/`
Expected: `README.md`, `rig-api-surface.md`, `tech-stack.md`, `external-index.md`, `external/`.

- [ ] **Step 5: Commit**

```bash
rtk git add -A
rtk git commit -m "refactor(struct): move ref/ external notes to docs/references/"
```

---

## Task 13: Move `ref/` external materials into `reference/`

**Files:** 7 directories + 1 mhtml + 2 PDFs.

- [ ] **Step 1: Move 7 external dirs**

```bash
rtk git mv ref/literature reference/literature
rtk git mv ref/MolDetect reference/MolDetect
rtk git mv ref/PocketXMol reference/PocketXMol
rtk git mv ref/MoleCode reference/MoleCode
rtk git mv ref/chematic reference/chematic
rtk git mv ref/GESim reference/GESim
rtk git mv ref/paddleocr-vl-local reference/paddleocr-vl-local
```

- [ ] **Step 2: Move MolScribe (renamed)**

```bash
rtk git mv ref/MolScribe reference/MolScribe-ref
```

- [ ] **Step 3: Move 1 mhtml (renamed) + 2 PDFs**

```bash
rtk git mv "ref/PatSight - Streamlining Patent Analysis To Jump-Start Your Drug Discovery.mhtml" reference/PatSight-Streamlining-Patent-Analysis.mhtml
rtk git mv ref/CN120118069A.PDF reference/CN120118069A.PDF
rtk git mv ref/US20260027089A1.PDF reference/US20260027089A1.PDF
```

- [ ] **Step 4: Verify ref/ contents (will still have _test_gen.py until Task 15)**

Run: `ls -A ref/`
Expected: `_test_gen.py` only (cleaned up in Task 15). Do NOT `rmdir ref/` yet.

- [ ] **Step 5: Verify reference/ count**

Run: `ls reference/`
Expected: 8 directories + 3 files.

- [ ] **Step 6: Commit**

```bash
rtk git add -A
rtk git commit -m "refactor(struct): move ref/ external materials to reference/"
```

---

## Task 14: Move `setup/MolScribe/` into `reference/MolScribe-setup/`

**Files:** 1 untracked external model copy.

- [ ] **Step 1: Check git tracking status**

Run: `rtk git ls-files setup/MolScribe/ | head -3`
Expected: empty (it's untracked, see git status).

- [ ] **Step 2: Move directory (plain mv, not git mv since untracked)**

```bash
mv setup/MolScribe reference/MolScribe-setup
```

- [ ] **Step 3: Verify**

Run: `ls reference/`
Expected: includes `MolScribe-setup` and `MolScribe-ref`.

- [ ] **Step 4: No commit needed (untracked); status will show as new untracked under reference/**

Run: `rtk git status --short reference/`
Expected: `?? reference/MolScribe-setup/` (or similar untracked).

---

## Task 15: Delete dead files (`reasonix.toml`, `ref/_test_gen.py`)

**Files:** Remove 2 dead files.

- [ ] **Step 1: Verify ref/_test_gen.py is tracked**

Run: `rtk git ls-files ref/_test_gen.py`
Expected: shows the file (so we use `git rm`).

- [ ] **Step 2: git rm the tracked file**

```bash
rtk git rm ref/_test_gen.py
```

- [ ] **Step 3: Now ref/ should be empty; remove it**

Run: `ls -A ref/`
Expected: empty. Then:
```bash
rmdir ref
```

- [ ] **Step 4: Remove reasonix.toml (gitignored local file)**

```bash
rm -f reasonix.toml
```

- [ ] **Step 5: Verify both gone**

Run: `ls reasonix.toml 2>&1; ls ref 2>&1`
Expected: "No such file or directory" for both.

- [ ] **Step 6: Commit**

```bash
rtk git add -A
rtk git commit -m "chore(struct): delete dead files (_test_gen.py, reasonix.toml) and empty ref/"
```

---

## Task 16: Create `.claude/documentation-governance.md`

**Files:** Create governance doc codifying the rules.

- [ ] **Step 1: Write the governance doc**

Create `.claude/documentation-governance.md` with the following content:

```markdown
# Documentation Governance

**Last updated:** 2026-06-24

This file is the source of truth for "where does X go?" in the MBForge repository.

## Three-Zone Model

| Zone | Purpose | Path |
|---|---|---|
| **code/** | Sources that compile or run | `frontend/`, `src-tauri/`, `src/`, `tests/`, `scripts/` |
| **plans/** | Dated work-in-progress | `plans/INDEX.md`, `plans/YYYY-MM-DD-*.md` |
| **docs/** | Timeless reference | `docs/{specs,superpowers,research,references,plans,audit,diagrams,visuals,archive}/` |

Auxiliary: `reference/` (external materials only), `configs/` (cross-language source-of-truth configs), `setup/` (installer), `archived/` (deprecated subsystems).

## Archive Rules

- **A1** Plan ≥1 week untouched AND/OR superseded by merged code → `plans/archived/`
- **A2** Looks "inexplicably useless" (no inbound links + no recent edit + bulky/orphaned) → `docs/archive/`
- **A3** Old subsystems → `archived/{subsystem}/`
- **A4** Archive is append-only. Never delete archived files.

## Decision Tree: Where does X go?

| Artifact | Destination |
|---|---|
| Compiles/runs (TS, Rust, Python source) | `code/` (frontend/src-tauri/src/) |
| Code helper scripts (.py, .ps1, .sh) | `scripts/` |
| Cross-language source-of-truth config | `configs/` |
| Dated task plan (active) | `plans/YYYY-MM-DD-{topic}.md` |
| Stale plan (≥1 week) | `plans/archived/` |
| Canonical spec | `docs/specs/` |
| Auto-generated design plan | `docs/superpowers/` |
| One-off investigation | `docs/research/` |
| API/tech surface reference | `docs/references/` |
| External tool/model/library reference | `docs/references/external/` or `reference/` |
| Review/audit report | `docs/audit/` |
| DrawIO diagram | `docs/diagrams/` |
| HTML presentation | `docs/visuals/` |
| External materials (PDFs, models, libs) | `reference/` |
| Deprecated subsystem | `archived/{subsystem}/` |

## Enforcement

- `skills/doc-audit/scripts/scan_dead_refs.py` runs in CI to flag broken links after moves.
- PRs that move files should `git mv` (not `mv`) to preserve history.
- New top-level dirs must be approved via spec → plan → review cycle.
```

- [ ] **Step 2: Commit governance doc**

```bash
rtk git add .claude/documentation-governance.md
rtk git commit -m "docs(governance): codify 3-zone model + archive rules"
```

---

## Task 17: Update `AGENTS.md` "Key Directories" section

**Files:** Modify `AGENTS.md` lines 41-74 ("Key Directories" code block).

- [ ] **Step 1: Read current Key Directories section**

Run: `Read AGENTS.md offset 41 limit 35`
Expected: shows the current directory tree.

- [ ] **Step 2: Replace with new layout**

Edit `AGENTS.md`, replacing the code block at lines 41-74 with:

````markdown
## Key Directories

```
MBForge/
├── code/                          sources that compile/run
│   ├── frontend/                  React + Vite + TS app
│   ├── src-tauri/                 Rust workspace (5 crates + zvec-bindings)
│   ├── src/                       Python sidecar (FastAPI on port 18792)
│   ├── tests/                     cross-language tests
│   └── scripts/                   code helpers (git mv'd from ref/)
├── plans/                         dated work-in-progress
│   ├── INDEX.md                   master task board
│   └── archived/                  ≥1-week untouched plans
├── docs/                          timeless reference
│   ├── specs/                     canonical specs (esmiles, molecode, architecture, code-style, molecular-rep, pdf-frontend-api)
│   ├── superpowers/               auto-generated design plans (KEEP path)
│   ├── research/                  one-off investigations
│   ├── references/                tech-stack, API surface, external notes
│   ├── plans/                     design-level plans (vs dated task plans)
│   ├── audit/                     review reports
│   ├── diagrams/                  DrawIO files
│   ├── visuals/                   HTML presentations
│   └── archive/                   dead/legacy docs
├── reference/                     external materials only (PDFs, models, libs)
├── configs/                       cross-language source-of-truth configs (constants.yaml)
├── setup/                         installer scripts + modules
├── archived/                      deprecated subsystems (e.g. legacy agent code)
├── .claude/                       settings, hooks, skills, governance
└── (root)                         AGENTS.md, CLAUDE.md, README.md, LICENSE, .env.template, .gitignore, .editorconfig, pyproject.toml, uv.lock
```

See `.claude/documentation-governance.md` for the canonical "where does X go?" rules.
````

- [ ] **Step 3: Verify AGENTS.md renders correctly**

Run: `rtk grep -n "## Key Directories" AGENTS.md`
Expected: 1 match.

- [ ] **Step 4: Commit**

```bash
rtk git add AGENTS.md
rtk git commit -m "docs(agents): update Key Directories to 3-zone model"
```

---

## Task 18: Run link audit and fix broken refs

**Files:** Run scan + fix any broken links surfaced.

- [ ] **Step 1: Run doc-audit script**

Run: `python skills/doc-audit/scripts/scan_dead_refs.py` (or `uv run python ...` if script lives outside src/)
Expected: list of broken refs (if any).

- [ ] **Step 2: Triage findings**

For each broken link:
- If file moved: update path in the referring file.
- If file archived: replace with `(archived: see plans/archived/{file})`.
- If genuinely missing: flag for follow-up.

- [ ] **Step 3: Apply fixes**

Edit each referring file found in Step 2. Examples:
- `CLAUDE.md`: any reference to `docs/REFERENCES.md` → `docs/references/README.md`.
- `docs/specs/README.md`: any reference to `docs/TECH_STACK.md` → `docs/references/tech-stack.md`.
- `plans/2026-06-22-llm-extraction-paper-research.md`: any reference to old paths.

- [ ] **Step 4: Re-run audit to confirm 0 broken refs**

Run: `python skills/doc-audit/scripts/scan_dead_refs.py`
Expected: clean output (or only pre-existing intentional flags per the script's allowlist).

- [ ] **Step 5: Commit link fixes**

```bash
rtk git add -A
rtk git commit -m "docs(audit): fix broken refs surfaced by doc-audit after restructure"
```

---

## Task 19: Verification — code still compiles/lints/tests pass

**Files:** No file changes; verification commands only.

- [ ] **Step 1: Rust check**

Run: `cd src-tauri && cargo check 2>&1 | tail -20`
Expected: "Finished" line, no errors (warnings OK since suppressed by `.cargo/config.toml`).

- [ ] **Step 2: TypeScript check**

Run: `cd frontend && npx tsc --noEmit 2>&1 | tail -10`
Expected: clean output or only pre-existing warnings.

- [ ] **Step 3: Python lint**

Run: `uv run ruff check src/ 2>&1 | tail -10`
Expected: clean (or only pre-existing findings).

- [ ] **Step 4: Python format check**

Run: `uv run ruff format src/ --check 2>&1 | tail -10`
Expected: clean.

- [ ] **Step 5: Final status**

Run: `rtk git status`
Expected: only pre-existing untracked items (e.g. `setup/MolScribe/` if not yet moved, or `reference/MolScribe-setup/` after Task 14).

- [ ] **Step 6: Final log**

Run: `rtk git log --oneline origin/main..HEAD`
Expected: ~13-17 new commits corresponding to Tasks 1-18.

---

## Open Follow-ups (out of plan scope)

- Dedupe `reference/MolScribe-ref/` vs `reference/MolScribe-setup/` (single source of truth).
- Decide whether `setup/setup_molscribe.py` should symlink or copy `reference/MolScribe-setup/`.
- Remove `docs/visuals/` if it remains empty after this migration.
