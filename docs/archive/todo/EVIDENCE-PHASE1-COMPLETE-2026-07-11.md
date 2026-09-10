# Evidence-Linked Molecular Infrastructure — Phase 1 Complete

> **COMPLETION RECORD** — historical sign-off (2026-07-11). For open work see [INDEX.md](INDEX.md). Paths/field names may lag current code.

> **Date**: 2026-07-11  
> **Status**: ✅ All 6 plan steps landed and verified  
> **Next**: bbox highlight on PDF viewer (follow-up)

---

## What Was Built

### Backend

**Core Infrastructure:**
- `src/mbforge/core/database.py`
  - Added `evidence` table (id, canonical_smiles, doc_id, page_idx, kind, bbox_pdf, confidence, crop_relpath, context_text, created_at)
  - SCHEMA_VERSION bumped 3→4
  - `_migrate_molecules_v3_to_v4` backfills `molecules.canonical_smiles` and mirrors rows from `molecule_detections` + `text_molecule_links` into `evidence` (figure/text kinds)
  - Migration is idempotent (tolerates already-v4 schemas)

- `src/mbforge/core/artifact.py` (NEW)
  - `ArtifactResolver` — single authority for paths under `library_root`
  - Methods: `source_pdf`, `reorganized_md`, `indexed_md`, `report_json`, `pages_dir`, `page_text`, `crops_dir`, `crop`
  - `legacy_crop` for back-compat reads (`.mbforge/crops/`)
  - Rejects path traversal with `InvalidDocIdError` / `PathTraversalError`

- `src/mbforge/routers/library.py`
  - `_resolve_doc_artifact` and `_resolve_crop_artifact` now thin wrappers over `ArtifactResolver`
  - Crop handler falls back to `.mbforge/crops/` for pre-migration libraries

**Pipeline Integration:**
- `src/mbforge/pipeline/extract_molecules.py`
  - New crop writes go to `storage/{doc_id}/crops/` via resolver

- `src/mbforge/pipeline/persist_molecules.py`
  - `persist_molecule_candidates` now upserts `molecules` row keyed by `canonical_smiles`
  - Inserts parallel figure-kind `evidence` row alongside existing `molecule_detections` row

- `src/mbforge/pipeline/organizer.py`
  - `register_molecules_from_text` adds text-kind `evidence` insert

**API Endpoints:**
- `src/mbforge/routers/molecule.py`
  - `GET /api/v1/molecule/list` attaches `evidence` (truncated to 50) and `evidence_total` to each item via batched SELECT
  - `POST /api/v1/molecule/evidence` (NEW) returns full evidence chain for a canonical SMILES
  - `crop_url` is server-built, matches existing `cropImageUrl` shape

**Migration Script:**
- `scripts/migrate_artifact_paths.py` (NEW)
  - Idempotent one-shot: moves legacy `.mbforge/crops/{doc_id}/*.png` to `storage/{doc_id}/crops/`
  - Updates `evidence.crop_relpath` and `molecule_detections.crop_relpath` in SQLite DB
  - Tolerant of missing tables

---

### Frontend

**Types:**
- `frontend/src/types/index.ts`
  - New `EvidenceItem` interface
  - `MoleculeRecord.evidence` and `MoleculeRecord.evidence_total` are optional fields (existing 19 callers unaffected)

**API Client:**
- `frontend/src/api/http/molecule_admin.ts`
  - `molAdminEvidence(projectRoot, canonicalSmiles)` POSTs to `/api/v1/molecule/evidence`

**Components:**
- `frontend/src/components/molecule/EvidencePanel.tsx` (NEW)
  - Vertical list of evidence rows
  - 48×48 thumbnail (figure kind), doc_id, page, confidence
  - "打开原文" button

- `frontend/src/components/molecule/MoleculeDetailPanel.tsx`
  - `BaseProps` gains optional `onOpenPdf`
  - Renders `EvidencePanel` after `ReadOnlyMeta` when evidence exists

