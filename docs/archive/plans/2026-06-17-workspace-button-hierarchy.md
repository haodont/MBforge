# Workspace 按钮层级重设计实现计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 将工作区顶部独立的「扫描」「索引」「分子扫描」三个按钮合并/重排为「同步文献」「检测分子结构」两个项目级主操作，并把设置入口弱化为图标。

**Architecture:** 在 `ProjectView` 层合并扫描与索引的 handler，用一个 `handleSync` 顺序执行扫描、enqueue、索引；`ProjectDashboard` 只负责展示两个主按钮和一个设置图标；所有用户文案通过 i18n key 集中管理。

**Tech Stack:** React 19 + TypeScript 6 + Vite 8 + react-i18next + Tauri IPC

---

## 文件结构

| 文件 |  responsibility  |
|------|------------------|
| `frontend/src/components/ProjectView.tsx` | 新增 `handleSync`，合并原 `handleScan` + `handleIndex`；管理同步阶段状态；向 `ProjectDashboard` 暴露新的回调与状态。 |
| `frontend/src/components/project/ProjectDashboard.tsx` | 渲染新的顶部按钮层级：同步文献、检测分子结构、设置图标；接收新的 props。 |
| `frontend/src/i18n/locales/zh-CN.json` | 新增/调整中文文案 key。 |
| `frontend/src/i18n/locales/en.json` | 同步新增/调整英文文案 key。 |

---

## Task 1: 合并 ProjectView 的扫描与索引逻辑

**Files:**
- Modify: `frontend/src/components/ProjectView.tsx`
- Test: `frontend/src/components/project/__tests__/ProcessingQueue.logs.test.tsx`（如存在 ProjectView 相关测试需同步更新，当前无直接测试）

- [ ] **Step 1: 新增同步相关状态**

在 `ProjectView` 组件内，把原来的 `isLoading`、`isIndexing` 合并为一个更语义化的同步状态：

```tsx
// 移除
// const [isLoading, setIsLoading] = useState(false)
// const [isIndexing, setIsIndexing] = useState(false)

// 新增
const [isSyncing, setIsSyncing] = useState(false)
const [syncStage, setSyncStage] = useState<'scanning' | 'indexing' | null>(null)
```

同时保留 `indexProgress`、`indexResult`、`scanWarnings`、`error` 的现有状态。

- [ ] **Step 2: 新增 handleSync 函数**

替换原来的 `handleScan` 和 `handleIndex`，新增 `handleSync`：

```tsx
const handleSync = async () => {
  if (!projectRoot) {
    setError(t('project.noProjectRoot'))
    return
  }
  setIsSyncing(true)
  setSyncStage('scanning')
  setError('')
  setScanWarnings([])
  setIndexResult(null)
  setIndexProgress(null)

  try {
    // 1. 扫描文件系统
    const scanResp = await scanProjectFiles(projectRoot)
    if (scanResp.documents) {
      setDocs(scanResp.documents)
    }
    setScanWarnings(scanResp.warnings ?? [])

    if (scanResp.documents.length === 0 && (scanResp.warnings ?? []).length === 0) {
      setError(t('project.noFilesFound', { papers: PAPERS_DIR, notes: NOTES_DIR }))
      setIsSyncing(false)
      setSyncStage(null)
      return
    }

    // 2. 将未处理文档加入队列
    void enqueueUnresolvedDocuments(projectRoot).catch(() => {})

    // 3. 建立向量索引
    setSyncStage('indexing')
    let total = 0
    const unlisten = await listen<{ stage: string; payload: Record<string, unknown> }>(EVT.DocProgress, (event) => {
      const payload = event.payload.payload
      const parser = (payload.parser as string) || ''
      if (parser.startsWith('indexing')) {
        const match = parser.match(/indexing\s+(\d+)\/(\d+)/)
        if (match) {
          const current = parseInt(match[1], 10)
          total = parseInt(match[2], 10)
          setIndexProgress({ file: parser, current, total })
        }
      }
    })

    const INDEX_TIMEOUT_MS = 5 * 60 * 1000
    try {
      const result: IndexResult = await Promise.race([
        indexProjectRust(projectRoot),
        new Promise<never>((_, reject) =>
          setTimeout(() => reject(new Error(t('project.indexTimeout'))), INDEX_TIMEOUT_MS)
        ),
      ])
      setIndexResult({ indexed: result.indexed, sections: result.sections })
      listProjectDocuments(projectRoot).then(r => { if (r.documents) setDocs(r.documents) })
    } catch (e) {
      const msg = String(e)
      if (msg.includes('ipc.localhost') || msg.includes('Failed to fetch') || msg.includes('ERR_CONNECTION_REFUSED')) {
        setError(t('project.indexEngineFailed'))
      } else if (msg.includes('索引超时') || msg.includes('Index timeout')) {
        setError(t('project.indexOperationTimeout'))
      } else {
        setError(msg)
      }
    } finally {
      unlisten()
      setIndexProgress(null)
    }
  } catch (e) {
    const msg = String(e)
    console.error('[ProjectView] Sync error:', msg)
    setError(msg.includes('not allowed') ? t('project.scanPermissionDenied') : t('project.scanFailed', { error: msg }))
  } finally {
    setIsSyncing(false)
    setSyncStage(null)
  }
}
```

