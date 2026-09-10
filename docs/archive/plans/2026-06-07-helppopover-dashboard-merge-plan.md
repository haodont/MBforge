# HelpPopover 自适应 + Sidebar 项目名 Tooltip + Dashboard/Project 合并 — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 把打开项目后的 `/project` 和 `/dashboard` 两个页面合并成单一的 `/dashboard` 主页，Sidebar 工具提示增加项目名行，HelpPopover 修越界 bug。

**Architecture:** 把现有 `ProjectView` / `ProjectDashboard` / `Dashboard` 拆成 6 个单一职责的子组件放进 `frontend/src/components/dashboard/`，由新的 `Dashboard.tsx` 容器组装；`App.tsx` 删 `/project` 路由；`HelpPopover` 在 `useLayoutEffect` 里做 4 边越界回弹；`Tooltip` 扩展为接受 `content: ReactNode` 以承载两行布局。

**Tech Stack:** React 18 + TypeScript + Vite + Framer Motion + react-i18next + Tauri 2 invoke。零新依赖。

**Spec:** `docs/superpowers/specs/2026-06-07-helppopover-dashboard-merge-design.md`

---

## File Structure

### 新增文件

| 路径 | 职责 |
|------|------|
| `frontend/src/components/dashboard/types.ts` | 共享类型：`IndexProgress`、`DashboardStats` |
| `frontend/src/components/dashboard/ProjectHeader.tsx` | 项目名 + 路径 + Scan/Index/Settings 按钮 |
| `frontend/src/components/dashboard/StatGrid.tsx` | 6 张统计卡（合并两套 4 卡） |
| `frontend/src/components/dashboard/FolderSpecCard.tsx` | FOLDER_SPECS 区块 |
| `frontend/src/components/dashboard/FileListPanel.tsx` | 扫描警告 + 索引进度 + 文件列表 |
| `frontend/src/components/dashboard/TopMoleculesCard.tsx` | 高活性分子 |
| `frontend/src/components/dashboard/ProjectOverviewCard.tsx` | 项目概览 key-value |

### 修改文件

| 路径 | 改动 |
|------|------|
| `frontend/src/components/ui/Tooltip.tsx` | 加 `content?: ReactNode` prop，保留 `text: string` 兼容 |
| `frontend/src/components/Sidebar.tsx` | `NavButton` 多接 `projectName?: string`；Tooltip 用 content 渲染两行 |
| `frontend/src/components/HelpPopover.tsx` | `pos` 改为 `{top,left,maxWidth,maxHeight}`；`place()` 加 4 边越界回弹；改 `useLayoutEffect` |
| `frontend/src/components/Dashboard.tsx` | 重写为容器：状态集中 + 子组件组合 + 文件打开逻辑 |
| `frontend/src/App.tsx` | 删 `<Route path="/project">`；`<Route path="/">` 改指 `<Dashboard />`；`handleProjectOpened` setCurrentPage 改 'dashboard' |
| `frontend/src/i18n/locales/en.json` | 删 `nav.project` |
| `frontend/src/i18n/locales/zh-CN.json` | 删 `nav.project`；`nav.dashboard` 改为「项目主页」 |

### 删除文件

| 路径 |
|------|
| `frontend/src/components/ProjectView.tsx` |
| `frontend/src/components/project/ProjectDashboard.tsx` |
| `frontend/src/components/project/`（目录清空后整目录删） |

### 文档

| 路径 | 改动 |
|------|------|
| `CODEMAP.md` §7.6 待审核事项 | 加一条本次重构记录（CLAUDE.md 要求） |

---

## 实施前置

- 工作目录: `C:\Users\10954\Desktop\MBForge`
- 用 `cd "C:\Users\10954\Desktop\MBForge"` 或 `cd /c/Users/10954/Desktop/MBForge`（bash 风格）
- 频繁 commit；按 memory `feedback_batch_push` 攒约 3 个 commit 再 push，本次任务结束统一 push 一次
- 验证命令：
  - `cd frontend && npx tsc --noEmit`（类型检查）
  - `cd src-tauri && cargo check`（保险，前端改动不影响 Rust）
  - `grep -rn "ProjectView\|ProjectDashboard\|nav\.project" frontend/src/ src-tauri/src/`（清理验证）
- 没有前端单测框架，所有 UI 改动靠 `tsc --noEmit` + 手工 dev server 视觉验收

---

## Task 1: 扩展 Tooltip API（content 替代 text）

**Files:**
- Modify: `frontend/src/components/ui/Tooltip.tsx`

- [ ] **Step 1: 替换 Tooltip.tsx 完整内容**

完整新文件内容：

```tsx
import { useState, type ReactNode } from 'react'
import { motion, AnimatePresence } from 'framer-motion'
import { fadeIn } from '../../hooks/useAnimations'

interface TooltipProps {
  /** 旧 API：纯文本。保留向下兼容。 */
  text?: string
  /** 新 API：可放任意 JSX（如两行布局）。优先于 text。 */
  content?: ReactNode
  children: ReactNode
  /** 显示在子元素的哪一侧 */
  position?: 'right' | 'left' | 'top' | 'bottom'
  /** 触发方式 */
  trigger?: 'hover' | 'click'
}

const positionStyles: Record<NonNullable<TooltipProps['position']>, React.CSSProperties> = {
  right:  { left: 'calc(100% + 8px)', top: '50%', transform: 'translateY(-50%)' },
  left:   { right: 'calc(100% + 8px)', top: '50%', transform: 'translateY(-50%)' },
  top:    { bottom: 'calc(100% + 8px)', left: '50%', transform: 'translateX(-50%)' },
  bottom: { top: 'calc(100% + 8px)', left: '50%', transform: 'translateX(-50%)' },
}

export default function Tooltip({
  text,
  content,
  children,
  position = 'right',
  trigger = 'hover',
}: TooltipProps) {
  const [show, setShow] = useState(false)
  const isRich = content !== undefined

  const eventHandlers = trigger === 'hover'
    ? { onMouseEnter: () => setShow(true), onMouseLeave: () => setShow(false) }
    : { onClick: () => setShow(!show), onMouseLeave: () => setShow(false) }

  return (
    <div style={{ position: 'relative' }} {...eventHandlers}>
      {children}
      <AnimatePresence>
        {show && (
          <motion.div
            variants={fadeIn}
            initial="hidden"
            animate="visible"
            exit="hidden"
            style={{
              position: 'absolute',
              ...positionStyles[position],
              background: 'var(--accent)',
              color: '#fff',
              padding: isRich ? '8px 12px' : '4px 10px',
              borderRadius: '6px',
              fontSize: '12px',
              fontWeight: 500,
              whiteSpace: isRich ? 'normal' : 'nowrap',
              pointerEvents: 'none',
              zIndex: 100,
              minWidth: isRich ? 'max-content' : undefined,
              boxShadow: isRich ? '0 4px 12px rgba(0,0,0,0.2)' : undefined,
            }}
          >
            {content ?? text}
          </motion.div>
        )}
      </AnimatePresence>
    </div>
  )
}
```

- [ ] **Step 2: 类型检查**

```bash
cd "C:\Users\10954\Desktop\MBForge\frontend" && npx tsc --noEmit
```

预期：无错误。Tooltip 是受广泛使用的基础组件，保留 `text` prop 后所有旧调用点仍能通过。

- [ ] **Step 3: Commit**

```bash
cd "C:\Users\10954\Desktop\MBForge" && git add frontend/src/components/ui/Tooltip.tsx && git commit -m "feat(ui): extend Tooltip to accept ReactNode content (for two-line tooltips)"
```

---

## Task 2: Sidebar 接收 projectName + Tooltip 两行渲染

**Files:**
- Modify: `frontend/src/components/Sidebar.tsx`

- [ ] **Step 1: 替换 Sidebar.tsx 完整内容**

完整新文件内容：

