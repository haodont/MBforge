# 清理废弃文件与进一步拆分样式实现计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 删除已废弃的 SettingsModal.tsx 和 Environment.tsx，将 environment/ 子组件迁移到 settings/ 下，并将 global.css 中剩余的 PDF Viewer、Notes、MoleculeDisplay 样式拆分为独立样式文件。

**Architecture:** 通过文件移动、导入路径更新、CSS 规则迁移完成清理；每个样式域一个独立文件，main.tsx 统一导入。

**Tech Stack:** React, TypeScript, CSS, Vite

---

## 文件结构映射

### 迁移目录

- `frontend/src/components/environment/StatCard.tsx` → `frontend/src/components/settings/environment/StatCard.tsx`
- `frontend/src/components/environment/LibrarySection.tsx` → `frontend/src/components/settings/environment/LibrarySection.tsx`
- `frontend/src/components/environment/sections/` → `frontend/src/components/settings/environment/sections/`
- `frontend/src/components/environment/types.ts` → `frontend/src/components/settings/environment/types.ts`
- 其他 `frontend/src/components/environment/*.tsx` 一并迁移（保持目录结构不变）

### 删除文件

- `frontend/src/components/SettingsModal.tsx`
- `frontend/src/components/Environment.tsx`

### 新增样式文件

- `frontend/src/styles/pdf-viewer.css`
- `frontend/src/styles/notes.css`
- `frontend/src/styles/molecule-display.css`

### 修改文件

- `frontend/src/components/settings/SystemTab.tsx` — 更新 environment 子组件导入路径
- `frontend/src/components/settings/DetectionCacheCard.tsx` — 更新注释
- `frontend/src/components/settings/SidecarCard.tsx` — 更新注释
- `frontend/src/styles/global.css` — 移除 PDF/Notes/MoleculeDisplay 样式
- `frontend/src/main.tsx` — 导入新增样式文件

---

## Task 1: 迁移 environment/ 目录到 settings/ 下

**Files:**
- Create: `frontend/src/components/settings/environment/`（通过移动）
- Delete: `frontend/src/components/environment/`
- Modify: `frontend/src/components/settings/SystemTab.tsx`
- Modify: `frontend/src/components/settings/DetectionCacheCard.tsx`
- Modify: `frontend/src/components/settings/SidecarCard.tsx`

- [ ] **Step 1: 移动目录**

Run:
```bash
cd frontend/src/components
mv environment settings/environment
```

- [ ] **Step 2: 更新 SystemTab.tsx 导入路径**

Change:
```typescript
import StatCard from '@/components/environment/StatCard'
import LibrarySection, { type CapabilityStatus } from '@/components/environment/LibrarySection'
} from '@/components/environment/sections'
import type { ModelInfo, ModelPaths } from '@/components/environment/types'
```

To:
```typescript
import StatCard from '@/components/settings/environment/StatCard'
import LibrarySection, { type CapabilityStatus } from '@/components/settings/environment/LibrarySection'
} from '@/components/settings/environment/sections'
import type { ModelInfo, ModelPaths } from '@/components/settings/environment/types'
```

- [ ] **Step 3: 更新注释**

In `DetectionCacheCard.tsx` and `SidecarCard.tsx`, change the comment:
```typescript
// Used by the main Environment page.
```
To:
```typescript
// Used by Settings > System tab.
```

- [ ] **Step 4: 运行类型检查**

Run: `cd frontend && npx tsc --noEmit`
Expected: 零 errors

- [ ] **Step 5: 提交**

```bash
git add frontend/src/components/settings/environment/ frontend/src/components/environment/ frontend/src/components/settings/SystemTab.tsx frontend/src/components/settings/DetectionCacheCard.tsx frontend/src/components/settings/SidecarCard.tsx
git commit -m "refactor(frontend): move environment components under settings"
```

---

## Task 2: 删除废弃的 SettingsModal.tsx 和 Environment.tsx

**Files:**
- Delete: `frontend/src/components/SettingsModal.tsx`
- Delete: `frontend/src/components/Environment.tsx`

- [ ] **Step 1: 确认无引用**

Run:
```bash
cd frontend/src
grep -R "from ['\"].*SettingsModal['\"]" --include='*.tsx' --include='*.ts' .
grep -R "from ['\"].*Environment['\"]" --include='*.tsx' --include='*.ts' . | grep -v "components/settings/environment"
```

Expected: 两条命令均无输出（无引用）。

- [ ] **Step 2: 删除文件**

```bash
cd frontend/src/components
rm SettingsModal.tsx Environment.tsx
```

- [ ] **Step 3: 运行类型检查**

Run: `cd frontend && npx tsc --noEmit`
Expected: 零 errors

- [ ] **Step 4: 提交**

```bash
git add frontend/src/components/SettingsModal.tsx frontend/src/components/Environment.tsx
git commit -m "chore(frontend): remove deprecated SettingsModal and Environment page"
```

