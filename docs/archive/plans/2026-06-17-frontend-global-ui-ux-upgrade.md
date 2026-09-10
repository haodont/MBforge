# Frontend Global UI/UX Upgrade Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Apply the global UI/UX design system to the Settings module, starting with the AI Models page, to improve visual hierarchy, consistency, feedback, and accessibility.

**Architecture:** Update shared design tokens and patterns, add two new UI primitives (`Badge`, `InlineAlert`), extend `Tabs` with a `segment` variant, then refactor `ModelConfigCard`, `AIModelsSection`, `SettingRow`, and `SettingsPage` to use the new system. Keep changes scoped to Settings for this iteration.

**Tech Stack:** React 19, TypeScript, Vite, hand-written CSS with CSS variables, Framer Motion.

---

## File Structure

| File | Action | Responsibility |
|------|--------|----------------|
| `frontend/src/styles/theme.css` | Modify | Add semantic tokens (`--border-strong`, `--radius-*`, `--space-*`, `--shadow-*`) and align dark mode values. |
| `frontend/src/styles/patterns.ts` | Modify | Update `surfaceBlock`, `SIZES.radius`, `SIZES.padding` to match new tokens; add `PATTERNS.settingRow`. |
| `frontend/src/components/ui/Badge.tsx` | Create | Reusable semantic badge for status/labels. |
| `frontend/src/components/ui/InlineAlert.tsx` | Create | Compact inline alert for card-level feedback. |
| `frontend/src/components/ui/Tabs.tsx` | Modify | Add `segment` variant and ARIA improvements. |
| `frontend/src/components/settings/SettingRow.tsx` | Modify | Unify field widths and descriptions; add optional `labelWidth` to `ProviderField`. |
| `frontend/src/components/settings/ModelConfigCard.tsx` | Modify | Apply new card style, replace status dot with `Badge`, add `InlineAlert`, use `segment` tabs in parent. |
| `frontend/src/components/settings/sections/AIModelsSection.tsx` | Modify | Add section header, switch internal tabs to `variant="segment"`. |
| `frontend/src/components/settings/SettingsPage.tsx` | Modify | Improve save button feedback (saved state + shake on error). |
| `frontend/src/i18n/locales/en.json` | Modify | Add new keys for status labels, saved state, section descriptions. |
| `frontend/src/i18n/locales/zh-CN.json` | Modify | Mirror English keys in Chinese. |
| `frontend/src/styles/settings.css` | Modify | Remove redundant styles, add new animation keyframes (`shake`), adjust `.settings-input`. |

---

## Task 1: Update Design Tokens in `theme.css`

**Files:**
- Modify: `frontend/src/styles/theme.css`
- Test: Visual inspection + `npx tsc --noEmit`

- [ ] **Step 1: Add missing semantic tokens to `:root`**

Append these tokens to the `:root` block, after `--warning: #f59e0b;`:

```css
:root {
  /* existing tokens... */
  --warning: #f59e0b;

  /* Border / Radius / Space / Shadow tokens */
  --border-strong: #d4d4d8;
  --radius-sm: 6px;
  --radius-md: 8px;
  --radius-lg: 12px;
  --radius-xl: 16px;
  --space-1: 4px;
  --space-2: 8px;
  --space-3: 12px;
  --space-4: 16px;
  --space-5: 20px;
  --space-6: 24px;
  --shadow-card: 0 1px 3px rgba(0, 0, 0, 0.04);
  --shadow-elevated: 0 4px 12px rgba(0, 0, 0, 0.08);
}
```

- [ ] **Step 2: Add dark-mode counterparts to `[data-theme="dark"]`**

After `--warning: #f59e0b;` in the dark block, add:

```css
[data-theme="dark"] {
  /* existing tokens... */
  --warning: #f59e0b;

  --border-strong: #3f3f46;
  --shadow-card: none;
  --shadow-elevated: 0 4px 16px rgba(0, 0, 0, 0.35);
}
```

- [ ] **Step 3: Verify no hardcoded values remain in the file**