- [ ] **Step 3: 删除 handleScan 与 handleIndex**

从 `ProjectView.tsx` 中移除 `handleScan` 和 `handleIndex` 函数定义。

- [ ] **Step 4: 更新传给 ProjectDashboard 的 props**

将：

```tsx
onScan={handleScan}
onIndex={handleIndex}
onMoldetScan={handleMoldetScan}
```

改为：

```tsx
onSync={handleSync}
onMoldetScan={handleMoldetScan}
```

同时把 `isLoading` 和 `isIndexing` 替换为 `isSyncing` + `syncStage`：

```tsx
<ProjectDashboard
  projectRoot={projectRoot}
  docs={docs}
  isSyncing={isSyncing}
  syncStage={syncStage}
  indexProgress={indexProgress}
  indexResult={indexResult}
  isMoldetScanning={isMoldetScanning}
  moldetProgress={moldetProgress}
  moldetResult={moldetResult}
  error={error}
  scanWarnings={scanWarnings}
  moleculeStats={moleculeStats}
  onSync={handleSync}
  onMoldetScan={handleMoldetScan}
  onOpenFile={handleOpenFile}
  onDismissError={() => setError('')}
  onDismissWarnings={() => setScanWarnings([])}
  onRefreshDocs={loadDocs}
/>
```

- [ ] **Step 5: Commit**

```bash
cd /c/Users/10954/Desktop/MBForge
git add frontend/src/components/ProjectView.tsx
git commit -m "refactor(frontend): merge scan and index into sync handler in ProjectView"
```

---

## Task 2: 调整 ProjectDashboard 顶部按钮层级

**Files:**
- Modify: `frontend/src/components/project/ProjectDashboard.tsx`

- [ ] **Step 1: 更新 Props 接口**

把：

```tsx
interface Props {
  projectRoot: string
  docs: DocumentEntry[]
  isLoading: boolean
  isIndexing: boolean
  indexProgress: IndexProgress | null
  // ...
  onScan: () => void
  onIndex: () => void
  onMoldetScan: () => void
  // ...
}
```

改为：

```tsx
interface Props {
  projectRoot: string
  docs: DocumentEntry[]
  isSyncing: boolean
  syncStage: 'scanning' | 'indexing' | null
  indexProgress: IndexProgress | null
  // ...
  onSync: () => void
  onMoldetScan: () => void
  // ...
}
```

- [ ] **Step 2: 解构新的 props**

在组件签名中：

