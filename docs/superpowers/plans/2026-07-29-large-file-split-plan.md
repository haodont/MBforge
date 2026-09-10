# 大文件拆分实施计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 把 `icons/index.tsx`、`MoleculeDetailPanel.tsx`、`services/pdfService.ts`、`styles/pdf-viewer.css` 四个大文件按域拆分或合并，行为不变，单测与导入路径继续可用。

**Architecture:** 纯重构，无业务改动。原子提交四个。已存在的 `api/http/pdf.ts` 与 `pdfService` 含同名但不同命名字段，避免硬合并；检测类搬到新建 `api/http/pdfDetection.ts`。

**Tech Stack:** React 19, TypeScript 6, Vitest 4.

---

## 文件结构

| 文件 | 现状 | 变化 |
|---|---|---|
| `frontend/src/components/icons/index.tsx` | 564 行单文件 | 拆 6 个域文件 + barrel |
| `frontend/src/components/molecule/MoleculeDetailPanel.tsx` | 667 行 | 抽 8 个子组件到 `detail/` |
| `frontend/src/services/pdfService.ts` | 599 行 | 拆检测函数到 `api/http/pdfDetection.ts`，删除 services/ |
| `frontend/src/styles/pdf-viewer.css` | 1392 行 | 拆 4 个 css |

---

### Task 1: 拆分 icons/index.tsx

**Files:**
- Create: `frontend/src/components/icons/nav.tsx`
- Create: `frontend/src/components/icons/actions.tsx`
- Create: `frontend/src/components/icons/ui.tsx`
- Create: `frontend/src/components/icons/arrows.tsx`
- Create: `frontend/src/components/icons/science.tsx`
- Create: `frontend/src/components/icons/brand.tsx`
- Modify: `frontend/src/components/icons/index.tsx`

- [ ] **Step 1: 把 nav 图标搬到 nav.tsx**

新建 `frontend/src/components/icons/nav.tsx`，从原 `index.tsx` 复制 `FolderIcon`、`FolderOpenIcon`、`FileTextIcon`、`PdfIcon`、`LayoutIcon`、`EnvironmentIcon`，加上 `import type { FC } from 'react'` 和 `import { baseSvg, type IconProps } from './types'`。

- [ ] **Step 2: 把 actions 图标搬到 actions.tsx**

新建 `frontend/src/components/icons/actions.tsx`，复制：`PlusIcon`、`XIcon`、`CheckIcon`、`SendIcon`、`TrashIcon`、`DownloadIcon`、`UploadIcon`、`EditIcon`、`CopyIcon`、`RefreshCwIcon`、`EyeIcon`、`EyeOffIcon`、`PinIcon`、`UnpinIcon`。

- [ ] **Step 3: 把 ui 图标搬到 ui.tsx**

新建 `frontend/src/components/icons/ui.tsx`，复制：`SearchIcon`、`SettingsIcon`、`ChatIcon`、`UserIcon`、`BotIcon`、`HelpIcon`、`InfoIcon`、`AlertIcon`、`GlobeIcon`、`HashIcon`、`ClockIcon`、`NoteIcon`、`CpuIcon`、`QueueIcon`、`TableIcon`、`GridIcon`、`ChevronDownIcon`、`ChevronUpIcon`。

- [ ] **Step 4: 把 arrows 图标搬到 arrows.tsx**

新建 `frontend/src/components/icons/arrows.tsx`，复制：`ChevronRightIcon`、`ChevronLeftIcon`、`ArrowLeftIcon`、`ExternalLinkIcon`。

- [ ] **Step 5: 把 science 图标搬到 science.tsx**

新建 `frontend/src/components/icons/science.tsx`，复制：`FlaskIcon`、`SparklesIcon`、`TargetIcon`、`BarChartIcon`、`ClusterIcon`、`NetworkIcon`、`FilterIcon`、`EmbedIcon`。

- [ ] **Step 6: 把 brand 图标搬到 brand.tsx**

新建 `frontend/src/components/icons/brand.tsx`，复制 `MoleculeLogo`。

- [ ] **Step 7: 替换 index.tsx 为 barrel**

替换 `frontend/src/components/icons/index.tsx` 内容为：

