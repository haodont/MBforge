import type { ReactNode } from 'react'

export interface IconContainerProps {
  children: ReactNode
  size?: number
  style?: React.CSSProperties
  className?: string
}

export default function IconContainer({ children, size = 48, style, className }: IconContainerProps) {
  return (
    <div
      className={className}
      style={{
        width: size,
        height: size,
        borderRadius: size >= 48 ? '12px' : '10px',
        background: 'var(--accent-muted)',
        display: 'flex',
        alignItems: 'center',
        justifyContent: 'center',
        color: 'var(--accent)',
        flexShrink: 0,
        ...style,
      }}
    >
      {children}
    </div>
  )
}
