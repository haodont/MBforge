# 分子库与 SAR 分析合并实施计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 将 `MoleculeLibrary` 与 `SARAnalysis` 重构为左右分栏的单一视图，左侧为可筛选/可多选的分子列表，右侧为基于选中集合实时刷新的 SAR + Analytics 分析面板。

**Architecture:** 前端以 `useMoleculeLibrary` hook 统一维护列表、过滤、分页、选择状态；`MoleculeLibrary` 主容器负责左右布局；右侧 `MoleculeAnalysisPanel` 接收 `analysisInput: MoleculeRecord[]` 并渲染 Overview / R-Group / Activity Cliffs / Analytics / Relations 五个 tab。Rust 后端复用现有命令，不做破坏性变更。

**Tech Stack:** React 19, TypeScript 6, Tauri v2 invoke, 现有 UI 组件库（`frontend/src/components/ui`, `frontend/src/components/icons`）。

---

## 0. 文件结构

### 新增文件

| 文件 | 职责 |
|------|------|
| `frontend/src/hooks/useMoleculeLibrary.ts` | 列表加载、过滤、排序、分页、选择、视图模式状态管理 |
| `frontend/src/hooks/useMoleculeAnalysis.ts` | 分析输入派生、active tab、选中集合到 SARSession 转换 |
| `frontend/src/components/molecule/MoleculeTable.tsx` | 表格视图（行选择、排序、分页） |
| `frontend/src/components/molecule/MoleculeCardGrid.tsx` | 卡片网格视图（可切换） |
| `frontend/src/components/molecule/MoleculeFilters.tsx` | 过滤控件（搜索、状态、来源、活性范围） |
| `frontend/src/components/molecule/MoleculeDetailDrawer.tsx` | 详情/编辑抽屉，OCR 矫正模式下嵌入 CorrectionPanel |
| `frontend/src/components/molecule/MoleculeAnalysisPanel.tsx` | 右侧分析面板容器 + 5 个 tab 路由 |
| `frontend/src/components/molecule/analysis/OverviewTab.tsx` | 当前集合的统计概览（从 `components/sar/SessionOverview.tsx` 迁移/封装） |
| `frontend/src/components/molecule/analysis/RGroupTab.tsx` | R-group 矩阵分析（复用 `components/sar/RGroupTab.tsx`） |
| `frontend/src/components/molecule/analysis/CliffsTab.tsx` | 活性悬崖（复用 `components/sar/CliffsTab.tsx`） |
| `frontend/src/components/molecule/analysis/AnalyticsTab.tsx` | 子结构/类似物/聚类/关系/去重工具聚合 |
| `frontend/src/components/molecule/analysis/RelationsTab.tsx` | 分子关系图 |

### 修改文件

| 文件 | 变更 |
|------|------|
| `frontend/src/components/MoleculeLibrary.tsx` | 完全重写为左右分栏单一视图 |
| `frontend/src/components/SARAnalysis.tsx` | 删除或标记为废弃，功能合并到 MoleculeLibrary |
| `frontend/src/components/analysis/SarPanel.tsx` | 删除或重定向到 `/molecules` |
| `frontend/src/components/analysis/Analysis.tsx` | 移除 SAR 面板，或改为重定向 |
| `frontend/src/components/molecule/MoleculeAnalytics.tsx` | 废弃，能力迁移到 `AnalyticsTab` |
| `frontend/src/components/molecule/MoleculeDetailPanel.tsx` | 改造以支持 `MoleculeRecord` 编辑 |
| `frontend/src/App.tsx` | 调整 `/analysis` 路由（重定向或移除 SAR） |
| `frontend/src/components/Sidebar.tsx` | 若 Analysis 菜单仅用于 SAR，调整或移除 |

### 保留/复用文件

| 文件 | 说明 |
|------|------|
| `frontend/src/components/sar/SessionOverview.tsx` | 复用，可能迁移目录 |
| `frontend/src/components/sar/OverviewTab.tsx` | 复用于 Overview tab |
| `frontend/src/components/sar/RGroupTab.tsx` | 复用于 R-Group tab |
| `frontend/src/components/sar/RGroupMatrix.tsx` | 复用 |
| `frontend/src/components/sar/CliffsTab.tsx` | 复用于 Activity Cliffs tab |
| `frontend/src/components/molecule/analytics/*` | 复用于 Analytics tab |
| `frontend/src/components/molecule/CorrectionPanel.tsx` | 嵌入详情抽屉 |
| `frontend/src/components/ui/*` | 复用 |

---

## Task 1: 创建 `useMoleculeLibrary` hook

**Files:**
- Create: `frontend/src/hooks/useMoleculeLibrary.ts`
- Modify: `frontend/src/types/index.ts`（如需新增 status 联合类型）

**Context:** 该 hook 是单一视图的状态核心，集中管理列表加载、过滤、排序、分页、选择和视图模式。

- [ ] **Step 1: 定义 hook 的返回类型与状态结构**

```typescript
// frontend/src/hooks/useMoleculeLibrary.ts
import { useState, useEffect, useCallback, useMemo } from 'react'
import { molAdminList, molAdminSearchText } from '../api/tauri/molecule_admin'
import type { MoleculeRecord } from '../types'

export type MoleculeStatusFilter = 'all' | 'confirmed' | 'pending' | 'rejected' | 'corrected'
export type MoleculeViewMode = 'table' | 'card'
export type MoleculeSortField = 'name' | 'activity' | 'status' | 'created_at'
export type MoleculeSortDirection = 'asc' | 'desc'

export interface MoleculeFilters {
  status: MoleculeStatusFilter
  sourceType: string | 'all'
  sourceDoc: string | 'all'
  activityMin: number | null
  activityMax: number | null
}

export interface MoleculePagination {
  page: number
  pageSize: number
}

export interface MoleculeSort {
  field: MoleculeSortField
  direction: MoleculeSortDirection
}

export interface UseMoleculeLibraryResult {
  molecules: MoleculeRecord[]
  totalCount: number
  loading: boolean
  error: string | null
  query: string
  filters: MoleculeFilters
  sort: MoleculeSort
  pagination: MoleculePagination
  viewMode: MoleculeViewMode
  selectedIds: Set<string>
  isCorrectionMode: boolean

  setQuery: (q: string) => void
  setFilters: React.Dispatch<React.SetStateAction<MoleculeFilters>>
  setSort: (sort: MoleculeSort) => void
  setPagination: React.Dispatch<React.SetStateAction<MoleculePagination>>
  setViewMode: (mode: MoleculeViewMode) => void
  toggleSelection: (molId: string) => void
  selectRange: (startId: string, endId: string) => void
  selectAll: () => void
  clearSelection: () => void
  refresh: () => void
}
```

- [ ] **Step 2: 实现列表加载逻辑**

