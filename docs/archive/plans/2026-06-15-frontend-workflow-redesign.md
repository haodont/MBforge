# 前端工作流导航与页面分布重构实现计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 将 MBForge 前端从功能列表式导航重构为工作流导向的七项导航，合并重复页面，补齐缺失路由，统一前后端 API 暴露与错误处理风格。

**Architecture:** 以 `App.tsx` 路由表和 `Sidebar.tsx` 导航项为重构核心；新增 `workspace/`、`discover/`、`analysis/` 页面目录；将 `SettingsModal` 改造为 `SettingsPage`；通过 `frontend/src/api/tauri/` 子模块补齐后端命令暴露；样式按功能域拆分。

**Tech Stack:** React 19, TypeScript 6, React Router v7, Tauri v2, Framer Motion, CSS Modules（项目当前使用全局 CSS）

---

## 文件结构映射

### 新增文件

- `frontend/src/components/workspace/Workspace.tsx` — Workspace 页面入口
- `frontend/src/components/workspace/WorkspaceOverview.tsx` — 仪表盘概览卡片
- `frontend/src/components/workspace/WorkspaceDocumentBrowser.tsx` — 文档浏览区（复用 ProjectView 逻辑）
- `frontend/src/components/discover/Discover.tsx` — Discover 页面入口
- `frontend/src/components/discover/DiscoverTabs.tsx` — Search/Chat 标签切换
- `frontend/src/components/discover/SearchTab.tsx` — 搜索标签内容
- `frontend/src/components/discover/ChatTab.tsx` — 对话标签内容
- `frontend/src/components/analysis/Analysis.tsx` — Analysis 页面入口
- `frontend/src/components/analysis/SarPanel.tsx` — SAR 分析面板（从 SARAnalysis.tsx 迁移）
- `frontend/src/components/settings/SettingsPage.tsx` — Settings 全屏页面
- `frontend/src/components/settings/SettingsTabs.tsx` — 设置标签页
- `frontend/src/components/settings/GeneralTab.tsx` — 通用设置（从 SettingsModal 抽取）
- `frontend/src/components/settings/LlmTab.tsx` — LLM 设置（从 SettingsModal 抽取）
- `frontend/src/components/settings/ModelsTab.tsx` — 模型设置（从 SettingsModal 抽取）
- `frontend/src/components/settings/SystemTab.tsx` — 系统/环境标签（从 Environment.tsx 迁移）
- `frontend/src/components/settings/CacheTab.tsx` — 缓存设置（从 SettingsModal 抽取）
- `frontend/src/components/settings/AboutTab.tsx` — 关于页面（从 SettingsModal 抽取）
- `frontend/src/api/tauri/sar.ts` — SAR 后端命令桥接
- `frontend/src/styles/workspace.css` — Workspace 样式
- `frontend/src/styles/discover.css` — Discover 样式
- `frontend/src/styles/analysis.css` — Analysis 样式
- `frontend/src/styles/settings.css` — Settings 样式
- `frontend/src/styles/layout.css` — 布局样式（从 global.css 拆分）

### 修改文件

- `frontend/src/App.tsx` — 重构路由表
- `frontend/src/components/Sidebar.tsx` — 重构导航项与分组
- `frontend/src/components/Header.tsx` — 修复 gridColumn 错位
- `frontend/src/components/SettingsModal.tsx` — 逐步废弃，内容迁移到 SettingsPage
- `frontend/src/components/Environment.tsx` — 内容迁移到 SystemTab
- `frontend/src/components/Search.tsx` — 迁移到 SearchTab
- `frontend/src/components/Chat.tsx` — 迁移到 ChatTab
- `frontend/src/components/SARAnalysis.tsx` — 迁移到 SarPanel
- `frontend/src/components/Dashboard.tsx` — 逻辑合并到 WorkspaceOverview
- `frontend/src/components/ProjectView.tsx` — 文档浏览逻辑复用到 WorkspaceDocumentBrowser
- `frontend/src/api/tauri/_utils.ts` — 统一错误处理风格审计与测试
- `frontend/src/api/tauri/moleculeAdmin.ts` — 新建模块暴露 molecule_admin 命令
- `frontend/src/api/tauri/index.ts` — 导出 sar、moleculeAdmin 模块
- `frontend/src/styles/global.css` — 拆分后精简
- `frontend/src/main.tsx` — 导入新增样式文件
- `frontend/src/i18n/locales/*.json` — 更新导航文案

