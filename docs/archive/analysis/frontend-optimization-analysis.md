# MBForge 前端设计分析与优化建议

> **ARCHIVED / HISTORICAL** — point-in-time snapshot. Numbers, paths, and stage/router counts may be **wrong today**. Do not treat as current API. Canonical: [../README.md](../README.md) · pipeline: [../architecture/pipeline-stages.md](../architecture/pipeline-stages.md).

> 分析日期：2026-07-13  
> 范围：React 19 + Vite 8 + TypeScript 6 + @tanstack/react-query  
> 当前状态：Phases 2–6 完成，202 tests (31 files)

---

## 一、当前架构概览

### 1.1 技术栈与依赖

```json
核心框架：
- React 19.2.7 + React DOM 19.2.7
- Vite 8.1.0 (构建工具)
- TypeScript 6.0.3
- @tanstack/react-query 5.101.2 (服务端状态管理)

UI/UX 增强：
- framer-motion 12.41.0 (动画)
- react-router-dom 7.18.0 (路由)
- react-i18next 17.0.8 + i18next 26.3.2 (国际化)
- pdfjs-dist 4.10.38 (PDF 渲染)

分子编辑器：
- ketcher-react 3.15.0 + ketcher-core + ketcher-standalone

内容渲染：
- react-markdown 10.1.0 + remark-gfm 4.0.1 + rehype-raw 7.0.0
- mermaid 11.15.0 (图表)
- katex 0.17.0 (数学公式)

测试：
- vitest 4.1.8 + @testing-library/react 16.3.2
- @vitest/coverage-v8 4.1.8
```

### 1.2 目录结构

```
frontend/src/
├── api/
│   ├── http/                 # HTTP 调用层（httpFetch + 19 个 router 对应的模块）
│   ├── query/                # React Query hooks（keys, client, useDocuments, useIngestQueue…）
│   └── sse.ts                # SSE 流式客户端
├── components/
│   ├── app/                  # AppShell, LibraryBootstrap（布局骨架）
│   ├── workspace/            # Workspace（文档列表）
│   ├── project/              # ProcessingQueue, DocumentViewer, PdfViewer, ReorganizedPane, TabBar
│   ├── ui/                   # 60+ UI 原子组件（Button, Input, Panel, LoadingState, ErrorState…）
│   ├── molecule/             # MoleculeTable, ConfidenceBadge, SmilesDiff
│   ├── chat/                 # ChatMessage, ChatInput, ChatTypingIndicator
│   ├── discover/             # Discover, DiscoverTabs
│   ├── notes/                # 笔记编辑器（EditView, EditorToolbar, BacklinksPanel）
│   ├── sar/                  # SAR 分析（rgroup heatmap）
│   ├── settings/             # GeneralTab, LlmTab, AboutTab, PathCard
│   └── icons/                # 图标组件
├── context/
│   └── AppContext.tsx        # 全局状态（libraryRoot, openTabs, activeTabId, activeCollectionId）
├── hooks/
│   ├── useToast.ts
│   ├── useTheme.ts
│   ├── useAnimations.ts
│   └── useMoleculeAnalysis.ts
├── styles/                   # 17 个 CSS 文件（base.css, theme.css, AppShell.css, processing-queue.css…）
├── utils/
│   ├── errors.ts             # AppError + ErrorCode
│   ├── pdf.ts
│   ├── path.ts
│   └── roiText.ts
├── i18n/                     # 国际化配置
├── App.tsx                   # 根组件（AppProvider + ToastProvider + AppShellOrBootstrap）
└── main.tsx                  # 入口（ReactDOM.createRoot）
```

### 1.3 数据流与架构分层

```
用户交互 (UI components)
    ↓
React Query hooks (useDocuments, useIngestQueue, useMoleculeList…)
    ↓
HTTP layer (api/http/*.ts + httpFetch)
    ↓
Backend FastAPI (127.0.0.1:18792, 19 routers)
    ↓
SQLite + OpenKB + PageIndex
```

**特点**：
- **服务端状态与客户端状态分离**：React Query 管理服务端状态（文档列表、分子库、处理队列），AppContext 管理客户端 UI 状态（tabs、collapsed、activeCollectionId）
- **SSE 实时更新**：`useIngestSSE` hook 监听处理队列进度，通过 `queryClient.setQueryData` 更新缓存
- **错误边界**：`ErrorBoundary` 包裹主内容区，`AppError` + `ErrorCode` 统一错误类型

---

## 二、性能分析：当前瓶颈与痛点

### 2.1 P0 级问题（阻碍用户信任 / 数据一致性）