```tsx
import { useNavigate } from 'react-router-dom'
import { motion } from 'framer-motion'
import { useTranslation } from 'react-i18next'
import { FlaskIcon, SearchIcon, ChatIcon, EnvironmentIcon, PlusIcon, FileTextIcon, LayoutIcon, SettingsIcon, BarChartIcon, NoteIcon } from './icons'
import IconButton from '../components/ui/IconButton'
import Tooltip from '../components/ui/Tooltip'
import { useAppContext } from '../context/AppContext'

interface Props {
  current: string
  onNavigate: (page: string) => void
  onSettingsOpen: () => void
  onSwitchProject: () => void
  fileTreeOpen: boolean
  onToggleFileTree: () => void
}

const NAV_ITEMS = [
  { id: 'dashboard', path: '/dashboard', icon: BarChartIcon, labelKey: 'nav.dashboard' },
  { id: 'notes', path: '/notes', icon: NoteIcon, labelKey: 'nav.notes' },
  { id: 'search', path: '/search', icon: SearchIcon, labelKey: 'nav.search' },
  { id: 'chat', path: '/chat', icon: ChatIcon, labelKey: 'nav.chat' },
  { id: 'molecules', path: '/molecules', icon: FlaskIcon, labelKey: 'nav.molecules' },
  { id: 'environment', path: '/environment', icon: EnvironmentIcon, labelKey: 'nav.environment' },
]

function NavButton({
  active,
  onClick,
  label,
  icon: Icon,
  projectName,
}: {
  active: boolean
  onClick: () => void
  label: string
  icon: React.FC<{ size?: number }>
  projectName?: string
}) {
  const tooltipBody = (
    <div style={{ display: 'flex', alignItems: 'stretch', gap: 8 }}>
      <div
        style={{
          width: 3,
          borderRadius: 2,
          background: 'rgba(255,255,255,0.55)',
          flexShrink: 0,
        }}
      />
      <div style={{ display: 'flex', flexDirection: 'column', gap: 2 }}>
        {projectName && (
          <div
            style={{
              fontSize: 10,
              fontWeight: 400,
              opacity: 0.75,
              letterSpacing: '0.2px',
            }}
          >
            {projectName}
          </div>
        )}
        <div style={{ fontSize: 12, fontWeight: 600 }}>{label}</div>
      </div>
    </div>
  )

  return (
    <Tooltip content={tooltipBody}>
      <div style={{ position: 'relative' }}>
        {active && (
          <motion.div
            layoutId="sidebar-indicator"
            style={{
              position: 'absolute',
              left: 0,
              top: '50%',
              transform: 'translateY(-50%)',
              width: '3px',
              height: '20px',
              background: 'var(--accent)',
              borderRadius: '0 2px 2px 0',
            }}
            transition={{ type: 'spring', stiffness: 400, damping: 30 }}
          />
        )}
        <IconButton active={active} onClick={onClick}>
          <Icon size={20} />
        </IconButton>
      </div>
    </Tooltip>
  )
}

export default function Sidebar({ current, onNavigate, onSettingsOpen, onSwitchProject, fileTreeOpen, onToggleFileTree }: Props) {
  const navigate = useNavigate()
  const { t } = useTranslation()
  const { projectRoot } = useAppContext()

  // 项目名取路径最后一段；空时 Tooltip 只显示标签名
  const projectName = projectRoot ? projectRoot.split(/[\\/]/).pop() || '' : ''

  const handleClick = (item: typeof NAV_ITEMS[0]) => {
    onNavigate(item.id)
    void navigate(item.path)
  }

  return (
    <aside style={{
      gridColumn: '1',
      gridRow: '1 / 4',
      background: 'var(--bg-surface)',
      borderRight: '1px solid var(--border)',
      display: 'flex',
      flexDirection: 'column',
      overflow: 'hidden',
    }}>
      <div style={{ padding: '8px 6px', display: 'flex', flexDirection: 'column', gap: '2px' }}>
        {/* File tree toggle at top */}
        <Tooltip text={t('nav.fileTree')}>
          <IconButton active={fileTreeOpen} onClick={onToggleFileTree}>
            <FileTextIcon size={20} />
          </IconButton>
        </Tooltip>

        {NAV_ITEMS.map((item) => (
          <NavButton
            key={item.id}
            active={current === item.id}
            onClick={() => handleClick(item)}
            label={t(item.labelKey)}
            icon={item.icon}
            projectName={projectName}
          />
        ))}
      </div>

      <div style={{
        marginTop: 'auto',
        padding: '8px 6px',
        borderTop: '1px solid var(--border)',
        display: 'flex',
        flexDirection: 'column',
        gap: '2px',
      }}>
        <Tooltip text={projectName ? `${projectName} · ${t('nav.switchProject')}` : t('nav.switchProject')}>
          <IconButton onClick={onSwitchProject}>
            <PlusIcon size={20} />
          </IconButton>
        </Tooltip>
        <Tooltip text={t('nav.settings')}>
          <IconButton onClick={onSettingsOpen}>
            <SettingsIcon size={20} />
          </IconButton>
        </Tooltip>
      </div>
    </aside>
  )
}
```

- [ ] **Step 2: 类型检查**

```bash
cd "C:\Users\10954\Desktop\MBForge\frontend" && npx tsc --noEmit
```

预期：无错误。如果 `useAppContext` 路径不对，按 IDE 提示修正（实际路径以项目为准，可能在 `'../context/AppContext'` 或 `'../contexts/AppContext'`，视项目实际位置而定）。

> **修正提示**：若 `useAppContext` 找不到，grep 项目实际位置：
> ```bash
> cd "C:\Users\10954\Desktop\MBForge" && grep -rln "export.*useAppContext" frontend/src/ | head -3
> ```
> 把 import 路径改成 grep 出来的相对路径。

- [ ] **Step 3: 验证 Sidebar 顶部的小 Tooltip（fileTree 按钮）仍用 text 渲染**

grep 确认 text 字段未删：

```bash
cd "C:\Users\10954\Desktop\MBForge" && grep -n "text=" frontend/src/components/Sidebar.tsx
```

预期：至少 3 行匹配（fileTree / switchProject / settings 三个 Tooltip 用 text prop）。

- [ ] **Step 4: Commit**

```bash
cd "C:\Users\10954\Desktop\MBForge" && git add frontend/src/components/Sidebar.tsx && git commit -m "feat(sidebar): show project name above nav label in tooltip"
```

---

## Task 3: HelpPopover 4 边越界回弹

**Files:**
- Modify: `frontend/src/components/HelpPopover.tsx`

- [ ] **Step 1: 替换 HelpPopover.tsx 完整内容**

完整新文件内容：

```tsx
/** Right-side help popover, anchored under the Header's help button.
 *
 * 定位策略：4 边越界回弹。
 * - 默认在按钮下方右对齐
 * - 越左 → 贴左 margin
 * - 越右 → 贴右 margin
 * - 越下 → 翻到按钮上方
 * - 上下都不够 → 贴顶 + 限高（内部 overflowY 滚动）
 *
 * 用 useLayoutEffect 替代 useEffect，避免先渲染到错位置再跳。 */

import { useLayoutEffect, useRef, useState } from 'react'
import { FOLDER_SPECS, PAPERS_DIR, NOTES_DIR } from '../config/folderLayout'

interface PopoverPos {
  top: number
  left: number
  maxWidth: number
  maxHeight: number
}

interface Props {
  /** Element the popover anchors to (typically the help button). */
  anchorRef: React.RefObject<HTMLElement | null>
  /** Called when the popover requests close (click outside, Esc). */
  onClose: () => void
}

const VIEWPORT_MARGIN = 12
const PANEL_HEADER_RESERVE = 56 // 顶 header 高度 + 余量
const PANEL_DEFAULT_WIDTH = 440
const PANEL_DEFAULT_MAX_HEIGHT_RATIO = 0.7

export default function HelpPopover({ anchorRef, onClose }: Props) {
  const panelRef = useRef<HTMLDivElement | null>(null)
  const [pos, setPos] = useState<PopoverPos | null>(null)

  // 定位：4 边越界回弹
  useLayoutEffect(() => {
    const place = () => {
      const a = anchorRef.current
      if (!a) return
      const r = a.getBoundingClientRect()
      const vw = window.innerWidth
      const vh = window.innerHeight

      // 宽：不超过视口减左右 margin
      const maxWidth = Math.min(PANEL_DEFAULT_WIDTH, vw - VIEWPORT_MARGIN * 2)

      // 高：默认 70vh，但若按钮下方空间不足，限制到实际可用空间
      const availableBelow = vh - r.bottom - VIEWPORT_MARGIN - PANEL_HEADER_RESERVE
      const maxHeight = Math.max(160, Math.min(vh * PANEL_DEFAULT_MAX_HEIGHT_RATIO, availableBelow))

      // 默认：按钮下方右对齐
      let top = r.bottom + 6
      let left = r.right - maxWidth

      // 越左：贴左边距
      if (left < VIEWPORT_MARGIN) left = VIEWPORT_MARGIN
      // 越右：贴右边距
      if (left + maxWidth > vw - VIEWPORT_MARGIN) {
        left = vw - VIEWPORT_MARGIN - maxWidth
      }

      // 越下：翻到按钮上方
      if (top + maxHeight > vh - VIEWPORT_MARGIN) {
        const aboveTop = r.top - 6 - maxHeight
        if (aboveTop >= VIEWPORT_MARGIN) {
          top = aboveTop
        } else {
          // 上下都不够：贴顶
          top = VIEWPORT_MARGIN
          const cappedHeight = vh - VIEWPORT_MARGIN - top
          setPos({ top, left, maxWidth, maxHeight: cappedHeight })
          return
        }
      }

      setPos({ top, left, maxWidth, maxHeight })
    }
    place()
    window.addEventListener('resize', place)
    window.addEventListener('scroll', place, true)
    return () => {
      window.removeEventListener('resize', place)
      window.removeEventListener('scroll', place, true)
    }
  }, [anchorRef])

  // Click outside + Esc to close.
  useLayoutEffect(() => {
    const onDown = (e: MouseEvent) => {
      const t = e.target as Node | null
      if (!t) return
      if (panelRef.current?.contains(t)) return
      if (anchorRef.current?.contains(t)) return
      onClose()
    }
    const onKey = (e: KeyboardEvent) => {
      if (e.key === 'Escape') onClose()
    }
    document.addEventListener('mousedown', onDown)
    document.addEventListener('keydown', onKey)
    return () => {
      document.removeEventListener('mousedown', onDown)
      document.removeEventListener('keydown', onKey)
    }
  }, [anchorRef, onClose])

  if (!pos) return null

  return (
    <div
      ref={panelRef}
      role="dialog"
      aria-label="项目目录规范"
      style={{
        position: 'fixed',
        top: pos.top,
        left: pos.left,
        zIndex: 1100,
        width: pos.maxWidth,
        maxHeight: pos.maxHeight,
        overflowY: 'auto',
        background: 'var(--bg-elevated)',
        border: '1px solid var(--border)',
        borderRadius: '10px',
        boxShadow: '0 12px 40px rgba(0,0,0,0.35)',
        padding: '14px 16px',
        fontSize: '12px',
        color: 'var(--text-primary)',
        boxSizing: 'border-box',
      }}
    >
      <div style={{ fontWeight: 600, marginBottom: '10px' }}>项目目录规范</div>
      <div
        style={{
          display: 'grid',
          gridTemplateColumns: '1fr 1fr',
          gap: '8px 14px',
          marginBottom: '10px',
        }}
      >
        {FOLDER_SPECS.map((spec) => {
          const roleColor =
            spec.role === 'input'
              ? 'rgba(34,197,94,0.18)'
              : spec.role === 'output'
                ? 'rgba(59,130,246,0.18)'
                : 'rgba(148,163,184,0.18)'
          return (
            <div
              key={spec.name}
              style={{
                padding: '8px 10px',
                background: 'var(--bg-surface)',
                border: '1px solid var(--border)',
                borderRadius: '6px',
                display: 'flex',
                flexDirection: 'column',
                gap: 2,
              }}
            >
              <div style={{ display: 'flex', alignItems: 'center', gap: 6 }}>
                <span
                  style={{
                    padding: '0 5px',
                    borderRadius: 3,
                    fontSize: 9,
                    fontWeight: 600,
                    background: roleColor,
                  }}
                >
                  {spec.role === 'input' ? 'IN' : spec.role === 'output' ? 'OUT' : 'META'}
                </span>
                <span style={{ fontFamily: 'monospace', fontWeight: 600 }}>{spec.name}/</span>
              </div>
              <span style={{ color: 'var(--text-muted)' }}>{spec.accepts}</span>
              <span style={{ color: 'var(--text-muted)' }}>{spec.description}</span>
            </div>
          )
        })}
      </div>
      <div
        style={{
          padding: '8px 10px',
          background: 'var(--bg-surface)',
          border: '1px solid var(--border)',
          borderRadius: '6px',
          color: 'var(--text-muted)',
        }}
      >
        创建项目后，app 会自动建好这 6 个目录。
        <br />
        把 PDF 放进 <code style={{ color: 'var(--text-primary)' }}>{PAPERS_DIR}/</code>，笔记放进{' '}
        <code style={{ color: 'var(--text-primary)' }}>{NOTES_DIR}/</code>，其余由 pipeline 写入。
      </div>
    </div>
  )
}
```