```tsx
export * from './nav'
export * from './actions'
export * from './ui'
export * from './arrows'
export * from './science'
export * from './brand'
```

- [ ] **Step 8: 类型与 lint 检查**

```bash
npx --prefix frontend tsc --noEmit --pretty false
npx --prefix frontend eslint src/components/icons
```

Expected: 无错误；既有 import 路径不需改。

- [ ] **Step 9: 提交**

```bash
git add frontend/src/components/icons
git commit -m "refactor(frontend): split icons barrel into domain files"
```

---

### Task 2: 拆分 MoleculeDetailPanel 子组件

**Files:**
- Create: `frontend/src/components/molecule/detail/DetectionHeader.tsx`
- Create: `frontend/src/components/molecule/detail/MoleculeRecordForm.tsx`
- Create: `frontend/src/components/molecule/detail/ReadOnlyMeta.tsx`
- Create: `frontend/src/components/molecule/detail/RelatedTextPanel.tsx`
- Create: `frontend/src/components/molecule/detail/DescItem.tsx`
- Create: `frontend/src/components/molecule/detail/DescGrid.tsx`
- Create: `frontend/src/components/molecule/detail/MoleCodeView.tsx`
- Create: `frontend/src/components/molecule/detail/FormField.tsx`
- Create: `frontend/src/components/molecule/detail/formInputStyle.ts`
- Modify: `frontend/src/components/molecule/MoleculeDetailPanel.tsx`

- [ ] **Step 1: 抽 formInputStyle**

新建 `frontend/src/components/molecule/detail/formInputStyle.ts`：

```ts
import type { CSSProperties } from 'react'

export const formInputStyle: CSSProperties = {
  padding: '6px 10px',
  fontSize: 13,
  borderRadius: 6,
  border: '1px solid var(--border)',
  background: 'var(--bg-base)',
  color: 'var(--text-primary)',
  fontFamily: 'inherit',
  outline: 'none',
}
```

- [ ] **Step 2: 抽 FormField**

新建 `frontend/src/components/molecule/detail/FormField.tsx`：

```tsx
import type { ReactNode } from 'react'

interface FormFieldProps {
  label: string
  children: ReactNode
}

export default function FormField({ label, children }: FormFieldProps) {
  return (
    <label style={{ display: 'flex', flexDirection: 'column', gap: 4 }}>
      <span style={{ fontSize: 12, fontWeight: 600, color: 'var(--text-muted)' }}>{label}</span>
      {children}
    </label>
  )
}
```

- [ ] **Step 3: 抽 DescItem 与 DescGrid**

新建 `frontend/src/components/molecule/detail/DescItem.tsx`：

```tsx
import type { CSSProperties } from 'react'

interface DescItemProps {
  label: string
  value: string
  unit?: string
}

export default function DescItem({ label, value, unit }: DescItemProps) {
  return (
    <div
      style={{
        display: 'flex',
        flexDirection: 'column',
        minHeight: 82,
        justifyContent: 'space-between',
        gap: 8,
        padding: '12px 14px',
        background: 'var(--bg-base)',
        borderRadius: 'var(--radius-md)',
        border: '1px solid var(--border)',
        boxShadow: 'var(--shadow-card)',
      }}
    >
      <div style={{ fontSize: 12, color: 'var(--text-muted)', fontWeight: 600 }}>{label}</div>
      <div style={{ display: 'flex', alignItems: 'baseline', gap: 6, minWidth: 0 }}>
        <span style={{ color: 'var(--text-primary)', fontFamily: 'monospace', fontSize: 19, fontWeight: 600, fontVariantNumeric: 'tabular-nums', overflowWrap: 'anywhere' }}>
          {value}
        </span>
        {unit && <span style={{ flexShrink: 0, color: 'var(--text-muted)', fontSize: 12 }}>{unit}</span>}
      </div>
    </div>
  )
}
```

新建 `frontend/src/components/molecule/detail/DescGrid.tsx`：