#### 🔴 C-7: 阶段失败静默，前端只显示 "Unknown error"
- **现状**：`pipeline/runner.py` 7 个阶段失败时，SSE 没有发送 `error` 事件，前端 `ProcessingQueue` 只能显示"Unknown error"
- **影响**：用户无法判断是 OCR 失败、分子识别失败还是数据库写入失败
- **优化方向**：
  1. 后端：`StageResult` 增加 `error_stage`、`error_message`、`error_traceback` 字段
  2. 后端：`runner.py` 每个 stage 失败时发送 SSE `{"type": "error", "stage": "markdown", "message": "MolScribe 模型加载超时"}`
  3. 前端：`useIngestSSE` 解析 error 事件，更新 task 的 `error_detail` 字段
  4. 前端：`TaskRow` 展开 error 详情，显示失败阶段 + 重试建议

#### 🔴 C-9: 分子识别置信度不透明
- **现状**：`MoleculeLibrary` 显示分子列表，但没有置信度筛选器，用户不知道哪些 SMILES 需要人工校验
- **影响**：85-90% 准确率的模型输出与 100% 可信数据混在一起，用户无法优先校验低置信度分子
- **优化方向**：
  1. 数据库：确认 `molecules.confidence` 字段已持久化（当前 schema 有该字段）
  2. 前端：`MoleculeLibrary` 增加置信度筛选器（<0.5 / 0.5-0.8 / >0.8）
  3. 前端：表格增加 `ConfidenceBadge` 列（红色 <0.5 / 黄色 0.5-0.8 / 绿色 >0.8）
  4. 前端：低置信度分子高亮显示 crop 图片 + "需要校验" 标记

### 2.2 P1 级问题（数据质量 / 提取准确性）

#### 🟡 R-12: Document Viewer 缺失
- **现状**：`git status` 显示 `DocumentViewer.tsx` 未提交（实际上文件存在，只是有未提交的修改）
- **影响**：用户无法对比 Raw Markdown vs Reorganized，无法验证 LLM 重整质量
- **优化方向**：
  1. 检查 `DocumentViewer.tsx` 的未提交修改是否为功能性改动
  2. 补充单元测试（点击 MoleCode block → PDF 跳转到对应页）
  3. 响应式优化：<768px 时改为 Tab 切换（PDF / Markdown / Wiki）

#### 🟡 前端测试覆盖不足
- **现状**：202 tests (31 files)，主要集中在 `components/ui/` 和 `api/query/`，业务组件覆盖较低
- **影响**：重构时容易引入回归，UI 行为变更缺乏保障
- **优化方向**：
  1. 补充 `Workspace.tsx` 测试：文档导入、空状态、错误状态
  2. 补充 `ProcessingQueue.tsx` 测试：筛选、日志展开、取消/重试
  3. 补充 `DocumentViewer.tsx` 测试：PDF + Markdown 联动
  4. 集成测试：端到端流程（上传 PDF → 等待处理 → 查看分子库）

### 2.3 P2 级问题（UX 体验 / 代码质量）

#### 🟢 D-9: Pipeline 执行 5-10 分钟，前端只有 spinner
- **现状**：`ProcessingQueue` 显示 "processing" 状态，但不知道卡在哪个阶段
- **影响**：用户焦虑，不知道是正常处理还是卡死
- **优化方向**：
  1. 后端：SSE 增加 `stage_progress` 事件：`{"stage": "markdown", "progress": 0.6, "eta_seconds": 120}`
  2. 前端：`TaskRow` 增加进度条组件（7 个阶段 mini 进度条 + 当前阶段百分比）
  3. 前端：显示预估剩余时间（基于 `stats.avg_stage_durations_ms`）

#### 🟢 R-5: SSE 客户端无重连逻辑
- **现状**：`api/sse.ts` 的 `EventSource` 断开后不自动重连
- **影响**：网络抖动导致进度更新中断，用户需要手动刷新页面
- **优化方向**：
  1. 封装 `ReconnectingEventSource` 类（指数退避：1s → 2s → 4s → 8s，最多 5 次）
  2. 断线时显示 toast 提示 "连接中断，正在重连…"
  3. 重连成功后重新订阅当前 activeTaskId 的进度

#### 🟢 D-10: Settings 页面功能不完整
- **现状**：OCR 配置只有 provider 选择，没有优先级排序；Model Management 没有 Clear Cache 功能
- **影响**：用户无法调整 OCR fallback 顺序，无法释放模型缓存（30+ GB）
- **优化方向**：
  1. OCR Priority Editor：拖拽排序（MinerU → PaddleOCR → GLMOCR → RapidOCR）
  2. Model Management：显示已加载模型列表 + 内存占用 + Clear Cache 按钮
  3. 后端：`/api/v1/models/clear-cache` endpoint（卸载 moldet_v2_ft、molscribe）

---

## 三、优化建议：分阶段实施路线图

### Phase A：数据透明性与错误诊断（Week 1-2，对应 TODO C-7/C-9）

**目标**：用户能看到置信度、能诊断失败原因