```tsx
export default function ProjectDashboard({
  projectRoot,
  docs,
  isSyncing,
  syncStage,
  indexProgress,
  indexResult,
  isMoldetScanning,
  moldetProgress,
  moldetResult,
  error,
  scanWarnings,
  moleculeStats,
  onSync,
  onMoldetScan,
  onOpenFile,
  onDismissError,
  onDismissWarnings,
  onRefreshDocs,
}: Props) {
```

- [ ] **Step 3: 替换 header 中的按钮**

把原来的四个按钮：

```tsx
<div className="project-dashboard-actions">
  <Button ... onClick={onScan} ...>{isLoading ? t('project.scanning') : t('project.scan')}</Button>
  <Button ... onClick={onIndex} ...>{isIndexing ? t('project.indexing') : t('project.index')}</Button>
  <Button ... onClick={onMoldetScan} ...>{isMoldetScanning ? t('project.molScanning') : t('project.molScan')}</Button>
  <Button ... onClick={() => void navigate('/settings')}>{t('nav.settings')}</Button>
</div>
```

替换为：

```tsx
<div className="project-dashboard-actions">
  <Button
    variant="primary"
    size="sm"
    icon={<ExternalLinkIcon size={14} />}
    onClick={onSync}
    disabled={!projectRoot || isSyncing || isMoldetScanning}
    loading={isSyncing}
  >
    {isSyncing
      ? syncStage === 'scanning'
        ? t('project.syncScanning')
        : t('project.syncIndexing')
      : t('project.sync')}
  </Button>
  <Button
    variant="secondary"
    size="sm"
    icon={<SearchIcon size={14} />}
    onClick={onMoldetScan}
    disabled={!projectRoot || isSyncing || isMoldetScanning}
    loading={isMoldetScanning}
  >
    {isMoldetScanning ? t('project.detectingMolecules') : t('project.detectMolecules')}
  </Button>
  <IconButton
    title={t('nav.settings')}
    onClick={() => void navigate('/settings')}
  >
    <SettingsIcon size={18} />
  </IconButton>
</div>
```

注意需要引入 `IconButton`：

```tsx
import IconButton from '@/components/ui/IconButton'
```

- [ ] **Step 4: 更新进度条文案（可选但推荐）**

同步文献进行中的进度条标题改为使用 `project.syncIndexingProgress`：

```tsx
<BodyText size="sm" className="project-index-progress-title">
  {t('project.syncIndexingProgress', { current: indexProgress.current, total: indexProgress.total })}
</BodyText>
```

分子检测进度条标题保持使用 `project.scanningMoldet`。

- [ ] **Step 5: Commit**

```bash
cd /c/Users/10954/Desktop/MBForge
git add frontend/src/components/project/ProjectDashboard.tsx
git commit -m "ui(frontend): redesign ProjectDashboard header buttons"
```

---

## Task 3: 更新 i18n 文案

**Files:**
- Modify: `frontend/src/i18n/locales/zh-CN.json`
- Modify: `frontend/src/i18n/locales/en.json`

- [ ] **Step 1: 更新 zh-CN.json**

找到 `"project.scan"` 所在区域（约第 276-289 行），替换为新的 key 集合：

```json
  "project.sync": "同步文献",
  "project.syncing": "同步中…",
  "project.syncScanning": "扫描文件中…",
  "project.syncIndexing": "建立索引中…",
  "project.syncIndexingProgress": "正在建立索引 {{current}}/{{total}}",
  "project.detectMolecules": "检测分子结构",
  "project.detectingMolecules": "检测分子结构中…",
```

同时删除或保留以下旧 key（建议保留旧 key 避免其他未改动代码引用时报错，但本计划已同步替换所有引用，可删除）：

```json
  "project.scan": "扫描",
  "project.scanning": "扫描中...",
  "project.index": "索引",
  "project.indexing": "索引中...",
  "project.molScan": "分子扫描",
  "project.molScanning": "扫描分子中...",
  "project.indexingProgress": "正在索引 {{current}}/{{total}}",
```