```tsx
import DescItem from './DescItem'

export interface ChemDescriptors {
  molecular_weight: number
  logp: number
  tpsa: number
  hba: number
  hbd: number
  formula: string
}

interface Props {
  descriptors: ChemDescriptors | null
  loading: boolean
}

export default function DescGrid({ descriptors, loading }: Props) {
  if (loading) {
    return (
      <div style={{ gridColumn: '1 / -1', textAlign: 'center', padding: 16, color: 'var(--text-muted)', fontSize: 13 }}>
        正在计算…
      </div>
    )
  }
  if (!descriptors) {
    return (
      <div style={{ gridColumn: '1 / -1', textAlign: 'center', padding: 16, color: 'var(--text-muted)', fontSize: 13 }}>
        无法计算理化性质
      </div>
    )
  }
  return (
    <>
      <DescItem label="分子式" value={descriptors.formula} />
      <DescItem label="分子量" value={descriptors.molecular_weight.toFixed(1)} unit="g/mol" />
      <DescItem label="脂溶性" value={descriptors.logp.toFixed(2)} unit="LogP" />
      <DescItem label="极性表面积" value={descriptors.tpsa.toFixed(1)} unit="Å²" />
      <DescItem label="氢键受体" value={String(descriptors.hba)} unit="HBA" />
      <DescItem label="氢键供体" value={String(descriptors.hbd)} unit="HBD" />
    </>
  )
}
```

注：父组件中的 `gridTemplateColumns` 容器仍保留在主面板中，子组件负责填充项。

- [ ] **Step 4: 抽 MoleCodeView**

新建 `frontend/src/components/molecule/detail/MoleCodeView.tsx`：

```tsx
import type { CSSProperties } from 'react'

interface Props {
  code: string | null
  loading: boolean
  error: string | null
}

export default function MoleCodeView({ code, loading, error }: Props) {
  const frameStyle: CSSProperties = {
    margin: 0,
    maxHeight: 240,
    overflow: 'auto',
    border: '1px solid var(--border)',
    borderRadius: 'var(--radius-md)',
    background: 'var(--bg-base)',
  }

  if (loading) {
    return <div style={{ ...frameStyle, padding: 14, color: 'var(--text-muted)', fontSize: 13 }}>正在生成 MoleCode…</div>
  }
  if (error) {
    return <div style={{ ...frameStyle, padding: 14, color: 'var(--danger)', fontSize: 13 }}>生成失败: {error}</div>
  }
  if (!code) {
    return <div style={{ ...frameStyle, padding: 14, color: 'var(--text-muted)', fontSize: 13 }}>无法生成 MoleCode</div>
  }

  return (
    <details style={frameStyle}>
      <summary style={{ minHeight: 40, display: 'flex', alignItems: 'center', padding: '0 14px', cursor: 'pointer', color: 'var(--text-secondary)', fontSize: 13, fontWeight: 600 }}>
        查看 MoleCode 文本
      </summary>
      <pre style={{ margin: 0, padding: '0 14px 14px', color: 'var(--text-secondary)', fontSize: 13, lineHeight: 1.6, whiteSpace: 'pre-wrap', wordBreak: 'break-word' }}>{code}</pre>
    </details>
  )
}
```

- [ ] **Step 5: 抽 RelatedTextPanel**

新建 `frontend/src/components/molecule/detail/RelatedTextPanel.tsx`：

```tsx
interface Props {
  texts: string[]
}

export default function RelatedTextPanel({ texts }: Props) {
  return (
    <section>
      <div style={{ fontSize: 11, fontWeight: 600, color: 'var(--text-muted)', marginBottom: 4 }}>
        相关文本
      </div>
      <div
        style={{
          display: 'flex',
          flexDirection: 'column',
          gap: 8,
          padding: '8px 10px',
          border: '1px solid var(--border)',
          borderRadius: 6,
          background: 'var(--bg-base)',
        }}
      >
        {texts.map((text) => (
          <p
            key={text}
            style={{
              margin: 0,
              color: 'var(--text-secondary)',
              fontSize: 11,
              lineHeight: 1.5,
              whiteSpace: 'pre-wrap',
              overflowWrap: 'anywhere',
            }}
          >
            {text}
          </p>
        ))}
      </div>
    </section>
  )
}
```

- [ ] **Step 6: 抽 ReadOnlyMeta**

新建 `frontend/src/components/molecule/detail/ReadOnlyMeta.tsx`：