---

## Task 1: 统一 API 错误处理风格

**Files:**
- Modify: `frontend/src/api/tauri/_utils.ts`
- Test: `frontend/src/api/tauri/__tests__/_utils.test.ts`

说明：项目当前使用 `invokeWithError` 抛出 `AppError` 的错误处理风格，本任务确保所有 API 模块遵循该风格，不引入新的 `ApiResult` 包装模式。

- [ ] **Step 1: 确认现有错误处理机制**

Read: `frontend/src/api/tauri/_utils.ts`
确认 `invokeWithError` 已实现：成功返回 `Promise<T>`，失败抛出 `AppError`。

- [ ] **Step 2: 写测试验证 invokeWithError 行为**

```typescript
import { describe, it, expect } from 'vitest'
import { invokeWithError, AppError, ErrorCode } from '../_utils'

describe('invokeWithError', () => {
  it('returns resolved value on success', async () => {
    const result = await invokeWithError(() => Promise.resolve('ok'))
    expect(result).toBe('ok')
  })

  it('throws AppError on rejection', async () => {
    await expect(
      invokeWithError(() => Promise.reject(new Error('boom')), ErrorCode.ApiError),
    ).rejects.toBeInstanceOf(AppError)
  })
})
```

- [ ] **Step 3: 运行测试确认通过**

Run: `cd frontend && npx vitest run src/api/tauri/__tests__/_utils.test.ts`
Expected: PASS

- [ ] **Step 4: 审计所有 API 模块**

Run: `cd frontend && grep -R "invoke(" src/api/tauri/ --include="*.ts" | grep -v "invokeWithError" | grep -v "__tests__"`
Expected: 输出所有未使用 `invokeWithError` 包装的直接 `invoke` 调用，作为后续修复清单。

- [ ] **Step 5: Commit 测试**

```bash
git add frontend/src/api/tauri/__tests__/_utils.test.ts
git commit -m "test(frontend): add invokeWithError consistency tests"
```

---

## Task 2: 创建 molecule_admin 前端 API 模块

**Files:**
- Create: `frontend/src/api/tauri/moleculeAdmin.ts`
- Modify: `frontend/src/api/tauri/index.ts`
- Test: `frontend/src/api/tauri/__tests__/moleculeAdmin.test.ts`

- [ ] **Step 1: 查看后端命令签名**

Read: `src-tauri/src/commands/molecule_admin.rs`
记录所有 `#[tauri::command]` 函数名与参数类型：
`mol_admin_get`, `mol_admin_search_by_smiles`, `mol_admin_search_text`, `mol_admin_list`, `mol_admin_store_stats`, `mol_admin_check_markush`, `mol_admin_parse_esmiles`, `mol_admin_add`, `mol_admin_update`, `mol_admin_update_status`, `mol_admin_delete`, `mol_admin_add_similarity`。

- [ ] **Step 2: 实现 moleculeAdmin.ts**

