# PdfCanvas 文档缓存 LRU 修复实施计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 修复 `PdfCanvas` PDF 文档缓存的 LRU 驱逐顺序，并用前端测试锁定缓存命中、驱逐和销毁行为。

**Architecture:** 将缓存顺序逻辑保留在 `PdfCanvas.tsx`，但抽出一个小型、可测试的缓存辅助模块，避免测试依赖 React canvas 和 PDF.js worker。辅助模块维护 `Map<string, Promise<PDFDocumentProxy>>`，每次访问将 key 移到尾部；超容量时驱逐首项并异步销毁文档。组件继续通过同一缓存 API 获取 PDF 文档。

**Tech Stack:** React 19, TypeScript 6, pdfjs-dist 4, Vitest 4.

---

### Task 1: 添加可测试缓存模块和失败测试

**Files:**
- Create: `frontend/src/components/pdfDocumentCache.ts`
- Create: `frontend/src/components/__tests__/pdfDocumentCache.test.ts`
- Modify: `frontend/src/components/PdfCanvas.tsx:15-37`

- [ ] **Step 1: 写缓存行为测试**

在 `frontend/src/components/__tests__/pdfDocumentCache.test.ts` 中 mock `pdfjs-dist` 的 `getDocument`，用可控 Promise 文档验证：

```ts
import { describe, expect, it, vi } from 'vitest'
import { createPdfDocumentCache } from '../pdfDocumentCache'

type FakeDocument = { destroy: ReturnType<typeof vi.fn> }

function deferred<T>() {
  let resolve!: (value: T) => void
  const promise = new Promise<T>(nextResolve => { resolve = nextResolve })
  return { promise, resolve }
}

describe('createPdfDocumentCache', () => {
  it('evicts least recently used document after capacity is exceeded', async () => {
    const documents = new Map<string, FakeDocument>()
    const getDocument = vi.fn((url: string) => {
      const document = { destroy: vi.fn().mockResolvedValue(undefined) }
      documents.set(url, document)
      return { promise: Promise.resolve(document) }
    })
    const cache = createPdfDocumentCache<FakeDocument>(3, getDocument)

    await cache.get('one.pdf')
    await cache.get('two.pdf')
    await cache.get('three.pdf')
    await cache.get('one.pdf')
    await cache.get('four.pdf')

    expect(documents.get('two.pdf')?.destroy).toHaveBeenCalledOnce()
    expect(documents.get('one.pdf')?.destroy).not.toHaveBeenCalled()
    expect(cache.keys()).toEqual(['three.pdf', 'one.pdf', 'four.pdf'])
  })

  it('reuses promise on cache hit and destroys evicted document', async () => {
    const document = { destroy: vi.fn().mockResolvedValue(undefined) }
    const getDocument = vi.fn(() => ({ promise: Promise.resolve(document) }))
    const cache = createPdfDocumentCache<FakeDocument>(1, getDocument)

    const first = cache.get('same.pdf')
    const second = cache.get('same.pdf')
    await cache.get('other.pdf')
    await Promise.all([first, second])

    expect(first).toBe(second)
    expect(getDocument).toHaveBeenCalledTimes(2)
    expect(document.destroy).toHaveBeenCalledOnce()
  })
})
```

测试应只验证 LRU 行为，不渲染 React 组件。

- [ ] **Step 2: 运行测试，确认按预期失败**

Run:

```bash
npm --prefix frontend run test -- src/components/__tests__/pdfDocumentCache.test.ts
```

Expected: FAIL，因为 `frontend/src/components/pdfDocumentCache.ts` 尚不存在，或 `createPdfDocumentCache` 尚未导出。若出现 TypeScript/import 错误，先修正测试 setup，直到失败原因明确指向缺失实现。

- [ ] **Step 3: 写最小缓存实现**

创建 `frontend/src/components/pdfDocumentCache.ts`：