```typescript
const PAGE_SIZE_OPTIONS = [50, 100, 200]
const VIEW_MODE_KEY = 'mbforge_molecule_view_mode'

export function useMoleculeLibrary(projectRoot: string | null): UseMoleculeLibraryResult {
  const [molecules, setMolecules] = useState<MoleculeRecord[]>([])
  const [totalCount, setTotalCount] = useState(0)
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [query, setQuery] = useState('')
  const [filters, setFilters] = useState<MoleculeFilters>({
    status: 'all',
    sourceType: 'all',
    sourceDoc: 'all',
    activityMin: null,
    activityMax: null,
  })
  const [sort, setSort] = useState<MoleculeSort>({ field: 'created_at', direction: 'desc' })
  const [pagination, setPagination] = useState<MoleculePagination>({ page: 1, pageSize: 50 })
  const [viewMode, setViewModeState] = useState<MoleculeViewMode>(() => {
    const saved = localStorage.getItem(VIEW_MODE_KEY)
    return saved === 'card' ? 'card' : 'table'
  })
  const [selectedIds, setSelectedIds] = useState<Set<string>>(new Set())

  const isCorrectionMode = filters.status === 'pending'

  const setViewMode = useCallback((mode: MoleculeViewMode) => {
    localStorage.setItem(VIEW_MODE_KEY, mode)
    setViewModeState(mode)
  }, [])

  const load = useCallback(async () => {
    if (!projectRoot) {
      setMolecules([])
      setTotalCount(0)
      return
    }
    setLoading(true)
    setError(null)
    try {
      let records: MoleculeRecord[]
      if (query.trim()) {
        records = await molAdminSearchText(projectRoot, query.trim())
      } else {
        const offset = (pagination.page - 1) * pagination.pageSize
        records = await molAdminList(
          projectRoot,
          pagination.pageSize,
          offset,
          filters.sourceType === 'all' ? undefined : filters.sourceType,
          filters.status === 'all' ? undefined : filters.status,
        )
      }
      // 前端过滤：sourceDoc 与 activity 范围
      let filtered = records
      if (filters.sourceDoc !== 'all') {
        filtered = filtered.filter(m => m.source_doc === filters.sourceDoc)
      }
      if (filters.activityMin !== null) {
        filtered = filtered.filter(m => m.activity !== null && m.activity >= filters.activityMin!)
      }
      if (filters.activityMax !== null) {
        filtered = filtered.filter(m => m.activity !== null && m.activity <= filters.activityMax!)
      }
      // 前端排序
      filtered.sort((a, b) => {
        const dir = sort.direction === 'asc' ? 1 : -1
        switch (sort.field) {
          case 'name':
            return (a.name || '').localeCompare(b.name || '') * dir
          case 'activity':
            if (a.activity === null && b.activity === null) return 0
            if (a.activity === null) return 1 * dir
            if (b.activity === null) return -1 * dir
            return (a.activity - b.activity) * dir
          case 'status':
            return (a.status || '').localeCompare(b.status || '') * dir
          case 'created_at':
          default:
            return (a.created_at || '').localeCompare(b.created_at || '') * dir
        }
      })
      setMolecules(filtered)
      setTotalCount(filtered.length)
    } catch (e) {
      setError(e instanceof Error ? e.message : '加载分子失败')
      setMolecules([])
      setTotalCount(0)
    } finally {
      setLoading(false)
    }
  }, [projectRoot, query, filters, sort, pagination.page, pagination.pageSize])

  useEffect(() => {
    load()
  }, [load])

  const toggleSelection = useCallback((molId: string) => {
    setSelectedIds(prev => {
      const next = new Set(prev)
      if (next.has(molId)) next.delete(molId)
      else next.add(molId)
      return next
    })
  }, [])

  const selectRange = useCallback((startId: string, endId: string) => {
    setSelectedIds(prev => {
      const next = new Set(prev)
      const startIdx = molecules.findIndex(m => m.mol_id === startId)
      const endIdx = molecules.findIndex(m => m.mol_id === endId)
      if (startIdx === -1 || endIdx === -1) return prev
      const [low, high] = startIdx < endIdx ? [startIdx, endIdx] : [endIdx, startIdx]
      for (let i = low; i <= high; i++) {
        next.add(molecules[i].mol_id)
      }
      return next
    })
  }, [molecules])

  const selectAll = useCallback(() => {
    setSelectedIds(new Set(molecules.map(m => m.mol_id)))
  }, [molecules])

  const clearSelection = useCallback(() => {
    setSelectedIds(new Set())
  }, [])

  return {
    molecules,
    totalCount,
    loading,
    error,
    query,
    filters,
    sort,
    pagination,
    viewMode,
    selectedIds,
    isCorrectionMode,
    setQuery,
    setFilters,
    setSort,
    setPagination,
    setViewMode,
    toggleSelection,
    selectRange,
    selectAll,
    clearSelection,
    refresh: load,
  }
}
```

- [ ] **Step 3: 运行 TypeScript 检查**

```bash
cd frontend
npx tsc --noEmit
```

Expected: 零 errors（此时 hook 未引用，仅做类型检查）。

- [ ] **Step 4: Commit**

```bash
git add frontend/src/hooks/useMoleculeLibrary.ts
git commit -m "feat(frontend): add useMoleculeLibrary hook for unified molecule list state"
```

---

## Task 2: 创建 `useMoleculeAnalysis` hook

**Files:**
- Create: `frontend/src/hooks/useMoleculeAnalysis.ts`

**Context:** 将列表中的选中集合派生为 SAR 分析所需输入，管理右侧分析面板的 active tab。

- [ ] **Step 1: 实现 hook**

```typescript
// frontend/src/hooks/useMoleculeAnalysis.ts
import { useState, useMemo } from 'react'
import type { MoleculeRecord, SARSession } from '../types'
import { moleculesToSession } from '../components/sar/utils'

export type AnalysisTab = 'overview' | 'rgroup' | 'cliffs' | 'analytics' | 'relations'

export interface UseMoleculeAnalysisResult {
  activeTab: AnalysisTab
  setActiveTab: (tab: AnalysisTab) => void
  selectedMolecules: MoleculeRecord[]
  analysisInput: MoleculeRecord[]
  sarSession: SARSession | null
  hasSelection: boolean
}

export function useMoleculeAnalysis(
  molecules: MoleculeRecord[],
  selectedIds: Set<string>,
): UseMoleculeAnalysisResult {
  const [activeTab, setActiveTab] = useState<AnalysisTab>('overview')

  const selectedMolecules = useMemo(
    () => molecules.filter(m => selectedIds.has(m.mol_id)),
    [molecules, selectedIds],
  )

  const analysisInput = useMemo(
    () => (selectedIds.size > 0 ? selectedMolecules : molecules),
    [selectedIds.size, selectedMolecules, molecules],
  )

  const sarSession = useMemo(
    () => (analysisInput.length > 0 ? moleculesToSession(analysisInput) : null),
    [analysisInput],
  )

  return {
    activeTab,
    setActiveTab,
    selectedMolecules,
    analysisInput,
    sarSession,
    hasSelection: selectedIds.size > 0,
  }
}
```

- [ ] **Step 2: 运行 TypeScript 检查**

```bash
cd frontend
npx tsc --noEmit
```

Expected: 零 errors。

- [ ] **Step 3: Commit**

```bash
git add frontend/src/hooks/useMoleculeAnalysis.ts
git commit -m "feat(frontend): add useMoleculeAnalysis hook for derived SAR input"
```

---

## Task 3: 创建 `MoleculeFilters` 组件

**Files:**
- Create: `frontend/src/components/molecule/MoleculeFilters.tsx`

**Context:** 提供搜索框、状态过滤、来源过滤、活性范围过滤、视图切换、矫正模式入口。

- [ ] **Step 1: 实现组件**