```tsx
import type { MoleculeRecord } from '@/types'

interface Props {
  record: MoleculeRecord
}

export default function ReadOnlyMeta({ record }: Props) {
  return (
    <div
      style={{
        display: 'grid',
        gridTemplateColumns: 'repeat(2, 1fr)',
        gap: 8,
        padding: '8px 10px',
        background: 'var(--bg-base)',
        borderRadius: 6,
        border: '1px solid var(--border)',
        fontSize: 12,
        color: 'var(--text-muted)',
      }}
    >
      <div>来源文档: {record.source_doc || '-'}</div>
      <div>来源类型: {record.source_type || '-'}</div>
      <div>创建时间: {new Date(record.created_at).toLocaleString()}</div>
      <div>ID: {record.mol_id}</div>
    </div>
  )
}
```

- [ ] **Step 7: 抽 DetectionHeader**

新建 `frontend/src/components/molecule/detail/DetectionHeader.tsx`：

```tsx
import type { ExtractionResult } from '@/types'

interface Props {
  detection: ExtractionResult
  index: number
  onEdit: () => void
}

export default function DetectionHeader({ detection, index, onEdit }: Props) {
  return (
    <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between' }}>
      <div style={{ display: 'flex', alignItems: 'center', gap: 12 }}>
        <div style={{ fontSize: '13px', fontWeight: 600 }}>
          分子 #{index + 1}
        </div>
        <div style={{ display: 'flex', gap: '8px', fontSize: '11px', color: 'var(--text-muted)' }}>
          <span>检测: {Math.round(detection.moldet_conf * 100)}%</span>
          <span>识别: {Math.round(detection.scribe_conf * 100)}%</span>
          <span style={{ fontWeight: 600, color: 'var(--text-primary)' }}>
            综合: {Math.round(detection.composite_conf * 100)}%
          </span>
        </div>
      </div>
      <button
        onClick={onEdit}
        style={{
          padding: '5px 12px',
          background: 'var(--bg-elevated)',
          color: 'var(--text-primary)',
          border: '1px solid var(--border)',
          borderRadius: 6,
          fontSize: 11,
          fontWeight: 500,
          cursor: 'pointer',
          display: 'inline-flex',
          alignItems: 'center',
          gap: 4,
        }}
      >
        <svg width={11} height={11} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth={2}>
          <path d="M12 20h9" />
          <path d="M16.5 3.5a2.12 2.12 0 0 1 3 3L7 19l-4 1 1-4L16.5 3.5z" />
        </svg>
        编辑
      </button>
    </div>
  )
}
```

- [ ] **Step 8: 抽 MoleculeRecordForm**

新建 `frontend/src/components/molecule/detail/MoleculeRecordForm.tsx`：

```tsx
import type { ReactNode } from 'react'
import Button from '@/components/ui/Button'
import { EditIcon } from '@/components/icons'
import type { MoleculeRecord } from '@/types'
import FormField from './FormField'
import { formInputStyle } from './formInputStyle'

const VALID_STATUSES = ['confirmed', 'pending', 'corrected', 'rejected'] as const

interface Props {
  record: MoleculeRecord
  saving: boolean
  onChange: <K extends keyof MoleculeRecord>(field: K, value: MoleculeRecord[K]) => void
  onSave: () => void
  onEditStructure: () => void
  evidence: ReactNode
}

export default function MoleculeRecordForm({
  record,
  saving,
  onChange,
  onSave,
  onEditStructure,
  evidence,
}: Props) {
  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 12 }}>
      <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between' }}>
        <div style={{ fontSize: '16px', fontWeight: 600 }}>
          {record.name || record.mol_id}
        </div>
        <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
          <Button
            variant="secondary"
            size="sm"
            icon={<EditIcon size={13} />}
            onClick={onEditStructure}
          >
            编辑结构
          </Button>
          <Button variant="primary" size="sm" onClick={onSave} disabled={saving}>
            {saving ? '保存中...' : '保存'}
          </Button>
        </div>
      </div>

      {evidence}

      <FormField label="名称">
        <input
          type="text"
          value={record.name || ''}
          onChange={e => onChange('name', e.target.value)}
          style={formInputStyle}
        />
      </FormField>

      <FormField label="E-SMILES">
        <input
          type="text"
          value={record.esmiles}
          onChange={e => onChange('esmiles', e.target.value)}
          style={formInputStyle}
        />
      </FormField>

      <div style={{ display: 'grid', gridTemplateColumns: 'repeat(3, 1fr)', gap: 10 }}>
        <FormField label="活性">
          <input
            type="number"
            step="any"
            value={record.activity ?? ''}
            onChange={e =>
              onChange('activity', e.target.value === '' ? null : Number(e.target.value))
            }
            style={formInputStyle}
          />
        </FormField>

        <FormField label="活性类型">
          <input
            type="text"
            value={record.activity_type || ''}
            onChange={e => onChange('activity_type', e.target.value)}
            style={formInputStyle}
          />
        </FormField>

        <FormField label="单位">
          <input
            type="text"
            value={record.units || ''}
            onChange={e => onChange('units', e.target.value)}
            style={formInputStyle}
          />
        </FormField>
      </div>

      <FormField label="状态">
        <select
          value={record.status}
          onChange={e => onChange('status', e.target.value)}
          style={formInputStyle}
        >
          {VALID_STATUSES.map(status => (
            <option key={status} value={status}>
              {status}
            </option>
          ))}
        </select>
      </FormField>

    </div>
  )
}
```