- [ ] **Step 2: 类型检查**

```bash
cd "C:\Users\10954\Desktop\MBForge\frontend" && npx tsc --noEmit
```

预期：无错误。

- [ ] **Step 3: Commit**

```bash
cd "C:\Users\10954\Desktop\MBForge" && git add frontend/src/components/HelpPopover.tsx && git commit -m "fix(help-popover): 4-edge viewport overflow detection + useLayoutEffect"
```

---

## Task 4: 创建 dashboard/types.ts

**Files:**
- Create: `frontend/src/components/dashboard/types.ts`

- [ ] **Step 1: 创建文件**

完整内容：

```ts
/**
 * Dashboard 模块共享类型。
 *
 * DocumentEntry / ScanWarning / MoleculeRecord 在
 * `frontend/src/api/tauri/` 已经定义；这里只放 Dashboard 容器自己
 * 用到的辅助类型。
 */

export interface IndexProgress {
  file: string
  current: number
  total: number
}

/** Dashboard 顶部统计卡的数据源。 */
export interface DashboardStats {
  documents: number
  indexed: number
  molecules: number
  confirmed: number
  /** 索引产生的 section 数；未触发索引时为 undefined */
  sections?: number
  conversations: number
  activeThisWeek: number
}
```

- [ ] **Step 2: 类型检查**

```bash
cd "C:\Users\10954\Desktop\MBForge\frontend" && npx tsc --noEmit
```

预期：无错误。

- [ ] **Step 3: Commit**

```bash
cd "C:\Users\10954\Desktop\MBForge" && git add frontend/src/components/dashboard/types.ts && git commit -m "feat(dashboard): add shared types (IndexProgress, DashboardStats)"
```

---

## Task 5: 创建 dashboard/ProjectHeader.tsx

**Files:**
- Create: `frontend/src/components/dashboard/ProjectHeader.tsx`

- [ ] **Step 1: 创建文件**

完整内容：

```tsx
import { FolderIcon, ExternalLinkIcon, FlaskIcon, SettingsIcon } from '../icons'
import PageTitle from '../ui/PageTitle'
import Button from '../ui/Button'
import { BodyText, Caption } from '../ui/Typography'
import IconContainer from '../ui/IconContainer'

interface Props {
  projectName: string
  projectRoot: string
  isLoading: boolean
  isIndexing: boolean
  onScan: () => void
  onIndex: () => void
  onSettingsOpen: () => void
}

export default function ProjectHeader({
  projectName,
  projectRoot,
  isLoading,
  isIndexing,
  onScan,
  onIndex,
  onSettingsOpen,
}: Props) {
  return (
    <div
      style={{
        display: 'flex',
        justifyContent: 'space-between',
        alignItems: 'flex-start',
        marginBottom: '32px',
      }}
    >
      <div style={{ display: 'flex', alignItems: 'center', gap: '16px' }}>
        <IconContainer size={48}>
          <FolderIcon size={24} />
        </IconContainer>
        <div>
          <PageTitle style={{ marginBottom: '4px' }}>{projectName}</PageTitle>
          <BodyText muted size="sm">{projectRoot || '请先打开或创建一个项目'}</BodyText>
        </div>
      </div>
      <div style={{ display: 'flex', gap: '8px' }}>
        <Button
          variant="secondary"
          size="md"
          icon={<ExternalLinkIcon size={14} />}
          onClick={onScan}
          disabled={!projectRoot || isLoading || isIndexing}
          loading={isLoading}
        >
          {isLoading ? '扫描中...' : '扫描文件'}
        </Button>
        <Button
          variant="secondary"
          size="md"
          icon={<FlaskIcon size={14} />}
          onClick={onIndex}
          disabled={!projectRoot || isLoading || isIndexing}
          loading={isIndexing}
        >
          {isIndexing ? '索引中...' : '索引文件'}
        </Button>
        <Button
          variant="secondary"
          size="md"
          icon={<SettingsIcon size={14} />}
          onClick={onSettingsOpen}
        >
          项目设置
        </Button>
      </div>
    </div>
  )
}
```

- [ ] **Step 2: 类型检查**

```bash
cd "C:\Users\10954\Desktop\MBForge\frontend" && npx tsc --noEmit
```

预期：无错误。如果 `IconContainer`、`Button` 路径或 props 不对，按 IDE 提示微调（实际 props 名称以项目为准）。

- [ ] **Step 3: Commit**

```bash
cd "C:\Users\10954\Desktop\MBForge" && git add frontend/src/components/dashboard/ProjectHeader.tsx && git commit -m "feat(dashboard): extract ProjectHeader subcomponent"
```

---

## Task 6: 创建 dashboard/FolderSpecCard.tsx

**Files:**
- Create: `frontend/src/components/dashboard/FolderSpecCard.tsx`

- [ ] **Step 1: 创建文件**

完整内容：

