# 复核中心参比优先对照 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 为统一复核中心提供参比证据图片优先展示，并在下方显示由当前 SMILES/eSMILES 自动生成的 RDKit 2D 渲染；复用分子库现有组件和 PDF 定位能力。

**Architecture:** 复核队列继续由 `review.ts` 提供数据。复核详情将队列项目映射为现有证据模型，复用 `EvidencePanel` 的图片/结构对照和 `PdfCanvas` 的页码、bbox 定位；复核动作与结构修正仍走现有 review/molecule API。缺失 crop 或 RDKit 失败时显示明确状态，不伪造图片。

**Tech Stack:** React 19, TypeScript 6, React Query, Vitest, existing `EvidencePanel`, `MoleculeDetailPanel`, `PdfCanvas`, RDKit SVG HTTP client.

---

## 文件结构

- Modify: `frontend/src/components/review/ReviewCenter.tsx`（或当前复核中心实际入口；先确认现有文件名）——队列、详情布局、PDF 打开回调。
- Create/Modify: `frontend/src/components/review/ReviewEvidenceComparison.tsx`——参比优先容器；封装 `EvidencePanel` 所需证据映射和缺失状态。
- Modify: `frontend/src/components/molecule/EvidencePanel.tsx`——导出或参数化结构对照能力，保持分子库现有行为。
- Modify: `frontend/src/components/PdfCanvas.tsx` 或现有 PDF tab 调度组件——仅在当前复核入口缺少回调时接入既有定位链路，不重复实现 PDF 渲染。
- Test: `frontend/src/components/review/__tests__/ReviewEvidenceComparison.test.tsx`——图片、RDKit、缺失状态、PDF 定位入口。
- Test: 当前复核中心测试文件——验证队列项目选中后显示详情，并保留 review action 行为。
- Modify: `CHANGELOG.md`——记录用户可见的复核中心对照能力。

### Task 1: 盘点并锁定复核中心入口

**Files:**
- Read: `frontend/src/components/review/**`, `frontend/src/components/**/*Review*`, `frontend/src/api/http/review.ts`
- Test: 当前复核中心相关测试文件

- [ ] **Step 1: 定位入口与现有详情状态**

运行：
```bash
rg -n "reviewQueue|ReviewQueueItem|reviewDecide|复核|ReviewCenter" frontend/src
```

记录实际入口、选中项 state、详情组件、PDF 打开函数和测试文件；若路径不同，以实际路径替换本计划后续路径。

- [ ] **Step 2: 运行现有相关测试**

运行：
```bash
npm --prefix frontend run test -- --run <当前复核中心测试文件>
```

预期：现有测试通过；若基线失败，记录完整错误，不带着基线失败进入实现。

- [ ] **Step 3: 提交盘点结果**

不修改代码；将实际文件路径和接口字段写入本计划对应位置，确保后续任务不依赖猜测。

### Task 2: 先写参比优先组件失败测试

**Files:**
- Create: `frontend/src/components/review/__tests__/ReviewEvidenceComparison.test.tsx`
- Test data: `ReviewQueueItem` fixture with `doc_id`, `page`, `bbox`, `crop_relpath`, `smiles`

- [ ] **Step 1: 写图片与当前渲染行为测试**

测试应断言：传入有效 `crop_url` 和 SMILES 后，DOM 同时包含“参比图片”和“当前渲染”标签；参比 `<img>` 使用 crop URL；当前渲染最终使用 `data:image/svg+xml` 图片。

- [ ] **Step 2: 写缺失证据测试**

传入 `crop_url: null`，断言显示明确的“无参比图片”状态，仍显示 SMILES 文本；禁止断言伪造图片 URL。

- [ ] **Step 3: 写 PDF 定位入口测试**

点击“打开原文”，断言回调收到：
```ts
(docId, page, { x0, y0, x1, y1 })
```
且数值来自队列项目，不发生坐标转换或丢失。

- [ ] **Step 4: 运行测试确认失败**

运行：
```bash
npm --prefix frontend run test -- --run frontend/src/components/review/__tests__/ReviewEvidenceComparison.test.tsx
```

预期：FAIL，因为组件尚未实现。

### Task 3: 实现参比优先证据组件

**Files:**
- Create/Modify: `frontend/src/components/review/ReviewEvidenceComparison.tsx`
- Modify: `frontend/src/components/molecule/EvidencePanel.tsx`（仅导出共享渲染函数/组件或增加可选布局参数）

- [ ] **Step 1: 定义严格输入类型**

使用现有 `ReviewQueueItem`，额外接收：
```ts
interface ReviewEvidenceComparisonProps {
  item: ReviewQueueItem
  cropUrl: string | null
  libraryRoot: string | null
  onOpenPdf: (docId: string, page: number | null, bbox: EvidenceItem['bbox']) => void
}
```

- [ ] **Step 2: 映射证据字段**

将 `doc_id`、`page`、`bbox`、`cropUrl` 映射为单个 `EvidenceItem`；保留 null 值。不要直接拼接 `storage/` 或 `.mbforge/` 路径；使用现有 artifact URL/client 规则。