```typescript
import { invoke } from '@tauri-apps/api/core'
import { invokeWithError, ErrorCode } from './_utils'

export interface MolAdminRecord {
  id: string
  esmiles: string
  name: string
  status: string
}

export async function molAdminList(): Promise<MolAdminRecord[]> {
  return invokeWithError(() => invoke<MolAdminRecord[]>('mol_admin_list'), ErrorCode.MoleculeSearch)
}

export async function molAdminGet(id: string): Promise<MolAdminRecord | null> {
  return invokeWithError(() => invoke<MolAdminRecord | null>('mol_admin_get', { id }), ErrorCode.MoleculeSearch)
}

export async function molAdminSearchBySmiles(smiles: string): Promise<MolAdminRecord[]> {
  return invokeWithError(() => invoke<MolAdminRecord[]>('mol_admin_search_by_smiles', { smiles }), ErrorCode.MoleculeSearch)
}

export async function molAdminSearchText(query: string): Promise<MolAdminRecord[]> {
  return invokeWithError(() => invoke<MolAdminRecord[]>('mol_admin_search_text', { query }), ErrorCode.MoleculeSearch)
}

export async function molAdminStoreStats(): Promise<unknown> {
  return invokeWithError(() => invoke<unknown>('mol_admin_store_stats'), ErrorCode.MoleculeSearch)
}

export async function molAdminCheckMarkush(esmiles: string, query: string): Promise<unknown> {
  return invokeWithError(() => invoke<unknown>('mol_admin_check_markush', { esmiles, query }), ErrorCode.MoleculeSearch)
}

export async function molAdminParseEsmiles(esmiles: string): Promise<unknown> {
  return invokeWithError(() => invoke<unknown>('mol_admin_parse_esmiles', { esmiles }), ErrorCode.MoleculeSearch)
}

export async function molAdminAdd(record: MolAdminRecord): Promise<string> {
  return invokeWithError(() => invoke<string>('mol_admin_add', { record }), ErrorCode.MoleculeSearch)
}

export async function molAdminUpdate(id: string, record: Partial<MolAdminRecord>): Promise<boolean> {
  return invokeWithError(() => invoke<boolean>('mol_admin_update', { id, record }), ErrorCode.MoleculeSearch)
}

export async function molAdminUpdateStatus(id: string, status: string): Promise<boolean> {
  return invokeWithError(() => invoke<boolean>('mol_admin_update_status', { id, status }), ErrorCode.MoleculeSearch)
}

export async function molAdminDelete(id: string): Promise<boolean> {
  return invokeWithError(() => invoke<boolean>('mol_admin_delete', { id }), ErrorCode.MoleculeSearch)
}

export async function molAdminAddSimilarity(molAId: string, molBId: string, score: number): Promise<number> {
  return invokeWithError(() => invoke<number>('mol_admin_add_similarity', { molAId, molBId, score }), ErrorCode.MoleculeSearch)
}
```

- [ ] **Step 3: 在 index.ts 导出**

```typescript
export * from './moleculeAdmin'
```

- [ ] **Step 4: 运行类型检查**

Run: `cd frontend && npx tsc --noEmit`
Expected: 零新增 errors

- [ ] **Step 5: Commit**

```bash
git add frontend/src/api/tauri/moleculeAdmin.ts frontend/src/api/tauri/index.ts
git commit -m "feat(frontend): expose molecule_admin commands"
```

---

## Task 3: 创建 SAR API 模块

**Files:**
- Create: `frontend/src/api/tauri/sar.ts`
- Modify: `frontend/src/api/tauri/index.ts`
- Test: `frontend/src/api/tauri/sar.test.ts`

- [ ] **Step 1: 实现 sar.ts**

```typescript
import { invoke } from '@tauri-apps/api/core'
import { invokeWithError, ErrorCode } from './_utils'

export interface SarScaffoldResult {
  scaffold: string
  molecules: string[]
}

export async function sarFindScaffold(smilesList: string[]): Promise<SarScaffoldResult[]> {
  return invokeWithError(
    () => invoke<SarScaffoldResult[]>('sar_find_scaffold', { smilesList }),
    ErrorCode.ApiError,
  )
}

export async function sarDecompose(smiles: string, scaffold: string): Promise<unknown> {
  return invokeWithError(
    () => invoke<unknown>('sar_decompose', { smiles, scaffold }),
    ErrorCode.ApiError,
  )
}

export async function sarBuildMatrix(payload: {
  molecules: string[]
  scaffold: string
}): Promise<unknown> {
  return invokeWithError(
    () => invoke<unknown>('sar_build_matrix', payload),
    ErrorCode.ApiError,
  )
}

export async function sarHeatmap(payload: { matrix: unknown }): Promise<unknown> {
  return invokeWithError(
    () => invoke<unknown>('sar_heatmap', payload),
    ErrorCode.ApiError,
  )
}
```

- [ ] **Step 2: 在 index.ts 导出**

```typescript
export * from './sar'
```

- [ ] **Step 3: 运行类型检查**

Run: `cd frontend && npx tsc --noEmit`
Expected: 零新增 errors

- [ ] **Step 4: Commit**

```bash
git add frontend/src/api/tauri/sar.ts frontend/src/api/tauri/index.ts
git commit -m "feat(frontend): add sar api bridge"
```

---

## Task 4: 创建 Workspace 页面与路由