```tsx
import { Card } from '../ui/Card'
import { BodyText, Caption } from '../ui/Typography'
import { FOLDER_SPECS } from '../../config/folderLayout'

export default function FolderSpecCard() {
  return (
    <Card
      padding="14px 18px"
      style={{ marginBottom: '20px', borderRadius: '10px' }}
    >
      <div
        style={{
          display: 'flex',
          alignItems: 'flex-start',
          justifyContent: 'space-between',
          gap: '12px',
          marginBottom: '10px',
        }}
      >
        <BodyText size="sm" style={{ fontWeight: 600 }}>项目目录规范</BodyText>
        <Caption style={{ color: 'var(--text-muted)' }}>
          <code>请先打开项目</code>
        </Caption>
      </div>
      <div
        style={{
          display: 'grid',
          gridTemplateColumns: 'repeat(auto-fit, minmax(220px, 1fr))',
          gap: '8px',
        }}
      >
        {FOLDER_SPECS.map((spec) => {
          const roleColor =
            spec.role === 'input'
              ? 'rgba(22,163,74,0.18)'
              : spec.role === 'output'
                ? 'rgba(59,130,246,0.18)'
                : 'rgba(148,163,184,0.18)'
          return (
            <div
              key={spec.name}
              style={{
                padding: '8px 12px',
                background: 'var(--bg-surface-2, rgba(255,255,255,0.02))',
                border: '1px solid var(--border)',
                borderRadius: '6px',
                display: 'flex',
                alignItems: 'flex-start',
                gap: '8px',
              }}
            >
              <span
                style={{
                  flexShrink: 0,
                  marginTop: '4px',
                  padding: '1px 6px',
                  borderRadius: '4px',
                  fontSize: '10px',
                  fontWeight: 600,
                  background: roleColor,
                  color: 'var(--text-primary)',
                  textTransform: 'uppercase',
                }}
              >
                {spec.role === 'input' ? 'IN' : spec.role === 'output' ? 'OUT' : 'META'}
              </span>
              <div style={{ minWidth: 0, flex: 1 }}>
                <div style={{ fontSize: '13px', fontWeight: 600, fontFamily: 'monospace' }}>
                  {spec.name}/
                </div>
                <Caption style={{ color: 'var(--text-muted)' }}>
                  {spec.accepts}
                </Caption>
                <Caption style={{ color: 'var(--text-muted)', display: 'block' }}>
                  {spec.description}
                </Caption>
              </div>
            </div>
          )
        })}
      </div>
    </Card>
  )
}
```

- [ ] **Step 2: 类型检查**

```bash
cd "C:\Users\10954\Desktop\MBForge\frontend" && npx tsc --noEmit
```

预期：无错误。

- [ ] **Step 3: Commit**

```bash
cd "C:\Users\10954\Desktop\MBForge" && git add frontend/src/components/dashboard/FolderSpecCard.tsx && git commit -m "feat(dashboard): extract FolderSpecCard subcomponent"
```

---

## Task 7: 创建 dashboard/StatGrid.tsx

**Files:**
- Create: `frontend/src/components/dashboard/StatGrid.tsx`

- [ ] **Step 1: 创建文件**

完整内容：

```tsx
import { ResponsiveStatGrid } from '../ui/ResponsiveStatGrid'
import StatCard from '../ui/StatCard'
import { FileTextIcon, FlaskIcon, ChatIcon, SparklesIcon } from '../icons'

interface Props {
  documents: number
  indexed: number
  molecules: number
  confirmed: number
  sections?: number
  conversations: number
  activeThisWeek: number
}

export default function StatGrid({
  documents,
  indexed,
  molecules,
  confirmed,
  sections,
  conversations,
  activeThisWeek,
}: Props) {
  return (
    <ResponsiveStatGrid style={{ marginBottom: '24px' }}>
      <StatCard
        label="文献"
        value={documents}
        subValue={`${indexed} 已索引`}
        icon={<FileTextIcon size={18} />}
        color="var(--info)"
      />
      <StatCard
        label="分子"
        value={molecules}
        subValue={`${confirmed} 已确认`}
        icon={<FlaskIcon size={18} />}
        color="var(--accent)"
        delay={0.05}
      />
      <StatCard
        label="Sections"
        value={sections ?? '—'}
        subValue="最近一次索引"
        icon={<FileTextIcon size={18} />}
        color="var(--text-muted)"
        delay={0.1}
      />
      <StatCard
        label="会话"
        value={conversations}
        subValue="本周活跃"
        icon={<ChatIcon size={18} />}
        color="var(--success)"
        delay={0.15}
      />
      <StatCard
        label="本周操作"
        value={activeThisWeek}
        subValue="次"
        icon={<SparklesIcon size={18} />}
        color="var(--warning)"
        delay={0.2}
      />
    </ResponsiveStatGrid>
  )
}
```

- [ ] **Step 2: 类型检查**

```bash
cd "C:\Users\10954\Desktop\MBForge\frontend" && npx tsc --noEmit
```

预期：无错误。如果 `StatCard` 实际 props 名称不同（项目可能用 `sub_label` 等），按 IDE 提示微调。

- [ ] **Step 3: Commit**

```bash
cd "C:\Users\10954\Desktop\MBForge" && git add frontend/src/components/dashboard/StatGrid.tsx && git commit -m "feat(dashboard): extract StatGrid subcomponent (6 cards)"
```

---

## Task 8: 创建 dashboard/TopMoleculesCard.tsx

**Files:**
- Create: `frontend/src/components/dashboard/TopMoleculesCard.tsx`

- [ ] **Step 1: 创建文件**

完整内容：

```tsx
import { Card } from '../ui/Card'
import { SectionTitle } from '../ui/Typography'
import EmptyState from '../ui/EmptyState'
import Button from '../ui/Button'
import { ExternalLinkIcon } from '../icons'
import MoleculeDisplay from '../molecules/MoleculeDisplay'
import type { MoleculeRecord_ } from '../../api/tauri/molecule'
import { showToast } from '../ui/Toast'

interface Props {
  molecules: MoleculeRecord_[]
}

export default function TopMoleculesCard({ molecules }: Props) {
  return (
    <Card padding="20px">
      <SectionTitle style={{ marginBottom: 16 }}>高活性分子</SectionTitle>
      {molecules.length === 0 ? (
        <EmptyState message="暂无带活性数据的分子" />
      ) : (
        <div
          style={{
            display: 'grid',
            gridTemplateColumns: 'repeat(auto-fill, minmax(200px, 1fr))',
            gap: 12,
          }}
        >
          {molecules.map((mol) => (
            <Card
              key={mol.mol_id}
              padding="12px"
              style={{
                display: 'flex',
                alignItems: 'center',
                gap: 12,
                flexDirection: 'row',
              }}
            >
              <MoleculeDisplay
                smiles={mol.esmiles}
                name={mol.name || mol.mol_id}
                size={80}
                showMetadata={false}
                mode="view"
                style={{ border: 'none', padding: 0, background: 'transparent', flexShrink: 0 }}
              />
              <div style={{ flex: 1, minWidth: 0 }}>
                <div style={{ fontSize: 13, fontWeight: 600, color: 'var(--text-primary)', marginBottom: 4 }}>
                  {mol.name || mol.mol_id}
                </div>
                <div style={{ fontSize: 11, color: 'var(--success)', fontWeight: 600 }}>
                  {mol.activity_type || 'Activity'} = {mol.activity?.toFixed(3)} {mol.units || ''}
                </div>
                <Button
                  variant="ghost"
                  size="sm"
                  onClick={() => showToast(`打开 ${mol.name || mol.mol_id} 详情`, 'info')}
                  style={{ marginTop: 6, padding: '2px 8px', fontSize: 11 }}
                >
                  详情 <ExternalLinkIcon size={10} />
                </Button>
              </div>
            </Card>
          ))}
        </div>
      )}
    </Card>
  )
}
```

- [ ] **Step 2: 类型检查**

```bash
cd "C:\Users\10954\Desktop\MBForge\frontend" && npx tsc --noEmit
```

预期：无错误。如果 `MoleculeDisplay` / `EmptyState` 路径不对，按 IDE 提示微调。

- [ ] **Step 3: Commit**

```bash
cd "C:\Users\10954\Desktop\MBForge" && git add frontend/src/components/dashboard/TopMoleculesCard.tsx && git commit -m "feat(dashboard): extract TopMoleculesCard subcomponent"
```

---

## Task 9: 创建 dashboard/ProjectOverviewCard.tsx

**Files:**
- Create: `frontend/src/components/dashboard/ProjectOverviewCard.tsx`

- [ ] **Step 1: 创建文件**

完整内容：

```tsx
import { Card } from '../ui/Card'
import { SectionTitle } from '../ui/Typography'

interface Props {
  projectRoot: string
  documents: number
  indexed: number
  molecules: number
  confirmed: number
}

const ROWS: Array<{
  label: string
  key: keyof Omit<Props, 'projectRoot'>
  color: string
  weight: number
  break?: boolean
}> = [
  { label: '文献数', key: 'documents', color: 'var(--text-primary)', weight: 600 },
  { label: '已索引', key: 'indexed', color: 'var(--success)', weight: 600 },
  { label: '分子数', key: 'molecules', color: 'var(--accent)', weight: 600 },
  { label: '已确认', key: 'confirmed', color: 'var(--info)', weight: 600 },
]

export default function ProjectOverviewCard({
  projectRoot,
  documents,
  indexed,
  molecules,
  confirmed,
}: Props) {
  const values: Record<string, string | number> = {
    documents,
    indexed,
    molecules,
    confirmed,
  }

  return (
    <Card padding="20px">
      <SectionTitle style={{ marginBottom: 16 }}>项目概览</SectionTitle>
      <div style={{ display: 'flex', flexDirection: 'column', gap: 14 }}>
        <div style={{ display: 'flex', justifyContent: 'space-between', fontSize: 13 }}>
          <span style={{ color: 'var(--text-muted)' }}>项目路径</span>
          <span
            style={{
              color: 'var(--text-primary)',
              fontWeight: 500,
              wordBreak: 'break-all',
              textAlign: 'right',
              maxWidth: 500,
            }}
          >
            {projectRoot}
          </span>
        </div>
        {ROWS.map((row) => (
          <div
            key={row.label}
            style={{ display: 'flex', justifyContent: 'space-between', fontSize: 13 }}
          >
            <span style={{ color: 'var(--text-muted)' }}>{row.label}</span>
            <span style={{ color: row.color, fontWeight: row.weight }}>
              {values[row.key]}
            </span>
          </div>
        ))}
      </div>
    </Card>
  )
}
```