- [ ] **Step 9: 瘦身 MoleculeDetailPanel.tsx**

修改 `frontend/src/components/molecule/MoleculeDetailPanel.tsx`：
- 删除 `DetectionHeader`、`MoleculeRecordForm`、`ReadOnlyMeta`、`RelatedTextPanel`、`DescItem`、`MoleCodeView`、`FormField` 函数和 `formInputStyle` 常量。
- 删除 `ChemDescriptors` 接口定义（移到 `DescGrid.tsx`）。
- 在文件顶部添加子组件导入：

```ts
import DetectionHeader from './detail/DetectionHeader'
import MoleculeRecordForm from './detail/MoleculeRecordForm'
import ReadOnlyMeta from './detail/ReadOnlyMeta'
import RelatedTextPanel from './detail/RelatedTextPanel'
import DescGrid from './detail/DescGrid'
import MoleCodeView from './detail/MoleCodeView'
```

- JSX 中 `descriptors` 网格部分替换为：

```tsx
<DescGrid descriptors={descriptors} loading={descLoading} />
```

- 文件其它逻辑保持不变。

- [ ] **Step 10: 类型与单测检查**

```bash
npx --prefix frontend tsc --noEmit --pretty false
npm --prefix frontend run test -- src/components/molecule/__tests__/MoleculeDetailPanel.test.tsx
```

Expected: tsc 通过；MoleculeDetailPanel 测试通过。

- [ ] **Step 11: 提交**

```bash
git add frontend/src/components/molecule/MoleculeDetailPanel.tsx frontend/src/components/molecule/detail
git commit -m "refactor(frontend): split MoleculeDetailPanel into sub-components"
```

---

### Task 3: 合并 services/pdfService 到 api/http/pdfDetection

**Files:**
- Create: `frontend/src/api/http/pdfDetection.ts`
- Modify: `frontend/src/components/project/pdf/usePdfViewer.ts`
- Delete: `frontend/src/services/pdfService.ts`
- Delete: `frontend/src/services/` 目录

- [ ] **Step 1: 创建 pdfDetection.ts**

新建 `frontend/src/api/http/pdfDetection.ts`，仅包含 pdfService 中检测/缓存相关导出：

