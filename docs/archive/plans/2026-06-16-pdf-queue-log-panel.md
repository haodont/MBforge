# PDF 处理队列详细日志面板实施计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 为 `ProcessingQueue` 每个任务项添加可展开的处理日志面板，订阅并展示 `EVT_INGEST_LOG` 实时日志。

**Architecture:** 前端 `ProcessingQueue` 订阅 `ingest-log` 事件并按 `doc_id` 缓存到 `Map`；每行任务渲染一个 `ChevronDown/ChevronUp` 切换按钮，点击后在行下方展开 `IngestLogPanel` 组件显示该文档的日志；日志按时间排序并自动滚动到底部。

**Tech Stack:** React 19, TypeScript 6, Tauri v2 event API, 现有 UI 组件库。

---

## 0. 文件结构

### 新增文件

| 文件 | 职责 |
|------|------|
| `frontend/src/components/project/IngestLogPanel.tsx` | 接收日志数组，渲染时间/阶段/级别/消息，处理空状态和自动滚动 |
| `frontend/src/components/project/__tests__/IngestLogPanel.test.tsx` | 测试日志面板渲染、空状态、级别颜色 |
| `frontend/src/components/project/__tests__/ProcessingQueue.logs.test.tsx` | 测试点击箭头展开/收起、订阅事件追加日志 |

### 修改文件

| 文件 | 变更 |
|------|------|
| `frontend/src/components/project/ProcessingQueue.tsx` | 导入 `IngestLogEvent`，订阅 `EVT.INGEST_LOG`，维护 `logMap` 与 `expandedLogDocs`，渲染行末箭头按钮和展开框 |
| `frontend/src/components/icons/ui.tsx` | 若不存在则新增 `ChevronDownIcon` / `ChevronUpIcon` |
| `frontend/src/styles/processing-queue.css` | 添加日志面板、日志行、展开动画样式 |

### 复用文件

| 文件 | 说明 |
|------|------|
| `frontend/src/api/tauri/ingest_queue.ts` | 复用 `IngestLogEvent` 类型 |
| `frontend/src/api/tauri-events.ts` | 复用 `EVT.INGEST_LOG` |
| `frontend/src/components/ui/Button.tsx` | 复用按钮组件 |

---

## Task 1: 确认或创建 Chevron 图标

**Files:**
- Modify: `frontend/src/components/icons/ui.tsx`

**Context:** `ProcessingQueue` 行末需要一个向下/向上的箭头图标。检查现有图标库，若不存在则创建两个简单 SVG 图标。

- [ ] **Step 1: 检查现有图标**

```bash
cd frontend
grep -r "ChevronDown\|ChevronUp" src/components/icons/ --include="*.ts" --include="*.tsx"
```

Expected: 若已有则记录路径；若无则继续下一步。

- [ ] **Step 2: 创建缺失的图标（如需要）**

在 `frontend/src/components/icons/ui.tsx` 中添加：

```tsx
export function ChevronDownIcon({ size = 16 }: { size?: number }) {
  return (
    <svg width={size} height={size} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
      <polyline points="6 9 12 15 18 9" />
    </svg>
  )
}

export function ChevronUpIcon({ size = 16 }: { size?: number }) {
  return (
    <svg width={size} height={size} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
      <polyline points="6 15 12 9 18 15" />
    </svg>
  )
}
```

- [ ] **Step 3: 运行 TypeScript 检查**

```bash
cd frontend && npx tsc --noEmit
```

Expected: 零 errors。

- [ ] **Step 4: Commit**

```bash
git add frontend/src/components/icons/ui.tsx
git commit -m "feat(frontend): add chevron icons for log panel toggle"
```

---

## Task 2: 创建 `IngestLogPanel` 组件

**Files:**
- Create: `frontend/src/components/project/IngestLogPanel.tsx`
- Create: `frontend/src/components/project/__tests__/IngestLogPanel.test.tsx`