```ts
export interface PdfDocumentCache<T> {
  get: (url: string) => Promise<T>
  keys: () => string[]
}

export function createPdfDocumentCache<T>(
  maxSize: number,
  load: (url: string) => { promise: Promise<T> },
): PdfDocumentCache<T> {
  const entries = new Map<string, Promise<T>>()

  function get(url: string): Promise<T> {
    const existing = entries.get(url)
    entries.delete(url)
    const promise = existing ?? load(url).promise
    entries.set(url, promise)

    if (entries.size > maxSize) {
      const oldest = entries.keys().next().value
      if (oldest !== undefined && oldest !== url) {
        const evicted = entries.get(oldest)
        entries.delete(oldest)
        void evicted?.then(document => {
          if (typeof document === 'object' && document !== null && 'destroy' in document) {
            const destroy = document.destroy
            if (typeof destroy === 'function') void destroy.call(document)
          }
        }).catch(() => undefined)
      }
    }
    return promise
  }

  return { get, keys: () => [...entries.keys()] }
}
```

- [ ] **Step 4: 将 `PdfCanvas` 接入辅助模块**

在 `PdfCanvas.tsx` 删除本地 `docCache` 与 `getCachedDoc` 实现，保留 `DOC_CACHE_MAX = 3`，导入辅助工厂，并用 `pdfjsLib.getDocument` 创建缓存：

```ts
import { createPdfDocumentCache } from './pdfDocumentCache'

const docCache = createPdfDocumentCache<PDFDocumentProxy>(
  DOC_CACHE_MAX,
  url => pdfjsLib.getDocument(url),
)
```

`getCachedDoc(url)` 调用改为 `docCache.get(url)`。

- [ ] **Step 5: 运行单测，确认通过**

Run:

```bash
npm --prefix frontend run test -- src/components/__tests__/pdfDocumentCache.test.ts
```

Expected: PASS，2 tests passed。

- [ ] **Step 6: 运行 lint 和类型构建检查**

Run:

```bash
npm --prefix frontend run lint
npm --prefix frontend run build
```

Expected: 两条命令均成功；无新增 lint 或 TypeScript 错误。

- [ ] **Step 7: 提交原子变更**

```bash
git add frontend/src/components/PdfCanvas.tsx frontend/src/components/pdfDocumentCache.ts frontend/src/components/__tests__/pdfDocumentCache.test.ts
git commit -m "fix(frontend): preserve PDF cache LRU order"
```

只提交 item 12 文件；不包含已有无关工作树修改。

---

### Task 2: 回归验证并更新任务记录

**Files:**
- Modify: `TODO/IMMEDIATE-ACTIONS.md:21`
- Modify: `TODO/INDEX.md`（如需将 item 12 从活动项移入已完成记录）

- [ ] **Step 1: 运行完整前端测试**

```bash
npm --prefix frontend run test
```

Expected: 全部现有测试通过；若失败，记录完整失败输出并修复与本变更相关的回归。

- [ ] **Step 2: 检查 git diff 和状态**

```bash
git status --short
git show --stat --oneline HEAD
```

Expected：提交只包含 PdfCanvas 缓存实现和测试；工作树中其他预存修改保持不变。

- [ ] **Step 3: 更新任务板**

在 `TODO/IMMEDIATE-ACTIONS.md` 中将 item 12 标记为已完成，或按仓库现有规则把它移入 `docs/archive/todo/RESOLVED-2026-07-23.md`。不要改写其他任务内容。

- [ ] **Step 4: 提交任务记录更新**

```bash
git add TODO/IMMEDIATE-ACTIONS.md TODO/INDEX.md docs/archive/todo/RESOLVED-2026-07-23.md
git commit -m "docs: close PDF cache LRU task"
```

若仓库规则要求文档与功能同一原子提交，则将此步骤并入 Task 1；否则保持文档提交独立、可回滚。

## 自检

- 规格中的 LRU 驱逐、MRU 命中、`destroy()`、Promise 复用均由 Task 1 测试覆盖。
- 测试先于生产实现，并明确运行失败和通过命令。
- 未引入 item 11、渲染流程或其他 PDF 重构。
- 所有路径、函数名和类型在任务步骤中保持一致。