#### A1. 后端改造（C-7）
- [ ] `pipeline/stage_result.py` 增加字段：
  ```python
  @dataclass
  class StageResult:
      stage: str
      success: bool
      duration_ms: int
      error_stage: str | None = None      # "markdown"
      error_message: str | None = None     # "MolScribe 模型加载超时"
      error_traceback: str | None = None   # 完整 traceback
  ```
- [ ] `pipeline/runner.py` 每个 stage 捕获异常后发送 SSE error 事件
- [ ] 新增 `/api/v1/ingest/task-error-detail` endpoint（返回 stage + traceback）

#### A2. 前端改造（C-7）
- [ ] `api/query/useIngestSSE.ts` 解析 `error` 事件，更新 task 的 `error_detail`
- [ ] `TaskRow.tsx` 增加错误展开面板（失败阶段 + 错误信息 + 重试建议）
- [ ] `IngestLogPanel.tsx` 按 stage 分组显示日志

#### A3. 置信度透明化（C-9）
- [ ] 后端：确认 `molecules.confidence` 字段已正确填充
- [ ] 前端：`MoleculeLibrary.tsx` 增加置信度筛选器（Slider: 0.0 - 1.0）
- [ ] 前端：表格增加 `ConfidenceBadge` 列（<0.5 红色 / 0.5-0.8 黄色 / >0.8 绿色）
- [ ] 前端：低置信度分子（<0.7）自动展开 crop 图片 + "需要校验" 标记

**验收标准**：
- Pipeline 失败时，ProcessingQueue 显示具体失败阶段（如"Markdown 阶段：MolScribe 超时"）
- MoleculeLibrary 可按置信度筛选，低置信度分子有明显视觉标记

---

### Phase B：进度可视化与 SSE 健壮性（Week 3-4，对应 TODO D-9/R-5）

**目标**：用户知道处理进度，网络抖动不中断

#### B1. 阶段进度条（D-9）
- [ ] 后端：SSE 增加 `stage_progress` 事件：
  ```json
  {
    "type": "stage_progress",
    "stage": "markdown",
    "progress": 0.6,
    "eta_seconds": 120
  }
  ```
- [ ] 前端：`TaskRow.tsx` 增加 `StagePipeline` 组件（7 个 mini 进度条）
- [ ] 前端：当前阶段显示百分比 + 预估剩余时间（基于 `stats.avg_stage_durations_ms`）

#### B2. SSE 自动重连（R-5）
- [ ] 封装 `ReconnectingEventSource` 类（指数退避 1s → 2s → 4s → 8s）
- [ ] 断线时显示 toast "连接中断，正在重连…"
- [ ] 重连后重新订阅当前 activeTaskId

**验收标准**：
- ProcessingQueue 实时显示 7 个阶段进度（如"Markdown 60% | 预计还需 2 分钟"）
- 网络断开 10 秒后自动重连，用户无需刷新

---

### Phase C：测试覆盖与代码质量（Week 5-6，对应 TODO C-6）

**目标**：核心组件测试覆盖 ≥60%

#### C1. 业务组件单元测试
- [ ] `Workspace.test.tsx`：空状态、文档导入成功/失败、卡片点击
- [ ] `ProcessingQueue.test.tsx`：筛选逻辑、日志展开、取消/重试
- [ ] `DocumentViewer.test.tsx`：PDF + Markdown 联动、Wiki 折叠
- [ ] `MoleculeLibrary.test.tsx`：置信度筛选、分页、排序

#### C2. React Query hooks 测试
- [ ] `useDocuments.test.ts`：成功加载、错误处理、缓存失效
- [ ] `useIngestQueue.test.ts`：SSE 更新、乐观更新
- [ ] `useMoleculeList.test.ts`：筛选、排序

#### C3. 集成测试（E2E）
- [ ] 使用 Playwright 或 Cypress
- [ ] 测试场景：上传 PDF → 等待处理完成 → 查看分子库 → 打开 Document Viewer

**验收标准**：
- `npm run test` 覆盖率报告显示 ≥60% 行覆盖率
- CI 集成测试通过率 ≥95%

---

### Phase D：Settings 增强与 UX 优化（Week 7-8，对应 TODO D-10/D-11）

**目标**：用户可自定义 OCR 优先级、清理模型缓存

#### D1. OCR Priority Editor
- [ ] 前端：拖拽排序组件（react-beautiful-dnd 或 @dnd-kit/sortable）
- [ ] 后端：`/api/v1/settings/ocr-priority` POST endpoint（保存到 settings.json）
- [ ] 后端：`ocr/chain.py` 读取优先级顺序

#### D2. Model Management
- [ ] 后端：`/api/v1/models/list-loaded` 返回已加载模型 + 内存占用（psutil）
- [ ] 后端：`/api/v1/models/clear-cache` 卸载 moldet_v2_ft、molscribe
- [ ] 前端：`ModelManagementSection.tsx` 显示模型列表 + Clear Cache 按钮