**Context:** 独立的日志展示组件，接收日志数组，渲染列表，支持空状态和自动滚动。

- [ ] **Step 1: 编写失败的测试**

```tsx
// frontend/src/components/project/__tests__/IngestLogPanel.test.tsx
import { describe, it, expect } from 'vitest'
import { render, screen } from '@testing-library/react'
import IngestLogPanel from '../IngestLogPanel'
import type { IngestLogEvent } from '../../../api/tauri/ingest_queue'

const logs: IngestLogEvent[] = [
  { doc_id: 'd1', stage: 'inspector', level: 'info', message: '开始解析', ts_ms: 1718500000000 },
  { doc_id: 'd1', stage: 'ocr', level: 'warn', message: '第3页置信度低', ts_ms: 1718500001000 },
]

describe('IngestLogPanel', () => {
  it('renders log rows', () => {
    render(<IngestLogPanel logs={logs} />)
    expect(screen.getByText('开始解析')).toBeInTheDocument()
    expect(screen.getByText('第3页置信度低')).toBeInTheDocument()
  })

  it('shows empty state when no logs', () => {
    render(<IngestLogPanel logs={[]} />)
    expect(screen.getByText(/暂无日志/)).toBeInTheDocument()
  })
})
```

- [ ] **Step 2: 运行测试确认失败**

```bash
cd frontend && npm test -- --run src/components/project/__tests__/IngestLogPanel.test.tsx
```

Expected: FAIL — `IngestLogPanel` 未定义。

- [ ] **Step 3: 实现组件**

```tsx
// frontend/src/components/project/IngestLogPanel.tsx
import { useEffect, useRef } from 'react'
import type { IngestLogEvent } from '../../api/tauri/ingest_queue'

interface IngestLogPanelProps {
  logs: IngestLogEvent[]
}

function formatTime(tsMs: number): string {
  const d = new Date(tsMs)
  return d.toLocaleTimeString('zh-CN', { hour12: false })
}

function levelClass(level: string): string {
  switch (level.toLowerCase()) {
    case 'error':
      return 'is-error'
    case 'warn':
    case 'warning':
      return 'is-warn'
    case 'info':
    default:
      return 'is-info'
  }
}

export default function IngestLogPanel({ logs }: IngestLogPanelProps) {
  const bottomRef = useRef<HTMLDivElement | null>(null)
  const containerRef = useRef<HTMLDivElement | null>(null)

  useEffect(() => {
    if (containerRef.current) {
      containerRef.current.scrollTop = containerRef.current.scrollHeight
    }
  }, [logs])

  if (logs.length === 0) {
    return (
      <div className="ingest-log-panel is-empty">
        暂无日志，处理开始后将在此显示。
      </div>
    )
  }

  return (
    <div ref={containerRef} className="ingest-log-panel">
      {logs.map((log, index) => (
        <div key={`${log.ts_ms}-${index}`} className="ingest-log-row">
          <span className="ingest-log-time">{formatTime(log.ts_ms)}</span>
          <span className="ingest-log-stage">{log.stage}</span>
          <span className={`ingest-log-level ${levelClass(log.level)}`}>{log.level.toUpperCase()}</span>
          <span className="ingest-log-message">{log.message}</span>
        </div>
      ))}
      <div ref={bottomRef} />
    </div>
  )
}
```

- [ ] **Step 4: 运行测试确认通过**

```bash
cd frontend && npm test -- --run src/components/project/__tests__/IngestLogPanel.test.tsx
```

Expected: PASS。

- [ ] **Step 5: Commit**

```bash
git add frontend/src/components/project/IngestLogPanel.tsx \
  frontend/src/components/project/__tests__/IngestLogPanel.test.tsx
git commit -m "feat(frontend): add IngestLogPanel component for ingest logs"
```

---

## Task 3: 修改 `ProcessingQueue` 订阅事件并渲染展开按钮