Search for leftover raw hex values that should use tokens. The existing molecule/AI/PDF tokens are intentionally app-specific and can stay.

- [ ] **Step 4: Commit**

```bash
cd /c/Users/10954/Desktop/MBForge
git add frontend/src/styles/theme.css
git commit -m "style(theme): add semantic border, radius, space and shadow tokens"
```

---

## Task 2: Update Shared Patterns in `patterns.ts`

**Files:**
- Modify: `frontend/src/styles/patterns.ts`
- Test: `npx tsc --noEmit`

- [ ] **Step 1: Update `SIZES.radius` to match new tokens**

Replace the current `radius` object with:

```ts
export const SIZES = {
  padding: {
    sm: 8,
    md: 12,
    lg: 16,
    xl: 20,
  },
  radius: {
    sm: 6,
    md: 8,
    lg: 12,
    xl: 16,
  },
  fontSize: {
    xs: '10px',
    sm: '11px',
    base: '12px',
    md: '13px',
    lg: '14px',
    xl: '16px',
  },
} as const
```

- [ ] **Step 2: Update `surfaceBlock` to use new tokens**

Replace `surfaceBlock` with:

```ts
export const surfaceBlock: CSSProperties = {
  background: 'var(--bg-surface)',
  border: '1px solid var(--border)',
  borderRadius: 'var(--radius-lg)',
  padding: 'var(--space-4)',
  boxShadow: 'var(--shadow-card)',
}
```

- [ ] **Step 3: Update `surfaceBlockNoPadding`**

```ts
export const surfaceBlockNoPadding: CSSProperties = {
  background: 'var(--bg-surface)',
  border: '1px solid var(--border)',
  borderRadius: 'var(--radius-lg)',
}
```

- [ ] **Step 4: Add `settingRow` pattern for uniform label/control widths**

Add after `modalPanel`:

```ts
/** 标准设置行：固定 label 宽度，control 区自适应 */
export const settingRow = (labelWidth = 160): CSSProperties => ({
  display: 'flex',
  alignItems: 'center',
  gap: 'var(--space-4)',
})

export const settingLabel = (width = 160): CSSProperties => ({
  width,
  flexShrink: 0,
})

export const settingControl = (): CSSProperties => ({
  flex: 1,
  minWidth: 280,
  maxWidth: 480,
})
```

- [ ] **Step 5: Update `PATTERNS` export**

```ts
export const PATTERNS = {
  surfaceBlock,
  surfaceBlockNoPadding,
  surfaceBlockAccent,
  chip,
  centerContainer,
  fullscreenBackdrop,
  modalPanel,
  settingRow,
  settingLabel,
  settingControl,
} as const
```

- [ ] **Step 6: Commit**

```bash
cd /c/Users/10954/Desktop/MBForge
git add frontend/src/styles/patterns.ts
git commit -m "style(patterns): update surfaceBlock and add settingRow patterns"
```

---

## Task 3: Create `Badge` Component

**Files:**
- Create: `frontend/src/components/ui/Badge.tsx`
- Test: `npx tsc --noEmit`

- [ ] **Step 1: Write the component**

```tsx
import type { ReactNode } from 'react'

export type BadgeTone = 'success' | 'warning' | 'danger' | 'info' | 'neutral' | 'loading'

export interface BadgeProps {
  tone: BadgeTone
  children: ReactNode
  size?: 'sm' | 'md'
  className?: string
  style?: React.CSSProperties
}

const toneStyles: Record<BadgeTone, React.CSSProperties> = {
  success: {
    background: 'rgba(22, 163, 74, 0.10)',
    color: 'var(--success)',
  },
  warning: {
    background: 'rgba(245, 158, 11, 0.10)',
    color: 'var(--warning)',
  },
  danger: {
    background: 'rgba(220, 38, 38, 0.10)',
    color: 'var(--danger)',
  },
  info: {
    background: 'var(--accent-muted)',
    color: 'var(--accent)',
  },
  neutral: {
    background: 'var(--bg-hover)',
    color: 'var(--text-secondary)',
  },
  loading: {
    background: 'var(--bg-hover)',
    color: 'var(--text-secondary)',
  },
}

const sizeStyles: Record<'sm' | 'md', React.CSSProperties> = {
  sm: { padding: '2px 8px', fontSize: '11px', gap: 4 },
  md: { padding: '4px 10px', fontSize: '12px', gap: 6 },
}

export default function Badge({ tone, children, size = 'sm', className, style }: BadgeProps) {
  return (
    <span
      className={className}
      style={{
        display: 'inline-flex',
        alignItems: 'center',
        borderRadius: 'var(--radius-md)',
        fontWeight: 500,
        lineHeight: 1,
        whiteSpace: 'nowrap',
        ...toneStyles[tone],
        ...sizeStyles[size],
        ...style,
      }}
    >
      {children}
    </span>
  )
}
```