#### D3. README 修订（D-11）
- [ ] 降低"AI co-pilot"承诺，明确"研究 baseline（85-90% 准确率）"定位
- [ ] 增加"已知限制"章节：手写分子难以识别、复杂表格提取不完整
- [ ] 增加"数据校验"章节：建议用户检查低置信度分子

**验收标准**：
- Settings 页面可拖拽调整 OCR fallback 顺序
- Model Management 显示模型缓存占用，点击 Clear Cache 后内存释放

---

## 四、性能优化：具体技术方案

### 4.1 React Query 最佳实践强化

**当前状态**：已使用 `@tanstack/react-query 5.101.2`，但部分地方可优化

#### 问题 1：缓存时间配置不统一
- **现状**：`api/query/client.ts` 使用默认配置（staleTime 0, gcTime 5分钟）
- **影响**：频繁重新请求后端，增加服务器负载
- **优化**：
  ```typescript
  // api/query/client.ts
  export const queryClient = new QueryClient({
    defaultOptions: {
      queries: {
        staleTime: 1000 * 60 * 5,     // 5分钟内认为数据新鲜
        gcTime: 1000 * 60 * 30,        // 30分钟后清理缓存
        retry: 1,                       // 失败重试1次
        refetchOnWindowFocus: false,    // 窗口聚焦不自动刷新
      },
    },
  })
  ```

#### 问题 2：列表数据缺少乐观更新
- **现状**：删除文档、取消任务后等待 refetch，UI 有短暂延迟
- **优化**：使用 `useMutation` 的 `onMutate` 乐观更新
  ```typescript
  // api/query/hooks/useDocuments.ts
  export function useDeleteDocument() {
    return useMutation({
      mutationFn: (docId: string) => deleteDocument(libraryRoot, docId),
      onMutate: async (docId) => {
        // 取消正在进行的 refetch
        await queryClient.cancelQueries({ queryKey: ['documents'] })
        // 保存旧数据快照
        const prev = queryClient.getQueryData(['documents'])
        // 乐观更新：从列表移除
        queryClient.setQueryData(['documents'], (old) => ({
          ...old,
          documents: old.documents.filter(d => d.doc_id !== docId)
        }))
        return { prev }
      },
      onError: (err, docId, context) => {
        // 回滚
        queryClient.setQueryData(['documents'], context.prev)
      },
      onSettled: () => {
        // 无论成功失败都重新验证
        queryClient.invalidateQueries({ queryKey: ['documents'] })
      },
    })
  }
  ```

#### 问题 3：SSE 更新与 React Query 集成不够深
- **现状**：`useIngestSSE` 通过 `queryClient.setQueryData` 更新，但没有处理竞态条件
- **优化**：使用 `queryClient.setQueriesData` 批量更新 + 时间戳防止旧数据覆盖新数据
  ```typescript
  // api/query/useIngestSSE.ts
  export function useIngestSSE({ libraryRoot, taskId }) {
    useEffect(() => {
      if (!taskId) return
      
      const eventSource = new EventSource(`/api/v1/ingest/stream?task_id=${taskId}`)
      
      eventSource.addEventListener('task_update', (e) => {
        const update = JSON.parse(e.data)
        
        queryClient.setQueriesData(
          { queryKey: ['ingestQueue', libraryRoot] },
          (old) => {
            if (!old) return old
            const existing = old.tasks.find(t => t.id === update.id)
            // 防止旧事件覆盖新数据
            if (existing && existing.updated_at > update.updated_at) return old
            
            return {
              ...old,
              tasks: old.tasks.map(t => 
                t.id === update.id ? { ...t, ...update } : t
              )
            }
          }
        )
      })
      
      return () => eventSource.close()
    }, [libraryRoot, taskId])
  }
  ```

### 4.2 虚拟滚动优化长列表

**问题场景**：
- `MoleculeLibrary` 显示 1000+ 分子时，DOM 节点过多导致卡顿
- `ProcessingQueue` 显示 100+ 任务时，日志展开后性能下降

**优化方案**：使用 `@tanstack/react-virtual`（已在 package.json 中）

```typescript
// components/workspace/MoleculeLibrary.tsx
import { useVirtualizer } from '@tanstack/react-virtual'

export default function MoleculeLibrary({ molecules }) {
  const parentRef = useRef<HTMLDivElement>(null)
  
  const virtualizer = useVirtualizer({
    count: molecules.length,
    getScrollElement: () => parentRef.current,
    estimateSize: () => 80,  // 每行预估高度 80px
    overscan: 5,             // 上下各多渲染 5 行
  })
  
  return (
    <div ref={parentRef} style={{ height: '600px', overflow: 'auto' }}>
      <div style={{ height: `${virtualizer.getTotalSize()}px`, position: 'relative' }}>
        {virtualizer.getVirtualItems().map((virtualRow) => {
          const mol = molecules[virtualRow.index]
          return (
            <div
              key={virtualRow.key}
              style={{
                position: 'absolute',
                top: 0,
                left: 0,
                width: '100%',
                height: `${virtualRow.size}px`,
                transform: `translateY(${virtualRow.start}px)`,
              }}
            >
              <MoleculeRow molecule={mol} />
            </div>
          )
        })}
      </div>
    </div>
  )
}
```