```ts
/**
 * PDF detection — molecule detection cache and coref chain APIs.
 *
 * Mirrors the legacy `services/pdfService.ts` surface used by
 * `usePdfViewer`. Kept narrow on purpose: classification, OCR layout, and
 * image extraction live in `./pdf` to avoid snake_case / camelCase
 * drift between two near-identical interfaces.
 */

import { httpPost } from './_utils'
import type { ExtractionResult } from '@/types'

export interface ServiceResult<T> {
  success: boolean
  data?: T
  error?: string
}

export interface DetectionResponse {
  results: ExtractionResult[]
  count: number
  source: 'cache' | 'sidecar' | 'sidecar_error' | 'cache_miss'
  cachePath?: string
}

export interface CacheStats {
  diskUsageBytes: number
  cachedPageCount: number
  cachedDocCount: number
  schemaVersion: number
}

export interface CorefChain {
  molId: string
  occurrences: Array<{
    docId: string
    page: number
    bbox: [number, number, number, number]
    context: string
    confidence: number
    smiles: string
    esmiles: string
  }>
  aliases: string[]
}

function normalizeDetection(raw: Record<string, unknown>, page: number, index: number): ExtractionResult {
  const rawBbox = raw.bbox_pdf ?? raw.bbox
  const bbox = Array.isArray(rawBbox)
    ? rawBbox.map(Number) as [number, number, number, number]
    : rawBbox && typeof rawBbox === 'object'
      ? [
          Number((rawBbox as Record<string, unknown>).x1),
          Number((rawBbox as Record<string, unknown>).y1),
          Number((rawBbox as Record<string, unknown>).x2),
          Number((rawBbox as Record<string, unknown>).y2),
        ] as [number, number, number, number]
      : null
  const confidence = Number(raw.composite_conf ?? raw.confidence ?? raw.moldet_conf ?? 0)
  const esmiles = typeof raw.esmiles === 'string'
    ? raw.esmiles
    : typeof raw.smiles === 'string' ? raw.smiles : ''
  const name = typeof raw.name === 'string'
    ? raw.name
    : `Mol_${String(index + 1).padStart(3, '0')}`
  const contextText = typeof raw.context_text === 'string' ? raw.context_text : ''

  return {
    esmiles,
    smiles: esmiles,
    name,
    source: 'image',
    moldet_conf: confidence,
    scribe_conf: Number(raw.scribe_conf ?? confidence),
    composite_conf: confidence,
    bbox_pdf: bbox,
    page_idx: Number.isFinite(Number(raw.page_idx)) ? Number(raw.page_idx) : page - 1,
    context_text: contextText,
    mol_img_path: typeof raw.mol_img_path === 'string' ? raw.mol_img_path : null,
    status: 'pending',
    properties: raw.properties && typeof raw.properties === 'object'
      ? raw.properties as Record<string, unknown>
      : {},
  }
}

export async function detectPageMolecules(params: {
  libraryRoot: string
  docId: string
  page: number
  imageBase64: string
  pageWPts: number
  pageHPts: number
  imageW: number
  imageH: number
  force?: boolean
}): Promise<ServiceResult<DetectionResponse>> {
  try {
    const resp = await httpPost<{
      molecules: unknown[]
      count: number
      page_num: number
      width: number
      height: number
    }>('/api/v1/moldet/extract-pdf', {
      library_root: params.libraryRoot,
      doc_id: params.docId,
      page: params.page,
      dpi: 300,
      use_coref: false,
    })
    return {
      success: true,
      data: {
        results: resp.molecules.map((raw, index) => normalizeDetection(raw as Record<string, unknown>, params.page, index)),
        count: resp.count,
        source: 'sidecar',
      },
    }
  } catch (e) {
    return { success: false, error: String(e) }
  }
}

export async function saveDetections(
  libraryRoot: string,
  docId: string,
  page: number,
  results: ExtractionResult[],
): Promise<ServiceResult<void>> {
  try {
    await httpPost('/api/v1/detection-cache/save', {
      library_root: libraryRoot,
      detections: results.map((result, index) => ({
        mol_id: result.name || `Mol_${String(index + 1).padStart(3, '0')}`,
        doc_id: docId,
        page,
        bbox_x0: result.bbox_pdf?.[0] ?? null,
        bbox_y0: result.bbox_pdf?.[1] ?? null,
        bbox_x1: result.bbox_pdf?.[2] ?? null,
        bbox_y1: result.bbox_pdf?.[3] ?? null,
        conf_moldet: result.moldet_conf,
        conf_molscribe: result.scribe_conf,
        vlm_verified_esmiles: result.esmiles,
      })),
    })
    return { success: true }
  } catch (e) {
    return { success: false, error: String(e) }
  }
}

export async function getCachedDetections(params: {
  libraryRoot: string
  docId: string
  page: number
}): Promise<ServiceResult<DetectionResponse>> {
  try {
    const resp = await httpPost<{
      results: unknown[]
      count: number
      source: string
    }>('/api/v1/detection-cache/get', {
      library_root: params.libraryRoot,
      doc_id: params.docId,
      page: params.page,
    })
    return {
      success: true,
      data: {
        results: resp.results as ExtractionResult[],
        count: resp.count,
        source: resp.source as DetectionResponse['source'],
      },
    }
  } catch (e) {
    return { success: false, error: String(e) }
  }
}

export async function clearDocumentDetections(
  libraryRoot: string,
  docId: string,
): Promise<ServiceResult<void>> {
  try {
    await httpPost('/api/v1/detection-cache/clear-doc', { library_root: libraryRoot, doc_id: docId })
    return { success: true }
  } catch (e) {
    return { success: false, error: String(e) }
  }
}

export async function getDetectionStats(
  libraryRoot: string,
): Promise<ServiceResult<CacheStats>> {
  try {
    const resp = await httpPost<{
      disk_usage_bytes: number
      cached_page_count: number
      cached_doc_count: number
      schema_version: number
    }>('/api/v1/detection-cache/stats', { library_root: libraryRoot })
    return {
      success: true,
      data: {
        diskUsageBytes: resp.disk_usage_bytes,
        cachedPageCount: resp.cached_page_count,
        cachedDocCount: resp.cached_doc_count,
        schemaVersion: resp.schema_version,
      },
    }
  } catch (e) {
    return { success: false, error: String(e) }
  }
}

export async function getMoleculeCorefChain(
  libraryRoot: string,
  molId: string,
): Promise<ServiceResult<CorefChain>> {
  try {
    const resp = await httpPost<{
      mol_id: string
      occurrences: Array<{
        doc_id: string
        page: number
        bbox: [number, number, number, number]
        context: string
        confidence: number
        smiles: string
        esmiles: string
      }>
      aliases: string[]
    }>('/api/v1/coref/molecule-chain', { library_root: libraryRoot, mol_id: molId })

    return {
      success: true,
      data: {
        molId: resp.mol_id,
        occurrences: resp.occurrences.map(o => ({
          docId: o.doc_id,
          page: o.page,
          bbox: o.bbox,
          context: o.context,
          confidence: o.confidence,
          smiles: o.smiles,
          esmiles: o.esmiles,
        })),
        aliases: resp.aliases,
      },
    }
  } catch (e) {
    return { success: false, error: String(e) }
  }
}
```