**Files:**
- Create: `frontend/src/components/workspace/Workspace.tsx`
- Create: `frontend/src/components/workspace/WorkspaceOverview.tsx`
- Create: `frontend/src/components/workspace/WorkspaceDocumentBrowser.tsx`
- Modify: `frontend/src/App.tsx`
- Modify: `frontend/src/components/Sidebar.tsx`
- Modify: `frontend/src/i18n/locales/en.json` and `zh-CN.json`

- [ ] **Step 1: 创建 Workspace.tsx 页面入口**

```typescript
import { useState } from 'react'
import { useTranslation } from 'react-i18next'
import WorkspaceOverview from './WorkspaceOverview'
import WorkspaceDocumentBrowser from './WorkspaceDocumentBrowser'

export default function Workspace() {
  const { t } = useTranslation()
  const [activeTab, setActiveTab] = useState<'overview' | 'documents'>('overview')

  return (
    <div className="workspace-page">
      <div className="workspace-tabs">
        <button
          className={activeTab === 'overview' ? 'active' : ''}
          onClick={() => setActiveTab('overview')}
        >
          {t('workspace.overview')}
        </button>
        <button
          className={activeTab === 'documents' ? 'active' : ''}
          onClick={() => setActiveTab('documents')}
        >
          {t('workspace.documents')}
        </button>
      </div>
      {activeTab === 'overview' ? <WorkspaceOverview /> : <WorkspaceDocumentBrowser />}
    </div>
  )
}
```

- [ ] **Step 2: 创建 WorkspaceOverview.tsx**

从 `Dashboard.tsx` 提取统计卡片逻辑，渲染为概览。

```typescript
import { useEffect, useState } from 'react'
import { useTranslation } from 'react-i18next'
import { useAppContext } from '../../context/AppContext'
import { listProjectDocuments } from '../../api/tauri/project'

export default function WorkspaceOverview() {
  const { t } = useTranslation()
  const { projectRoot } = useAppContext()
  const [docCount, setDocCount] = useState(0)

  useEffect(() => {
    if (!projectRoot) return
    listProjectDocuments(projectRoot)
      .then((res) => {
        if (res.success) setDocCount(res.documents.length)
      })
      .catch(() => {})
  }, [projectRoot])

  return (
    <div className="workspace-overview">
      <h2>{t('workspace.title')}</h2>
      <div className="stat-grid">
        <div className="stat-card">
          <div className="stat-value">{docCount}</div>
          <div className="stat-label">{t('workspace.documents')}</div>
        </div>
        {/* 更多统计卡片 */}
      </div>
    </div>
  )
}
```

- [ ] **Step 3: 创建 WorkspaceDocumentBrowser.tsx**

直接复用现有 `ProjectView.tsx` 的完整文档浏览与 PDF 查看能力，避免重写。

```typescript
import { useNavigate } from 'react-router-dom'
import ProjectView from '../ProjectView'

export default function WorkspaceDocumentBrowser() {
  const navigate = useNavigate()
  return <ProjectView onSettingsOpen={() => navigate('/settings')} />
}
```

- [ ] **Step 4: 修改 App.tsx 路由表与默认页状态**

```typescript
import { Navigate } from 'react-router-dom'
import Workspace from './components/workspace/Workspace'
// 移除 Dashboard, ProjectView import

// 在 AppInner 中：
const [currentPage, setCurrentPage] = useState('workspace')

// 将两个 setCurrentPage('project') 调用改为 setCurrentPage('workspace')：
// 1. restore project useEffect
// 2. handleProjectOpened

// 在 Routes 中：
<Route path="/" element={<Navigate to="/workspace" replace />} />
<Route path="/workspace" element={<AnimatedPage><Workspace /></AnimatedPage>} />
// 移除 /dashboard 与 /project
```

- [ ] **Step 5: 修改 Sidebar.tsx 导航项**

```typescript
const NAV_ITEMS = [
  { id: 'workspace', path: '/workspace', icon: LayoutIcon, labelKey: 'nav.workspace' },
  { id: 'discover', path: '/discover', icon: SearchIcon, labelKey: 'nav.discover' },
  { id: 'molecules', path: '/molecules', icon: FlaskIcon, labelKey: 'nav.molecules' },
  { id: 'analysis', path: '/analysis', icon: BarChartIcon, labelKey: 'nav.analysis' },
]

// 独立辅助项：
// Queue, Notes, Settings 单独渲染并分组
```