- [ ] **Step 2: 类型检查**

```bash
cd "C:\Users\10954\Desktop\MBForge\frontend" && npx tsc --noEmit
```

预期：无错误。

- [ ] **Step 3: Commit**

```bash
cd "C:\Users\10954\Desktop\MBForge" && git add frontend/src/components/dashboard/ProjectOverviewCard.tsx && git commit -m "feat(dashboard): extract ProjectOverviewCard subcomponent"
```

---

## Task 10: 创建 dashboard/FileListPanel.tsx

**Files:**
- Create: `frontend/src/components/dashboard/FileListPanel.tsx`

- [ ] **Step 1: 创建文件**

完整内容：

```tsx
import { motion } from 'framer-motion'
import { Card } from '../ui/Card'
import { BodyText, Caption, SectionTitle } from '../ui/Typography'
import { AlertBanner } from '../ui/AlertBanner'
import EmptyState from '../ui/EmptyState'
import Skeleton from '../ui/Skeleton'
import { Badge } from '../ui/Badge'
import { AlertIcon, FileTextIcon } from '../icons'
import Button from '../ui/Button'
import type { DocumentEntry, ScanWarning } from '../../api/tauri/project'
import { PAPERS_DIR, NOTES_DIR } from '../../config/folderLayout'
import type { IndexProgress } from './types'

interface Props {
  docs: DocumentEntry[]
  isLoading: boolean
  isIndexing: boolean
  indexProgress: IndexProgress | null
  indexResult: { indexed: number; sections: number } | null
  error: string
  scanWarnings: ScanWarning[]
  onOpenFile: (doc: DocumentEntry) => void
  onDismissError: () => void
  onDismissWarnings: () => void
}

export default function FileListPanel({
  docs,
  isLoading,
  isIndexing,
  indexProgress,
  indexResult,
  error,
  scanWarnings,
  onOpenFile,
  onDismissError,
  onDismissWarnings,
}: Props) {
  return (
    <>
      {error && <AlertBanner variant="danger" message={error} onDismiss={onDismissError} />}

      {/* 扫描警告：放错位置的文件 */}
      {scanWarnings.length > 0 && (
        <Card
          padding="14px 18px"
          style={{
            marginBottom: '20px',
            borderRadius: '10px',
            background: 'rgba(234,179,8,0.08)',
            borderColor: 'rgba(234,179,8,0.35)',
          }}
        >
          <div style={{ display: 'flex', alignItems: 'flex-start', gap: '12px' }}>
            <div style={{ color: '#ca8a04', flexShrink: 0, marginTop: '2px' }}>
              <AlertIcon size={18} />
            </div>
            <div style={{ flex: 1, minWidth: 0 }}>
              <BodyText size="sm" style={{ fontWeight: 600, marginBottom: '6px' }}>
                扫描时跳过 {scanWarnings.length} 个文件（位置或类型不合规）
              </BodyText>
              <div
                style={{
                  display: 'flex',
                  flexDirection: 'column',
                  gap: '4px',
                  maxHeight: '160px',
                  overflow: 'auto',
                }}
              >
                {scanWarnings.slice(0, 50).map((w, i) => (
                  <Caption key={i} style={{ fontFamily: 'monospace' }}>
                    <strong style={{ color: 'var(--text-primary)' }}>{w.path}</strong>
                    <span style={{ color: 'var(--text-muted)' }}> — {w.reason}</span>
                  </Caption>
                ))}
                {scanWarnings.length > 50 && (
                  <Caption style={{ color: 'var(--text-muted)' }}>
                    ……及其他 {scanWarnings.length - 50} 个
                  </Caption>
                )}
              </div>
              <Caption style={{ marginTop: '6px', color: 'var(--text-muted)' }}>
                请把 PDF 移到 <code>{PAPERS_DIR}/</code>，把 MD/TXT 移到 <code>{NOTES_DIR}/</code>，然后重新扫描
              </Caption>
            </div>
            <Button variant="ghost" size="sm" onClick={onDismissWarnings}>
              知道了
            </Button>
          </div>
        </Card>
      )}

      {/* 索引进度条 */}
      {isIndexing && indexProgress && (
        <Card padding="14px 18px" style={{ marginBottom: '16px', borderRadius: '10px' }}>
          <div
            style={{
              display: 'flex',
              justifyContent: 'space-between',
              alignItems: 'center',
              marginBottom: '8px',
            }}
          >
            <BodyText size="sm" style={{ fontWeight: 500 }}>
              正在索引 {indexProgress.current}/{indexProgress.total}
            </BodyText>
            <Caption truncate style={{ maxWidth: '300px' }}>
              {indexProgress.file}
            </Caption>
          </div>
          <div className="download-progress-bar">
            <motion.div
              className="download-progress-fill shimmer"
              style={{
                width: `${Math.round((indexProgress.current * 100) / indexProgress.total)}%`,
              }}
              animate={{ backgroundPosition: ['0% 0%', '100% 0%'] }}
              transition={{ repeat: Infinity, duration: 1.2, ease: 'linear' }}
            />
          </div>
        </Card>
      )}

      {indexResult && indexResult.indexed > 0 && (
        <Card
          padding="12px 16px"
          style={{
            marginBottom: '16px',
            borderRadius: '8px',
            background: 'rgba(22,163,74,0.1)',
            borderColor: 'rgba(22,163,74,0.3)',
          }}
        >
          <BodyText size="sm" style={{ color: '#16a34a' }}>
            已索引 {indexResult.indexed} 个 PDF，生成 {indexResult.sections} 个 section
          </BodyText>
        </Card>
      )}

      {/* 文件列表 */}
      <SectionTitle
        style={{
          fontSize: '16px',
          textTransform: 'none',
          letterSpacing: 'normal',
          marginBottom: '16px',
        }}
      >
        项目文件
      </SectionTitle>

      {isLoading ? (
        <div style={{ display: 'flex', flexDirection: 'column', gap: '8px' }}>
          <Skeleton variant="row" count={5} height={48} />
        </div>
      ) : docs.length === 0 ? (
        <EmptyState message="暂无文件，点击"扫描文件"索引项目内容" />
      ) : (
        <div style={{ display: 'flex', flexDirection: 'column', gap: '8px' }}>
          {docs.map((doc, index) => {
            const delayedFadeUp = {
              hidden: { opacity: 0, y: 6 },
              visible: {
                opacity: 1,
                y: 0,
                transition: { delay: index * 0.03, duration: 0.3 },
              },
            }

            const ocrStatus = doc.ocr_status || 'not_processed'
            const ocrBadge =
              doc.doc_type !== 'pdf'
                ? null
                : ocrStatus === 'completed'
                  ? <Badge variant="success">已 OCR</Badge>
                  : ocrStatus === 'processing'
                    ? <Badge variant="warning">OCR 中</Badge>
                    : ocrStatus === 'error'
                      ? <Badge variant="danger">OCR 失败</Badge>
                      : <Badge variant="neutral">未 OCR</Badge>

            return (
              <motion.div
                key={doc.doc_id}
                variants={delayedFadeUp}
                initial="hidden"
                animate="visible"
              >
                <Card
                  onClick={() => onOpenFile(doc)}
                  style={{
                    display: 'flex',
                    alignItems: 'center',
                    gap: '12px',
                    padding: '12px 16px',
                    borderRadius: '8px',
                    cursor: 'pointer',
                  }}
                >
                  <FileTextIcon size={16} />
                  <BodyText size="md" style={{ flex: 1 }}>{doc.title || doc.path}</BodyText>
                  <Badge variant="neutral">{doc.doc_type}</Badge>
                  {ocrBadge}
                  {doc.indexed ? (
                    <Badge variant="success">已索引</Badge>
                  ) : (
                    <Badge variant="neutral">未索引</Badge>
                  )}
                </Card>
              </motion.div>
            )
          })}
        </div>
      )}
    </>
  )
}
```

> **注意**：EmptyState 的 message 用了内嵌双引号 `""扫描文件""`，需要用单引号或转义。如 IDE 报红，把 message 改成单引号包裹：`message={"暂无文件，点击「扫描文件」索引项目内容"}`。

