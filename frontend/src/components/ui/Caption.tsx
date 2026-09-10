import type { ReactNode } from 'react'

export interface CaptionProps {
  children: ReactNode
  truncate?: boolean
  color?: string
  style?: React.CSSProperties
  className?: string
}

export default function Caption({ children, truncate = false, color = 'var(--text-muted)', style, className }: CaptionProps) {
  return (
    <span
      className={className}
      style={{
        fontSize: '12px',
        color,
        overflow: truncate ? 'hidden' : undefined,
        textOverflow: truncate ? 'ellipsis' : undefined,
        whiteSpace: truncate ? 'nowrap' : undefined,
        ...style,
      }}
    >
      {children}
    </span>
  )
}