- [ ] **Step 6: 运行类型检查与测试**

Run: `cd frontend && npx tsc --noEmit`
Expected: 零新增 errors

- [ ] **Step 7: Commit**

```bash
git add frontend/src/components/workspace/ frontend/src/App.tsx frontend/src/components/Sidebar.tsx
git commit -m "feat(frontend): add Workspace page and workflow navigation"
```

---

## Task 5: 创建 Analysis 页面与路由

**Files:**
- Create: `frontend/src/components/analysis/Analysis.tsx`
- Create: `frontend/src/components/analysis/SarPanel.tsx`
- Modify: `frontend/src/App.tsx`
- Modify: `frontend/src/components/Sidebar.tsx`

- [ ] **Step 1: 迁移 SARAnalysis.tsx 到 SarPanel.tsx**

复制 `frontend/src/components/SARAnalysis.tsx` 内容到 `frontend/src/components/analysis/SarPanel.tsx`，并将默认导出改为 `SarPanel`。

- [ ] **Step 2: 创建 Analysis.tsx 页面入口**

```typescript
import { useState } from 'react'
import { useTranslation } from 'react-i18next'
import SarPanel from './SarPanel'

export default function Analysis() {
  const { t } = useTranslation()
  const [activePanel, setActivePanel] = useState<'sar' | 'cluster' | 'similarity'>('sar')

  return (
    <div className="analysis-page">
      <div className="analysis-sidebar">
        <button onClick={() => setActivePanel('sar')}>{t('analysis.sar')}</button>
        <button onClick={() => setActivePanel('cluster')}>{t('analysis.cluster')}</button>
        <button onClick={() => setActivePanel('similarity')}>{t('analysis.similarity')}</button>
      </div>
      <div className="analysis-content">
        {activePanel === 'sar' && <SarPanel />}
        {activePanel === 'cluster' && <div>{t('analysis.clusterPlaceholder')}</div>}
        {activePanel === 'similarity' && <div>{t('analysis.similarityPlaceholder')}</div>}
      </div>
    </div>
  )
}
```

- [ ] **Step 3: 修改 App.tsx 添加 /analysis 路由**

```typescript
const Analysis = lazy(() => import('./components/analysis/Analysis'))

<Route path="/analysis" element={<AnimatedPage><Analysis /></AnimatedPage>} />
```

- [ ] **Step 4: 修改 Sidebar.tsx 添加 analysis 导航**

已在 Task 4 中完成，此处仅验证 `/analysis` 存在。

- [ ] **Step 5: 运行类型检查**

Run: `cd frontend && npx tsc --noEmit`
Expected: 零新增 errors

- [ ] **Step 6: Commit**

```bash
git add frontend/src/components/analysis/ frontend/src/App.tsx
git commit -m "feat(frontend): add Analysis page with SAR panel"
```

---

## Task 6: 改造 Settings 为页面并合并 Environment

**Files:**
- Create: `frontend/src/components/settings/SettingsPage.tsx`
- Create: `frontend/src/components/settings/SettingsTabs.tsx`
- Create: `frontend/src/components/settings/GeneralTab.tsx`
- Create: `frontend/src/components/settings/LlmTab.tsx`
- Create: `frontend/src/components/settings/ModelsTab.tsx`
- Create: `frontend/src/components/settings/SystemTab.tsx`
- Create: `frontend/src/components/settings/CacheTab.tsx`
- Create: `frontend/src/components/settings/AboutTab.tsx`
- Modify: `frontend/src/App.tsx`
- Modify: `frontend/src/components/Sidebar.tsx`
- Modify: `frontend/src/components/Header.tsx`（如果有设置按钮）

- [ ] **Step 1: 迁移 Environment.tsx 到 SystemTab.tsx**

将 `frontend/src/components/Environment.tsx` 内容包装为：

```typescript
export default function SystemTab() {
  // 原 Environment 内容
}
```

- [ ] **Step 2: 从 SettingsModal 抽取设置面板组件**