**Files:**
- Modify: `frontend/src/components/project/ProcessingQueue.tsx`

**Context:** 在任务行添加日志展开按钮，订阅 `EVT.INGEST_LOG` 并缓存日志。

- [ ] **Step 1: 导入需要的类型和图标**

在 `frontend/src/components/project/ProcessingQueue.tsx` 顶部添加：

```tsx
import { ChevronDownIcon, ChevronUpIcon } from '../icons/ui'
import IngestLogPanel from './IngestLogPanel'
import type { IngestLogEvent } from '../../api/tauri/ingest_queue'
```

- [ ] **Step 2: 添加日志相关 state**

在组件内部（与其他 state 一起）添加：

```tsx
const [logMap, setLogMap] = useState<Map<string, IngestLogEvent[]>>(new Map())
const [expandedLogDocs, setExpandedLogDocs] = useState<Set<string>>(new Set())
```

- [ ] **Step 3: 订阅 EVT_INGEST_LOG**

在现有事件监听器旁添加新的 `useEffect`：

```tsx
useEffect(() => {
  let unlisten: (() => void) | null = null
  const setup = async () => {
    unlisten = await listen<IngestLogEvent>(EVT.IngestLog, (event) => {
      const payload = event.payload
      setLogMap((prev) => {
        const next = new Map(prev)
        const list = next.get(payload.doc_id) ?? []
        const updated = [...list, payload]
        if (updated.length > 200) updated.shift()
        next.set(payload.doc_id, updated)
        return next
      })
    })
  }
  void setup().catch((e: unknown) => {
    console.error('[ProcessingQueue] log listen failed:', e)
  })
  return () => {
    unlisten?.()
  }
}, [])
```

- [ ] **Step 4: 添加展开/收起函数**

```tsx
const toggleLogs = useCallback((docId: string) => {
  setExpandedLogDocs((prev) => {
    const next = new Set(prev)
    if (next.has(docId)) next.delete(docId)
    else next.add(docId)
    return next
  })
}, [])
```

- [ ] **Step 5: 在行操作区添加箭头按钮**

在 `processing-queue-item-actions` div 的最前面（或其他合适位置）添加：

```tsx
<Button
  variant="ghost"
  size="sm"
  onClick={() => toggleLogs(task.doc_id)}
  aria-label={expandedLogDocs.has(task.doc_id) ? '隐藏日志' : '显示日志'}
  title={expandedLogDocs.has(task.doc_id) ? '隐藏日志' : '显示日志'}
>
  {expandedLogDocs.has(task.doc_id) ? <ChevronUpIcon size={16} /> : <ChevronDownIcon size={16} />}
</Button>
```

- [ ] **Step 6: 在行底部添加日志展开框**

在 `motion.div` 内部、错误块之后添加：

```tsx
{expandedLogDocs.has(task.doc_id) && (
  <div className="processing-queue-log-panel">
    <IngestLogPanel logs={logMap.get(task.doc_id) ?? []} />
  </div>
)})
```

- [ ] **Step 7: 运行 TypeScript 检查**

```bash
cd frontend && npx tsc --noEmit
```

Expected: 零 errors。

- [ ] **Step 8: Commit**

```bash
git add frontend/src/components/project/ProcessingQueue.tsx
git commit -m "feat(frontend): subscribe to ingest logs and render expandable log panel per task"
```

---

## Task 4: 添加 CSS 样式

**Files:**
- Modify: `frontend/src/styles/processing-queue.css`

**Context:** 为日志面板、日志行、级别颜色、空状态添加样式。

- [ ] **Step 1: 添加样式**

在 `frontend/src/styles/processing-queue.css` 末尾追加：