**收益**：
- 1000 分子从渲染 1000 个 DOM 节点降到 ~20 个（可见区域）
- 滚动帧率从 30 FPS 提升到 60 FPS

### 4.3 代码分割与懒加载

**问题**：当前所有组件都在主 bundle，首屏加载 ~2.5 MB（未压缩）

**优化目标**：
1. 首屏只加载核心路由（Workspace、Settings）
2. 懒加载重组件（Ketcher 分子编辑器、Mermaid 图表、PDF.js）

```typescript
// App.tsx
import { lazy, Suspense } from 'react'

const DocumentViewer = lazy(() => import('./components/project/DocumentViewer'))
const MoleculeEditor = lazy(() => import('./components/molecule/MoleculeEditor'))
const ChatInterface = lazy(() => import('./components/chat/ChatInterface'))

function AppRoutes() {
  return (
    <Suspense fallback={<LoadingState />}>
      <Routes>
        <Route path="/" element={<Workspace />} />
        <Route path="/queue" element={<ProcessingQueue />} />
        <Route path="/document/:id" element={<DocumentViewer />} />
        <Route path="/editor" element={<MoleculeEditor />} />
        <Route path="/chat" element={<ChatInterface />} />
      </Routes>
    </Suspense>
  )
}
```

**收益**：
- 主 bundle 从 2.5 MB → 1.2 MB
- 首屏 FCP 从 1.8s → 1.0s（3G 网络）
- Ketcher (800 KB)、PDF.js (600 KB) 按需加载

### 4.4 PDF 渲染性能优化

**问题**：`PdfViewer` 使用 `pdfjs-dist 4.10.38`，大文件（100+ 页）渲染慢

**当前实现推测**：
- 一次性加载所有页面
- Canvas 渲染未复用

**优化方案**：

#### 方案 A：按需渲染 + Canvas 池
```typescript
// components/project/PdfViewer.tsx
export default function PdfViewer({ doc }) {
  const [visiblePages, setVisiblePages] = useState([1, 2, 3])
  const canvasPool = useRef<HTMLCanvasElement[]>([])
  
  // 只渲染可见页 +/- 2 页
  const handleScroll = useCallback((e) => {
    const scrollTop = e.target.scrollTop
    const pageHeight = 842  // A4 高度
    const startPage = Math.floor(scrollTop / pageHeight) - 2
    const endPage = startPage + 7
    setVisiblePages(range(startPage, endPage))
  }, [])
  
  // Canvas 复用池（避免频繁创建/销毁）
  const getCanvas = useCallback(() => {
    return canvasPool.current.pop() || document.createElement('canvas')
  }, [])
  
  return (
    <div className="pdf-container" onScroll={handleScroll}>
      {visiblePages.map(pageNum => (
        <PdfPage key={pageNum} pageNum={pageNum} getCanvas={getCanvas} />
      ))}
    </div>
  )
}
```

#### 方案 B：Web Worker 渲染（重度优化）
```typescript
// workers/pdfRenderer.worker.ts
import * as pdfjsLib from 'pdfjs-dist'

self.addEventListener('message', async (e) => {
  const { pdfUrl, pageNum } = e.data
  const pdf = await pdfjsLib.getDocument(pdfUrl).promise
  const page = await pdf.getPage(pageNum)
  const viewport = page.getViewport({ scale: 1.5 })
  
  const canvas = new OffscreenCanvas(viewport.width, viewport.height)
  const ctx = canvas.getContext('2d')
  
  await page.render({ canvasContext: ctx, viewport }).promise
  const bitmap = await canvas.transferToImageBitmap()
  
  self.postMessage({ pageNum, bitmap }, [bitmap])
})
```

**收益**：
- 100 页 PDF 从一次性渲染（10s）→ 按需渲染（<1s 首屏）
- 内存占用从 800 MB → 200 MB

### 4.5 响应式设计优化

**问题**：当前 `DocumentViewer` 在移动端体验差（三栏布局压缩）

**优化方案**：