```typescript
// frontend/src/components/molecule/MoleculeFilters.tsx
import { useState, useEffect } from 'react'
import { useTranslation } from 'react-i18next'
import Button from '../ui/Button'
import {
  SearchIcon,
  FilterIcon,
  TableIcon,
  GridIcon,
  SparklesIcon,
} from '../icons'
import type {
  MoleculeFilters as MoleculeFiltersType,
  MoleculeViewMode,
} from '../../hooks/useMoleculeLibrary'

interface MoleculeFiltersProps {
  query: string
  onQueryChange: (q: string) => void
  filters: MoleculeFiltersType
  onFiltersChange: React.Dispatch<React.SetStateAction<MoleculeFiltersType>>
  viewMode: MoleculeViewMode
  onViewModeChange: (mode: MoleculeViewMode) => void
  onSearch: () => void
  sourceTypeOptions: string[]
  sourceDocOptions: string[]
  disabled?: boolean
}

export default function MoleculeFilters({
  query,
  onQueryChange,
  filters,
  onFiltersChange,
  viewMode,
  onViewModeChange,
  onSearch,
  sourceTypeOptions,
  sourceDocOptions,
  disabled,
}: MoleculeFiltersProps) {
  const { t } = useTranslation()
  const [localQuery, setLocalQuery] = useState(query)

  useEffect(() => {
    const timer = setTimeout(() => {
      if (localQuery !== query) {
        onQueryChange(localQuery)
      }
    }, 300)
    return () => clearTimeout(timer)
  }, [localQuery, query, onQueryChange])

  const handleStatusChange = (status: MoleculeFiltersType['status']) => {
    onFiltersChange(prev => ({ ...prev, status }))
  }

  return (
    <div
      style={{
        display: 'flex',
        flexDirection: 'column',
        gap: 12,
        padding: '12px 16px',
        background: 'var(--bg-surface)',
        border: '1px solid var(--border)',
        borderRadius: 10,
      }}
    >
      <div style={{ display: 'flex', alignItems: 'center', gap: 12 }}>
        <SearchIcon size={18} />
        <input
          type="text"
          value={localQuery}
          onChange={e => setLocalQuery(e.target.value)}
          placeholder={t('mol.search')}
          disabled={disabled}
          style={{
            flex: 1,
            background: 'transparent',
            border: 'none',
            outline: 'none',
            fontSize: 14,
            color: 'var(--text-primary)',
            fontFamily: 'inherit',
          }}
        />
        <Button variant="primary" size="sm" onClick={onSearch} disabled={disabled}>
          {t('mol.searchBtn')}
        </Button>
      </div>

      <div style={{ display: 'flex', alignItems: 'center', gap: 12, flexWrap: 'wrap' }}>
        <FilterIcon size={14} />
        <select
          value={filters.status}
          onChange={e => handleStatusChange(e.target.value as MoleculeFiltersType['status'])}
          disabled={disabled}
          style={{
            fontSize: 13,
            padding: '6px 10px',
            borderRadius: 6,
            border: '1px solid var(--border)',
            background: 'var(--bg-base)',
            color: 'var(--text-primary)',
          }}
        >
          <option value="all">{t('mol.status.all') ?? '全部状态'}</option>
          <option value="confirmed">{t('mol.status.confirmed') ?? '已确认'}</option>
          <option value="pending">{t('mol.status.pending') ?? '待矫正'}</option>
          <option value="corrected">{t('mol.status.corrected') ?? '已修正'}</option>
          <option value="rejected">{t('mol.status.rejected') ?? '已拒绝'}</option>
        </select>

        <select
          value={filters.sourceType}
          onChange={e =>
            onFiltersChange(prev => ({ ...prev, sourceType: e.target.value }))
          }
          disabled={disabled}
          style={{
            fontSize: 13,
            padding: '6px 10px',
            borderRadius: 6,
            border: '1px solid var(--border)',
            background: 'var(--bg-base)',
            color: 'var(--text-primary)',
          }}
        >
          <option value="all">{t('mol.sourceType.all') ?? '全部来源类型'}</option>
          {sourceTypeOptions.map(st => (
            <option key={st} value={st}>{st}</option>
          ))}
        </select>

        <select
          value={filters.sourceDoc}
          onChange={e =>
            onFiltersChange(prev => ({ ...prev, sourceDoc: e.target.value }))
          }
          disabled={disabled}
          style={{
            fontSize: 13,
            padding: '6px 10px',
            borderRadius: 6,
            border: '1px solid var(--border)',
            background: 'var(--bg-base)',
            color: 'var(--text-primary)',
          }}
        >
          <option value="all">{t('mol.sourceDoc.all') ?? '全部来源文档'}</option>
          {sourceDocOptions.map(doc => (
            <option key={doc} value={doc}>{doc}</option>
          ))}
        </select>

        <div style={{ display: 'flex', alignItems: 'center', gap: 6 }}>
          <input
            type="number"
            placeholder="Min activity"
            value={filters.activityMin ?? ''}
            onChange={e =>
              onFiltersChange(prev => ({
                ...prev,
                activityMin: e.target.value === '' ? null : Number(e.target.value),
              }))
            }
            disabled={disabled}
            style={{
              width: 90,
              fontSize: 13,
              padding: '6px 10px',
              borderRadius: 6,
              border: '1px solid var(--border)',
              background: 'var(--bg-base)',
              color: 'var(--text-primary)',
            }}
          />
          <span style={{ color: 'var(--text-muted)' }}>-</span>
          <input
            type="number"
            placeholder="Max activity"
            value={filters.activityMax ?? ''}
            onChange={e =>
              onFiltersChange(prev => ({
                ...prev,
                activityMax: e.target.value === '' ? null : Number(e.target.value),
              }))
            }
            disabled={disabled}
            style={{
              width: 90,
              fontSize: 13,
              padding: '6px 10px',
              borderRadius: 6,
              border: '1px solid var(--border)',
              background: 'var(--bg-base)',
              color: 'var(--text-primary)',
            }}
          />
        </div>

        <div style={{ marginLeft: 'auto', display: 'flex', alignItems: 'center', gap: 6 }}>
          <button
            type="button"
            onClick={() => onViewModeChange('table')}
            disabled={disabled}
            style={{
              padding: 6,
              borderRadius: 6,
              border: 'none',
              background: viewMode === 'table' ? 'var(--accent-muted)' : 'transparent',
              color: viewMode === 'table' ? 'var(--accent)' : 'var(--text-secondary)',
              cursor: 'pointer',
            }}
            aria-label="Table view"
          >
            <TableIcon size={16} />
          </button>
          <button
            type="button"
            onClick={() => onViewModeChange('card')}
            disabled={disabled}
            style={{
              padding: 6,
              borderRadius: 6,
              border: 'none',
              background: viewMode === 'card' ? 'var(--accent-muted)' : 'transparent',
              color: viewMode === 'card' ? 'var(--accent)' : 'var(--text-secondary)',
              cursor: 'pointer',
            }}
            aria-label="Card view"
          >
            <GridIcon size={16} />
          </button>
        </div>
      </div>

      {filters.status === 'pending' && (
        <div
          style={{
            display: 'flex',
            alignItems: 'center',
            gap: 8,
            padding: '8px 12px',
            background: 'var(--warning-muted)',
            color: 'var(--warning)',
            borderRadius: 6,
            fontSize: 13,
          }}
        >
          <SparklesIcon size={14} />
          {t('mol.correctionMode') ?? 'OCR 矫正模式：点击行打开矫正面板'}
        </div>
      )}
    </div>
  )
}
```

> 注意：如果 `TableIcon` 或 `GridIcon` 不存在，使用现有可用图标或创建 SVG 图标组件。

- [ ] **Step 2: 运行 TypeScript 检查**

```bash
cd frontend
npx tsc --noEmit
```

Expected: 零 errors。

- [ ] **Step 3: Commit**

```bash
git add frontend/src/components/molecule/MoleculeFilters.tsx
git commit -m "feat(frontend): add MoleculeFilters component for list filtering and view mode"
```

---

## Task 4: 创建 `MoleculeTable` 组件

**Files:**
- Create: `frontend/src/components/molecule/MoleculeTable.tsx`

**Context:** 表格视图，支持行选择、排序、分页、空状态。

- [ ] **Step 1: 实现组件**