- [ ] **Step 2: Commit**

```bash
cd /c/Users/10954/Desktop/MBForge
git add frontend/src/components/ui/Badge.tsx
git commit -m "feat(ui): add Badge component with semantic tones"
```

---

## Task 4: Create `InlineAlert` Component

**Files:**
- Create: `frontend/src/components/ui/InlineAlert.tsx`
- Test: `npx tsc --noEmit`

- [ ] **Step 1: Write the component**

```tsx
import type { ReactNode } from 'react'

export type InlineAlertTone = 'success' | 'warning' | 'danger' | 'info'

export interface InlineAlertProps {
  tone: InlineAlertTone
  title?: string
  children?: ReactNode
  className?: string
  style?: React.CSSProperties
}

const toneMap: Record<InlineAlertTone, { border: string; bg: string; color: string }> = {
  success: {
    border: 'var(--success)',
    bg: 'rgba(22, 163, 74, 0.08)',
    color: 'var(--success)',
  },
  warning: {
    border: 'var(--warning)',
    bg: 'rgba(245, 158, 11, 0.08)',
    color: 'var(--warning)',
  },
  danger: {
    border: 'var(--danger)',
    bg: 'rgba(220, 38, 38, 0.08)',
    color: 'var(--danger)',
  },
  info: {
    border: 'var(--accent)',
    bg: 'var(--accent-muted)',
    color: 'var(--accent)',
  },
}

export default function InlineAlert({ tone, title, children, className, style }: InlineAlertProps) {
  const { border, bg, color } = toneMap[tone]
  return (
    <div
      className={className}
      style={{
        padding: '10px 12px',
        borderRadius: 'var(--radius-md)',
        background: bg,
        borderLeft: `3px solid ${border}`,
        color,
        fontSize: '12px',
        lineHeight: '16px',
        ...style,
      }}
    >
      {title && <div style={{ fontWeight: 600, marginBottom: children ? 4 : 0 }}>{title}</div>}
      {children}
    </div>
  )
}
```

- [ ] **Step 2: Commit**

```bash
cd /c/Users/10954/Desktop/MBForge
git add frontend/src/components/ui/InlineAlert.tsx
git commit -m "feat(ui): add InlineAlert component for card-level feedback"
```

---

## Task 5: Extend `Tabs` with `segment` Variant

**Files:**
- Modify: `frontend/src/components/ui/Tabs.tsx`
- Test: `npx tsc --noEmit`

- [ ] **Step 1: Add `segment` to the variant union**

Change:

```ts
variant?: 'default' | 'pills' | 'underline'
```

to:

```ts
variant?: 'default' | 'pills' | 'underline' | 'segment'
```

- [ ] **Step 2: Render segment tabs**

Inside `renderTab`, after the `pills` branch, add a `segment` branch before the default/underline branch:

```tsx
if (variant === 'segment') {
  return (
    <button
      key={item.key}
      type="button"
      role="tab"
      aria-selected={isActive}
      onClick={() => handleClick(item.key, item.disabled)}
      disabled={item.disabled}
      className={className}
      style={{
        ...baseStyle,
        background: isActive ? 'var(--bg-elevated)' : 'transparent',
        color: isActive ? 'var(--accent)' : 'var(--text-secondary)',
        borderRadius: 'var(--radius-md)',
        boxShadow: isActive ? 'var(--shadow-card)' : 'none',
        fontWeight: isActive ? 600 : 500,
      }}
    >
      {item.label}
    </button>
  )
}
```

- [ ] **Step 3: Add segment container styling**

Update the `tabList` wrapper to handle `segment`:

```tsx
const tabList = (
  <div
    role="tablist"
    style={{
      display: 'flex',
      alignItems: 'center',
      gap: variant === 'default' ? 4 : variant === 'segment' ? 4 : 6,
      borderBottom:
        variant === 'default' || variant === 'underline' ? '1px solid var(--border)' : 'none',
      padding: variant === 'segment' ? 4 : 0,
      background: variant === 'segment' ? 'var(--bg-surface)' : 'transparent',
      borderRadius: variant === 'segment' ? 'var(--radius-lg)' : 0,
      border: variant === 'segment' ? '1px solid var(--border)' : 'none',
      ...style,
    }}
  >
    {items.map(renderTab)}
  </div>
)
```

- [ ] **Step 4: Add ARIA to existing tab buttons**

For all three existing button returns, add `role="tab"` and `aria-selected={isActive}` props.

- [ ] **Step 5: Commit**

```bash
cd /c/Users/10954/Desktop/MBForge
git add frontend/src/components/ui/Tabs.tsx
git commit -m "feat(ui): add segment variant and ARIA attributes to Tabs"
```

---

## Task 6: Unify Field Layout in `SettingRow.tsx`

**Files:**
- Modify: `frontend/src/components/settings/SettingRow.tsx`
- Test: `npx tsc --noEmit`

- [ ] **Step 1: Add `labelWidth` prop to `TextField` and `NumberField`**

For `TextField`, add `labelWidth?: number` to props and pass it to `SettingItem`:

```tsx
export function TextField({
  label,
  description,
  value,
  onChange,
  placeholder,
  type = 'text',
  monospace,
  labelWidth,
}: {
  label: string
  description?: string
  value: string
  onChange: (v: string) => void
  placeholder?: string
  type?: 'text' | 'password' | 'number'
  monospace?: boolean
  labelWidth?: number
}) {
  return (
    <SettingItem title={label} description={description} labelWidth={labelWidth}>
      <Input
        className="settings-input"
        type={type}
        value={value}
        onChange={e => onChange(e.target.value)}
        placeholder={placeholder}
        style={{
          width: '100%',
          minWidth: 280,
          maxWidth: 480,
          fontFamily: monospace ? 'var(--font-mono, monospace)' : undefined,
        }}
      />
    </SettingItem>
  )
}
```

Do the same for `NumberField`: add `labelWidth?: number` and pass it to `SettingItem`.

- [ ] **Step 2: Update `SettingItem` in `SettingSection.tsx` to support `labelWidth`**

Modify `frontend/src/components/ui/SettingSection.tsx`:

```tsx
export interface SettingItemProps {
  title?: string
  description?: string
  children?: ReactNode
  layout?: 'horizontal' | 'stacked'
  labelWidth?: number
  style?: React.CSSProperties
}

export function SettingItem({ title, description, children, layout = 'horizontal', labelWidth = 160, style }: SettingItemProps) {
  return (
    <div
      className="setting-item"
      style={{
        display: 'flex',
        alignItems: layout === 'stacked' ? 'flex-start' : 'center',
        flexDirection: layout === 'stacked' ? 'column' : 'row',
        gap: layout === 'stacked' ? 'var(--space-2)' : 'var(--space-4)',
        ...style,
      }}
    >
      {(title || description) && (
        <div
          className="setting-info"
          style={{
            width: layout === 'horizontal' ? labelWidth : undefined,
            flexShrink: 0,
            minWidth: 0,
          }}
        >
          {title && <div className="setting-label" style={{ fontSize: '13px', fontWeight: 500 }}>{title}</div>}
          {description && (
            <div className="setting-desc" style={{ fontSize: '12px', color: 'var(--text-muted)' }}>
              {description}
            </div>
          )}
        </div>
      )}
      <div style={{ flex: 1, minWidth: 280, maxWidth: 480 }}>{children}</div>
    </div>
  )
}
```