```css
/* ----- Ingest log panel ----- */
.processing-queue-log-panel {
  margin-top: 12px;
  padding: 12px;
  background: var(--bg-base);
  border: 1px solid var(--border);
  border-radius: 8px;
  max-height: 240px;
  overflow: auto;
}

.ingest-log-panel {
  display: flex;
  flex-direction: column;
  gap: 6px;
}

.ingest-log-panel.is-empty {
  color: var(--text-muted);
  font-size: 0.85rem;
  text-align: center;
  padding: 16px 0;
}

.ingest-log-row {
  display: grid;
  grid-template-columns: 72px 80px 56px 1fr;
  gap: 12px;
  align-items: baseline;
  font-size: 0.8rem;
  font-family: ui-monospace, SFMono-Regular, 'SF Mono', monospace;
}

.ingest-log-time {
  color: var(--text-muted);
  white-space: nowrap;
}

.ingest-log-stage {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  padding: 2px 6px;
  border-radius: 4px;
  background: var(--accent-muted);
  color: var(--accent);
  font-size: 0.7rem;
  font-weight: 600;
  text-transform: capitalize;
  white-space: nowrap;
}

.ingest-log-level {
  font-weight: 600;
  font-size: 0.7rem;
  text-transform: uppercase;
  white-space: nowrap;
}

.ingest-log-level.is-info {
  color: var(--text-secondary);
}

.ingest-log-level.is-warn {
  color: var(--warning);
}

.ingest-log-level.is-error {
  color: var(--danger);
}

.ingest-log-message {
  color: var(--text-primary);
  word-break: break-word;
}

@media (max-width: 640px) {
  .ingest-log-row {
    grid-template-columns: 1fr;
    gap: 2px;
  }

  .ingest-log-time {
    display: none;
  }
}
```

- [ ] **Step 2: 运行 TypeScript 检查（确认无样式相关类型问题）**

```bash
cd frontend && npx tsc --noEmit
```

Expected: 零 errors。

- [ ] **Step 3: Commit**

```bash
git add frontend/src/styles/processing-queue.css
git commit -m "style(frontend): add CSS for ingest log panel"
```

---

## Task 5: 添加 `ProcessingQueue` 日志交互测试

**Files:**
- Create: `frontend/src/components/project/__tests__/ProcessingQueue.logs.test.tsx`

**Context:** 验证点击箭头展开日志框、收到事件后日志追加到对应文档。

- [ ] **Step 1: 编写测试**

```tsx
// frontend/src/components/project/__tests__/ProcessingQueue.logs.test.tsx
import { describe, it, expect, vi, beforeEach } from 'vitest'
import { render, screen, fireEvent, waitFor } from '@testing-library/react'
import ProcessingQueue from '../ProcessingQueue'
import { EVT } from '../../../api/tauri-events'

const mockListen = vi.fn()

vi.mock('@tauri-apps/api/event', () => ({
  listen: (...args: unknown[]) => mockListen(...args),
}))

vi.mock('../../../api/tauri/ingest_queue', async () => {
  const actual = await vi.importActual<typeof import('../../../api/tauri/ingest_queue')>('../../../api/tauri/ingest_queue')
  return {
    ...actual,
    ingestList: vi.fn().mockResolvedValue([
      {
        id: 't1',
        file_path: '/docs/test.pdf',
        doc_id: 'doc1',
        status: 'processing',
        stage: 'ocr',
        progress_pct: 0.5,
        pages_total: 10,
        pages_done: 5,
        details: 'OCR 处理中',
        retry_count: 0,
        max_retries: 3,
        error: null,
        file_size_bytes: 1024,
        started_at: Date.now() / 1000,
        created_at: Date.now() / 1000,
        updated_at: Date.now() / 1000,
        priority: 0,
      },
    ]),
    ingestStats: vi.fn().mockResolvedValue({
      total: 1,
      pending: 0,
      processing: 1,
      done: 0,
      failed: 0,
      cancelled: 0,
      avg_stage_durations_ms: [0, 0, 0, 0, 0],
    }),
  }
})

describe('ProcessingQueue logs', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    mockListen.mockResolvedValue(() => {})
  })

  it('expands log panel when chevron button is clicked', async () => {
    render(<ProcessingQueue projectRoot="/project" />)
    await waitFor(() => expect(screen.getByText('test.pdf')).toBeInTheDocument())

    const toggleBtn = screen.getByRole('button', { name: /显示日志|隐藏日志/ })
    fireEvent.click(toggleBtn)

    expect(screen.getByText(/暂无日志/)).toBeInTheDocument()
  })

  it('appends incoming ingest logs to the expanded panel', async () => {
    let ingestLogHandler: ((event: { payload: unknown }) => void) | null = null
    mockListen.mockImplementation(async (eventName: string, handler: (event: { payload: unknown }) => void) => {
      if (eventName === EVT.IngestLog) {
        ingestLogHandler = handler
      }
      return () => {}
    })

    render(<ProcessingQueue projectRoot="/project" />)
    await waitFor(() => expect(screen.getByText('test.pdf')).toBeInTheDocument())

    fireEvent.click(screen.getByRole('button', { name: /显示日志|隐藏日志/ }))

    ingestLogHandler?.({
      payload: {
        doc_id: 'doc1',
        stage: 'ocr',
        level: 'info',
        message: 'OCR 完成',
        ts_ms: Date.now(),
      },
    })

    await waitFor(() => expect(screen.getByText('OCR 完成')).toBeInTheDocument())
  })
})
```