```typescript
// frontend/src/components/molecule/MoleculeTable.tsx
import { useTranslation } from 'react-i18next'
import type { MoleculeRecord } from '../../types'
import type {
  MoleculeSort,
  MoleculeSortField,
} from '../../hooks/useMoleculeLibrary'
import Skeleton from '../ui/Skeleton'
import EmptyState from '../ui/EmptyState'
import { CheckIcon } from '../icons'

interface MoleculeTableProps {
  molecules: MoleculeRecord[]
  loading: boolean
  selectedIds: Set<string>
  sort: MoleculeSort
  onSort: (field: MoleculeSortField) => void
  onToggleSelect: (molId: string) => void
  onSelectRange: (startId: string, endId: string) => void
  onRowClick: (mol: MoleculeRecord) => void
  lastClickedId: string | null
  setLastClickedId: (id: string | null) => void
}

const headers: { key: MoleculeSortField; label: string }[] = [
  { key: 'name', label: 'Name' },
  { key: 'activity', label: 'Activity' },
  { key: 'status', label: 'Status' },
  { key: 'created_at', label: 'Created' },
]

export default function MoleculeTable({
  molecules,
  loading,
  selectedIds,
  sort,
  onSort,
  onToggleSelect,
  onSelectRange,
  onRowClick,
  lastClickedId,
  setLastClickedId,
}: MoleculeTableProps) {
  const { t } = useTranslation()

  const handleCheckboxClick = (e: React.MouseEvent, molId: string) => {
    e.stopPropagation()
    if (e.shiftKey && lastClickedId) {
      onSelectRange(lastClickedId, molId)
    } else {
      onToggleSelect(molId)
      setLastClickedId(molId)
    }
  }

  const allSelected = molecules.length > 0 && molecules.every(m => selectedIds.has(m.mol_id))

  if (loading) {
    return (
      <div style={{ padding: '16px 0' }}>
        <Skeleton variant="list" count={8} />
      </div>
    )
  }

  if (molecules.length === 0) {
    return <EmptyState message={t('mol.empty') ?? '暂无分子'} />
  }

  return (
    <div
      style={{
        border: '1px solid var(--border)',
        borderRadius: 10,
        overflow: 'auto',
        background: 'var(--bg-surface)',
      }}
    >
      <table style={{ width: '100%', borderCollapse: 'collapse', fontSize: 13 }}>
        <thead>
          <tr style={{ borderBottom: '1px solid var(--border)' }}>
            <th style={{ padding: '10px 12px', width: 40, textAlign: 'center' }}>
              <input
                type="checkbox"
                checked={allSelected}
                onChange={() => {
                  if (allSelected) {
                    molecules.forEach(m => onToggleSelect(m.mol_id))
                  } else {
                    molecules.forEach(m => {
                      if (!selectedIds.has(m.mol_id)) onToggleSelect(m.mol_id)
                    })
                  }
                }}
              />
            </th>
            {headers.map(h => (
              <th
                key={h.key}
                onClick={() => onSort(h.key)}
                style={{
                  padding: '10px 12px',
                  textAlign: 'left',
                  cursor: 'pointer',
                  userSelect: 'none',
                  color: 'var(--text-secondary)',
                  fontWeight: 600,
                }}
              >
                {h.label}
                {sort.field === h.key && (
                  <span style={{ marginLeft: 6, color: 'var(--accent)' }}>
                    {sort.direction === 'asc' ? '↑' : '↓'}
                  </span>
                )}
              </th>
            ))}
            <th style={{ padding: '10px 12px', textAlign: 'left', color: 'var(--text-secondary)', fontWeight: 600 }}>
              Source
            </th>
          </tr>
        </thead>
        <tbody>
          {molecules.map(mol => (
            <tr
              key={mol.mol_id}
              onClick={() => onRowClick(mol)}
              style={{
                borderBottom: '1px solid var(--border-subtle)',
                background: selectedIds.has(mol.mol_id) ? 'var(--accent-muted)' : undefined,
                cursor: 'pointer',
              }}
            >
              <td style={{ padding: '10px 12px', textAlign: 'center' }}>
                <input
                  type="checkbox"
                  checked={selectedIds.has(mol.mol_id)}
                  onClick={e => e.stopPropagation()}
                  onChange={e => handleCheckboxClick(e as unknown as React.MouseEvent, mol.mol_id)}
                />
              </td>
              <td style={{ padding: '10px 12px' }}>
                <div style={{ fontWeight: 600 }}>{mol.name || mol.mol_id}</div>
                <div style={{ fontSize: 11, color: 'var(--text-muted)', fontFamily: 'monospace', marginTop: 2 }}>
                  {mol.esmiles}
                </div>
              </td>
              <td style={{ padding: '10px 12px' }}>
                {mol.activity !== null && mol.activity !== undefined
                  ? `${mol.activity.toFixed(2)} ${mol.units || 'nM'}`
                  : '-'}
              </td>
              <td style={{ padding: '10px 12px' }}>
                <StatusBadge status={mol.status} />
              </td>
              <td style={{ padding: '10px 12px', color: 'var(--text-muted)' }}>
                {new Date(mol.created_at).toLocaleDateString()}
              </td>
              <td style={{ padding: '10px 12px', color: 'var(--text-muted)' }}>
                {mol.source_doc || '-'}
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  )
}

function StatusBadge({ status }: { status: string }) {
  const colors: Record<string, { bg: string; text: string }> = {
    confirmed: { bg: 'var(--success-muted)', text: 'var(--success)' },
    pending: { bg: 'var(--warning-muted)', text: 'var(--warning)' },
    corrected: { bg: 'var(--info-muted)', text: 'var(--info)' },
    rejected: { bg: 'var(--danger-muted)', text: 'var(--danger)' },
  }
  const c = colors[status] || { bg: 'var(--bg-elevated)', text: 'var(--text-muted)' }
  return (
    <span
      style={{
        display: 'inline-flex',
        alignItems: 'center',
        gap: 4,
        padding: '2px 8px',
        borderRadius: 6,
        background: c.bg,
        color: c.text,
        fontSize: 11,
        fontWeight: 600,
        textTransform: 'capitalize',
      }}
    >
      {status}
    </span>
  )
}
```

> 注意：如果 `CheckIcon` 未使用可直接删除导入。确保 `Skeleton` 支持 `variant="list"`，否则改为 `variant="card"`。

- [ ] **Step 2: 运行 TypeScript 检查**

```bash
cd frontend
npx tsc --noEmit
```

Expected: 零 errors。

- [ ] **Step 3: Commit**

```bash
git add frontend/src/components/molecule/MoleculeTable.tsx
git commit -m "feat(frontend): add MoleculeTable component with selection and sorting"
```

---

## Task 5: 创建 `MoleculeCardGrid` 组件

**Files:**
- Create: `frontend/src/components/molecule/MoleculeCardGrid.tsx`

**Context:** 卡片网格视图，复用现有 `CardGrid` / `Card` 和 `MoleculeDisplay`。

- [ ] **Step 1: 实现组件**

```typescript
// frontend/src/components/molecule/MoleculeCardGrid.tsx
import { useTranslation } from 'react-i18next'
import type { MoleculeRecord } from '../../types'
import CardGrid from '../ui/CardGrid'
import Card from '../ui/Card'
import Skeleton from '../ui/Skeleton'
import EmptyState from '../ui/EmptyState'
import MoleculeDisplay from './MoleculeDisplay'

interface MoleculeCardGridProps {
  molecules: MoleculeRecord[]
  loading: boolean
  selectedIds: Set<string>
  onToggleSelect: (molId: string) => void
  onCardClick: (mol: MoleculeRecord) => void
}

export default function MoleculeCardGrid({
  molecules,
  loading,
  selectedIds,
  onToggleSelect,
  onCardClick,
}: MoleculeCardGridProps) {
  const { t } = useTranslation()

  if (loading) {
    return (
      <CardGrid>
        {Array.from({ length: 6 }).map((_, i) => (
          <Skeleton key={i} variant="card" count={1} />
        ))}
      </CardGrid>
    )
  }

  if (molecules.length === 0) {
    return <EmptyState message={t('mol.empty') ?? '暂无分子'} />
  }

  return (
    <CardGrid>
      {molecules.map(mol => {
        const isSelected = selectedIds.has(mol.mol_id)
        return (
          <Card
            key={mol.mol_id}
            hoverable
            onClick={() => onCardClick(mol)}
            style={{
              borderColor: isSelected ? 'var(--accent)' : undefined,
              background: isSelected ? 'var(--accent-muted)' : undefined,
            }}
          >
            <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start', marginBottom: 12 }}>
              <input
                type="checkbox"
                checked={isSelected}
                onClick={e => e.stopPropagation()}
                onChange={() => onToggleSelect(mol.mol_id)}
              />
              <span
                style={{
                  fontSize: 11,
                  padding: '2px 8px',
                  borderRadius: 6,
                  background: 'var(--bg-elevated)',
                  color: 'var(--text-muted)',
                  textTransform: 'capitalize',
                }}
              >
                {mol.status}
              </span>
            </div>
            <div style={{ height: 120, display: 'flex', alignItems: 'center', justifyContent: 'center', marginBottom: 12 }}>
              <MoleculeDisplay esmiles={mol.esmiles} size={100} />
            </div>
            <div style={{ fontWeight: 600, fontSize: 14, marginBottom: 4 }}>
              {mol.name || mol.mol_id}
            </div>
            <div style={{ fontSize: 12, color: 'var(--text-muted)', marginBottom: 8 }}>
              {mol.source_doc || t('mol.unknownSource')}
            </div>
            {mol.activity !== null && mol.activity !== undefined && (
              <div style={{ fontSize: 13, color: 'var(--text-secondary)' }}>
                {t('mol.activity')}: {mol.activity.toFixed(2)} {mol.units || 'nM'}
              </div>
            )}
          </Card>
        )
      })}
    </CardGrid>
  )
}
```

> 注意：`MoleculeDisplay` 的 props 以实际组件为准；如果不支持 `size`，改为支持的 prop。

- [ ] **Step 2: 运行 TypeScript 检查**

```bash
cd frontend
npx tsc --noEmit
```

Expected: 零 errors。

- [ ] **Step 3: Commit**

```bash
git add frontend/src/components/molecule/MoleculeCardGrid.tsx
git commit -m "feat(frontend): add MoleculeCardGrid component as alternative view"
```

---

## Task 6: 创建 `MoleculeDetailDrawer` 组件

**Files:**
- Create: `frontend/src/components/molecule/MoleculeDetailDrawer.tsx`

**Context:** 右侧或底部滑出的详情抽屉，普通模式下展示/编辑分子详情，矫正模式下嵌入 `CorrectionPanel`。

- [ ] **Step 1: 实现抽屉容器**