- `frontend/src/components/molecule/MoleculeDetailDrawer.tsx`
  - `useAppContext().openTab` opens new PDF tab for clicked doc
  - Drawer closes on click

---

## Verification

**End-to-End Test:**
- `scripts/smoke_evidence.py` (NEW)
  - 10-step test: DB init, schema migration, persist, list, evidence endpoint, ArtifactResolver routing, legacy + canonical crop coexistence, migration script, path-traversal rejection
  - ✅ All 10 checks pass

**Lint:**
- `ruff check src/mbforge/ scripts/migrate_artifact_paths.py` — clean
- `tsc --noEmit` — no new errors in touched files

**Import Check:**
- `from mbforge.app import create_app` — ✅ 139 routes registered

---

## Plan Deviations (Worth Flagging)

### 1. Tests Directory Removed
**Plan assumption**: `tests/unit/core/test_database_schema.py` exists  
**Reality**: Entire `tests/` directory was removed in earlier migration  
**Impact**: Verification via pytest could not be run  
**Solution**: `scripts/smoke_evidence.py` covers same surface as runnable script

### 2. persist_molecule_candidates Did Not Write to molecules
**Plan assumption**: Function wrote per-detection rows to `molecules` that we'd change to canonical upserts  
**Reality**: It only wrote `molecule_detections`; `molecules` was only populated by admin router  
**Impact**: Actual change added `molecules` upsert (ON CONFLICT DO UPDATE) + parallel `evidence` row, leaving legacy `molecule_detections` intact  
**Why**: Preserves every existing reader of `molecule_detections`

### 3. Bbox Highlight on PDF Viewer
**Plan**: Click-through opens PDF at specific page + bbox highlight  
**Reality**: "打开原文" button opens doc tab in Workspace; page-number / bbox-aware deep-linking is out of scope  
**Why**: Existing `Tab` type has no page or bbox field; PDF viewer doesn't read URL params for either  
**Status**: Follow-up work

### 4. molecules.canonical_smiles UNIQUE Constraint
**Plan**: Make `canonical_smiles` UNIQUE/NOT NULL in schema  
**Reality**: NOT enforced in schema (application logic enforces via ON CONFLICT upsert)  
**Why**: Forcing UNIQUE would fail v3→v4 migration on real libraries with legacy duplicates, or require data-loss dedup pass  
**Status**: Future migration can add UNIQUE once all libraries are clean

---

## Files Changed

### Backend (Python)
- `src/mbforge/core/database.py` (schema + migration)
- `src/mbforge/core/artifact.py` (NEW)
- `src/mbforge/routers/library.py` (use ArtifactResolver)
- `src/mbforge/routers/molecule.py` (attach evidence + new endpoint)
- `src/mbforge/pipeline/extract_molecules.py` (new crop path)
- `src/mbforge/pipeline/persist_molecules.py` (upsert molecules + evidence)
- `src/mbforge/pipeline/organizer.py` (text evidence)
- `scripts/migrate_artifact_paths.py` (NEW)
- `scripts/smoke_evidence.py` (NEW)

### Frontend (TypeScript/React)
- `frontend/src/types/index.ts` (EvidenceItem)
- `frontend/src/api/http/molecule_admin.ts` (molAdminEvidence)
- `frontend/src/components/molecule/EvidencePanel.tsx` (NEW)
- `frontend/src/components/molecule/MoleculeDetailPanel.tsx` (render EvidencePanel)
- `frontend/src/components/molecule/MoleculeDetailDrawer.tsx` (openTab handler)

---

## Migration Path for Existing Libraries

### Automatic (on app startup)
1. DB schema v3→v4 migration runs automatically on first launch
2. `molecules.canonical_smiles` backfilled from `molecule_detections`
3. `evidence` rows mirrored from `molecule_detections` + `text_molecule_links`

### Manual (one-time admin task)
```bash
# Move legacy crops to new location + update DB paths
uv run python scripts/migrate_artifact_paths.py /path/to/library_root
```