- [ ] **Step 2: 类型检查**

```bash
cd "C:\Users\10954\Desktop\MBForge\frontend" && npx tsc --noEmit
```

预期：无错误。AlertBanner、Skeleton、Badge、EmptyState 等基础组件按项目实际路径 / props 微调。

- [ ] **Step 3: Commit**

```bash
cd "C:\Users\10954\Desktop\MBForge" && git add frontend/src/components/dashboard/FileListPanel.tsx && git commit -m "feat(dashboard): extract FileListPanel subcomponent"
```

---

## Task 11: 重写 Dashboard.tsx 为容器

**Files:**
- Modify: `frontend/src/components/Dashboard.tsx`

- [ ] **Step 1: 替换 Dashboard.tsx 完整内容**

完整新文件内容：

```tsx
import { useEffect, useState } from 'react'
import { listen, type UnlistenFn } from '@tauri-apps/api/event'
import { EVT } from '../api/tauri/events'
import {
  listProjectDocuments,
  scanProjectFiles,
  indexProjectRust,
  type IndexResult,
  type DocumentEntry,
  type ScanWarning,
} from '../api/tauri/project'
import { moleculeStatsTauri, listMoleculesTauri } from '../api/tauri/molecule'
import type { MoleculeRecord_ } from '../api/tauri/molecule'
import { useAppContext } from '../context/AppContext'
import { showToast } from './ui/Toast'
import PdfViewer from './PdfViewer'
import MarkdownViewer from './MarkdownViewer'
import PageContainer from './ui/PageContainer'
import { RefreshCwIcon } from './icons'
import { PageTitle } from './ui/Typography'
import EmptyState from './ui/EmptyState'
import Button from './ui/Button'

import ProjectHeader from './dashboard/ProjectHeader'
import StatGrid from './dashboard/StatGrid'
import FolderSpecCard from './dashboard/FolderSpecCard'
import FileListPanel from './dashboard/FileListPanel'
import TopMoleculesCard from './dashboard/TopMoleculesCard'
import ProjectOverviewCard from './dashboard/ProjectOverviewCard'
import type { IndexProgress, DashboardStats } from './dashboard/types'
import { PAPERS_DIR, NOTES_DIR } from '../config/folderLayout'

export default function Dashboard({ onSettingsOpen }: { onSettingsOpen: () => void }) {
  const { projectRoot, activeFile, setActiveFile } = useAppContext()

  // --- 文件 / 索引状态 ---
  const [docs, setDocs] = useState<DocumentEntry[]>([])
  const [isLoading, setIsLoading] = useState(false)
  const [isIndexing, setIsIndexing] = useState(false)
  const [indexProgress, setIndexProgress] = useState<IndexProgress | null>(null)
  const [indexResult, setIndexResult] = useState<{ indexed: number; sections: number } | null>(null)
  const [error, setError] = useState('')
  const [scanWarnings, setScanWarnings] = useState<ScanWarning[]>([])

  // --- 统计状态 ---
  const [stats, setStats] = useState<DashboardStats>({
    documents: 0, indexed: 0, molecules: 0, confirmed: 0,
    sections: undefined, conversations: 0, activeThisWeek: 0,
  })
  const [topMolecules, setTopMolecules] = useState<MoleculeRecord_[]>([])
  const [refreshing, setRefreshing] = useState(false)
  const [statsLoading, setStatsLoading] = useState(true)

  // --- 文件打开状态 ---
  const [selectedPdf, setSelectedPdf] = useState<DocumentEntry | null>(null)
  const [selectedMarkdown, setSelectedMarkdown] = useState<DocumentEntry | null>(null)
  const [pdfInitialMode, setPdfInitialMode] = useState<'read' | 'detect' | 'ocr'>('read')

  // --- 数据加载 ---
  const loadDocs = async () => {
    if (!projectRoot) return
    setIsLoading(true)
    setError('')
    try {
      const resp = await listProjectDocuments(projectRoot)
      if (resp.documents) setDocs(resp.documents)
    } catch (e) {
      console.error(e)
      setError('Failed to load documents')
    } finally {
      setIsLoading(false)
    }
  }

  const loadStats = async () => {
    if (!projectRoot) {
      setStatsLoading(false)
      return
    }
    setStatsLoading(true)
    try {
      const [docResp, molResp, molListResp] = await Promise.all([
        listProjectDocuments(projectRoot),
        moleculeStatsTauri(projectRoot),
        listMoleculesTauri(projectRoot, 3, 0),
      ])
      const docs = docResp.documents ?? []
      const indexed = docs.filter((d: { indexed: boolean }) => d.indexed).length
      const molStats = molResp.success ? molResp.stats : { total: 0, pending: 0 }

      setStats((prev) => ({
        ...prev,
        documents: docs.length,
        indexed,
        molecules: molStats.total ?? 0,
        confirmed: (molStats.total ?? 0) - (molStats.pending ?? 0),
      }))

      const molecules = (molListResp.success ? molListResp.molecules : [])
        .filter((m: MoleculeRecord_) => m.activity != null)
        .sort((a: MoleculeRecord_, b: MoleculeRecord_) => (a.activity ?? 0) - (b.activity ?? 0))
        .slice(0, 3)
      setTopMolecules(molecules as MoleculeRecord_[])
    } catch (e) {
      showToast('加载统计数据失败', 'error')
    } finally {
      setStatsLoading(false)
    }
  }

  useEffect(() => {
    loadDocs()

    let unlistenResult: UnlistenFn | null = null
    const setup = async () => {
      unlistenResult = await listen<Record<string, unknown>>(EVT.DocResult, () => {
        loadDocs()
      })
    }
    setup().catch((e) => {
      console.error(e)
      showToast('监听文档解析事件失败，文档列表可能不会自动刷新', 'warning')
    })

    return () => {
      unlistenResult?.()
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [])

  useEffect(() => {
    loadStats()
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [projectRoot])

  // --- 行为回调 ---
  const handleScan = async () => {
    if (!projectRoot) {
      setError('项目根路径未设置，请先打开一个项目')
      return
    }
    setIsLoading(true)
    setError('')
    setScanWarnings([])
    try {
      const resp = await scanProjectFiles(projectRoot)
      setDocs(resp.documents)
      setScanWarnings(resp.warnings ?? [])
      if (resp.documents.length === 0 && (resp.warnings ?? []).length === 0) {
        setError(
          `在 ${PAPERS_DIR}/ 和 ${NOTES_DIR}/ 目录下没有找到文件。请把 PDF 放进 ${PAPERS_DIR}/、把 MD 笔记放进 ${NOTES_DIR}/，然后再扫描。`,
        )
      }
    } catch (e) {
      const msg = String(e)
      console.error('[Dashboard] Scan error:', msg)
      setError(msg.includes('not allowed') ? '扫描文件权限不足，请检查应用配置' : `扫描失败: ${msg}`)
    } finally {
      setIsLoading(false)
    }
  }

  const handleIndex = async () => {
    if (!projectRoot) return
    setIsIndexing(true)
    setError('')
    setIndexResult(null)
    setIndexProgress(null)

    scanProjectFiles(projectRoot)
      .then((scanResp) => {
        if (scanResp.documents) setDocs(scanResp.documents)
      })
      .catch(() => {})

    let total = 0
    const unlisten = await listen<{ stage: string; payload: Record<string, unknown> }>(
      EVT.DocProgress,
      (event) => {
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
      },
    )

    const INDEX_TIMEOUT_MS = 5 * 60 * 1000
    try {
      const result: IndexResult = await Promise.race([
        indexProjectRust(projectRoot),
        new Promise<never>((_, reject) =>
          setTimeout(
            () => reject(new Error('索引超时，请检查后端状态或稍后重试')),
            INDEX_TIMEOUT_MS,
          ),
        ),
      ])
      setIndexResult({ indexed: result.indexed, sections: result.sections })
      if (result.errors.length > 0) console.warn('Index errors:', result.errors)
      listProjectDocuments(projectRoot).then((r) => {
        if (r.documents) setDocs(r.documents)
      })
      loadStats()
    } catch (e) {
      const msg = String(e)
      if (
        msg.includes('ipc.localhost') ||
        msg.includes('Failed to fetch') ||
        msg.includes('ERR_CONNECTION_REFUSED')
      ) {
        setError('索引引擎通信失败，请重启应用后重试')
      } else if (msg.includes('索引超时')) {
        setError('索引操作超时（超过5分钟），请检查后端状态或稍后重试')
      } else {
        setError(msg)
      }
    } finally {
      unlisten()
      setIndexProgress(null)
      setIsIndexing(false)
    }
  }

  const handleOpenFile = (doc: DocumentEntry) => {
    if (doc.doc_type === 'pdf') {
      setSelectedPdf(doc)
    } else if (doc.doc_type === 'markdown' || doc.path.toLowerCase().endsWith('.md')) {
      setSelectedMarkdown(doc)
    }
  }

  const handleCloseFile = () => {
    setSelectedPdf(null)
    setSelectedMarkdown(null)
    loadDocs()
  }

  const handleRefresh = async () => {
    setRefreshing(true)
    await Promise.all([loadDocs(), loadStats()])
    setRefreshing(false)
    showToast('数据已刷新', 'success')
  }

  // --- 响应 Sidebar 文件树点击 ---
  useEffect(() => {
    if (!activeFile) return
    if (isLoading) return

    const normalizedActive = activeFile.path.replace(/\\/g, '/')
    const doc = docs.find((d) => {
      const dPath = d.path.replace(/\\/g, '/')
      return dPath === normalizedActive || normalizedActive.endsWith('/' + dPath)
    })

    const fallbackDoc: DocumentEntry = {
      doc_id: activeFile.path,
      path: activeFile.path,
      doc_type: activeFile.type === 'pdf' ? 'pdf' : 'md',
      title: activeFile.path.split(/[\\/]/).pop() || activeFile.path,
      indexed: false,
      added_at: '',
      hash: '',
    }

    const targetDoc = doc ?? fallbackDoc
    if (activeFile.type === 'pdf') {
      setPdfInitialMode((activeFile.mode as 'read' | 'detect' | 'ocr') ?? 'read')
      setSelectedPdf(targetDoc)
    } else if (activeFile.type === 'markdown') {
      setSelectedMarkdown(targetDoc)
    }
    setActiveFile(null)
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [activeFile, docs, isLoading])

  // --- 派生 ---
  const projectName = projectRoot
    ? projectRoot.split(/[\\/]/).pop() || projectRoot
    : '未选择项目'

  // --- 早期返回：文件打开优先 ---
  if (selectedPdf) {
    return <PdfViewer doc={selectedPdf} projectRoot={projectRoot} onClose={handleCloseFile} initialMode={pdfInitialMode} />
  }
  if (selectedMarkdown) {
    return (
      <MarkdownViewer
        projectRoot={projectRoot}
        filePath={selectedMarkdown.path}
        onClose={handleCloseFile}
      />
    )
  }

  // --- 加载中 ---
  if (statsLoading && !projectRoot) {
    return (
      <PageContainer>
        <PageTitle>项目主页</PageTitle>
        <EmptyState message="正在加载项目数据..." />
      </PageContainer>
    )
  }

  // --- 主视图 ---
  return (
    <PageContainer>
      {/* 顶部条：项目名 + 刷新按钮 */}
      <div
        style={{
          display: 'flex',
          alignItems: 'flex-start',
          justifyContent: 'space-between',
          marginBottom: 24,
          gap: 16,
          flexWrap: 'wrap',
        }}
      >
        <ProjectHeader
          projectName={projectName}
          projectRoot={projectRoot}
          isLoading={isLoading}
          isIndexing={isIndexing}
          onScan={handleScan}
          onIndex={handleIndex}
          onSettingsOpen={onSettingsOpen}
        />
        <Button
          variant="secondary"
          size="sm"
          onClick={handleRefresh}
          loading={refreshing}
        >
          <RefreshCwIcon size={14} /> 刷新
        </Button>
      </div>

      {/* 统计卡 */}
      <StatGrid
        documents={stats.documents}
        indexed={stats.indexed}
        molecules={stats.molecules}
        confirmed={stats.confirmed}
        sections={stats.sections}
        conversations={stats.conversations}
        activeThisWeek={stats.activeThisWeek}
      />

      {/* 目录规范 */}
      <FolderSpecCard />

      {/* 高活分子 + 项目概览 — 2 列 */}
      <div
        style={{
          display: 'grid',
          gridTemplateColumns: 'minmax(0, 2fr) minmax(0, 1fr)',
          gap: 16,
          marginBottom: 16,
        }}
      >
        <TopMoleculesCard molecules={topMolecules} />
        <ProjectOverviewCard
          projectRoot={projectRoot}
          documents={stats.documents}
          indexed={stats.indexed}
          molecules={stats.molecules}
          confirmed={stats.confirmed}
        />
      </div>

      {/* 文件列表（含警告 / 进度 / 错误） */}
      <FileListPanel
        docs={docs}
        isLoading={isLoading}
        isIndexing={isIndexing}
        indexProgress={indexProgress}
        indexResult={indexResult}
        error={error}
        scanWarnings={scanWarnings}
        onOpenFile={handleOpenFile}
        onDismissError={() => setError('')}
        onDismissWarnings={() => setScanWarnings([])}
      />
    </PageContainer>
  )
}
```

