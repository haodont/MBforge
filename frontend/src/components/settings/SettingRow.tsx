// Setting row — thin wrappers around field controls.
// Usage: `<TextField ... />` / `<NumberField ... />` / `<SelectField ... />`
// keeps each section reading like a form instead of a pile of <div>s.

import type { ReactNode } from 'react'
import Input from '@/components/ui/Input'
import Switch from '@/components/ui/Switch'
import { SettingItem } from '@/components/ui/SettingSection'
import Caption from '@/components/ui/Caption'
import ApiKeyInput from './ApiKeyInput'

// ────────── Text field ──────────
export function TextField({
  label,
  description,
  value,
  onChange,
  placeholder,
  type = 'text',
  monospace,
  labelWidth,
  dirty,
}: {
  label: string
  description?: string
  value: string
  onChange: (v: string) => void
  placeholder?: string
  type?: 'text' | 'password' | 'number'
  monospace?: boolean
  labelWidth?: number
  dirty?: boolean
}) {
  return (
    <SettingItem title={label} description={description} labelWidth={labelWidth} dirty={dirty}>
      <Input
        type={type}
        value={value}
        onChange={e => onChange(e.target.value)}
        placeholder={placeholder}
        style={{
          minWidth: 200,
          fontFamily: monospace ? 'var(--font-mono, monospace)' : undefined,
        }}
      />
    </SettingItem>
  )
}

// ────────── Number field ──────────
export function NumberField({
  label,
  description,
  value,
  onChange,
  min,
  max,
  step = 1,
  width = 120,
  placeholder,
  labelWidth,
  dirty,
}: {
  label: string
  description?: string
  value: number
  onChange: (v: number) => void
  min?: number
  max?: number
  step?: number
  width?: number
  placeholder?: string
  labelWidth?: number
  dirty?: boolean
}) {
  return (
    <SettingItem title={label} description={description} labelWidth={labelWidth} dirty={dirty}>
      <Input
        type="number"
        value={Number.isFinite(value) ? String(value) : ''}
        onChange={e => {
          const raw = e.target.value
          if (raw === '') {
            onChange(0)
            return
          }
          const n = Number(raw)
          if (!Number.isFinite(n)) return
          onChange(n)
        }}
        min={min}
        max={max}
        step={step}
        placeholder={placeholder}
        style={{ width, minWidth: width, maxWidth: width, textAlign: 'right' }}
      />
    </SettingItem>
  )
}

// ────────── Select field ──────────
export function SelectField<T extends string | number>({
  label,
  description,
  value,
  onChange,
  options,
  labelWidth,
  dirty,
}: {
  label: string
  description?: string
  value: T
  onChange: (v: T) => void
  options: { value: T; label: string }[]
  labelWidth?: number
  dirty?: boolean
}) {
  return (
    <SettingItem title={label} description={description} labelWidth={labelWidth} dirty={dirty}>
      <select
        className="ui-select"
        value={String(value)}
        onChange={e => {
          const v = e.target.value
          const match = options.find(o => String(o.value) === v)
          if (match) onChange(match.value)
        }}
        style={{ width: '100%' }}
      >
        {options.map(o => (
          <option key={String(o.value)} value={String(o.value)}>{o.label}</option>
        ))}
      </select>
    </SettingItem>
  )
}

// ────────── Toggle field ──────────
export function ToggleField({
  label,
  description,
  value,
  onChange,
  labelWidth,
  dirty,
}: {
  label: string
  description?: string
  value: boolean
  onChange: (v: boolean) => void
  labelWidth?: number
  dirty?: boolean
}) {
  return (
    <SettingItem title={label} description={description} labelWidth={labelWidth} dirty={dirty}>
      <Switch checked={value} onChange={onChange} size="sm" />
    </SettingItem>
  )
}

// ────────── Custom content (nested layouts) ──────────
export function CustomField({
  label,
  description,
  children,
  labelWidth,
  dirty,
}: {
  label: string
  description?: string
  children: ReactNode
  labelWidth?: number
  dirty?: boolean
}) {
  return (
    <SettingItem title={label} description={description} layout="stacked" labelWidth={labelWidth} dirty={dirty}>
      <div style={{ width: '100%' }}>{children}</div>
    </SettingItem>
  )
}

// ────────── Provider + linked Base URL + optional API Key ──────────
// Unified "provider switch → baseUrl sync": when baseUrl is still the default,
// switching provider fills the new default; user-customized values are kept.
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
  labelWidth,
  dirty,
  baseUrlDirty,
  apiKeyDirty,
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
  dirty?: boolean
  baseUrlDirty?: boolean
  apiKeyDirty?: boolean
}) {
  return (
    <>
      <SettingItem title={label} description={description} labelWidth={labelWidth} dirty={dirty}>
        <select
          className="ui-select"
          value={provider}
          onChange={e => onProviderChange(e.target.value)}
          style={{ width: '100%' }}
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
          dirty={baseUrlDirty ?? dirty}
        />
      )}
      {needsKey && (
        <SettingItem title={apiKeyLabel ?? 'API Key'} labelWidth={labelWidth} dirty={apiKeyDirty ?? dirty}>
          <ApiKeyInput value={apiKey} onChange={onApiKeyChange} />
        </SettingItem>
      )}
    </>
  )
}

export { ApiKeyInput, Caption }