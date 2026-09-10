# Discover URL Search Bridge Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 让 `/discover?q=关键词` 在首次进入及同页 `q` 变化时同步搜索框并自动执行一次搜索，同时保持普通输入为本地状态。

**Architecture:** `Discover` 负责读取路由 `q` 并维护受控搜索框值；它把路由值作为独立 `autoSearchQuery` 传给 `SearchTab`。`SearchTab` 只监听 `autoSearchQuery` 触发请求，因此本地键入不会自动请求或写回 URL。

**Tech Stack:** React 19、React Router 7、TypeScript 6、Vitest 4、Testing Library

---

## File map

- Create: `frontend/src/components/discover/__tests__/Discover.test.tsx` — 覆盖路由参数、受控输入和自动搜索之间的集成行为。
- Modify: `frontend/src/components/discover/Discover.tsx` — 读取并同步 `q`，向 `SearchTab` 传递独立自动搜索值。
- Modify: `frontend/src/components/discover/SearchTab.tsx` — 监听 `autoSearchQuery`，不监听用户编辑的 `query`。
- Preserve: `frontend/src/components/discover/__tests__/SearchTab.test.tsx` — 保留工作树中既有 `initReactI18next` 测试修正，不覆盖或回退。

### Task 1: 添加失败的路由搜索回归测试

**Files:**
- Create: `frontend/src/components/discover/__tests__/Discover.test.tsx`

- [ ] **Step 1: 写集成测试**

```tsx
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import { MemoryRouter, Route, Routes, useNavigate } from 'react-router-dom'

vi.mock('react-i18next', () => ({
  initReactI18next: { type: '3rdParty', init: () => {} },
  useTranslation: () => ({
    t: (key: string, options?: { returnObjects?: boolean }) =>
      options?.returnObjects ? [] : key,
  }),
}))

vi.mock('@/context/AppContext', () => ({
  useAppContext: () => ({ libraryRoot: '/tmp/library' }),
}))

vi.mock('@/api/http', () => ({
  kbSearchStream: vi.fn(() => () => undefined),
}))

vi.mock('../ChatTab', () => ({
  default: () => null,
}))

import { kbSearchStream } from '@/api/http'
import Discover from '../Discover'

function RouteHarness() {
  const navigate = useNavigate()

  return (
    <>
      <button type="button" onClick={() => void navigate('/discover?q=caffeine')}>
        search caffeine
      </button>
      <Discover />
    </>
  )
}

describe('Discover route search', () => {
  beforeEach(() => {
    vi.mocked(kbSearchStream).mockClear()
  })

  it('syncs and searches each route q without auto-searching local edits', async () => {
    render(
      <MemoryRouter initialEntries={['/discover?q=aspirin']}>
        <Routes>
          <Route path="/discover" element={<RouteHarness />} />
        </Routes>
      </MemoryRouter>,
    )

    await waitFor(() => {
      expect(kbSearchStream).toHaveBeenCalledWith(
        '/tmp/library',
        'aspirin',
        10,
        expect.any(Function),
      )
    })
    expect(screen.getByRole('textbox')).toHaveValue('aspirin')

    fireEvent.click(screen.getByRole('button', { name: 'search caffeine' }))

    await waitFor(() => {
      expect(screen.getByRole('textbox')).toHaveValue('caffeine')
      expect(kbSearchStream).toHaveBeenCalledWith(
        '/tmp/library',
        'caffeine',
        10,
        expect.any(Function),
      )
    })
    expect(kbSearchStream).toHaveBeenCalledTimes(2)

    vi.mocked(kbSearchStream).mockClear()
    fireEvent.change(screen.getByRole('textbox'), { target: { value: 'ibuprofen' } })

    expect(screen.getByRole('textbox')).toHaveValue('ibuprofen')
    expect(kbSearchStream).not.toHaveBeenCalled()
  })
})
```

- [ ] **Step 2: 运行测试，证明当前工作树实现仍失败**