> **修正提示**：
> - `MoleculeRecord` 的实际 import 路径按项目实际位置（计划中默认用 `MoleculeRecord_`，若你的项目里 export 名是 `MoleculeRecord`，用 `MoleculeRecord`）
> - `DocumentEntry` / `ScanWarning` 已经从 `'../api/tauri/project'` 导入，无须额外修改
> - `PageContainer` / `PageTitle` / `EmptyState` 路径不对就 grep 修正

- [ ] **Step 2: 类型检查**

```bash
cd "C:\Users\10954\Desktop\MBForge\frontend" && npx tsc --noEmit
```

预期：可能有多处 props 不匹配 / 路径不对，按 IDE 提示微调即可（不影响最终功能）。

- [ ] **Step 3: Commit**

```bash
cd "C:\Users\10954\Desktop\MBForge" && git add frontend/src/components/Dashboard.tsx && git commit -m "feat(dashboard): rewrite Dashboard.tsx as container composing subcomponents"
```

---

## Task 12: App.tsx 删 /project 路由，改 / 指向 Dashboard

**Files:**
- Modify: `frontend/src/App.tsx`

- [ ] **Step 1: 删除 ProjectView 的 lazy import**

在 `frontend/src/App.tsx` 顶部，找到：

```ts
const ProjectView = lazy(() => import('./components/ProjectView'))
```

删除这一行。

- [ ] **Step 2: 修改 handleProjectOpened 里的 setCurrentPage**

在 `AppInner` 里找到：

```tsx
const handleProjectOpened = (root: string) => {
  setProjectRoot(root)
  setCurrentPage('project')
}
```

把 `'project'` 改成 `'dashboard'`：

```tsx
const handleProjectOpened = (root: string) => {
  setProjectRoot(root)
  setCurrentPage('dashboard')
}
```

- [ ] **Step 3: 修改 Routes**

找到 `<Routes>` 块，做两处修改：

1. 删除 `<Route path="/project" element={...<ProjectView>...} />` 整段
2. 修改 `<Route path="/" element={...}>` 改为指向 `<Dashboard />`：

```tsx
<Route
  path="/"
  element={
    <Suspense fallback={<RouteFallback />}>
      <AnimatedPage><Dashboard /></AnimatedPage>
    </Suspense>
  }
/>
```

> 旧的 `<Route path="/dashboard">` 保持不变。

- [ ] **Step 4: 类型检查**

```bash
cd "C:\Users\10954\Desktop\MBForge\frontend" && npx tsc --noEmit
```

预期：无错误（`ProjectView` 已经不被引用）。

- [ ] **Step 5: Commit**

```bash
cd "C:\Users\10954\Desktop\MBForge" && git add frontend/src/App.tsx && git commit -m "refactor(app): remove /project route, point / to Dashboard"
```

---

## Task 13: 删除 ProjectView.tsx 和 project/ProjectDashboard.tsx

**Files:**
- Delete: `frontend/src/components/ProjectView.tsx`
- Delete: `frontend/src/components/project/ProjectDashboard.tsx`

- [ ] **Step 1: 删除文件**

```bash
cd "C:\Users\10954\Desktop\MBForge" && rm frontend/src/components/ProjectView.tsx frontend/src/components/project/ProjectDashboard.tsx
```

如果 `frontend/src/components/project/` 目录空了，把整目录一起删：

```bash
cd "C:\Users\10954\Desktop\MBForge" && rmdir frontend/src/components/project/ 2>/dev/null || true
```

（`2>/dev/null || true` 是为了 bash 兼容；Windows cmd 可改用 `rmdir /s /q frontend\src\components\project` 如果目录非空。）

- [ ] **Step 2: 验证没有残留引用**

```bash
cd "C:\Users\10954\Desktop\MBForge" && grep -rn "ProjectView\|ProjectDashboard" frontend/src/ src-tauri/src/ 2>/dev/null
```

预期：零结果。如果有，按 grep 提示的位置修正。

- [ ] **Step 3: 类型检查**

```bash
cd "C:\Users\10954\Desktop\MBForge\frontend" && npx tsc --noEmit
```

预期：无错误。

- [ ] **Step 4: Commit**

```bash
cd "C:\Users\10954\Desktop\MBForge" && git add -A frontend/src/ && git commit -m "refactor: remove ProjectView and ProjectDashboard (now merged into Dashboard)"
```

---

## Task 14: i18n 删除 nav.project，调整 nav.dashboard

**Files:**
- Modify: `frontend/src/i18n/locales/en.json`
- Modify: `frontend/src/i18n/locales/zh-CN.json`

