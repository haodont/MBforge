import { CheckIcon, XIcon } from '../icons'

export interface LibStatusRowProps {
  name: string
  version?: string | null
  available: boolean
  hint?: string
  showBorder?: boolean
}

export default function LibStatusRow({ name, version, available, hint, showBorder = true }: LibStatusRowProps) {
  return (
    <div
      style={{
        display: 'flex',
        alignItems: 'center',
        justifyContent: 'space-between',
        padding: '6px 0',
        borderBottom: showBorder ? '1px solid var(--border)' : 'none',
      }}
    >
      <div style={{ display: 'flex', alignItems: 'center', gap: '8px' }}>
        <span style={{ fontWeight: 500, fontSize: 'var(--text-md)' }}>{name}</span>
        {hint && (
          <span style={{ fontSize: 'var(--text-xs)', color: 'var(--text-muted)' }}>{hint}</span>
        )}
      </div>
      <div style={{ display: 'flex', alignItems: 'center', gap: '8px' }}>
        {version && (
          <span style={{ fontSize: 'var(--text-xs)', color: 'var(--text-secondary)', fontVariantNumeric: 'tabular-nums' }}>v{version}</span>
        )}
        {available ? (
          <CheckIcon size={14} style={{ color: 'var(--success)' }} />
        ) : (
          <XIcon size={14} style={{ color: 'var(--danger)' }} />
        )}
      </div>
    </div>
  )
}