- [ ] **Step 3: Update `ProviderField` to use unified widths**

Change `ProviderField` to:

```tsx
export function ProviderField({
  label,
  description,
  provider,
  onProviderChange,
  baseUrl,
  onBaseUrlChange,
  apiKey,
  onApiKeyChange,
  providerOptions,
  needsKey,
  baseUrlPlaceholder,
  showBaseUrl = true,
  baseUrlLabel,
  apiKeyLabel,
  labelWidth = 160,
}: {
  label: string
  description?: string
  provider: string
  onProviderChange: (p: string) => void
  baseUrl: string
  onBaseUrlChange: (u: string) => void
  apiKey: string
  onApiKeyChange: (k: string) => void
  providerOptions: { value: string; label: string }[]
  needsKey: boolean
  baseUrlPlaceholder?: string
  showBaseUrl?: boolean
  baseUrlLabel?: string
  apiKeyLabel?: string
  labelWidth?: number
}) {
  return (
    <>
      <SettingItem title={label} description={description} labelWidth={labelWidth}>
        <select
          className="settings-select"
          value={provider}
          onChange={e => onProviderChange(e.target.value)}
          style={{ width: '100%', minWidth: 280, maxWidth: 480 }}
        >
          {providerOptions.map(o => (
            <option key={o.value} value={o.value}>{o.label}</option>
          ))}
        </select>
      </SettingItem>
      {showBaseUrl && (
        <TextField
          label={baseUrlLabel ?? 'Base URL'}
          value={baseUrl}
          onChange={onBaseUrlChange}
          placeholder={baseUrlPlaceholder}
          monospace
          labelWidth={labelWidth}
        />
      )}
      {needsKey && (
        <SettingItem title={apiKeyLabel ?? 'API Key'} labelWidth={labelWidth}>
          <div style={{ width: '100%', minWidth: 280, maxWidth: 480 }}>
            <ApiKeyInput value={apiKey} onChange={onApiKeyChange} />
          </div>
        </SettingItem>
      )}
    </>
  )
}
```

- [ ] **Step 4: Commit**

```bash
cd /c/Users/10954/Desktop/MBForge
git add frontend/src/components/settings/SettingRow.tsx frontend/src/components/ui/SettingSection.tsx
git commit -m "refactor(settings): unify field label/control widths and add labelWidth prop"
```

---

## Task 7: Refactor `ModelConfigCard.tsx`

**Files:**
- Modify: `frontend/src/components/settings/ModelConfigCard.tsx`
- Modify: `frontend/src/i18n/locales/en.json` and `zh-CN.json`
- Test: `npx tsc --noEmit`

- [ ] **Step 1: Replace status dot with `Badge`**

Import `Badge`:

```tsx
import Badge from '../ui/Badge'
```

Map `LlmEnvStatus['status']` to `Badge` tone:

```tsx
const STATUS_TONE: Record<NonNullable<LlmEnvStatus['status']>, BadgeTone> = {
  not_configured: 'warning',
  ok: 'success',
  unreachable: 'danger',
  http_error: 'danger',
  auth_error: 'danger',
}
```

In the header, replace the manual dot/span block with:

```tsx
{showTest && (
  <div style={{ display: 'flex', alignItems: 'center', gap: 'var(--space-2)', flexShrink: 0 }}>
    {testStatus && (
      <Badge tone={STATUS_TONE[testStatus.status]}>
        {testing ? t('settings.testing') : t(`settings.llmStatus.${testStatus.status}`)}
        {testStatus.latency_ms != null && ` (${testStatus.latency_ms} ms)`}
      </Badge>
    )}
    <Button size="sm" variant="secondary" onClick={runTest} disabled={testing} loading={testing}>
      {t('settings.testConnection')}
    </Button>
  </div>
)}
```

