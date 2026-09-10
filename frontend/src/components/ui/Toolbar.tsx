import type { ReactNode } from 'react'

export interface ToolbarProps {
  children?: ReactNode
  title?: string
  style?: React.CSSProperties
  className?: string
}

export default function Toolbar({ children, title, style, className }: ToolbarProps) {
  return (
    <div
      className={className}
      style={{
        display: 'flex',
        alignItems: 'center',
        justifyContent: 'space-between',
        padding: '8px 16px',
        background: 'var(--bg-surface)',
        borderBottom: '1px solid var(--border)',
        flexShrink: 0,
        ...style,
      }}
    >
      {title && (
        <span style={{
          fontSize: '13px',
          fontWeight: 500,
          overflow: 'hidden',
          textOverflow: 'ellipsis',
          whiteSpace: 'nowrap',
        }}>
          {title}
        </span>
      )}
      {children}
    </div>
  )
}