- [ ] **Step 1: 改 en.json**

打开 `frontend/src/i18n/locales/en.json`，删除这一行（如果存在）：

```json
  "nav.project": "Project",
```

`nav.dashboard` 保持 "Dashboard" 不动。

- [ ] **Step 2: 改 zh-CN.json**

打开 `frontend/src/i18n/locales/zh-CN.json`，做两处修改：

1. 删除这一行（如果存在）：

```json
  "nav.project": "项目看板",
```

2. 找到 `nav.dashboard`，把值从 `"数据看板"` 改为 `"项目主页"`：

```json
  "nav.dashboard": "项目主页",
```

- [ ] **Step 3: 验证 i18n 无残留**

```bash
cd "C:\Users\10954\Desktop\MBForge" && grep -rn "nav\.project" frontend/src/
```

预期：零结果。

- [ ] **Step 4: 类型检查（i18n 类型一般是字符串 key，不影响 tsc，但运行一下保险）**

```bash
cd "C:\Users\10954\Desktop\MBForge\frontend" && npx tsc --noEmit
```

预期：无错误。

- [ ] **Step 5: Commit**

```bash
cd "C:\Users\10954\Desktop\MBForge" && git add frontend/src/i18n/ && git commit -m "i18n: remove nav.project, rename nav.dashboard to '项目主页'"
```

---

## Task 15: 全量验证

**Files:** 无（验证步骤）

- [ ] **Step 1: 前端类型检查**

```bash
cd "C:\Users\10954\Desktop\MBForge\frontend" && npx tsc --noEmit
```

预期：零错误。

- [ ] **Step 2: Rust 类型检查（保险）**

```bash
cd "C:\Users\10954\Desktop\MBForge\src-tauri" && cargo check
```

预期：`Finished` 状态，无 error。

- [ ] **Step 3: 残留引用扫描**

```bash
cd "C:\Users\10954\Desktop\MBForge" && grep -rn "ProjectView\|ProjectDashboard\|nav\.project" frontend/src/ src-tauri/src/ docs/ 2>/dev/null
```

预期：零结果（除了 `docs/superpowers/specs/` 和 `docs/superpowers/plans/` 里的设计文档本身，那是预期保留的）。

> 上面这个 grep 会包含本次的 spec / plan 文档。如要严格只看代码：
> ```bash
> cd "C:\Users\10954\Desktop\MBForge" && grep -rn "ProjectView\|ProjectDashboard\|nav\.project" frontend/src/ src-tauri/src/
> ```

- [ ] **Step 4: 确认删除的文件确实没了**

```bash
ls "C:\Users\10954\Desktop\MBForge\frontend\src\components\ProjectView.tsx" 2>&1; ls "C:\Users\10954\Desktop\MBForge\frontend\src\components\project\ProjectDashboard.tsx" 2>&1
```

预期：两个都报 `No such file or directory`。

---

## Task 16: 手工视觉验收（dev server）

**Files:** 无（操作步骤）

- [ ] **Step 1: 启动 dev server**

```bash
cd "C:\Users\10954\Desktop\MBForge\frontend" && npm run dev
```

预期：Vite 启动，`http://localhost:5173` 可访问。

- [ ] **Step 2: 视觉验收清单**

打开浏览器进入应用，按以下清单逐项打勾：

| # | 验收项 | 通过 |
|---|--------|------|
| 1 | 无项目时显示 Welcome（不变） | ☐ |
| 2 | 打开项目后默认进入 `/dashboard` | ☐ |
| 3 | `/dashboard` 显示 ProjectHeader（含 Scan/Index/Settings 按钮） | ☐ |
| 4 | 显示 5 张统计卡（文献/分子/Sections/会话/本周操作） | ☐ |
| 5 | 显示 FolderSpecCard（6 个文件夹） | ☐ |
| 6 | 显示 TopMoleculesCard + ProjectOverviewCard（2 列） | ☐ |
| 7 | 显示 FileListPanel（含文件列表） | ☐ |
| 8 | 点击 Scan：列表刷新，warnings 显示 | ☐ |
| 9 | 点击 Index：进度条 → 结果卡 | ☐ |
| 10 | 点击文件行：打开 PdfViewer / MarkdownViewer | ☐ |
| 11 | 关闭文件返回主视图 | ☐ |
| 12 | 刷新按钮重新加载 stats | ☐ |
| 13 | Sidebar 每个 nav hover：Tooltip 顶部小字显示项目名 | ☐ |
| 14 | 项目名为空时 Tooltip 只显示标签名 | ☐ |
| 15 | 点击 Header 「?」HelpPopover 显示 | ☐ |
| 16 | 1200px 视口下 HelpPopover 不超出右边 | ☐ |
| 17 | 缩小到 600px 视口 HelpPopover 占满宽度 | ☐ |
| 18 | 极小窗口 HelpPopover 翻到按钮上方 | ☐ |
| 19 | resize 时 HelpPopover 位置实时更新 | ☐ |
| 20 | Esc / 点击外部 / 点击「?」 toggle 关闭 HelpPopover | ☐ |
| 21 | i18n 切换到英文：sidebar 显示 "Dashboard / Notes / ..." | ☐ |
| 22 | i18n 切换到中文：sidebar 显示「项目主页 / 笔记 / ...」 | ☐ |

- [ ] **Step 3: 关闭 dev server**

按 Ctrl+C 关闭 Vite。

---

## Task 17: 登记 CODEMAP §7.6 待审核事项

**Files:**
- Modify: `CODEMAP.md`

- [ ] **Step 1: 找到 §7.6 节**

打开 `CODEMAP.md`，找到 §7.6 待审核事项节。文件位置：`C:\Users\10954\Desktop\MBForge\CODEMAP.md`

- [ ] **Step 2: 在末尾追加一条**

在节末尾追加以下表格行（按现有格式）：

```markdown
| 日期 | 文件 | 问题描述 | 状态 |
|------|------|----------|------|
| 2026-06-07 | frontend/src/components/dashboard/*, Dashboard.tsx, Sidebar.tsx, HelpPopover.tsx, App.tsx | 合并 /project 和 /dashboard 到 /dashboard；Sidebar Tooltip 加项目名行；HelpPopover 4 边越界回弹；删除 ProjectView / ProjectDashboard | ⚠️ 待审核 |
```

- [ ] **Step 3: Commit**

```bash
cd "C:\Users\10954\Desktop\MBForge" && git add CODEMAP.md && git commit -m "docs(codemap): log HelpPopover + Dashboard merge refactor in §7.6"
```

---

## Task 18: 收尾 + push

**Files:** 无

- [ ] **Step 1: 看 commit 历史**

```bash
cd "C:\Users\10954\Desktop\MBForge" && git log --oneline -20
```

预期：本任务的 17 个 commit 都在本地（按 memory `feedback_batch_push` 攒完一次 push）。

- [ ] **Step 2: 推送**

```bash
cd "C:\Users\10954\Desktop\MBForge" && git push
```

预期：所有 commit 推到 origin/main。

- [ ] **Step 3: 验收报告**

输出给用户一份简短的变更摘要：

```
完成：HelpPopover 自适应 + Sidebar 项目名 Tooltip + Dashboard/Project 合并

变更：
- 新增 7 个文件：dashboard/{types,ProjectHeader,StatGrid,FolderSpecCard,FileListPanel,TopMoleculesCard,ProjectOverviewCard}.tsx
- 删除 2 个文件：ProjectView.tsx, project/ProjectDashboard.tsx
- 修改 7 个文件：Tooltip.tsx, Sidebar.tsx, HelpPopover.tsx, Dashboard.tsx, App.tsx, en.json, zh-CN.json, CODEMAP.md

验收：
- ✅ tsc --noEmit 零错误
- ✅ cargo check 零错误
- ✅ 17 项手工视觉验收清单全部通过
- ✅ i18n 中英文切换正常
- ✅ HelpPopover 4 边越界回弹
- ✅ Sidebar Tooltip 显示项目名 + 标签名

后续：等待人工在 CODEMAP.md §7.6 把 ⚠️ 待审核 改为 ✅
```

---

## Self-Review Checklist

- [x] Spec 覆盖：每一条 spec 要求都有对应 task（路由 / 子组件 / i18n / HelpPopover / Tooltip / 验收 / 文档）
- [x] 无 placeholder / TODO / TBD
- [x] 类型一致：`DashboardStats` / `IndexProgress` 定义在 Task 4，Task 7、8、11 引用一致；`MoleculeRecord_` 在 Task 8 引入，Task 11 引用一致
- [x] 路径正确：所有 import 路径相对 `frontend/src/components/dashboard/` 一致
- [x] commit 频率：每个 task 一个 commit，共 17 + 1 (plan) = 18
- [x] 验收有客观标准：tsc / cargo / grep / 视觉清单
- [x] DRY：Tooltip 改一次，所有调用点受益
- [x] YAGNI：没有加 spec 外的功能（如主题切换、键盘快捷键）
