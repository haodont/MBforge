# 大文件拆分设计

## 范围

按用户选择，处理以下四个文件/目录：

1. `frontend/src/components/icons/index.tsx`（564 行）
2. `frontend/src/components/molecule/MoleculeDetailPanel.tsx`（667 行）
3. `frontend/src/services/pdfService.ts`（599 行）
4. `frontend/src/styles/pdf-viewer.css`（1392 行）

只做拆分/合并，不重写业务逻辑，不引入新依赖。

---

## A. icons 按域拆分

源文件内已按类别注释分组：Nav / Actions / UI / Arrows / Science / Brand。

新结构：

```
frontend/src/components/icons/
  types.ts                 # 保持现状
  nav.tsx                  # FolderIcon, FolderOpenIcon, FileTextIcon, PdfIcon, LayoutIcon, EnvironmentIcon
  actions.tsx              # Plus, X, Check, Send, Trash, Download, Upload, Edit, Copy, RefreshCw, Eye, EyeOff, Pin, Unpin
  ui.tsx                   # Search, Settings, Chat, User, Bot, Help, Info, Alert, Globe, Hash, Clock, Note, Cpu, Queue, Table, Grid, ChevronDown, ChevronUp
  arrows.tsx               # ChevronRight, ChevronLeft, ArrowLeft, ExternalLink
  science.tsx              # Flask, Sparkles, Target, BarChart, Cluster, Network, Filter, Embed
  brand.tsx                # MoleculeLogo
  index.tsx                # 仅做 re-export，保持外部 `import { EditIcon } from '@/components/icons'` 可用
```

行为不变；导入路径不变；测试无需改。

---

## B. MoleculeDetailPanel 拆子组件

主面板只保留编排和共享状态；将现有内部子组件移到独立文件：

```
frontend/src/components/molecule/MoleculeDetailPanel.tsx     # 编排、状态、MoleculeEditorDialog 渲染
frontend/src/components/molecule/detail/
  DetectionHeader.tsx       # 检测模式头部（置信度 + 编辑按钮）
  MoleculeRecordForm.tsx    # 记录模式编辑表单
  ReadOnlyMeta.tsx          # 记录模式只读元信息
  RelatedTextPanel.tsx      # 相关文本列表
  DescItem.tsx              # 理化性质卡片
  DescGrid.tsx              # 理化性质 6 项网格（含 loading/empty）
  MoleCodeView.tsx          # MoleCode 折叠面板
  FormField.tsx             # 标签+控件包装
  formInputStyle.ts         # 共享 input 样式常量
```

主面板文件目标行数约 220（状态 + JSX 编排）。Props 类型随组件迁移。`MoleculeEditorDialog` 与 `EvidencePanel` 引用不变。

---

## C. services/pdfService 合并到 api/http/pdf

源文件导出：`detectPageMolecules`、`saveDetections`、`clearDocumentDetections`、`getCachedDetections`、类型 `DetectionResponse`、`CacheStats`、`ServiceResult`。

合并目标：`frontend/src/api/http/pdf.ts`。仅把函数体搬到该文件；调用方 `usePdfViewer.ts` 修改 import。

删除：`frontend/src/services/` 整目录。

`ServiceResult<T>` 是泛型包装，可能被其他服务共用；保留导出，但不强制 `pdf.ts` 内使用。

---

## D. pdf-viewer.css 按域拆分

源文件 1392 行；类名域集中在四个组件：`PdfViewer`、`PdfContinuousView`、`PdfResultPane`、`DocumentViewer` 工具栏。

新结构：

```
frontend/src/styles/
  pdf-viewer.css            # 仅保留 @import 入口 + 通用变量（如果需要）
  pdf-canvas.css             # .pdf-viewer, .pdf-canvas, canvas 相关
  pdf-continuous.css         # .pdf-continuous-pages, .pdf-continuous-page*, .pdf-continuous-page__placeholder, .pdf-continuous-page__number, .pdf-continuous-page__canvas
  pdf-result-pane.css        # .pdf-result-pane*, .pdf-stream-text, .pdf-stream-mol, .pdf-unified-stream
  pdf-toolbar.css            # .document-viewer-toolbar, .document-viewer-title, .document-viewer-layout-controls
```

`main.tsx` 顺序 import 新文件；删除 `pdf-viewer.css` 引用或保留为 `@import` 聚合入口。

类名按上述四组分隔；如果中间存在跨组件共享的样式（`.pdf-canvas-container` 等），归到对应组件文件。

---

## 测试

每个改动只验证组件/导入行为不变：

- `npm --prefix frontend run test -- src/components/molecule/__tests__/MoleculeDetailPanel.test.tsx`
- `npm --prefix frontend run test -- src/components/project/__tests__/DocumentViewer.test.tsx`
- `npm --prefix frontend run test`

未新增测试需求；既有测试覆盖上述组件。

## 验证

```bash
npx --prefix frontend eslint src/components/icons src/components/molecule src/api/http/pdf.ts src/components/project/pdf/usePdfViewer.ts src/styles
npx --prefix frontend tsc --noEmit --pretty false
npm --prefix frontend run test
npm --prefix frontend run build
```

## 风险

- `MoleculeDetailPanel` 子组件 props 类型需在迁移时一并带走，避免破坏。
- `pdfService` 合并后若 `ServiceResult` 在别处有引用，需要保留导出。
- `pdf-viewer.css` 拆分需保证 CSS 选择器不跨文件耦合；建议拆分后保留一段时间的 `@import` 聚合，待验证后再彻底删除原文件。
- 工作树中已存在未提交改动（含 `settings-*` 拆分文件）；本改动不与之冲突。