**Idempotent**: Safe to run multiple times

---

## Known Limitations

1. **PDF bbox highlight**: "打开原文" opens doc tab but doesn't scroll to page or highlight bbox (follow-up)
2. **molecules.canonical_smiles not UNIQUE**: Application-enforced, not schema-enforced (future migration)
3. **Evidence truncation**: `/molecule/list` returns max 50 evidence items per molecule (call `/molecule/evidence` for full list)
4. **Legacy crop fallback**: Old libraries read from `.mbforge/crops/` until `migrate_artifact_paths.py` is run

---

## Testing Checklist

- [x] DB schema migration (v3→v4)
- [x] `ArtifactResolver` path routing
- [x] Legacy crop fallback
- [x] New crop writes to `storage/`
- [x] `molecules` upsert by canonical_smiles
- [x] `evidence` insert (figure + text kinds)
- [x] `/molecule/list` attaches evidence
- [x] `/molecule/evidence` returns full chain
- [x] Frontend `EvidencePanel` renders
- [x] "打开原文" opens doc tab
- [x] Path traversal rejection
- [x] Migration script idempotency

---

## Next Steps (Follow-Up Work)

### Short-Term (Week 3-4)
1. **PDF viewer deep-linking**
   - Add `page` and `bbox` fields to `Tab` type
   - Modify PDF viewer to accept URL params: `?page=5&bbox=100,200,300,400`
   - Update "打开原文" to pass page + bbox

2. **Evidence panel enhancements**
   - Pagination for molecules with >50 evidence items
   - Filter by kind (figure/text)
   - Sort by confidence/page

### Medium-Term (Week 5-6)
3. **Activity data extraction**
   - New `activities` table (IC50/Ki/EC50)
   - Link activities to evidence rows
   - Display in `EvidencePanel`

4. **Confidence transparency**
   - Show confidence distribution histogram
   - "High confidence only" filter in Molecule Library

### Long-Term (Phase 1+)
5. **Cross-document aggregation**
   - Same molecule in multiple docs → single `molecules` row with multiple `evidence` rows
   - "Appears in 5 documents" badge

6. **Evidence quality scoring**
   - Combine MolDet conf + MolScribe conf + context quality
   - Flag low-quality evidence for review

---

## Lessons Learned

### Edit Tool Auto-Repair Trap
**Pattern**: SWAP range auto-repair deletes lines that match content near (but outside) the SWAP range, treating them as restated keepers  
**Impact**: Multiple recovery passes needed on `database.py`, `library.py`, `extract_molecules.py`, `migrate_artifact_paths.py`, `MoleculeDetailDrawer.tsx`, `MoleculeDetailPanel.tsx`  
**Solution**: For complex multi-line edits (>20 lines, repeated structures), use Write instead of Edit  
**Memory updated**: Added to `.claude/memory/feedback-debugging.md`

### Plan-vs-Reality Gap
**Issue**: Plan referenced `tests/unit/core/test_database_schema.py` but entire `tests/` directory was removed in earlier migration  
**Impact**: Verification strategy had to shift to runnable smoke script  
**Takeaway**: Verify file existence before writing plan; don't assume directory structure from memory

### persist_molecule_candidates Misunderstanding
**Issue**: Plan assumed function wrote per-detection rows to `molecules`; in reality it only wrote `molecule_detections`  
**Impact**: Actual implementation added new upsert logic rather than modifying existing logic  
**Takeaway**: Read target function before planning structural changes

---

## Documentation Updates

- [x] Updated `TODO/INDEX.md` (R-11 marked RESOLVED 2026-07-11)
- [x] Updated `.claude/memory/feedback-debugging.md` (Edit tool trap pattern)
- [x] Created `TODO/EVIDENCE-PHASE1-COMPLETE.md` (this file)

---

**Status**: Phase 1 complete ✅  
**Next checkpoint**: Week 3-4 (Activity Extraction + PDF deep-linking)