```typescript
// frontend/src/components/molecule/MoleculeDetailDrawer.tsx
import { useTranslation } from 'react-i18next'
import type { MoleculeRecord } from '../../types'
import Button from '../ui/Button'
import { CloseIcon } from '../icons'
import MoleculeDetailPanel from './MoleculeDetailPanel'
import CorrectionPanel from './CorrectionPanel'

interface MoleculeDetailDrawerProps {
  molecule: MoleculeRecord | null
  open: boolean
  isCorrectionMode: boolean
  projectRoot: string | null
  onClose: () => void
  onSaved: () => void
}

export default function MoleculeDetailDrawer({
  molecule,
  open,
  isCorrectionMode,
  projectRoot,
  onClose,
  onSaved,
}: MoleculeDetailDrawerProps) {
  const { t } = useTranslation()

  if (!open || !molecule) return null

  return (
    <div
      style={{
        position: 'fixed',
        inset: 0,
        zIndex: 100,
        pointerEvents: 'none',
      }}
    >
      <div
        onClick={onClose}
        style={{
          position: 'absolute',
          inset: 0,
          background: 'rgba(0,0,0,0.3)',
          pointerEvents: 'auto',
        }}
      />
      <div
        style={{
          position: 'absolute',
          right: 0,
          top: 0,
          bottom: 0,
          width: 'min(520px, 90vw)',
          background: 'var(--bg-surface)',
          borderLeft: '1px solid var(--border)',
          boxShadow: '-4px 0 24px rgba(0,0,0,0.1)',
          pointerEvents: 'auto',
          display: 'flex',
          flexDirection: 'column',
        }}
      >
        <div
          style={{
            display: 'flex',
            justifyContent: 'space-between',
            alignItems: 'center',
            padding: '16px 20px',
            borderBottom: '1px solid var(--border)',
          }}
        >
          <h3 style={{ margin: 0, fontSize: 16, fontWeight: 600 }}>
            {isCorrectionMode ? t('mol.correctTitle') ?? 'OCR 矫正' : molecule.name || molecule.mol_id}
          </h3>
          <Button variant="ghost" size="sm" onClick={onClose} aria-label="Close">
            <CloseIcon size={18} />
          </Button>
        </div>
        <div style={{ flex: 1, overflow: 'auto', padding: 20 }}>
          {isCorrectionMode ? (
            <CorrectionPanelWrapper
              molecule={molecule}
              projectRoot={projectRoot}
              onSaved={onSaved}
              onClose={onClose}
            />
          ) : (
            <MoleculeDetailPanel
              molecule={molecule}
              projectRoot={projectRoot}
              onSaved={onSaved}
            />
          )}
        </div>
      </div>
    </div>
  )
}

function CorrectionPanelWrapper({
  molecule,
  projectRoot,
  onSaved,
  onClose,
}: {
  molecule: MoleculeRecord
  projectRoot: string | null
  onSaved: () => void
  onClose: () => void
}) {
  if (!projectRoot) return null
  return (
    <CorrectionPanel
      projectRoot={projectRoot}
      items={[
        {
          id: molecule.mol_id,
          ocrSmiles: molecule.esmiles,
          ocrConfidence: 0.5,
          name: molecule.name || undefined,
          sourceDoc: molecule.source_doc || undefined,
          context: molecule.notes || undefined,
          status: 'pending',
          sourceRecord: molecule,
        },
      ]}
      onItemsChange={() => {}}
      onComplete={(saved, failed) => {
        if (failed === 0 && saved > 0) {
          onSaved()
          onClose()
        }
      }}
    />
  )
}
```

> 注意：`MoleculeDetailPanel` 当前可能只接受 `ExtractionResult` props，需要在 Task 7 中改造。`CorrectionPanel` 的 props 以实际组件为准；如果不匹配，需调整。

- [ ] **Step 2: 运行 TypeScript 检查**

```bash
cd frontend
npx tsc --noEmit
```

Expected: 可能有关于 `MoleculeDetailPanel` 和 `CorrectionPanel` prop 不匹配的错误；记录并在 Task 7 / Task 8 中修复。

- [ ] **Step 3: Commit**

```bash
git add frontend/src/components/molecule/MoleculeDetailDrawer.tsx
git commit -m "feat(frontend): add MoleculeDetailDrawer component"
```

---

## Task 7: 改造 `MoleculeDetailPanel` 支持 `MoleculeRecord` 编辑

**Files:**
- Modify: `frontend/src/components/molecule/MoleculeDetailPanel.tsx`

**Context:** 当前 `MoleculeDetailPanel` 主要面向 `ExtractionResult`（PDF 检测产物），需要扩展以支持 `MoleculeRecord` 的查看与编辑。

- [ ] **Step 1: 读取当前 `MoleculeDetailPanel.tsx` 并理解 props**

```bash
cat frontend/src/components/molecule/MoleculeDetailPanel.tsx | head -60
```

- [ ] **Step 2: 扩展 props 接口**

```typescript
// 在 MoleculeDetailPanel.tsx 顶部添加/修改
import type { MoleculeRecord } from '../../types'

interface MoleculeDetailPanelProps {
  molecule: MoleculeRecord
  projectRoot: string | null
  onSaved?: () => void
}
```

- [ ] **Step 3: 使用 `molAdminUpdate` 实现保存逻辑**

```typescript
import { molAdminUpdate } from '../../api/tauri/molecule_admin'
import { showToast } from '../../hooks/useToast'

// 在组件内部保存回调中：
const handleSave = async (updated: MoleculeRecord) => {
  if (!projectRoot) return
  try {
    const ok = await molAdminUpdate(projectRoot, updated)
    if (ok) {
      showToast('分子已更新', 'success')
      onSaved?.()
    } else {
      showToast('更新失败', 'error')
    }
  } catch (e) {
    showToast(e instanceof Error ? e.message : '更新失败', 'error')
  }
}
```

- [ ] **Step 4: 调整渲染逻辑**

保留现有的 MoleCode、理化性质展示，但数据来源从 `ExtractionResult` 改为 `MoleculeRecord` 的 `esmiles` / `properties`。编辑表单字段包括：name、esmiles、activity、activity_type、units、status、notes。

- [ ] **Step 5: 运行 TypeScript 检查**

```bash
cd frontend
npx tsc --noEmit
```

Expected: 零 errors。

- [ ] **Step 6: Commit**

```bash
git add frontend/src/components/molecule/MoleculeDetailPanel.tsx
git commit -m "feat(frontend): adapt MoleculeDetailPanel for MoleculeRecord editing"
```

---

## Task 8: 创建右侧分析面板 `MoleculeAnalysisPanel`

**Files:**
- Create: `frontend/src/components/molecule/MoleculeAnalysisPanel.tsx`
- Create: `frontend/src/components/molecule/analysis/AnalyticsTab.tsx`
- Create: `frontend/src/components/molecule/analysis/RelationsTab.tsx`

**Context:** 右侧固定区域，基于 `analysisInput` 渲染 5 个分析 tab。

- [ ] **Step 1: 创建 `AnalyticsTab.tsx`**

```typescript
// frontend/src/components/molecule/analysis/AnalyticsTab.tsx
import { useState } from 'react'
import type { MoleculeRecord } from '../../../types'
import Tabs from '../../ui/Tabs'
import SubstructureSearchPanel from '../analytics/SubstructureSearchPanel'
import AnalogSearchPanel from '../analytics/AnalogSearchPanel'
import ClusterPanel from '../analytics/ClusterPanel'
import RelationPanel from '../analytics/RelationPanel'
import DedupPanel from '../analytics/DedupPanel'

type InnerTab = 'substructure' | 'analogs' | 'clusters' | 'relations' | 'dedup'

interface AnalyticsTabProps {
  molecules: MoleculeRecord[]
  projectRoot: string | null
  onRefresh: () => void
}

export default function AnalyticsTab({ molecules, projectRoot, onRefresh }: AnalyticsTabProps) {
  const [innerTab, setInnerTab] = useState<InnerTab>('substructure')

  return (
    <div>
      <Tabs
        items={[
          { key: 'substructure', label: '子结构搜索' },
          { key: 'analogs', label: '活性类似物' },
          { key: 'clusters', label: '聚类' },
          { key: 'relations', label: '关系' },
          { key: 'dedup', label: '去重' },
        ]}
        activeKey={innerTab}
        onChange={k => setInnerTab(k as InnerTab)}
        size="sm"
        variant="pills"
      />
      <div style={{ marginTop: 16 }}>
        {innerTab === 'substructure' && <SubstructureSearchPanel />}
        {innerTab === 'analogs' && <AnalogSearchPanel molecules={molecules} />}
        {innerTab === 'clusters' && <ClusterPanel molecules={molecules} />}
        {innerTab === 'relations' && <RelationPanel molecules={molecules} />}
        {innerTab === 'dedup' && <DedupPanel molecules={molecules} onComplete={onRefresh} />}
      </div>
    </div>
  )
}
```