不搬 `classifyPdf`、`getOcrLayout`、`PdfClassification`、`OcrBlock`、`OcrLayoutResult`、`PageParseResult`、`extractPdfImages`、`SidecarHealth`、`getSidecarStatus`、`restartSidecar`、`QuickScanResult`、`batchQuickScan` — 它们在 `api/http/pdf.ts` 已有等价或已被覆盖的版本。

- [ ] **Step 2: 更新 usePdfViewer.ts 导入**

修改 `frontend/src/components/project/pdf/usePdfViewer.ts` 顶部：

```ts
import {
  detectPageMolecules,
  saveDetections,
  clearDocumentDetections,
  getCachedDetections,
} from '@/api/http/pdfDetection'
```

- [ ] **Step 3: 删除 services/pdfService.ts 与 services 目录**

```bash
rm frontend/src/services/pdfService.ts
rmdir frontend/src/services
```

- [ ] **Step 4: 类型与单测检查**

```bash
npx --prefix frontend tsc --noEmit --pretty false
npm --prefix frontend run test -- src/components/project/__tests__/DocumentViewer.test.tsx
```

Expected: tsc 通过；DocumentViewer 测试通过。

- [ ] **Step 5: 提交**

```bash
git add frontend/src/api/http/pdfDetection.ts frontend/src/components/project/pdf/usePdfViewer.ts
git commit -m "refactor(frontend): move pdfService detection APIs into api/http"
```

---

### Task 4: 拆分 styles/pdf-viewer.css

**Files:**
- Create: `frontend/src/styles/pdf-canvas.css`
- Create: `frontend/src/styles/pdf-continuous.css`
- Create: `frontend/src/styles/pdf-result-pane.css`
- Create: `frontend/src/styles/pdf-toolbar.css`
- Modify: `frontend/src/styles/pdf-viewer.css`
- Modify: `frontend/src/main.tsx`

- [ ] **Step 1: 读 pdf-viewer.css，按节拆分**