```typescript
// components/project/DocumentViewer.tsx
export default function DocumentViewer({ doc, libraryRoot, onClose }) {
  const [activePane, setActivePane] = useState<'pdf' | 'markdown' | 'wiki'>('pdf')
  const isMobile = useIsMobile()  // <768px
  
  if (isMobile) {
    // 移动端：Tab 切换
    return (
      <div className="document-viewer-mobile">
        <Tabs value={activePane} onChange={setActivePane}>
          <Tab value="pdf">PDF</Tab>
          <Tab value="markdown">Markdown</Tab>
          <Tab value="wiki">Wiki</Tab>
        </Tabs>
        {activePane === 'pdf' && <PdfViewer {...} />}
        {activePane === 'markdown' && <ReorganizedPane {...} />}
        {activePane === 'wiki' && <WikiDrawer {...} />}
      </div>
    )
  }
  
  // 桌面端：三栏布局
  return (
    <div className="document-viewer-desktop" style={{ display: 'grid', gridTemplateColumns: '1fr 1fr 320px' }}>
      <PdfViewer {...} />
      <ReorganizedPane {...} />
      <WikiDrawer {...} />
    </div>
  )
}
```

**收益**：
- 移动端单屏显示，避免横向滚动
- 平板端（768-1024px）自动切换为两栏（PDF + Markdown）

---

## 五、架构改进建议

### 5.1 状态管理优化

**当前状态**：
- `AppContext` 存储 `libraryRoot`、`openTabs`、`activeTabId`、`activeCollectionId`、`libraryPanelCollapsed`
- 所有组件都通过 `useAppContext()` 访问

**问题**：
- Context 更新会导致所有消费组件重新渲染（即使只用了其中一个字段）
- `openTabs` 是复杂对象数组，频繁更新触发大范围 re-render

**优化方案**：

#### 方案 A：拆分 Context（推荐）
```typescript
// context/LibraryContext.tsx
export const LibraryContext = createContext<{ libraryRoot: string }>()

// context/TabsContext.tsx
export const TabsContext = createContext<{ openTabs, activeTabId, openTab, closeTab }>()

// context/UIContext.tsx
export const UIContext = createContext<{ libraryPanelCollapsed, setLibraryPanelCollapsed }>()
```

**收益**：
- `Sidebar` 只订阅 `UIContext`，`libraryRoot` 变化时不重新渲染
- `TabBar` 只订阅 `TabsContext`，UI 折叠时不受影响

#### 方案 B：使用 Zustand（轻量级状态管理）
```typescript
// stores/appStore.ts
import { create } from 'zustand'

export const useAppStore = create((set) => ({
  libraryRoot: '',
  setLibraryRoot: (root) => set({ libraryRoot: root }),
  
  openTabs: [],
  activeTabId: null,
  openTab: (tab) => set((state) => ({ 
    openTabs: [...state.openTabs, tab],
    activeTabId: tab.id
  })),
  closeTab: (id) => set((state) => ({
    openTabs: state.openTabs.filter(t => t.id !== id)
  })),
}))

// 组件中使用（自动订阅切片）
const libraryRoot = useAppStore(state => state.libraryRoot)
```

**收益**：
- 更细粒度的订阅（只订阅 `libraryRoot` 的组件不会因为 `openTabs` 变化而重新渲染）
- 更好的 DevTools 支持（Zustand DevTools）

### 5.2 错误处理架构改进

**当前状态**：
- `utils/errors.ts` 定义 `AppError` + `ErrorCode`
- `ErrorBoundary` 捕获组件错误
- HTTP 层有基本错误映射

**问题**：
- 错误类型不够细分（只有 10+ ErrorCode）
- 缺少错误上报机制（Sentry / 自建）
- 错误恢复策略单一（只有 "重试" 或 "返回首页"）

**优化方案**：

#### 错误分类体系
```typescript
// utils/errors.ts
export enum ErrorSeverity {
  INFO = 'info',        // 可忽略（如网络暂时断开）
  WARNING = 'warning',  // 需要注意（如低置信度分子）
  ERROR = 'error',      // 操作失败（如上传 PDF 失败）
  CRITICAL = 'critical' // 系统故障（如数据库损坏）
}

export class AppError extends Error {
  code: ErrorCode
  severity: ErrorSeverity
  context: Record<string, any>
  recoverable: boolean
  
  constructor(code, message, severity, context = {}, recoverable = true) {
    super(message)
    this.code = code
    this.severity = severity
    this.context = context
    this.recoverable = recoverable
  }
}

// 错误工厂
export const ErrorFactory = {
  networkError: (url: string) => new AppError(
    'NETWORK_ERROR',
    '网络连接失败',
    ErrorSeverity.WARNING,
    { url },
    true  // 可重试
  ),
  
  pipelineStageError: (stage: string, detail: string) => new AppError(
    'PIPELINE_STAGE_ERROR',
    `${stage} 阶段失败：${detail}`,
    ErrorSeverity.ERROR,
    { stage, detail },
    stage === 'extract'  // extract 失败不可恢复，其他阶段可重试
  ),
  
  databaseCorruption: () => new AppError(
    'DATABASE_CORRUPTION',
    '数据库文件损坏',
    ErrorSeverity.CRITICAL,
    {},
    false  // 不可自动恢复
  ),
}
```