---

## Task 3: 拆分 PDF Viewer 样式到 pdf-viewer.css

**Files:**
- Create: `frontend/src/styles/pdf-viewer.css`
- Modify: `frontend/src/styles/global.css`
- Modify: `frontend/src/main.tsx`

- [ ] **Step 1: 读取 global.css 中 PDF Viewer 样式范围**

PDF Viewer 样式从 `frontend/src/styles/global.css` 第 24 行开始，到第 316 行之前结束（Notes 组件从第 317 行开始）。

- [ ] **Step 2: 创建 pdf-viewer.css**

Create `frontend/src/styles/pdf-viewer.css` and copy all CSS rules from line 24 up to (but not including) line 317 of `global.css` into it.

- [ ] **Step 3: 从 global.css 中移除 PDF Viewer 样式**

Remove the copied block from `frontend/src/styles/global.css`.

- [ ] **Step 4: 在 main.tsx 中导入 pdf-viewer.css**

Add after the existing `import './styles/settings.css'`:
```typescript
import './styles/pdf-viewer.css'
```

- [ ] **Step 5: 运行类型检查和构建**

Run: `cd frontend && npx tsc --noEmit`
Expected: 零 errors

Run: `cd frontend && npm run build`
Expected: 构建成功

- [ ] **Step 6: 提交**

```bash
git add frontend/src/styles/pdf-viewer.css frontend/src/styles/global.css frontend/src/main.tsx
git commit -m "style(frontend): split pdf-viewer styles into separate stylesheet"
```

---

## Task 4: 拆分 Notes 样式到 notes.css

**Files:**
- Create: `frontend/src/styles/notes.css`
- Modify: `frontend/src/styles/global.css`
- Modify: `frontend/src/main.tsx`

- [ ] **Step 1: 读取 global.css 中 Notes 样式范围**

Notes 样式从 `frontend/src/styles/global.css` 第 317 行开始，到第 521 行之前结束（MoleculeDisplay 组件从第 522 行开始）。

- [ ] **Step 2: 创建 notes.css**

Create `frontend/src/styles/notes.css` and copy all CSS rules from line 317 up to (but not including) line 522 of `global.css` into it.

- [ ] **Step 3: 从 global.css 中移除 Notes 样式**

Remove the copied block from `frontend/src/styles/global.css`.

- [ ] **Step 4: 在 main.tsx 中导入 notes.css**

Add after `pdf-viewer.css`:
```typescript
import './styles/notes.css'
```

- [ ] **Step 5: 运行类型检查和构建**

Run: `cd frontend && npx tsc --noEmit`
Expected: 零 errors

Run: `cd frontend && npm run build`
Expected: 构建成功

- [ ] **Step 6: 提交**

```bash
git add frontend/src/styles/notes.css frontend/src/styles/global.css frontend/src/main.tsx
git commit -m "style(frontend): split notes styles into separate stylesheet"
```

---

## Task 5: 拆分 MoleculeDisplay 样式到 molecule-display.css

**Files:**
- Create: `frontend/src/styles/molecule-display.css`
- Modify: `frontend/src/styles/global.css`
- Modify: `frontend/src/main.tsx`

- [ ] **Step 1: 读取 global.css 中 MoleculeDisplay 样式范围**

MoleculeDisplay 样式从 `frontend/src/styles/global.css` 第 522 行开始，到文件末尾。

- [ ] **Step 2: 创建 molecule-display.css**

Create `frontend/src/styles/molecule-display.css` and copy all CSS rules from line 522 to the end of `global.css` into it.

- [ ] **Step 3: 从 global.css 中移除 MoleculeDisplay 样式**

Remove the copied block from `frontend/src/styles/global.css`.

- [ ] **Step 4: 在 main.tsx 中导入 molecule-display.css**

Add after `notes.css`:
```typescript
import './styles/molecule-display.css'
```

- [ ] **Step 5: 运行类型检查和构建**

Run: `cd frontend && npx tsc --noEmit`
Expected: 零 errors

Run: `cd frontend && npm run build`
Expected: 构建成功

- [ ] **Step 6: 提交**

```bash
git add frontend/src/styles/molecule-display.css frontend/src/styles/global.css frontend/src/main.tsx
git commit -m "style(frontend): split molecule-display styles into separate stylesheet"
```

---

## Task 6: 端到端验证

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

- [ ] **Step 5: 报告结果**

Report all command outputs.

---

## Self-Review Checklist

- [x] Spec coverage：每个设计文档中的需求都有对应任务。
- [x] Placeholder scan：无 TBD、TODO 等模糊表述。
- [x] Type consistency：导入路径在 SystemTab 中一致。
- [x] File paths：所有文件路径均基于当前项目结构。
- [x] Testability：每个任务都有明确的类型检查或测试命令。