- [ ] **Step 2: 运行测试确认通过**

```bash
cd frontend && npm test -- --run src/components/project/__tests__/ProcessingQueue.logs.test.tsx
```

Expected: PASS。

- [ ] **Step 3: Commit**

```bash
git add frontend/src/components/project/__tests__/ProcessingQueue.logs.test.tsx
git commit -m "test(frontend): add ProcessingQueue log panel interaction tests"
```

---

## Task 6: 最终验证与提交

- [ ] **Step 1: 全量前端 TypeScript 检查**

```bash
cd frontend && npx tsc --noEmit
```

Expected: 零 errors。

- [ ] **Step 2: 全量前端测试**

```bash
cd frontend && npm test -- --run
```

Expected: 所有测试通过。

- [ ] **Step 3: 检查 lint（可选）**

```bash
cd frontend && npm run lint
```

Expected: 无新增错误（忽略 pre-existing 错误）。

- [ ] **Step 4: 最终提交或合并准备**

如果所有检查通过，创建最终提交：

```bash
git add -A
git commit -m "feat(frontend): add expandable ingest log panel to processing queue"
```

---

## 7. 自我审查清单

### Spec 覆盖

| 设计文档要求 | 对应 Task |
|--------------|-----------|
| 每行任务末尾添加下拉箭头 | Task 3 |
| 点击后展开日志框 | Task 3 |
| 显示时间/阶段/级别/消息 | Task 2 |
| 订阅 EVT_INGEST_LOG | Task 3 |
| 每个文档最多 200 条日志 | Task 3 |
| 日志框最大高度 240px | Task 4 |
| 实时日志不持久化 | Task 3（仅内存缓存） |
| 前端测试 | Task 2, Task 5 |

### Placeholder 扫描

- 无 TBD / TODO / "implement later"。
- 代码块包含具体实现。
- 命令包含预期输出。

### 类型一致性

- `IngestLogEvent` 来自 `frontend/src/api/tauri/ingest_queue.ts`。
- `EVT.IngestLog` 来自 `frontend/src/api/tauri-events.ts`。
- `listen` 类型参数使用 `IngestLogEvent`。

### 风险提醒

- `ProcessingQueue` 现有样式使用 CSS 类；新增样式应追加到 `processing-queue.css`。
- 若 `ChevronDownIcon` / `ChevronUpIcon` 已存在，Task 1 中不重复创建。
- 测试中对 `@tauri-apps/api/event` 的 mock 方式需与项目现有测试一致；若项目使用不同 mock 模式，需调整。