Run:

```bash
npm --prefix frontend run test -- src/components/discover/__tests__/Discover.test.tsx
```

Expected: FAIL。首次 `aspirin` 搜索可通过；导航到 `?q=caffeine` 后输入框仍为 `aspirin`，且未出现 `caffeine` 请求。

### Task 2: 实现路由值与本地输入分离

**Files:**
- Modify: `frontend/src/components/discover/Discover.tsx:1-21`
- Modify: `frontend/src/components/discover/SearchTab.tsx:27-47,189-195`

- [ ] **Step 1: 让 `Discover` 响应 `q` 变化**

将 React import、路由值和 `SearchTab` 调用改为：

```tsx
import { useEffect, useState } from 'react'
import { useSearchParams } from 'react-router-dom'
```

```tsx
export default function Discover() {
  const [searchParams] = useSearchParams()
  const routeQuery = searchParams.get('q') ?? ''
  const [activeTab, setActiveTab] = useState<'search' | 'chat'>('search')
  const [sharedQuery, setSharedQuery] = useState(routeQuery)

  useEffect(() => {
    setSharedQuery(routeQuery)
  }, [routeQuery])
```

```tsx
<SearchTab
  query={sharedQuery}
  autoSearchQuery={routeQuery}
  onQueryChange={setSharedQuery}
/>
```

- [ ] **Step 2: 让 `SearchTab` 只监听路由触发值**

将 props 改为：

```tsx
interface SearchTabProps {
  query: string
  autoSearchQuery?: string
  onQueryChange: (query: string) => void
}
```

将组件参数改为：

```tsx
export default function SearchTab({
  query,
  autoSearchQuery,
  onQueryChange,
}: SearchTabProps) {
```

删除：

```tsx
const initialQueryRef = useRef(query)
```

用以下 effect 替换现有首次挂载自动搜索 effect：

```tsx
useEffect(() => {
  const q = autoSearchQuery?.trim()
  if (q) {
    doSearch(q)
  }
  // eslint-disable-next-line react-hooks/exhaustive-deps
}, [autoSearchQuery])
```

`autoSearchQuery` 保持 optional，使现有 `SearchTab` 单元测试和非路由调用继续采用显式 Enter/按钮搜索。

- [ ] **Step 3: 运行聚焦测试**

Run:

```bash
npm --prefix frontend run test -- src/components/discover/__tests__/Discover.test.tsx src/components/discover/__tests__/SearchTab.test.tsx
```

Expected: 两个测试文件全部 PASS；路由 `q` 每次仅产生一个请求，普通输入不产生请求。

### Task 3: 验证前端回归与静态检查

**Files:**
- Verify only; no additional production changes expected.

- [ ] **Step 1: 运行 Discover 目录测试**

Run:

```bash
npm --prefix frontend run test -- src/components/discover/__tests__
```

Expected: Discover 相关测试全部 PASS。

- [ ] **Step 2: 运行 TypeScript 与 ESLint**

Run:

```bash
cd frontend && npx tsc --noEmit
npx eslint src/components/discover/Discover.tsx src/components/discover/SearchTab.tsx src/components/discover/__tests__/Discover.test.tsx src/components/discover/__tests__/SearchTab.test.tsx
```

Expected: 两条命令 exit code 0，无新增类型错误或 lint 错误。

- [ ] **Step 3: 检查最终 diff**

Run:

```bash
git diff -- frontend/src/components/discover/Discover.tsx frontend/src/components/discover/SearchTab.tsx frontend/src/components/discover/__tests__/Discover.test.tsx frontend/src/components/discover/__tests__/SearchTab.test.tsx
```

Expected: 仅包含路由搜索桥接、回归测试和工作树中既有 `initReactI18next` 修正；无相邻重构。

- [ ] **Step 4: 保持未提交状态**

不执行 `git add`、`git commit` 或 `git push`。提交仅在用户明确授权后进行。
