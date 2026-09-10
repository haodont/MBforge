import type { ReactNode } from 'react'

export interface AvatarProps {
  children: ReactNode
  size?: number
  variant?: 'user' | 'bot'
  style?: React.CSSProperties
  className?: string
}

export default function Avatar({ children, size = 32, variant = 'bot', style, className }: AvatarProps) {
  return (
    <div
      className={className}
      style={{
        width: size,
        height: size,
        borderRadius: '50%',
        background: variant === 'bot' ? 'var(--accent)' : 'var(--bg-hover)',
        color: variant === 'bot' ? 'white' : 'var(--text-secondary)',
        display: 'flex',
        alignItems: 'center',
        justifyContent: 'center',
        flexShrink: 0,
        ...style,
      }}
    >
      {children}
    </div>
  )
}