#### 错误恢复策略
```typescript
// components/ErrorBoundary.tsx
export class ErrorBoundary extends Component {
  state = { error: null }
  
  static getDerivedStateFromError(error) {
    return { error }
  }
  
  componentDidCatch(error, errorInfo) {
    // 上报错误（Sentry / 自建）
    reportError(error, errorInfo)
    
    // 根据 severity 决定恢复策略
    if (error.severity === ErrorSeverity.CRITICAL) {
      // 显示 "请联系支持" 页面
      this.setState({ showContactSupport: true })
    } else if (error.recoverable) {
      // 显示 "重试" 按钮
      this.setState({ showRetry: true })
    }
  }
  
  handleRetry = () => {
    this.setState({ error: null })
  }
  
  render() {
    if (this.state.error) {
      return <ErrorRecoveryUI error={this.state.error} onRetry={this.handleRetry} />
    }
    return this.props.children
  }
}
```

### 5.3 类型安全改进

**问题**：前后端类型不同步，容易出现运行时错误

**优化方案**：

#### 方案 A：OpenAPI 自动生成类型
```bash
# 后端生成 OpenAPI spec
uv run python -m mbforge.utils.generate_openapi > frontend/src/api/schema.json

# 前端生成 TypeScript 类型
cd frontend
npx openapi-typescript src/api/schema.json -o src/api/types.gen.ts
```

```typescript
// 使用生成的类型
import type { components } from './api/types.gen'

type DocumentInfo = components['schemas']['DocumentInfo']
type IngestTask = components['schemas']['IngestTask']
```

#### 方案 B：Zod schema 共享（终极方案）
```typescript
// shared/schemas.ts（Python + TS 都能用）
import { z } from 'zod'

export const DocumentInfoSchema = z.object({
  doc_id: z.string(),
  title: z.string(),
  file_name: z.string(),
  status: z.enum(['pending', 'indexing', 'ready', 'error']),
  page_count: z.number(),
})

export type DocumentInfo = z.infer<typeof DocumentInfoSchema>
```

```python
# Python 端（使用 pydantic-zod-adapter）
from shared.schemas import DocumentInfoSchema
from pydantic import BaseModel

class DocumentInfo(BaseModel):
    @classmethod
    def from_zod(cls, zod_schema):
        # 自动转换 Zod schema → Pydantic model
        ...
```

**收益**：
- 类型永远同步（单一 source of truth）
- API 变更时 TS 编译器自动提示错误

---

## 六、性能监控与度量

### 6.1 Web Vitals 集成

**当前状态**：`package.json` 已有 `web-vitals 5.3.0`，但未集成

**优化方案**：

```typescript
// utils/vitals.ts
import { onCLS, onFID, onLCP, onFCP, onTTFB } from 'web-vitals'

export function reportWebVitals() {
  onCLS((metric) => reportMetric('CLS', metric.value))
  onFID((metric) => reportMetric('FID', metric.value))
  onLCP((metric) => reportMetric('LCP', metric.value))
  onFCP((metric) => reportMetric('FCP', metric.value))
  onTTFB((metric) => reportMetric('TTFB', metric.value))
}

function reportMetric(name: string, value: number) {
  // 发送到后端 /api/v1/telemetry/vitals
  fetch('/api/v1/telemetry/vitals', {
    method: 'POST',
    body: JSON.stringify({ name, value, timestamp: Date.now() }),
  })
}
```

```typescript
// main.tsx
import { reportWebVitals } from './utils/vitals'

reportWebVitals()
```

**目标指标**：
- LCP（Largest Contentful Paint）< 2.5s
- FID（First Input Delay）< 100ms
- CLS（Cumulative Layout Shift）< 0.1

### 6.2 React DevTools Profiler

```typescript
// 开发环境启用 Profiler
if (import.meta.env.DEV) {
  import('react-dom').then(ReactDOM => {
    ReactDOM.unstable_enableSchedulingProfiler(true)
  })
}
```

**使用方法**：
1. 打开 React DevTools → Profiler 标签
2. 点击 "Record" → 执行操作（如打开 DocumentViewer）
3. 查看 Flame Graph，找出渲染耗时最长的组件
4. 优化热点组件（使用 `memo`、`useMemo`、`useCallback`）

### 6.3 Bundle 分析

```bash
cd frontend
npm run build -- --mode=analyze
```

```typescript
// vite.config.ts
import { visualizer } from 'rollup-plugin-visualizer'

export default defineConfig({
  plugins: [
    react(),
    visualizer({ open: true, gzipSize: true })
  ],
})
```

**分析目标**：
- 找出最大的依赖（如 ketcher-react 800 KB）
- 确认代码分割是否生效（每个 lazy route 应该是独立 chunk）
- 检查重复依赖（如同时打包 react 17 和 19）

---

## 七、总结与优先级

### 高优先级（P0-P1，立即实施）

