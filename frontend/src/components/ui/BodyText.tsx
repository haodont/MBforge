import type { ReactNode } from 'react'

export interface BodyTextProps {
  children: ReactNode
  muted?: boolean
  size?: 'sm' | 'md' | 'lg'
  style?: React.CSSProperties
  className?: string
}

const sizeMap = {
  sm: '13px',
  md: '14px',
  lg: '16px',
}

export default function BodyText({ children, muted = false, size = 'md', style, className }: BodyTextProps) {
  return (
    <p
      className={className}
      style={{
        fontSize: sizeMap[size],
        color: muted ? 'var(--text-muted)' : 'var(--text-secondary)',
        lineHeight: 1.5,
        margin: 0,
        ...style,
      }}
    >
      {children}
    </p>
  )
}