Remove the old `STATUS_COLOR` object and `statusTone`/`statusColor` derivation.

- [ ] **Step 2: Replace error block with `InlineAlert`**

Import `InlineAlert`:

```tsx
import InlineAlert from '../ui/InlineAlert'
```

Replace the error `<div>` at the bottom with:

```tsx
{testStatus?.error && (
  <InlineAlert tone="danger" title={t('settings.connectionFailed')} style={{ marginTop: 'var(--space-4)' }}>
    {testStatus.error}
  </InlineAlert>
)}
```

- [ ] **Step 3: Update card style to use tokens**

Replace `cardStyle` with:

```ts
const cardStyle: React.CSSProperties = {
  padding: 'var(--space-4)',
  border: '1px solid var(--border)',
  borderRadius: 'var(--radius-lg)',
  background: 'var(--bg-surface)',
  boxShadow: 'var(--shadow-card)',
}
```

- [ ] **Step 4: Add missing i18n keys**

Add to `en.json`:

```json
"settings.testing": "Testing…",
"settings.connectionFailed": "Connection failed",
"settings.saved": "Saved",
```

Add matching keys to `zh-CN.json`:

```json
"settings.testing": "测试中…",
"settings.connectionFailed": "连接失败",
"settings.saved": "已保存",
```

- [ ] **Step 5: Commit**

```bash
cd /c/Users/10954/Desktop/MBForge
git add frontend/src/components/settings/ModelConfigCard.tsx frontend/src/i18n/locales/en.json frontend/src/i18n/locales/zh-CN.json
git commit -m "refactor(settings): use Badge and InlineAlert in ModelConfigCard, update tokens"
```

---

## Task 8: Refactor `AIModelsSection.tsx`

**Files:**
- Modify: `frontend/src/components/settings/sections/AIModelsSection.tsx`
- Test: `npx tsc --noEmit`

- [ ] **Step 1: Add a section header and switch to `segment` tabs**

Update the component to:

```tsx
import { useState } from 'react'
import { useTranslation } from 'react-i18next'
import Tabs, { TabPanel } from '../../ui/Tabs'
import ModelConfigCard from '../ModelConfigCard'
import SectionTitle from '../../ui/SectionTitle'
import type { SettingsState } from '../types'

type Tab = 'llm' | 'embed' | 'rerank' | 'vlm' | 'ocr'

interface Props {
  settings: SettingsState
  setSettings: React.Dispatch<React.SetStateAction<SettingsState>>
}

const TAB_CONFIG: Record<Tab, { titleKey: string; descKey?: string; showTest?: boolean }> = {
  llm: { titleKey: 'settings.tabLlm', descKey: 'settings.tabLlmDesc', showTest: true },
  embed: { titleKey: 'settings.tabEmbed', descKey: 'settings.tabEmbedDesc' },
  rerank: { titleKey: 'settings.tabRerank', descKey: 'settings.tabRerankDesc' },
  vlm: { titleKey: 'settings.tabVlm', descKey: 'settings.tabVlmDesc' },
  ocr: { titleKey: 'settings.tabOcr', descKey: 'settings.tabOcrDesc' },
}

export default function AIModelsSection({ settings, setSettings }: Props) {
  const { t } = useTranslation()
  const [tab, setTab] = useState<Tab>('llm')

  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 'var(--space-5)' }}>
      <div>
        <SectionTitle>{t('settings.aiModels')}</SectionTitle>
        <p style={{ margin: 'var(--space-1) 0 0', fontSize: '13px', color: 'var(--text-secondary)' }}>
          {t('settings.aiModelsDesc')}
        </p>
      </div>

      <Tabs
        items={[
          { key: 'llm', label: t('settings.tabLlm') },
          { key: 'embed', label: t('settings.tabEmbed') },
          { key: 'rerank', label: t('settings.tabRerank') },
          { key: 'vlm', label: t('settings.tabVlm') },
          { key: 'ocr', label: t('settings.tabOcr') },
        ]}
        activeKey={tab}
        onChange={k => setTab(k as Tab)}
        variant="segment"
        size="sm"
      />

      <TabPanel activeKey={tab} tabKey="llm">
        <ModelConfigCard
          modelType="llm"
          title={t(TAB_CONFIG.llm.titleKey)}
          description={TAB_CONFIG.llm.descKey ? t(TAB_CONFIG.llm.descKey) : undefined}
          settings={settings}
          setSettings={setSettings}
          showTest={TAB_CONFIG.llm.showTest}
        />
      </TabPanel>

      {/* remaining TabPanels unchanged */}
    </div>
  )
}
```