用 `Read` 分段读 `frontend/src/styles/pdf-viewer.css`。按类名前缀分组：

- `.pdf-viewer*`、`.pdf-canvas*`、canvas 相关 → `pdf-canvas.css`
- `.pdf-continuous-pages*`、`.pdf-continuous-page*`、`.pdf-continuous-page__*` → `pdf-continuous.css`
- `.pdf-result-pane*`、`.pdf-stream-text`、`.pdf-stream-mol`、`.pdf-unified-stream`、`.pdf-result-*` → `pdf-result-pane.css`
- `.document-viewer-toolbar*`、`.document-viewer-title*`、`.document-viewer-layout-controls*`、`.document-viewer-pane*`、`.document-viewer-body*` → `pdf-toolbar.css`

如出现跨组类名（如 `.pdf-viewer-loader`），按组件归属就近放。

- [ ] **Step 2: 创建 pdf-canvas.css**

```bash
# 用 Edit 工具从原文件中剪出对应选择器块，粘贴到新文件。
```

新文件只放 `.pdf-viewer*` 起始到 `.pdf-canvas-loading` 结束的内容。

- [ ] **Step 3: 创建 pdf-continuous.css**

从原文件中复制 `.pdf-continuous-pages*` 全部分块到新文件。

- [ ] **Step 4: 创建 pdf-result-pane.css**

从原文件中复制 `.pdf-result-pane*`、`.pdf-stream-*`、`.pdf-unified-stream` 到新文件。

- [ ] **Step 5: 创建 pdf-toolbar.css**

从原文件中复制 `.document-viewer-toolbar*`、`.document-viewer-title*`、`.document-viewer-layout-controls*`、`.document-viewer-pane*`、`.document-viewer-body*` 到新文件。

- [ ] **Step 6: 清空 pdf-viewer.css 或改为聚合入口**

把 `frontend/src/styles/pdf-viewer.css` 改为：

```css
/* Aggregator — actual rules live in pdf-canvas.css, pdf-continuous.css,
 * pdf-result-pane.css, pdf-toolbar.css. Kept so legacy imports that
 * still reference this file continue to load the same styles. */
@import './pdf-canvas.css';
@import './pdf-continuous.css';
@import './pdf-result-pane.css';
@import './pdf-toolbar.css';
```

- [ ] **Step 7: 在 main.tsx 中显式 import**

修改 `frontend/src/main.tsx`，在原 `import './styles/pdf-viewer.css'` 处替换为：

```ts
import './styles/pdf-toolbar.css'
import './styles/pdf-canvas.css'
import './styles/pdf-continuous.css'
import './styles/pdf-result-pane.css'
```

同时删除 `import './styles/pdf-viewer.css'`。

- [ ] **Step 8: 构建验证**

```bash
npm --prefix frontend run build
```

Expected: 构建通过；不出现缺失类警告。

- [ ] **Step 9: 提交**

```bash
git add frontend/src/styles/pdf-canvas.css frontend/src/styles/pdf-continuous.css frontend/src/styles/pdf-result-pane.css frontend/src/styles/pdf-toolbar.css frontend/src/styles/pdf-viewer.css frontend/src/main.tsx
git commit -m "refactor(frontend): split pdf-viewer.css by component domain"
```

---

### Task 5: 收尾验证

**Files:**
- 无源码修改

- [ ] **Step 1: 完整测试**

```bash
npm --prefix frontend run test
```

记录既有失败（`Workspace.test.tsx`、`chem.test.ts`）与本次是否引入新失败。

- [ ] **Step 2: 类型与构建**

```bash
npx --prefix frontend tsc --noEmit --pretty false
npm --prefix frontend run build
```

- [ ] **Step 3: 检查工作树**

```bash
git status --short
git log --oneline -5
```

Expected：四个独立原子提交；其他既有工作树改动保持不变。

---

## 自检

- icons：6 个域文件 + barrel，导入路径不变。
- MoleculeDetailPanel：8 个子组件文件，主面板只编排。
- pdfService：检测函数迁入 `pdfDetection.ts`，其他保留在 `pdf.ts`，调用方改 import。
- pdf-viewer.css：4 个子 css + aggregator + main.tsx 显式 import。

未引入业务行为改动；测试预期保持现有通过率（既有失败除外）。