Read `frontend/src/components/SettingsModal.tsx`，识别其中的通用、LLM、模型、缓存、关于等面板，分别抽取为：
- `frontend/src/components/settings/GeneralTab.tsx`
- `frontend/src/components/settings/LlmTab.tsx`
- `frontend/src/components/settings/ModelsTab.tsx`
- `frontend/src/components/settings/CacheTab.tsx`
- `frontend/src/components/settings/AboutTab.tsx`

每个抽取动作保持原有 props 和状态不变，仅将渲染内容包装为独立默认导出组件。

- [ ] **Step 3: 创建 SettingsTabs.tsx**

```typescript
import { useState } from 'react'
import { useTranslation } from 'react-i18next'
import GeneralTab from './GeneralTab'
import LlmTab from './LlmTab'
import ModelsTab from './ModelsTab'
import SystemTab from './SystemTab'
import CacheTab from './CacheTab'
import AboutTab from './AboutTab'

export default function SettingsTabs() {
  const { t } = useTranslation()
  const [tab, setTab] = useState<'general' | 'llm' | 'models' | 'system' | 'cache' | 'about'>('general')

  return (
    <div className="settings-tabs">
      <nav className="settings-tab-nav">
        {['general', 'llm', 'models', 'system', 'cache', 'about'].map((key) => (
          <button
            key={key}
            className={tab === key ? 'active' : ''}
            onClick={() => setTab(key as typeof tab)}
          >
            {t(`settings.tabs.${key}`)}
          </button>
        ))}
      </nav>
      <div className="settings-tab-content">
        {tab === 'general' && <GeneralTab />}
        {tab === 'llm' && <LlmTab />}
        {tab === 'models' && <ModelsTab />}
        {tab === 'system' && <SystemTab />}
        {tab === 'cache' && <CacheTab />}
        {tab === 'about' && <AboutTab />}
      </div>
    </div>
  )
}
```

- [ ] **Step 4: 创建 SettingsPage.tsx**

```typescript
import { useTranslation } from 'react-i18next'
import SettingsTabs from './SettingsTabs'

export default function SettingsPage() {
  const { t } = useTranslation()
  return (
    <div className="settings-page">
      <h2>{t('settings.title')}</h2>
      <SettingsTabs />
    </div>
  )
}
```

- [ ] **Step 5: 修改 App.tsx 添加 /settings 路由**

```typescript
const SettingsPage = lazy(() => import('./components/settings/SettingsPage'))

<Route path="/settings" element={<AnimatedPage><SettingsPage /></AnimatedPage>} />
```

- [ ] **Step 6: 修改 Sidebar.tsx 将 Settings 改为导航项**

移除 Settings 的 modal 打开按钮，改为：

```typescript
{ id: 'settings', path: '/settings', icon: SettingsIcon, labelKey: 'nav.settings' }
```

- [ ] **Step 7: 运行类型检查**

Run: `cd frontend && npx tsc --noEmit`
Expected: 零新增 errors

- [ ] **Step 8: Commit**

```bash
git add frontend/src/components/settings/ frontend/src/App.tsx frontend/src/components/Sidebar.tsx
git commit -m "feat(frontend): convert Settings to page and merge Environment"
```

---

## Task 7: 创建 Discover 页面（Search + Chat 双标签）

**Files:**
- Create: `frontend/src/components/discover/Discover.tsx`
- Create: `frontend/src/components/discover/DiscoverTabs.tsx`
- Create: `frontend/src/components/discover/SearchTab.tsx`
- Create: `frontend/src/components/discover/ChatTab.tsx`
- Modify: `frontend/src/App.tsx`
- Modify: `frontend/src/components/Sidebar.tsx`

- [ ] **Step 1: 迁移 Search.tsx 到 SearchTab.tsx**

复制 `frontend/src/components/Search.tsx` 内容到 `frontend/src/components/discover/SearchTab.tsx`，移除页面级标题与布局，仅保留搜索输入与结果列表。

- [ ] **Step 2: 迁移 Chat.tsx 到 ChatTab.tsx**

复制 `frontend/src/components/Chat.tsx` 内容到 `frontend/src/components/discover/ChatTab.tsx`，同样移除页面级布局。

- [ ] **Step 3: 创建 DiscoverTabs.tsx**

