import type { ReactNode } from 'react'

export interface SectionTitleProps {
  children: ReactNode
  style?: React.CSSProperties
  className?: string
}

export default function SectionTitle({ children, style, className }: SectionTitleProps) {
  return (
    <h2
      className={className}
      style={{
        fontSize: '14px',
        fontWeight: 600,
        color: 'var(--text-secondary)',
        textTransform: 'uppercase',
        letterSpacing: '0.5px',
        margin: 0,
        ...style,
      }}
    >
      {children}
    </h2>
  )
}