- [ ] **Step 2: 创建 `RelationsTab.tsx`**

```typescript
// frontend/src/components/molecule/analysis/RelationsTab.tsx
import type { MoleculeRecord } from '../../../types'
import RelationPanel from '../analytics/RelationPanel'

interface RelationsTabProps {
  molecules: MoleculeRecord[]
}

export default function RelationsTab({ molecules }: RelationsTabProps) {
  return <RelationPanel molecules={molecules} />
}
```

- [ ] **Step 3: 创建 `MoleculeAnalysisPanel.tsx`**

```typescript
// frontend/src/components/molecule/MoleculeAnalysisPanel.tsx
import { useTranslation } from 'react-i18next'
import type { MoleculeRecord, SARSession } from '../../types'
import type { AnalysisTab } from '../../hooks/useMoleculeAnalysis'
import Tabs from '../ui/Tabs'
import EmptyState from '../ui/EmptyState'
import SessionOverview from '../sar/SessionOverview'
import OverviewTab from '../sar/OverviewTab'
import RGroupTab from '../sar/RGroupTab'
import CliffsTab from '../sar/CliffsTab'
import AnalyticsTab from './analysis/AnalyticsTab'
import RelationsTab from './analysis/RelationsTab'
import { FlaskIcon, TargetIcon, BarChartIcon, NetworkIcon, SearchIcon } from '../icons'

interface MoleculeAnalysisPanelProps {
  analysisInput: MoleculeRecord[]
  sarSession: SARSession | null
  activeTab: AnalysisTab
  onTabChange: (tab: AnalysisTab) => void
  projectRoot: string | null
  onRefresh: () => void
}

export default function MoleculeAnalysisPanel({
  analysisInput,
  sarSession,
  activeTab,
  onTabChange,
  projectRoot,
  onRefresh,
}: MoleculeAnalysisPanelProps) {
  const { t } = useTranslation()

  if (analysisInput.length === 0) {
    return (
      <div style={{ padding: 24 }}>
        <EmptyState message={t('mol.noSelection') ?? '请选择分子或清除过滤以查看分析'} />
      </div>
    )
  }

  return (
    <div style={{ display: 'flex', flexDirection: 'column', height: '100%', overflow: 'hidden' }}>
      <Tabs
        items={[
          { key: 'overview', label: <><FlaskIcon size={14} /> 概览</>, badge: analysisInput.length },
          { key: 'rgroup', label: <><TargetIcon size={14} /> R-Group</> },
          { key: 'cliffs', label: <><BarChartIcon size={14} /> 活性悬崖</> },
          { key: 'analytics', label: <><SearchIcon size={14} /> 高级分析</> },
          { key: 'relations', label: <><NetworkIcon size={14} /> 关系</> },
        ]}
        activeKey={activeTab}
        onChange={k => onTabChange(k as AnalysisTab)}
      />
      <div style={{ flex: 1, overflow: 'auto', padding: '16px 0' }}>
        {activeTab === 'overview' && sarSession && (
          <>
            <SessionOverview session={sarSession} />
            <div style={{ marginTop: 16 }}>
              <OverviewTab
                session={sarSession}
                selectedCompoundId={null}
                onSelect={() => {}}
              />
            </div>
          </>
        )}
        {activeTab === 'rgroup' && sarSession && (
          <RGroupTab session={sarSession} onSelectCompound={() => {}} />
        )}
        {activeTab === 'cliffs' && sarSession && projectRoot && (
          <CliffsTab session={sarSession} projectRoot={projectRoot} />
        )}
        {activeTab === 'analytics' && (
          <AnalyticsTab molecules={analysisInput} projectRoot={projectRoot} onRefresh={onRefresh} />
        )}
        {activeTab === 'relations' && (
          <RelationsTab molecules={analysisInput} />
        )}
      </div>
    </div>
  )
}
```

> 注意：如果 `SessionOverview`、`OverviewTab`、`RGroupTab`、`CliffsTab` 的 props 不完全匹配，需要调整。`CliffsTab` 需要 `projectRoot`，确保不为 null 时渲染。

- [ ] **Step 4: 运行 TypeScript 检查**

```bash
cd frontend
npx tsc --noEmit
```

Expected: 可能有 props 不匹配错误，根据错误调整。

- [ ] **Step 5: Commit**

```bash
git add frontend/src/components/molecule/MoleculeAnalysisPanel.tsx \
  frontend/src/components/molecule/analysis/AnalyticsTab.tsx \
  frontend/src/components/molecule/analysis/RelationsTab.tsx
git commit -m "feat(frontend): add MoleculeAnalysisPanel with 5 analysis tabs"
```

---

## Task 9: 重构 `MoleculeLibrary` 主容器

**Files:**
- Modify: `frontend/src/components/MoleculeLibrary.tsx`

**Context:** 将现有 3-tab 结构改为左右分栏单一视图，整合列表、过滤、详情抽屉和分析面板。

- [ ] **Step 1: 重写 `MoleculeLibrary.tsx`**

```typescript
// frontend/src/components/MoleculeLibrary.tsx
import { useState } from 'react'
import { useTranslation } from 'react-i18next'
import PageContainer from '../components/ui/PageContainer'
import PageTitle from '../components/ui/PageTitle'
import Button from '../components/ui/Button'
import { AddMoleculeDialog } from '../components/ui/AddMoleculeDialog'
import { useAppContext } from '../context/AppContext'
import { useMoleculeLibrary } from '../hooks/useMoleculeLibrary'
import { useMoleculeAnalysis } from '../hooks/useMoleculeAnalysis'
import MoleculeFilters from '../components/molecule/MoleculeFilters'
import MoleculeTable from '../components/molecule/MoleculeTable'
import MoleculeCardGrid from '../components/molecule/MoleculeCardGrid'
import MoleculeDetailDrawer from '../components/molecule/MoleculeDetailDrawer'
import MoleculeAnalysisPanel from '../components/molecule/MoleculeAnalysisPanel'

export default function MoleculeLibrary() {
  const { projectRoot } = useAppContext()
  const { t } = useTranslation()
  const [showAddDialog, setShowAddDialog] = useState(false)
  const [detailMolecule, setDetailMolecule] = useState<MoleculeRecord | null>(null)
  const [lastClickedId, setLastClickedId] = useState<string | null>(null)

  const {
    molecules,
    totalCount,
    loading,
    error,
    query,
    filters,
    sort,
    pagination,
    viewMode,
    selectedIds,
    isCorrectionMode,
    setQuery,
    setFilters,
    setSort,
    setPagination,
    setViewMode,
    toggleSelection,
    selectRange,
    selectAll,
    clearSelection,
    refresh,
  } = useMoleculeLibrary(projectRoot)

  const {
    activeTab: analysisTab,
    setActiveTab: setAnalysisTab,
    analysisInput,
    sarSession,
  } = useMoleculeAnalysis(molecules, selectedIds)

  const sourceTypeOptions = Array.from(new Set(molecules.map(m => m.source_type).filter(Boolean)))
  const sourceDocOptions = Array.from(new Set(molecules.map(m => m.source_doc).filter(Boolean)))

  const handleRowClick = (mol: MoleculeRecord) => {
    setDetailMolecule(mol)
  }

  return (
    <PageContainer>
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 16 }}>
        <PageTitle>{t('mol.title')}</PageTitle>
        <Button variant="primary" size="sm" onClick={() => setShowAddDialog(true)}>
          {t('mol.add')}
        </Button>
      </div>

      <div
        style={{
          display: 'flex',
          gap: 20,
          height: 'calc(100vh - 180px)',
          minHeight: 400,
        }}
      >
        {/* 左侧列表 */}
        <div
          style={{
            flex: '0 0 40%',
            minWidth: 360,
            maxWidth: '50%',
            display: 'flex',
            flexDirection: 'column',
            gap: 12,
            overflow: 'hidden',
          }}
        >
          <MoleculeFilters
            query={query}
            onQueryChange={setQuery}
            filters={filters}
            onFiltersChange={setFilters}
            viewMode={viewMode}
            onViewModeChange={setViewMode}
            onSearch={refresh}
            sourceTypeOptions={sourceTypeOptions}
            sourceDocOptions={sourceDocOptions}
            disabled={!projectRoot}
          />

          {error && (
            <div style={{ padding: 12, background: 'var(--danger-muted)', color: 'var(--danger)', borderRadius: 8 }}>
              {error}
            </div>
          )}

          <div style={{ flex: 1, overflow: 'auto' }}>
            {viewMode === 'table' ? (
              <MoleculeTable
                molecules={molecules}
                loading={loading}
                selectedIds={selectedIds}
                sort={sort}
                onSort={setSort}
                onToggleSelect={toggleSelection}
                onSelectRange={selectRange}
                onRowClick={handleRowClick}
                lastClickedId={lastClickedId}
                setLastClickedId={setLastClickedId}
              />
            ) : (
              <MoleculeCardGrid
                molecules={molecules}
                loading={loading}
                selectedIds={selectedIds}
                onToggleSelect={toggleSelection}
                onCardClick={handleRowClick}
              />
            )}
          </div>

          <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', fontSize: 13, color: 'var(--text-muted)' }}>
            <span>
              {selectedIds.size > 0
                ? `已选 ${selectedIds.size} / ${totalCount}`
                : `共 ${totalCount} 个分子`}
            </span>
            <div style={{ display: 'flex', gap: 8 }}>
              <Button variant="secondary" size="sm" onClick={selectAll} disabled={loading}>
                全选
              </Button>
              <Button variant="secondary" size="sm" onClick={clearSelection} disabled={selectedIds.size === 0}>
                清空选择
              </Button>
            </div>
          </div>
        </div>

        {/* 右侧分析面板 */}
        <div
          style={{
            flex: 1,
            minWidth: 0,
            border: '1px solid var(--border)',
            borderRadius: 10,
            background: 'var(--bg-surface)',
            padding: '0 16px',
            overflow: 'hidden',
          }}
        >
          <MoleculeAnalysisPanel
            analysisInput={analysisInput}
            sarSession={sarSession}
            activeTab={analysisTab}
            onTabChange={setAnalysisTab}
            projectRoot={projectRoot}
            onRefresh={refresh}
          />
        </div>
      </div>

      <MoleculeDetailDrawer
        molecule={detailMolecule}
        open={!!detailMolecule}
        isCorrectionMode={isCorrectionMode}
        projectRoot={projectRoot}
        onClose={() => setDetailMolecule(null)}
        onSaved={refresh}
      />

      {projectRoot && (
        <AddMoleculeDialog
          open={showAddDialog}
          onClose={() => setShowAddDialog(false)}
          projectRoot={projectRoot}
          onAdded={refresh}
        />
      )}
    </PageContainer>
  )
}
```