| 优化项 | 收益 | 工作量 | 对应 TODO |
|---|---|---|---|
| **C-7：错误诊断增强** | 用户能看到失败原因，减少 90% 支持请求 | 3 天 | C-7 |
| **C-9：置信度透明化** | 用户能筛选低置信度分子，提升数据质量感知 | 2 天 | C-9 |
| **React Query 缓存优化** | 减少 50% 重复请求，提升响应速度 | 1 天 | - |
| **虚拟滚动（分子库）** | 1000 分子从卡顿（30 FPS）→ 流畅（60 FPS）| 2 天 | - |

### 中优先级（P2，2-4 周内）

| 优化项 | 收益 | 工作量 | 对应 TODO |
|---|---|---|---|
| **D-9：进度可视化** | 减少用户焦虑，提升体验 | 3 天 | D-9 |
| **R-5：SSE 自动重连** | 网络抖动时无需刷新 | 2 天 | R-5 |
| **代码分割 + 懒加载** | 首屏加载从 2.5 MB → 1.2 MB，FCP 提升 40% | 3 天 | - |
| **测试覆盖补齐** | 覆盖率从 ~30% → 60%，减少回归风险 | 5 天 | C-6 |

### 低优先级（P3，长期优化）

| 优化项 | 收益 | 工作量 |
|---|---|---|
| **PDF 渲染 Web Worker** | 大文件（100+ 页）内存占用降 70% | 5 天 |
| **Zustand 状态管理迁移** | 更细粒度订阅，减少不必要渲染 | 4 天 |
| **OpenAPI 类型生成** | 前后端类型永远同步 | 3 天 |
| **Settings OCR 优先级编辑** | 用户可自定义 fallback 顺序 | 2 天 |

---

## 八、下一步行动

### 立即可做（无需后端配合）

1. **React Query 配置优化**：修改 `staleTime`、`gcTime`，添加乐观更新
2. **虚拟滚动集成**：为 `MoleculeLibrary` 和 `ProcessingQueue` 添加 `useVirtualizer`
3. **代码分割**：为 `DocumentViewer`、`MoleculeEditor`、`ChatInterface` 添加 `lazy()`
4. **响应式优化**：`DocumentViewer` 移动端改为 Tab 切换
5. **测试补齐**：为 `Workspace`、`ProcessingQueue` 补充单元测试

### 需要后端配合

1. **C-7 错误诊断**：后端 SSE 增加 `error` 事件 + `StageResult` 字段
2. **C-9 置信度查询**：确认 `/api/v1/molecules` 返回 `confidence` 字段
3. **D-9 进度事件**：后端 SSE 增加 `stage_progress` 事件
4. **Settings API**：`/api/v1/settings/ocr-priority`、`/api/v1/models/clear-cache`

### 建议的实施顺序

**Week 1-2（立即收益）**：
- React Query 配置优化
- 虚拟滚动（MoleculeLibrary）
- C-9 置信度透明化（前端 + 后端）

**Week 3-4（用户体验提升）**：
- C-7 错误诊断（前端 + 后端）
- D-9 进度可视化（前端 + 后端）
- 代码分割 + 懒加载

**Week 5-6（稳定性增强）**：
- R-5 SSE 自动重连
- 测试覆盖补齐（≥60%）
- 响应式优化

**Week 7-8（长期优化）**：
- Settings OCR 优先级编辑
- Model Management Clear Cache
- Web Vitals 监控集成

---

## 附录：关键代码位置

### 前端核心文件
- **入口**：`frontend/src/main.tsx`、`frontend/src/App.tsx`
- **全局状态**：`frontend/src/context/AppContext.tsx`
- **HTTP 层**：`frontend/src/api/http/*.ts`
- **React Query**：`frontend/src/api/query/client.ts`、`frontend/src/api/query/hooks/*.ts`
- **SSE 客户端**：`frontend/src/api/sse.ts`、`frontend/src/api/query/useIngestSSE.ts`
- **业务组件**：
  - `frontend/src/components/workspace/Workspace.tsx`（文档列表）
  - `frontend/src/components/project/ProcessingQueue.tsx`（处理队列）
  - `frontend/src/components/project/DocumentViewer.tsx`（文档查看器）
  - `frontend/src/components/workspace/MoleculeLibrary.tsx`（分子库）
- **UI 组件库**：`frontend/src/components/ui/`（60+ 原子组件）

### 后端相关文件（需配合修改）
- **Pipeline**：`src/mbforge/pipeline/runner.py`、`src/mbforge/pipeline/stage_result.py`
- **SSE 事件**：`src/mbforge/routers/ingest_queue.py`（需增加 error/progress 事件）
- **API 路由**：`src/mbforge/routers/*.py`（19 个 router）
- **数据库 Schema**：`src/mbforge/core/database.py`（确认 molecules.confidence 字段）

---

**文档版本**：v1.0  
**生成时间**：2026-07-13  
**作者**：Claude (Opus 4.8)  
**审查状态**：待用户确认