# Frontend Page Rename & API Alignment Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Rename the frontend's AppContext tab concept to Page, update all type and API layers to use `entity_id` / `library_root`, and align component props with the refactored backend API.

**Architecture:** Rename `Tab` → `Page` in `AppContext` and propagate the rename through all consumers; update `frontend/src/types/index.ts` and HTTP clients so that `doc_id` becomes `entity_id` and `projectRoot` becomes `libraryRoot`; keep the generic `Tabs` UI component unchanged since it is unrelated to AppContext Page state.

**Tech Stack:** React 19, TypeScript 6, Vite 8, vitest, @testing-library/react.

## Global Constraints

- Components use `export default function ComponentName()` for page-level components.
- Cross-directory imports MUST use `@/` alias; same-directory imports MAY use `./`.
- Use `import type` for type-only imports; group imports as std → third-party → project separated by blank lines.
- Run `cd frontend && npx tsc --noEmit` after edits.
- Run `cd frontend && npm run test` before claiming a task passes.
- Run `cd frontend && npm run lint` before final task.
- Commit each task independently.

---

## File Structure

### Modified files (grouped by responsibility)

- **Global state**
  - `frontend/src/context/AppContext.tsx` — Rename `Tab` → `Page`, `openTabs` → `openPages`, `activeTabId` → `activePageId`, `openTab` → `openPage`, `closeTab` → `closePage`, `setActiveTabId` → `setActivePageId`; remove legacy `projectRoot` / `setProjectRoot`.

- **Types**
  - `frontend/src/types/index.ts` — Rename `DocumentEntry.doc_id` → `entity_id`; `MoleculeRecord.source_doc` → `source_entity_id` if used.

- **HTTP clients**
  - `frontend/src/api/http/library.ts` — `doc_id` → `entity_id` body keys.
  - `frontend/src/api/http/project.ts` — `doc_id` → `entity_id`; `projectRoot` → `libraryRoot`.
  - `frontend/src/api/http/ingest_queue.ts` — `doc_id` → `entity_id`; `project_root` → `library_root`.
  - `frontend/src/api/http/pdf.ts` — `doc_id` → `entity_id`; `projectRoot` → `libraryRoot`.
  - `frontend/src/api/http/kb.ts` — `project_root` → `library_root`; `doc_id` → `entity_id`.
  - `frontend/src/api/http/detection_cache.ts` — `projectRoot` → `libraryRoot`; `doc_id`/`docId` → `entity_id`/`entityId`.
  - `frontend/src/api/http/result_pane.ts` — `doc_id`/`docId` → `entity_id`/`entityId`; `projectRoot` → `libraryRoot`.
  - `frontend/src/api/http/molecule.ts` — `projectRoot` → `libraryRoot`.
  - `frontend/src/api/http/molecule_admin.ts` — `projectRoot` → `libraryRoot`.
  - `frontend/src/api/http/agent.ts` — `project_root` → `library_root`.
  - `frontend/src/api/http/notes.ts` — `projectRoot` → `libraryRoot`.

- **Services**
  - `frontend/src/services/pdfService.ts` — `projectRoot`/`project_root`/`doc_id`/`docId` → `libraryRoot`/`library_root`/`entity_id`/`entityId`.