> 注意：`MoleculeRecord` 需要从 `../types` 导入。检查 `PageContainer` 是否支持子元素占满高度。

- [ ] **Step 2: 运行 TypeScript 检查**

```bash
cd frontend
npx tsc --noEmit
```

Expected: 零 errors。

- [ ] **Step 3: 运行开发服务器进行手动验证**

```bash
cd frontend
npm run dev
```

手动检查：
- `/molecules` 页面为左右分栏。
- 左侧默认表格视图，可切换卡片。
- 选中行后右侧分析面板更新。
- 点击行打开详情抽屉。

- [ ] **Step 4: Commit**

```bash
git add frontend/src/components/MoleculeLibrary.tsx
git commit -m "feat(frontend): refactor MoleculeLibrary into unified single-view layout"
```

---

## Task 10: 移除冗余的 SAR 容器并调整路由

**Files:**
- Modify: `frontend/src/components/SARAnalysis.tsx`
- Modify: `frontend/src/components/analysis/SarPanel.tsx`
- Modify: `frontend/src/components/analysis/Analysis.tsx`
- Modify: `frontend/src/App.tsx`
- Modify: `frontend/src/components/Sidebar.tsx`

**Context:** 清理重复代码，统一入口到 `/molecules`。

- [ ] **Step 1: 删除或简化 `SARAnalysis.tsx`**

如果 `MoleculeAnalysisPanel` 已完全覆盖 `SARAnalysis` 功能，将 `SARAnalysis.tsx` 改为一个轻量重定向组件：

```typescript
// frontend/src/components/SARAnalysis.tsx
import { useEffect } from 'react'
import { useNavigate } from 'react-router-dom'

export default function SARAnalysis() {
  const navigate = useNavigate()
  useEffect(() => {
    navigate('/molecules', { replace: true })
  }, [navigate])
  return null
}
```

或者如果没有任何路由直接引用 `SARAnalysis`，直接删除该文件并在引用处移除。

- [ ] **Step 2: 修改 `SarPanel.tsx` 重定向**

```typescript
// frontend/src/components/analysis/SarPanel.tsx
import { useEffect } from 'react'
import { useNavigate } from 'react-router-dom'

export default function SarPanel() {
  const navigate = useNavigate()
  useEffect(() => {
    navigate('/molecules', { replace: true })
  }, [navigate])
  return null
}
```

- [ ] **Step 3: 修改 `Analysis.tsx` 移除 SAR 导航**

读取 `frontend/src/components/analysis/Analysis.tsx`，移除 SAR 相关 tab/菜单，或保留其他非 SAR 分析能力（如果有）。

- [ ] **Step 4: 调整 `App.tsx`**

将 `/analysis` 路由重定向到 `/molecules`：

```typescript
import { Navigate } from 'react-router-dom'

// 替换 /analysis 路由
<Route
  path="/analysis"
  element={
    <Suspense fallback={<RouteFallback />}>
      <AnimatedPage><Navigate to="/molecules" replace /></AnimatedPage>
    </Suspense>
  }
/>
```

- [ ] **Step 5: 调整 `Sidebar.tsx`**

读取 `frontend/src/components/Sidebar.tsx`，如果 "Analysis" 菜单仅用于 SAR，移除或改为其他入口。

- [ ] **Step 6: 运行 TypeScript 检查**

```bash
cd frontend
npx tsc --noEmit
```

Expected: 零 errors。

- [ ] **Step 7: Commit**

```bash
git add frontend/src/components/SARAnalysis.tsx \
  frontend/src/components/analysis/SarPanel.tsx \
  frontend/src/components/analysis/Analysis.tsx \
  frontend/src/App.tsx \
  frontend/src/components/Sidebar.tsx
git commit -m "feat(frontend): remove redundant SAR containers and unify entry to /molecules"
```

---

## Task 11: 废弃 `MoleculeAnalytics.tsx`

**Files:**
- Modify: `frontend/src/components/molecule/MoleculeAnalytics.tsx`

**Context:** 能力已迁移到 `MoleculeAnalysisPanel` 的 Analytics tab，保留文件作为兼容层或标记废弃。

- [ ] **Step 1: 将 `MoleculeAnalytics.tsx` 改为废弃包装**

```typescript
// frontend/src/components/molecule/MoleculeAnalytics.tsx
import { useEffect } from 'react'
import { useNavigate } from 'react-router-dom'

/**
 * @deprecated Analytics capabilities have been merged into MoleculeLibrary.
 * This component now redirects to /molecules.
 */
export default function MoleculeAnalytics() {
  const navigate = useNavigate()
  useEffect(() => {
    navigate('/molecules', { replace: true })
  }, [navigate])
  return null
}
```

- [ ] **Step 2: 搜索并移除其他对 `MoleculeAnalytics` 的引用**

```bash
cd frontend
grep -r "MoleculeAnalytics" src/ --include="*.tsx" --include="*.ts"
```

移除所有引用（除了废弃文件自身）。

- [ ] **Step 3: 运行 TypeScript 检查**

```bash
cd frontend
npx tsc --noEmit
```

Expected: 零 errors。

- [ ] **Step 4: Commit**

```bash
git add frontend/src/components/molecule/MoleculeAnalytics.tsx
git commit -m "chore(frontend): deprecate MoleculeAnalytics in favor of unified panel"
```

---

## Task 12: 性能优化与细节打磨

**Files:**
- Modify: `frontend/src/hooks/useMoleculeLibrary.ts`
- Modify: `frontend/src/components/molecule/MoleculeTable.tsx`
- Modify: `frontend/src/components/molecule/MoleculeAnalysisPanel.tsx`

**Context:** 添加防抖、虚拟滚动、分析计算限制、过期结果忽略。

- [ ] **Step 1: 在 `useMoleculeLibrary` 中添加搜索防抖**

已在 Step 1 中通过 `useEffect` + `setTimeout` 实现 300ms 防抖。确认生效。

- [ ] **Step 2: 在 `MoleculeAnalysisPanel` 中添加分析计算防抖与上限提示**

