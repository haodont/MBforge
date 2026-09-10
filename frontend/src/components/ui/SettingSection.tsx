import type { ReactNode } from 'react'
import { useTranslation } from 'react-i18next'
import { hstack } from '../../styles/patterns'

export interface SettingItemProps {
  title?: string
  description?: string
  children?: ReactNode
  /** Main axis: horizontal (label left, control right) / stacked (label top, control bottom) */
  layout?: 'horizontal' | 'stacked'
  /** Fixed width of the label/info area in horizontal layout (default 160px) */
  labelWidth?: number
  /** Whether to show the "modified" dirty dot */
  dirty?: boolean
  style?: React.CSSProperties
}

/** Legacy alias kept for type-aggregation files that still reference it */
export type SettingSectionProps = SettingItemProps

/** Setting item container: title + description + control */
export function SettingItem({
  title,
  description,
  children,
  layout = 'horizontal',
  labelWidth = 160,
  dirty,
  style,
}: SettingItemProps) {
  const { t } = useTranslation()
  return (
    <div
      className="setting-item"
      style={{
        ...hstack(layout === 'horizontal' ? 16 : 8),
        flexDirection: layout === 'stacked' ? 'column' : 'row',
        alignItems: layout === 'stacked' ? 'flex-start' : 'center',
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
          {title && <div className="setting-label">{title}</div>}
          {description && <div className="setting-desc">{description}</div>}
        </div>
      )}
      <div style={{ flex: 1, minWidth: 280, maxWidth: 480, display: 'flex', alignItems: 'center', gap: 'var(--space-2)' }}>
        {children}
        {dirty && <span className="setting-dirty-dot" aria-label={t('settings.modified')} />}
      </div>
    </div>
  )
}

/** Setting group container: title + multiple SettingItems */
export function SettingGroup({ title, children, style }: { title?: string; children: ReactNode; style?: React.CSSProperties }) {
  return (
    <div className="settings-group" style={style}>
      {title && (
        <h3 className="settings-group-title">{title}</h3>
      )}
      <div style={{ display: 'flex', flexDirection: 'column', gap: 'var(--space-3)' }}>
        {children}
      </div>
    </div>
  )
}

/** Setting section container */
export default function SettingSection({ children, style }: { children: ReactNode; style?: React.CSSProperties }) {
  return (
    <div className="settings-section" style={style}>
      {children}
    </div>
  )
}