- [ ] **Step 3: 实现参比优先布局**

布局顺序固定为：
1. 参比图片大图和来源信息；
2. “打开原文”按钮；
3. 当前 RDKit 2D 渲染；
4. SMILES/eSMILES 文本。

RDKit 生成复用现有 `smilesToRdkitSvg`。请求中、失败中、无 SMILES 分别显示明确状态。图片使用 `alt`、`loading="lazy"` 和 contain 样式。

- [ ] **Step 4: 保持分子库回归行为**

若抽取 `StructureComparison`，保留 `EvidencePanel` 现有双栏默认布局和文案；复核中心通过独立容器使用参比优先布局，不改变分子库默认视觉。

- [ ] **Step 5: 运行组件测试**

运行：
```bash
npm --prefix frontend run test -- --run frontend/src/components/review/__tests__/ReviewEvidenceComparison.test.tsx
```

预期：PASS。

### Task 4: 接入复核中心详情与 PDF 定位

**Files:**
- Modify: Task 1 定位出的复核中心入口
- Modify: Task 1 定位出的 PDF/tab 调度组件（仅必要范围）
- Test: 当前复核中心测试文件

- [ ] **Step 1: 将选中队列项传入对照组件**

选中项变化时渲染 `ReviewEvidenceComparison`；无选中项显示现有空状态；loading/error 沿用复核中心现有状态组件。

- [ ] **Step 2: 解析 crop URL**

优先使用 review API 已提供的 URL/字段；若只有 `crop_relpath`，调用现有图片 URL helper 或增加最小 HTTP helper，遵守 `ArtifactResolver` 的 canonical storage 规则。禁止在组件中 `join('storage', ...)`。

- [ ] **Step 3: 接通 PDF 回调**

调用现有 `openTab`/PDF handler，传递 `doc_id`、页码和 bbox；复用 `PdfCanvas` 的初始页与 bbox 参数。不得新建第二套 PDF 渲染器。

- [ ] **Step 4: 保留复核动作**

确认、驳回、重新打开、结构修正仍调用既有 API；动作失败时不提前清除详情或更新状态，显示现有错误反馈。

- [ ] **Step 5: 更新集成测试**

断言：选择队列项后出现参比图标签；点击原文回调携带正确 page/bbox；执行 review action 后仍保持既有状态刷新逻辑。

- [ ] **Step 6: 运行相关测试**

运行：
```bash
npm --prefix frontend run test -- --run <复核中心测试> frontend/src/components/review/__tests__/ReviewEvidenceComparison.test.tsx
```

预期：PASS。

### Task 5: 视觉与类型回归

**Files:**
- Modify: 必要 CSS/组件文件

- [ ] **Step 1: 检查可访问性与响应式布局**

确认参比图和当前渲染均有稳定 `alt`，按钮可键盘操作；窄屏下布局不产生横向溢出；缺失状态可读且不占用虚假图片空间。

- [ ] **Step 2: 运行 lint 与类型检查**

运行：
```bash
npm --prefix frontend run lint
npx --prefix frontend tsc --noEmit
```

预期：均 PASS。

- [ ] **Step 3: 运行前端完整测试与构建**

运行：
```bash
npm --prefix frontend run test
npm --prefix frontend run build
```

预期：均 PASS。

### Task 6: 文档与交付

**Files:**
- Modify: `CHANGELOG.md`
- Modify: 相关复核中心用户文档（若 Task 1 发现已有文档）

- [ ] **Step 1: 更新用户可见变更**

记录：复核中心现在优先显示证据 crop，可通过页码/bbox 打开 PDF 原文，并显示基于当前 SMILES/eSMILES 的 RDKit 2D 渲染；无证据或渲染失败会显示明确状态。

- [ ] **Step 2: 检查变更范围**

运行：
```bash
git diff --check
git status --short
```

确认没有修改无关文件，没有提交 PDF、真实库数据或临时服务器文件。

- [ ] **Step 3: 提交原子变更**

```bash
git add frontend/src/components frontend/src/api frontend/src/components/review CHANGELOG.md
 git commit -m "feat(review): show evidence-first structure comparison"
```

提交前确认用户明确要求提交；若未要求，不自动提交。

## 自审结果

- 需求覆盖：参比证据图片、当前 RDKit 2D 渲染、B 方案参比优先布局、分子库组件复用、PDF 页码/bbox 定位、缺失与失败状态、测试、变更日志均有任务覆盖。
- 占位扫描：无 `TBD`、`TODO` 或“适当处理”类空泛步骤。
- 类型一致性：组件输入使用 `ReviewQueueItem`；PDF 回调复用 `EvidenceItem['bbox']`；现有 `smilesToRdkitSvg` 保持统一。
- 范围约束：Task 1 明确先确认实际复核入口，避免因仓库路径漂移猜测文件；不新增上传链路、不新增存储规则、不重复实现 PDF 渲染。