```typescript
import { useMemo } from 'react'

// 在组件内分析输入前检查上限
const effectiveInput = useMemo(() => {
  if (analysisInput.length > 200) {
    return analysisInput.slice(0, 200)
  }
  return analysisInput
}, [analysisInput])
```

当 `analysisInput.length > 200` 时显示提示："分析仅基于前 200 个选中分子，以减少计算时间。"

- [ ] **Step 3: 在 `MoleculeTable` 中考虑虚拟滚动**

如果 `DataTable` 组件已支持虚拟滚动，复用它；否则评估是否需要引入 `react-window`。本阶段以分页控制为主，虚拟滚动可选。

- [ ] **Step 4: Commit**

```bash
git add frontend/src/components/molecule/MoleculeAnalysisPanel.tsx
git commit -m "perf(frontend): limit analysis input size and add debounce"
```

---

## Task 13: 测试与验证

**Files:**
- Create: `frontend/src/hooks/__tests__/useMoleculeLibrary.test.ts`（如果项目有测试框架）
- Create: `frontend/src/components/molecule/__tests__/MoleculeTable.test.tsx`

**Context:** 验证核心交互逻辑。

- [ ] **Step 1: 检查测试框架**

```bash
cd frontend
cat package.json | grep -E '"vitest"|"jest"|"@testing-library"'
```

- [ ] **Step 2: 编写 `useMoleculeLibrary` 测试**

如果使用 vitest：

```typescript
// frontend/src/hooks/__tests__/useMoleculeLibrary.test.ts
import { describe, it, expect, vi, beforeEach } from 'vitest'
import { renderHook, waitFor } from '@testing-library/react'
import { useMoleculeLibrary } from '../useMoleculeLibrary'

vi.mock('../../api/tauri/molecule_admin', () => ({
  molAdminList: vi.fn(),
  molAdminSearchText: vi.fn(),
}))

import { molAdminList } from '../../api/tauri/molecule_admin'

describe('useMoleculeLibrary', () => {
  beforeEach(() => {
    vi.clearAllMocks()
  })

  it('loads molecules on mount', async () => {
    const molecules = [
      { mol_id: 'm1', name: 'A', esmiles: 'C', status: 'confirmed', activity: 10, created_at: '2026-01-01' },
    ]
    ;(molAdminList as any).mockResolvedValue(molecules)

    const { result } = renderHook(() => useMoleculeLibrary('/project'))

    await waitFor(() => expect(result.current.loading).toBe(false))
    expect(result.current.molecules).toEqual(molecules)
  })

  it('toggles selection', async () => {
    const molecules = [
      { mol_id: 'm1', name: 'A', esmiles: 'C', status: 'confirmed', activity: 10, created_at: '2026-01-01' },
    ]
    ;(molAdminList as any).mockResolvedValue(molecules)

    const { result } = renderHook(() => useMoleculeLibrary('/project'))
    await waitFor(() => expect(result.current.loading).toBe(false))

    result.current.toggleSelection('m1')
    expect(result.current.selectedIds.has('m1')).toBe(true)

    result.current.toggleSelection('m1')
    expect(result.current.selectedIds.has('m1')).toBe(false)
  })
})
```

- [ ] **Step 3: 编写 `MoleculeTable` 测试**

```typescript
// frontend/src/components/molecule/__tests__/MoleculeTable.test.tsx
import { describe, it, expect, vi } from 'vitest'
import { render, screen, fireEvent } from '@testing-library/react'
import MoleculeTable from '../MoleculeTable'

const mockMolecules = [
  { mol_id: 'm1', name: 'A', esmiles: 'C', status: 'confirmed', activity: 10, activity_type: 'IC50', units: 'nM', source_doc: 'doc1', source_type: 'text', properties: {}, tags: [], notes: '', created_at: '2026-01-01' },
]

describe('MoleculeTable', () => {
  it('renders molecule name', () => {
    render(
      <MoleculeTable
        molecules={mockMolecules}
        loading={false}
        selectedIds={new Set()}
        sort={{ field: 'name', direction: 'asc' }}
        onSort={vi.fn()}
        onToggleSelect={vi.fn()}
        onSelectRange={vi.fn()}
        onRowClick={vi.fn()}
        lastClickedId={null}
        setLastClickedId={vi.fn()}
      />,
    )
    expect(screen.getByText('A')).toBeInTheDocument()
  })

  it('calls onRowClick when row clicked', () => {
    const onRowClick = vi.fn()
    render(
      <MoleculeTable
        molecules={mockMolecules}
        loading={false}
        selectedIds={new Set()}
        sort={{ field: 'name', direction: 'asc' }}
        onSort={vi.fn()}
        onToggleSelect={vi.fn()}
        onSelectRange={vi.fn()}
        onRowClick={onRowClick}
        lastClickedId={null}
        setLastClickedId={vi.fn()}
      />,
    )
    fireEvent.click(screen.getByText('A'))
    expect(onRowClick).toHaveBeenCalledWith(mockMolecules[0])
  })
})
```

- [ ] **Step 4: 运行测试**

```bash
cd frontend
npm test -- --run
```

Expected: 新增测试通过；已有测试不回归。

- [ ] **Step 5: Commit**

```bash
git add frontend/src/hooks/__tests__/useMoleculeLibrary.test.ts \
  frontend/src/components/molecule/__tests__/MoleculeTable.test.tsx
git commit -m "test(frontend): add tests for molecule list state and table"
```

---

## Task 14: 最终验证与收尾

- [ ] **Step 1: 全量 TypeScript 检查**

```bash
cd frontend
npx tsc --noEmit
```

Expected: 零 errors。

- [ ] **Step 2: 运行 lint（如果配置了 ruff/ESLint）**

```bash
cd frontend
npx eslint src/ --ext .ts,.tsx
```

Expected: 零 errors（或仅现有 warning）。

- [ ] **Step 3: Rust 编译检查**

```bash
cd src-tauri
cargo check
```

Expected: 零 errors（本计划未改动 Rust 后端，仅做回归验证）。

- [ ] **Step 4: 手动端到端验证**

```bash
# 终端 1
cd src-tauri && cargo tauri dev

# 或仅前端
cd frontend && npm run dev
```

验证清单：
- [ ] `/molecules` 为左右分栏。
- [ ] 左侧默认表格，可切换卡片。
- [ ] 多选分子后右侧 Overview 更新。
- [ ] R-Group / Activity Cliffs tab 可正常计算。
- [ ] 高级分析工具可用。
- [ ] 点击行打开详情抽屉。
- [ ] `status=pending` 过滤进入矫正模式，详情抽屉显示 `CorrectionPanel`。
- [ ] `/analysis` 重定向到 `/molecules`。

- [ ] **Step 5: 更新 AGENTS.md / README（如必要）**

如果文档中描述了旧的 `/analysis` 或 `/molecules?tab=sar` 入口，同步更新。

- [ ] **Step 6: 最终 Commit**

```bash
git add -A
git commit -m "feat(frontend): merge molecule library and SAR analysis into unified view"
```

---

## 15. 自我审查清单

### Spec 覆盖

| 设计文档要求 | 对应 Task |
|--------------|-----------|
| 唯一入口 `/molecules` | Task 10 |
| 左侧表格/卡片视图 | Task 4, Task 5 |
| 多选驱动右侧分析 | Task 1, Task 2, Task 9 |
| 右侧 5 个分析 tab | Task 8 |
| OCR 矫正过滤模式 | Task 1, Task 6, Task 9 |
| `/analysis` 移除 SAR | Task 10 |
| Rust 后端最小改动 | 全计划复用现有命令 |
| 性能优化 | Task 12 |
| 测试 | Task 13 |

### Placeholder 扫描

- 无 TBD / TODO / "implement later"。
- 代码块已包含具体实现。
- 命令包含预期输出。

### 类型一致性

- `MoleculeStatusFilter`、`AnalysisTab` 等类型在 hooks 与组件间一致。
- `MoleculeRecord` 使用项目已有定义。
- `SARSession` 复用 `moleculesToSession`。

### 风险提醒

- `MoleculeDetailPanel` 和 `CorrectionPanel` 的现有 props 可能与示例不完全匹配，需根据实际组件调整。
- 部分图标（`TableIcon`、`GridIcon`、`CloseIcon`）可能不存在，需创建或使用替代图标。
- `SubstructureSearchPanel` 等 analytics 子组件可能不接受 `molecules` prop，需检查并调整。