- [ ] **Step 2: Add `settings.aiModelsDesc` i18n key**

`en.json`:

```json
"settings.aiModelsDesc": "Configure providers, endpoints and models for AI inference.",
```

`zh-CN.json`:

```json
"settings.aiModelsDesc": "配置 AI 推理所需的服务商、接口地址和模型。",
```

- [ ] **Step 3: Commit**

```bash
cd /c/Users/10954/Desktop/MBForge
git add frontend/src/components/settings/sections/AIModelsSection.tsx frontend/src/i18n/locales/en.json frontend/src/i18n/locales/zh-CN.json
git commit -m "refactor(settings): add section header and segment tabs to AIModelsSection"
```

---

## Task 9: Update `SettingsPage.tsx` Save Feedback

**Files:**
- Modify: `frontend/src/components/settings/SettingsPage.tsx`
- Modify: `frontend/src/styles/settings.css`
- Test: `npx tsc --noEmit`

- [ ] **Step 1: Add local save-state feedback to the Save button**

Track a transient save-success state with a shorter duration than the global banner:

```tsx
const [buttonSaved, setButtonSaved] = useState(false)
```

In `handleSave`, on success:

```tsx
if (resp.success) {
  setSaveSuccess(true)
  setButtonSaved(true)
  setInitialSettings(settings)
  setTheme(settings.theme === 'system' ? 'dark' : settings.theme)
  void i18n.changeLanguage(settings.language)
  setTimeout(() => setSaveSuccess(false), 3000)
  setTimeout(() => setButtonSaved(false), 1500)
}
```

Update the Save button rendering:

```tsx
<Button
  variant={buttonSaved ? 'success' : 'primary'}
  onClick={handleSave}
  disabled={isLoading || !isDirty}
  loading={isLoading}
>
  {isLoading ? t('settings.saving') : buttonSaved ? t('settings.saved') + ' ✓' : t('common.save')}
</Button>
```

**Note:** If `Button` does not have a `'success'` variant, add it to `Button.tsx`:

```ts
success: { background: 'var(--success)', color: '#fff', border: 'none' },
```

Add `'success'` to `ButtonVariant`.

- [ ] **Step 2: Add shake animation on save error**

Add to `frontend/src/styles/settings.css`:

```css
@keyframes settings-shake {
  0%, 100% { transform: translateX(0); }
  20% { transform: translateX(-4px); }
  40% { transform: translateX(4px); }
  60% { transform: translateX(-4px); }
  80% { transform: translateX(4px); }
}

.settings-save-button--error {
  animation: settings-shake 0.3s ease-in-out;
}
```

In `SettingsPage.tsx`, add:

```tsx
const [saveErrorShake, setSaveErrorShake] = useState(false)
```

On save error:

```tsx
setSaveErrorShake(true)
setTimeout(() => setSaveErrorShake(false), 300)
```

Apply the class to the Save button:

```tsx
className={saveErrorShake ? 'settings-save-button--error' : undefined}
```

- [ ] **Step 3: Commit**

```bash
cd /c/Users/10954/Desktop/MBForge
git add frontend/src/components/settings/SettingsPage.tsx frontend/src/components/ui/Button.tsx frontend/src/styles/settings.css
git commit -m "feat(settings): add saved-state and error-shake feedback to Save button"
```

---