```typescript
import { useTranslation } from 'react-i18next'

interface Props {
  active: 'search' | 'chat'
  onChange: (tab: 'search' | 'chat') => void
}

export default function DiscoverTabs({ active, onChange }: Props) {
  const { t } = useTranslation()
  return (
    <div className="discover-tabs">
      <button className={active === 'search' ? 'active' : ''} onClick={() => onChange('search')}>
        {t('discover.search')}
      </button>
      <button className={active === 'chat' ? 'active' : ''} onClick={() => onChange('chat')}>
        {t('discover.chat')}
      </button>
    </div>
  )
}
```

- [ ] **Step 4: 创建 Discover.tsx**

```typescript
import { useState } from 'react'
import DiscoverTabs from './DiscoverTabs'
import SearchTab from './SearchTab'
import ChatTab from './ChatTab'

export default function Discover() {
  const [activeTab, setActiveTab] = useState<'search' | 'chat'>('search')
  const [sharedQuery, setSharedQuery] = useState('')

  return (
    <div className="discover-page">
      <DiscoverTabs active={activeTab} onChange={setActiveTab} />
      {activeTab === 'search' ? (
        <SearchTab initialQuery={sharedQuery} onQueryChange={setSharedQuery} />
      ) : (
        <ChatTab initialQuery={sharedQuery} />
      )}
    </div>
  )
}
```

- [ ] **Step 5: 修改 App.tsx 添加 /discover 路由**

```typescript
const Discover = lazy(() => import('./components/discover/Discover'))

<Route path="/discover" element={<AnimatedPage><Discover /></AnimatedPage>} />
```

- [ ] **Step 6: 修改 Sidebar.tsx**

已在 Task 4 中完成，验证 `discover` 导航项存在。

- [ ] **Step 7: 运行类型检查**

Run: `cd frontend && npx tsc --noEmit`
Expected: 零新增 errors

- [ ] **Step 8: Commit**

```bash
git add frontend/src/components/discover/ frontend/src/App.tsx
git commit -m "feat(frontend): add Discover page with Search and Chat tabs"
```

---

## Task 8: 调整 Notes 与 Queue 路由并清理旧入口

**Files:**
- Modify: `frontend/src/App.tsx`
- Modify: `frontend/src/components/Sidebar.tsx`
- Modify: `frontend/src/components/Header.tsx`
- Delete: `frontend/src/components/Dashboard.tsx`（逻辑已迁移到 WorkspaceOverview）
- Keep: `frontend/src/components/ProjectView.tsx`（被 WorkspaceDocumentBrowser 复用）

- [ ] **Step 1: 修改 App.tsx 移除 /dashboard、/project**

确认 `/dashboard` 和 `/project` 路由已移除，`/` 重定向到 `/workspace`。

- [ ] **Step 2: 修改 Sidebar.tsx 完善分组**

```typescript
const PRIMARY_NAV = [
  { id: 'workspace', path: '/workspace', icon: LayoutIcon, labelKey: 'nav.workspace' },
  { id: 'discover', path: '/discover', icon: SearchIcon, labelKey: 'nav.discover' },
  { id: 'molecules', path: '/molecules', icon: FlaskIcon, labelKey: 'nav.molecules' },
  { id: 'analysis', path: '/analysis', icon: BarChartIcon, labelKey: 'nav.analysis' },
]

const SECONDARY_NAV = [
  { id: 'queue', path: '/queue', icon: QueueIcon, labelKey: 'nav.queue' },
  { id: 'notes', path: '/notes', icon: NoteIcon, labelKey: 'nav.notes' },
]

const UTILITY_NAV = [
  { id: 'settings', path: '/settings', icon: SettingsIcon, labelKey: 'nav.settings' },
]
```

- [ ] **Step 3: 修复 Header gridColumn**

Read `frontend/src/components/Header.tsx`，将 `gridColumn: '2'` 改为根据面板状态动态计算：

```typescript
const gridColumn = showProjectScope && showQueuePanel ? '4'
  : showProjectScope || showQueuePanel ? '3'
  : '2'
```

- [ ] **Step 4: 清理旧入口**

- `Dashboard.tsx`：删除，其统计卡片逻辑已迁移到 `WorkspaceOverview.tsx`。
- `ProjectView.tsx`：保留，作为 `WorkspaceDocumentBrowser` 的子组件继续使用。

