import type { ReactNode } from 'react'

export interface EnvCardProps {
  label: string
  value: string | ReactNode
  subValue?: string
  variant?: 'default' | 'success' | 'warning' | 'error'
  style?: React.CSSProperties
}

const variantStyles = {
  default: { bg: 'var(--bg-elevated)', color: 'inherit' },
  success: { bg: 'var(--success-muted)', color: 'var(--success-fg)' },
  warning: { bg: 'var(--warning-muted)', color: 'var(--warning-fg)' },
  error:   { bg: 'var(--danger-muted)', color: 'var(--danger-fg)' },
}

export default function EnvCard({ label, value, subValue, variant = 'default', style }: EnvCardProps) {
  const v = variantStyles[variant]

  return (
    <div
      style={{
        padding: '10px 14px',
        background: v.bg,
        borderRadius: 'var(--radius-md)',
        fontSize: 'var(--text-md)',
        color: v.color,
        ...style,
      }}
    >
      <span style={{ color: 'var(--text-secondary)', marginRight: '6px' }}>{label}</span>
      <strong style={{ fontWeight: 600 }}>{value}</strong>
      {subValue && (
        <span style={{ color: 'var(--text-muted)', marginLeft: '4px', fontSize: 'var(--text-sm)' }}>{subValue}</span>
      )}
    </div>
  )
}