- **Components / hooks**
  - `frontend/src/App.tsx` — consume `openPages`/`activePageId`/`closePage`.
  - `frontend/src/components/project/TabBar.tsx` — rename props/vars to Page terminology.
  - `frontend/src/hooks/useIngestNotifications.ts` — `projectRoot` → `libraryRoot`; `task.doc_id` → `task.entity_id`.
  - `frontend/src/hooks/useMoleculeLibrary.ts` — `projectRoot` → `libraryRoot`.
  - `frontend/src/components/project/pdf/usePdfViewer.ts` — `projectRoot` → `libraryRoot`; `doc.doc_id` → `doc.entity_id`.
  - `frontend/src/components/project/pdf/useIngestPipeline.ts` — `projectRoot` → `libraryRoot`; `t.doc_id` → `t.entity_id`.
  - `frontend/src/components/project/PdfViewer.tsx` — `doc.doc_id` → `doc.entity_id`.
  - `frontend/src/components/project/ProcessingQueue.tsx` — `task.doc_id` → `task.entity_id`.
  - `frontend/src/components/workspace/Workspace.tsx` — `doc.doc_id` → `doc.entity_id`.
  - `frontend/src/components/discover/SearchTab.tsx` — `md.doc_id` → `md.entity_id`.
  - `frontend/src/components/settings/DetectionCacheCard.tsx` — `projectRoot` → `libraryRoot`.
  - `frontend/src/components/settings/CacheTab.tsx` — `projectRoot` prop → `libraryRoot`.
  - `frontend/src/components/settings/StorageSection.tsx` — `projectRoot` → `libraryRoot`.
  - `frontend/src/components/settings/SettingsTabs.tsx` — `projectRoot` prop → `libraryRoot`.
  - `frontend/src/components/settings/SettingsPage.tsx` — `projectRoot` → `libraryRoot`.
  - `frontend/src/components/molecule/MoleculeAnalysisPanel.tsx` — `projectRoot` prop → `libraryRoot`.
  - `frontend/src/components/molecule/analysis/AnalyticsTab.tsx` — `projectRoot` prop → `libraryRoot`.
  - `frontend/src/components/sar/CliffsTab.tsx` — `projectRoot` prop → `libraryRoot`.
  - `frontend/src/components/settings/AIModelsSection.tsx` — rename local `type Tab` to `type SettingsSection` to avoid collision with global `Page`.

- **Tests**
  - `frontend/src/utils/__tests__/errors.test.ts` — `context.doc_id` → `context.entity_id`.
  - `frontend/src/api/http/__tests__/kb.test.ts` — mock data `doc_id` → `entity_id`.
  - `frontend/src/components/project/__tests__/IngestLogPanel.test.tsx` — `doc_id` → `entity_id`.
  - `frontend/src/context/__tests__/AppContext.test.tsx` (new) — verify Page state works.

---

## Task Decomposition

### Task 1: Rename AppContext `Tab` → `Page`

**Files:**
- Modify: `frontend/src/context/AppContext.tsx`
- Test: `frontend/src/context/__tests__/AppContext.test.tsx` (new)

**Interfaces:**
- Produces: `Page` interface, `openPages`, `activePageId`, `openPage`, `closePage`, `setActivePageId`

- [ ] **Step 1: Write the failing test**

```tsx
import { renderHook, act } from '@testing-library/react'
import { AppProvider, useAppContext } from './AppContext'

function wrapper({ children }: { children: React.ReactNode }) {
  return <AppProvider>{children}</AppProvider>
}

describe('AppContext Page state', () => {
  it('opens a page', () => {
    const { result } = renderHook(() => useAppContext(), { wrapper })
    const doc = {
      entity_id: 'e1',
      title: 'Paper',
      file_name: 'paper.pdf',
      page_count: 1,
      status: 'ready',
      created_at: '',
    }
    act(() => {
      result.current.openPage({
        type: 'pdf',
        title: 'Paper',
        doc,
        libraryRoot: '/lib',
      })
    })
    expect(result.current.openPages).toHaveLength(1)
    expect(result.current.openPages[0].title).toBe('Paper')
    expect(result.current.activePageId).toBe(result.current.openPages[0].id)
  })
})
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd frontend && npx vitest run src/context/__tests__/AppContext.test.tsx`
Expected: FAIL (openPage not defined)

- [ ] **Step 3: Write minimal implementation**

Edit `frontend/src/context/AppContext.tsx`:

1. Replace `Tab` interface with `Page`:

```tsx
// ============================================================================
// Page — 标签栏打开的文件/视图（原 Tab，避免与 Tag 混淆）
// ============================================================================

export interface Page {
  id: string
  type: 'pdf' | 'markdown'
  title: string
  doc: DocumentEntry
  libraryRoot: string
}

let _pageIdSeq = 0
function nextPageId(): string {
  _pageIdSeq += 1
  return `page-${_pageIdSeq}-${Date.now()}`
}
```

2. Update `AppState`:

```tsx
interface AppState {
  /** Unified library root directory */
  libraryRoot: string
  /** Set library root (persists to localStorage) */
  setLibraryRoot: (root: string) => void
  /** Active collection filter (null = show all) */
  activeCollectionId: string | null
  /** Set active collection filter */
  setActiveCollectionId: (id: string | null) => void
  /** 通过全局文件树选中的待打开文件 */
  activeFile: ActiveFile | null
  /** 设置待打开文件（ProjectView 消费后应置空） */
  setActiveFile: (file: ActiveFile | null) => void

  // --- 标签栏（Page） ---
  /** 所有打开的 Page（不含固定的 Project tab） */
  openPages: Page[]
  /** 当前激活的 Page ID。null = Project tab 激活（显示路由内容） */
  activePageId: string | null
  /** 打开一个文件 Page。如果已存在则激活它 */
  openPage: (page: Omit<Page, 'id'>) => void
  /** 关闭一个 Page。如果关闭的是激活 Page，自动激活相邻 Page */
  closePage: (pageId: string) => void
  /** 激活指定 Page。传 null 切回 Project tab */
  setActivePageId: (pageId: string | null) => void

  /** Files panel (Library + Groups) collapsed in left rail */
  libraryPanelCollapsed: boolean
  /** Toggle files panel visibility, persisted to localStorage */
  setLibraryPanelCollapsed: (collapsed: boolean) => void
}
```

3. Remove `projectRoot` / `setProjectRoot` state and callbacks.

4. Update hook implementation:

```tsx
  const [openPages, setOpenPages] = useState<Page[]>([])
  const [activePageId, setActivePageId] = useState<string | null>(null)

  const setLibraryRoot = useCallback((root: string) => {
    const cleaned = cleanWindowsPath(root)
    try {
      localStorage.setItem(STORAGE_KEY, cleaned)
    } catch (e) {
      console.warn('[AppContext] localStorage quota exceeded:', e)
    }
    setLibraryRootState(cleaned)
    setOpenPages([])
    setActivePageId(null)
  }, [])

  const openPage = useCallback((page: Omit<Page, 'id'>) => {
    const pages = openPages
    const existing = pages.find(
      p => p.type === page.type && p.doc.entity_id === page.doc.entity_id
    )
    const newId = nextPageId()

    if (existing) {
      setActivePageId(existing.id)
    } else {
      const newPage: Page = { ...page, id: newId }
      setOpenPages([...pages, newPage])
      setActivePageId(newId)
    }
  }, [openPages])

  const closePage = useCallback((pageId: string) => {
    setOpenPages(prev => {
      const idx = prev.findIndex(p => p.id === pageId)
      if (idx === -1) return prev
      const next = prev.filter(p => p.id !== pageId)

      setActivePageId(current => {
        if (current !== pageId) return current
        if (next.length === 0) return null
        const newActive = next[Math.min(idx, next.length - 1)]
        return newActive.id
      })

      return next
    })
  }, [])
```

5. Update provider value:

```tsx
    <AppContext.Provider value={{
      libraryRoot, setLibraryRoot,
      activeCollectionId, setActiveCollectionId,
      activeFile, setActiveFile,
      openPages, activePageId, openPage, closePage, setActivePageId,
      libraryPanelCollapsed, setLibraryPanelCollapsed,
    }}>
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd frontend && npx vitest run src/context/__tests__/AppContext.test.tsx`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add frontend/src/context/AppContext.tsx frontend/src/context/__tests__/AppContext.test.tsx
git commit -m "refactor(frontend): rename AppContext Tab to Page"
```

---

### Task 2: Update `frontend/src/types/index.ts`

**Files:**
- Modify: `frontend/src/types/index.ts`
- Test: typecheck

**Interfaces:**
- Produces: `DocumentEntry.entity_id`

- [ ] **Step 1: Write the failing test**

Run: `cd frontend && npx tsc --noEmit`
Expected: FAIL after AppContext change (DocumentEntry lacks entity_id)

- [ ] **Step 2: Run test to verify it fails**

(See above)

- [ ] **Step 3: Write minimal implementation**

Edit `frontend/src/types/index.ts`:

```ts
export interface DocumentEntry {
  entity_id: string
  title: string
  file_name: string
  page_count: number
  status: string
  created_at: string
}
```

If `MoleculeRecord` has `source_doc`, rename to `source_entity_id`.

- [ ] **Step 4: Run test to verify it passes**

Run: `cd frontend && npx tsc --noEmit`
Expected: PASS (may still fail in consumers)

- [ ] **Step 5: Commit**

```bash
git add frontend/src/types/index.ts
git commit -m "refactor(types): rename DocumentEntry.doc_id to entity_id"
```

---

### Task 3: Update HTTP client layer

**Files:**
- Modify: `frontend/src/api/http/library.ts`
- Modify: `frontend/src/api/http/project.ts`
- Modify: `frontend/src/api/http/ingest_queue.ts`
- Modify: `frontend/src/api/http/pdf.ts`
- Modify: `frontend/src/api/http/kb.ts`
- Modify: `frontend/src/api/http/detection_cache.ts`
- Modify: `frontend/src/api/http/result_pane.ts`
- Modify: `frontend/src/api/http/molecule.ts`
- Modify: `frontend/src/api/http/molecule_admin.ts`
- Modify: `frontend/src/api/http/agent.ts`
- Modify: `frontend/src/api/http/notes.ts`
- Test: existing HTTP client tests

**Interfaces:**
- Produces: functions and body keys using `entity_id` / `library_root` / `libraryRoot`

- [ ] **Step 1: Write the failing test**

Run: `cd frontend && npx tsc --noEmit`
Expected: FAIL in HTTP clients referencing old keys

- [ ] **Step 2: Run test to verify it fails**

(See above)

- [ ] **Step 3: Write minimal implementation**

Run mechanical replacements across `frontend/src/api/http/`:

```bash
cd frontend/src/api/http
sed -i 's/doc_id/entity_id/g; s/docId/entityId/g; s/project_root/library_root/g; s/projectRoot/libraryRoot/g' \
  library.ts project.ts ingest_queue.ts pdf.ts kb.ts detection_cache.ts result_pane.ts molecule.ts molecule_admin.ts agent.ts notes.ts
```

Then manually review the renamed interfaces. Example verified snippet in `library.ts`:

```ts
export interface EntityInfo {
  entity_id: string
  title: string
  file_name: string
  page_count: number
  status: string
  created_at: string
}

export async function deleteDocument(
  entityId: string
): Promise<{ success: boolean }> {
  return invokeWithError(() =>
    httpPost('/api/v1/library/documents/delete', { entity_id: entityId })
  )
}
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd frontend && npx vitest run src/api/http/`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add frontend/src/api/http/
git commit -m "refactor(frontend): align HTTP clients with entity_id/library_root API"
```

---

### Task 4: Update components and hooks consuming AppContext

**Files:**
- Modify: `frontend/src/App.tsx`
- Modify: `frontend/src/components/project/TabBar.tsx`
- Modify: `frontend/src/hooks/useIngestNotifications.ts`
- Modify: `frontend/src/hooks/useMoleculeLibrary.ts`
- Modify: `frontend/src/components/project/pdf/usePdfViewer.ts`
- Modify: `frontend/src/components/project/pdf/useIngestPipeline.ts`
- Modify: `frontend/src/components/project/PdfViewer.tsx`
- Modify: `frontend/src/components/project/ProcessingQueue.tsx`
- Modify: `frontend/src/components/workspace/Workspace.tsx`
- Modify: `frontend/src/components/discover/SearchTab.tsx`
- Modify: `frontend/src/components/settings/*`
- Modify: `frontend/src/components/molecule/*`
- Modify: `frontend/src/components/sar/CliffsTab.tsx`
- Modify: `frontend/src/services/pdfService.ts`
- Test: `cd frontend && npx tsc --noEmit`

**Interfaces:**
- Consumes: `Page`, `openPages`, `activePageId`, `openPage`, `closePage`, `setActivePageId`, `entity_id`, `libraryRoot`

- [ ] **Step 1: Write the failing test**

Run: `cd frontend && npx tsc --noEmit`
Expected: FAIL in multiple components

- [ ] **Step 2: Run test to verify it fails**

(See above)

- [ ] **Step 3: Write minimal implementation**

Run mechanical renames across components and hooks:

```bash
cd frontend/src
# AppContext Page state consumers
sed -i 's/openTabs/openPages/g; s/activeTabId/activePageId/g; s/openTab/openPage/g; s/closeTab/closePage/g; s/setActiveTabId/setActivePageId/g' \
  App.tsx components/project/TabBar.tsx

# doc_id -> entity_id and projectRoot -> libraryRoot everywhere
sed -i 's/\.doc_id/.entity_id/g; s/projectRoot/libraryRoot/g' \
  hooks/useIngestNotifications.ts \
  hooks/useMoleculeLibrary.ts \
  components/project/pdf/usePdfViewer.ts \
  components/project/pdf/useIngestPipeline.ts \
  components/project/PdfViewer.tsx \
  components/project/ProcessingQueue.tsx \
  components/workspace/Workspace.tsx \
  components/discover/SearchTab.tsx \
  components/settings/DetectionCacheCard.tsx \
  components/settings/CacheTab.tsx \
  components/settings/StorageSection.tsx \
  components/settings/SettingsTabs.tsx \
  components/settings/SettingsPage.tsx \
  components/molecule/MoleculeAnalysisPanel.tsx \
  components/molecule/analysis/AnalyticsTab.tsx \
  components/sar/CliffsTab.tsx \
  services/pdfService.ts
```

Then manually fix `components/settings/AIModelsSection.tsx` local type to avoid collision with global `Page`:

```ts
type SettingsSection = 'llm' | 'vlm' | 'ocr'
```

Run a verification grep:

```bash
grep -R "\.doc_id\|openTabs\|activeTabId\|openTab\|closeTab\|setActiveTabId\|projectRoot" \
  frontend/src/App.tsx frontend/src/components frontend/src/hooks frontend/src/services || echo "clean"
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd frontend && npx tsc --noEmit`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add frontend/src/App.tsx frontend/src/components/ frontend/src/hooks/ frontend/src/services/pdfService.ts
git commit -m "refactor(frontend): update components for Page state and entity_id"
```

---

### Task 5: Update frontend tests

**Files:**
- Modify: `frontend/src/utils/__tests__/errors.test.ts`
- Modify: `frontend/src/api/http/__tests__/kb.test.ts`
- Modify: `frontend/src/components/project/__tests__/IngestLogPanel.test.tsx`
- Test: `cd frontend && npm run test`

**Interfaces:**
- Produces: tests passing with new field names

- [ ] **Step 1: Write the failing test**

Run: `cd frontend && npm run test`
Expected: FAIL

- [ ] **Step 2: Run test to verify it fails**

(See above)

- [ ] **Step 3: Write minimal implementation**

Edit each test file:
- `errors.test.ts`: `context.doc_id` → `context.entity_id`
- `kb.test.ts`: mock data `doc_id` → `entity_id`
- `IngestLogPanel.test.tsx`: `doc_id` → `entity_id`

- [ ] **Step 4: Run test to verify it passes**

Run: `cd frontend && npm run test`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add frontend/src/utils/__tests__/errors.test.ts frontend/src/api/http/__tests__/kb.test.ts frontend/src/components/project/__tests__/IngestLogPanel.test.tsx
git commit -m "test(frontend): update tests for entity_id and Page rename"
```

---

### Task 6: Final typecheck and lint

**Files:**
- All modified frontend files

- [ ] **Step 1: Run typecheck**

Run: `cd frontend && npx tsc --noEmit`
Expected: no errors

- [ ] **Step 2: Run tests**

Run: `cd frontend && npm run test`
Expected: PASS

- [ ] **Step 3: Run lint**

Run: `cd frontend && npm run lint`
Expected: no errors

- [ ] **Step 4: Commit**

```bash
git commit -m "chore(frontend): typecheck, test, and lint after Page rename" --allow-empty
```

---

## Self-Review Checklist

- [ ] **Spec coverage:** Every frontend section of the spec maps to at least one task.
- [ ] **Placeholder scan:** No TBD, TODO, or vague steps remain.
- [ ] **Type consistency:** `Page` is used everywhere in AppContext; no `Tab` remains except the generic UI component.
- [ ] **API consistency:** All HTTP clients use `entity_id` and `library_root`/`libraryRoot`.
- [ ] **Test coverage:** `npm run test` passes.

---

## Execution Handoff

**Plan complete and saved to `docs/superpowers/plans/2026-07-08-frontend-page-rename.md`.**

Two execution options:

1. **Subagent-Driven (recommended)** - Dispatch a fresh subagent per task, review between tasks, fast iteration.
2. **Inline Execution** - Execute tasks in this session using executing-plans, batch execution with checkpoints.

Which approach?