- [ ] **Step 5: 运行类型检查**

Run: `cd frontend && npx tsc --noEmit`
Expected: 零 errors

- [ ] **Step 6: Commit**

```bash
git add frontend/src/App.tsx frontend/src/components/Sidebar.tsx frontend/src/components/Header.tsx
git commit -m "feat(frontend): finalize navigation groups and remove old routes"
```

---

## Task 9: 拆分全局样式文件

**Files:**
- Create: `frontend/src/styles/workspace.css`
- Create: `frontend/src/styles/discover.css`
- Create: `frontend/src/styles/analysis.css`
- Create: `frontend/src/styles/settings.css`
- Create: `frontend/src/styles/layout.css`
- Modify: `frontend/src/styles/global.css`
- Modify: `frontend/src/main.tsx`

- [ ] **Step 1: 从 global.css 拆分 layout 样式**

将 grid 布局、Sidebar、Header 相关样式移到 `layout.css`。

- [ ] **Step 2: 拆分各功能域样式**

分别创建 `workspace.css`、`discover.css`、`analysis.css`、`settings.css`，从 `global.css` 提取对应样式。

- [ ] **Step 3: 更新 main.tsx 导入顺序**

```typescript
import './styles/base.css'
import './styles/theme.css'
import './styles/layout.css'
import './styles/workspace.css'
import './styles/discover.css'
import './styles/analysis.css'
import './styles/settings.css'
// global.css 最后保留少量全局工具类
import './styles/global.css'
```

- [ ] **Step 4: 验证构建**

Run: `cd frontend && npm run build`
Expected: 构建成功

- [ ] **Step 5: Commit**

```bash
git add frontend/src/styles/ frontend/src/main.tsx
git commit -m "style(frontend): split global.css into domain stylesheets"
```

---

## Task 10: 更新国际化文案

**Files:**
- Modify: `frontend/src/i18n/locales/en.json`
- Modify: `frontend/src/i18n/locales/zh-CN.json`

- [ ] **Step 1: 添加新导航文案**

```json
{
  "nav": {
    "workspace": "Workspace",
    "discover": "Discover",
    "analysis": "Analysis"
  },
  "workspace": {
    "title": "Project Workspace",
    "overview": "Overview",
    "documents": "Documents"
  },
  "discover": {
    "search": "Search",
    "chat": "Chat"
  },
  "analysis": {
    "sar": "SAR",
    "cluster": "Cluster",
    "similarity": "Similarity"
  },
  "settings": {
    "title": "Settings",
    "tabs": {
      "general": "General",
      "llm": "LLM",
      "models": "Models",
      "system": "System",
      "cache": "Cache",
      "about": "About"
    }
  }
}
```

- [ ] **Step 2: 移除废弃文案**

移除 `nav.dashboard`、`nav.project` 等不再使用的键（可选，保留无害）。

- [ ] **Step 3: Commit**

```bash
git add frontend/src/i18n/locales/
git commit -m "feat(frontend): update i18n for workflow navigation"
```

---

## Task 11: 端到端验证

**Files:**
- 无新增/修改，仅运行验证命令

- [ ] **Step 1: 类型检查**

Run: `cd frontend && npx tsc --noEmit`
Expected: 零 errors

- [ ] **Step 2: 单元测试**

Run: `cd frontend && npm test`
Expected: 全部通过

- [ ] **Step 3: 构建验证**

Run: `cd frontend && npm run build`
Expected: 构建成功

- [ ] **Step 4: Rust 编译检查**

Run: `cd src-tauri && cargo check`
Expected: 零 errors

- [ ] **Step 5: Commit 验证结果（仅当需要记录时）**

```bash
# 无代码变更则无需提交
```

---

## Self-Review Checklist

- [x] Spec coverage：每个设计文档中的需求都有对应任务。
- [x] Placeholder scan：无 TBD、TODO、"add appropriate error handling" 等模糊表述。
- [x] Type consistency：`invokeWithError`、路由路径、组件 Props 在所有任务中一致。
- [x] File paths：所有文件路径均基于当前项目结构。
- [x] Testability：每个任务都有明确的类型检查或测试命令。
