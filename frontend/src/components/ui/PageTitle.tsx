import type { ReactNode } from 'react'

export interface PageTitleProps {
  children: ReactNode
  style?: React.CSSProperties
  className?: string
}

export default function PageTitle({ children, style, className }: PageTitleProps) {
  return (
    <h1
      className={className}
      style={{
        fontSize: 'var(--text-xl)',
        fontWeight: 600,
        marginBottom: '8px',
        ...style,
      }}
    >
      {children}
    </h1>
  )
}
