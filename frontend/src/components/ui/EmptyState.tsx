import type { ReactNode } from 'react'
import Button from './Button'

export interface EmptyStateProps {
  message: string
  icon?: ReactNode
  error?: boolean
  action?: { label: string; onClick: () => void }
  style?: React.CSSProperties
  className?: string
  /** 透传 data-testid 供测试定位 */
  testId?: string
}

export default function EmptyState({ message, icon, error = false, action, style, className, testId }: EmptyStateProps) {
  return (
    <div
      className={className}
      data-testid={testId}
      style={{
        padding: '40px',
        textAlign: 'center',
        color: error ? 'var(--danger)' : 'var(--text-muted)',
        background: 'var(--bg-surface)',
        borderRadius: '12px',
        border: error ? '1px solid var(--border)' : undefined,
        display: 'flex',
        flexDirection: 'column',
        alignItems: 'center',
        gap: '12px',
        ...style,
      }}
    >
      {icon}
      <span style={{ fontSize: '13px' }}>{message}</span>
      {action && (
        <Button
          variant="primary"
          style={{ marginTop: '8px' }}
          onClick={action.onClick}
        >
          {action.label}
        </Button>
      )}
    </div>
  )
}