如果担心遗漏引用，可先保留旧 key，仅新增新 key。

- [ ] **Step 2: 更新 en.json**

同步替换英文：

```json
  "project.sync": "Sync Literature",
  "project.syncing": "Syncing…",
  "project.syncScanning": "Scanning files…",
  "project.syncIndexing": "Building index…",
  "project.syncIndexingProgress": "Building index {{current}}/{{total}}",
  "project.detectMolecules": "Detect Molecule Structures",
  "project.detectingMolecules": "Detecting molecules…",
```

- [ ] **Step 3: Commit**

```bash
cd /c/Users/10954/Desktop/MBForge
git add frontend/src/i18n/locales/zh-CN.json frontend/src/i18n/locales/en.json
git commit -m "i18n: update workspace button labels for sync and molecule detection"
```

---

## Task 4: 类型检查与构建验证

**Files:**
- Verify: `frontend/src/components/ProjectView.tsx`
- Verify: `frontend/src/components/project/ProjectDashboard.tsx`
- Verify: `frontend/src/i18n/locales/zh-CN.json`
- Verify: `frontend/src/i18n/locales/en.json`

- [ ] **Step 1: 运行类型检查**

```bash
cd /c/Users/10954/Desktop/MBForge/frontend
npm run build
```

Expected: `tsc` 无类型错误，`vite build` 成功生成产物。

- [ ] **Step 2: 运行 lint（可选）**

```bash
cd /c/Users/10954/Desktop/MBForge/frontend
npm run lint
```

Expected: 无新增 lint 错误。

- [ ] **Step 3: Commit（如仅修复了 lint/format 问题）**

```bash
cd /c/Users/10954/Desktop/MBForge
git add -A
git commit -m "chore(frontend): typecheck and lint fixes"
```

---

## Self-Review

### Spec coverage

| Spec 要求 | 对应任务 |
|-----------|----------|
| 合并扫描与索引为「同步文献」 | Task 1 + Task 2 |
| 分子扫描改名为「检测分子结构」 | Task 2 + Task 3 |
| 设置入口弱化为图标 | Task 2 |
| 保持进度条与统计卡片 | Task 2（未移除） |
| 边界情况：无文件、无 PDF、引擎离线 | Task 1 保留原有错误处理 |
| 中英文文案更新 | Task 3 |

### Placeholder scan

计划中没有 TBD/TODO/"implement later"/"appropriate error handling" 等模糊表述。每个步骤都给出了具体代码或命令。

### Type consistency

- `ProjectDashboard` 接收 `isSyncing: boolean` 与 `syncStage: 'scanning' | 'indexing' | null`，与 `ProjectView` 中定义一致。
- 回调名统一为 `onSync` 和 `onMoldetScan`。
- i18n key 在代码和 JSON 文件中保持一致：`project.sync`、`project.syncScanning`、`project.syncIndexing`、`project.detectMolecules`、`project.detectingMolecules`。

### 风险点

- `ProjectDashboard` 中的 `ExternalLinkIcon` 当前用于「扫描」按钮；继续沿用它来代表「同步文献」在语义上略有偏差，可考虑替换为 `RefreshIcon` 或 `SyncIcon`（如果图标库中存在）。
- 原 `isLoading` 状态在 `DocumentList` 中用于显示骨架屏；合并为 `isSyncing` 后，文档列表的加载状态行为不变，因为 `ProjectDashboard` 会把 `isSyncing` 传给 `DocumentList` 的 `isLoading` prop。

---

## Execution Handoff

Plan complete and saved to `docs/superpowers/plans/2026-06-17-workspace-button-hierarchy.md`.

Two execution options:

1. **Subagent-Driven (recommended)** - Dispatch a fresh subagent per task, review between tasks, fast iteration.
2. **Inline Execution** - Execute tasks in this session using executing-plans, batch execution with checkpoints.

Which approach?