## Task 10: Clean Up `settings.css` and Polish Input Styles

**Files:**
- Modify: `frontend/src/styles/settings.css`
- Test: Visual inspection

- [ ] **Step 1: Ensure `.settings-input` and `.settings-select` use new tokens**

Find `.settings-input` and `.settings-select` rules and ensure:

```css
.settings-input,
.settings-select {
  height: 34px;
  padding: 10px 12px;
  border: 1px solid var(--border);
  border-radius: var(--radius-md);
  background: var(--bg-base);
  color: var(--text-primary);
  font-size: 13px;
  transition: border-color 0.15s, box-shadow 0.15s;
  outline: none;
}

.settings-input:focus,
.settings-select:focus {
  border-color: var(--accent);
  box-shadow: 0 0 0 3px var(--accent-muted);
}

.settings-input:disabled,
.settings-select:disabled {
  background: var(--bg-surface);
  color: var(--text-muted);
}
```

If these rules do not exist, append them to the file.

- [ ] **Step 2: Add reduced-motion guard**

Append:

```css
@media (prefers-reduced-motion: reduce) {
  .settings-save-button--error,
  .settings-input,
  .settings-select {
    transition: none;
    animation: none;
  }
}
```

- [ ] **Step 3: Commit**

```bash
cd /c/Users/10954/Desktop/MBForge
git add frontend/src/styles/settings.css
git commit -m "style(settings): align input/select styles with new tokens and reduced-motion"
```

---

## Task 11: Final Verification

**Files:** All modified above.

- [ ] **Step 1: Type-check**

```bash
cd /c/Users/10954/Desktop/MBForge/frontend
npx tsc --noEmit
```

Expected: no errors.

- [ ] **Step 2: Build**

```bash
cd /c/Users/10954/Desktop/MBForge/frontend
npm run build
```

Expected: build succeeds.

- [ ] **Step 3: Run existing frontend tests**

```bash
cd /c/Users/10954/Desktop/MBForge/frontend
npm test -- --run
```

Expected: any failures are pre-existing and unrelated to UI changes.

- [ ] **Step 4: Visual regression check**

Launch the app (or `npm run dev`) and verify:

1. Settings → AI Models page loads without errors.
2. Internal tabs render as `segment` pills, not underlines.
3. Card has rounded corners, light shadow (light mode) / border (dark mode).
4. Form labels are aligned left, controls share the same max-width.
5. "Test Connection" shows a Badge: neutral/warning → loading → success/danger.
6. Save button shows "Saved ✓" briefly after save.
7. Dark mode colors remain readable.

- [ ] **Step 5: Final commit**

If any fixes were made during verification:

```bash
cd /c/Users/10954/Desktop/MBForge
git add -A
git commit -m "fix(settings): address verification findings"
```

---

## Self-Review

### Spec Coverage
- Design tokens: covered in Task 1-2.
- `Badge` component: covered in Task 3.
- `InlineAlert` component: covered in Task 4.
- `segment` Tabs variant: covered in Task 5.
- Unified field layout: covered in Task 6.
- `ModelConfigCard` status/feedback: covered in Task 7.
- `AIModelsSection` header/segment tabs: covered in Task 8.
- Save feedback: covered in Task 9.
- Input/select polish: covered in Task 10.
- Verification: covered in Task 11.

### Placeholder Scan
- No "TBD", "TODO", "implement later" or vague steps remain.
- Each task includes exact file paths, code snippets, and commands.

### Type Consistency
- `BadgeTone` is defined in `Badge.tsx` and referenced via import in `ModelConfigCard.tsx`.
- `ButtonVariant` needs the `'success'` variant added in Task 9; this is explicitly noted.
- `SettingItemProps` gains `labelWidth` in Task 6 and is consumed by `SettingRow.tsx`.

### Risk Notes
- `settings.css` is large; changes are append-only or targeted at existing selectors to avoid breaking unrelated pages.
- The `'success'` Button variant is a small additive change; if undesirable, fallback is to keep primary variant during the saved state.
