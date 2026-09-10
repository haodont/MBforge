import { motion } from 'framer-motion'
import type { ReactNode, MouseEvent } from 'react'

export interface IconButtonProps {
  children: ReactNode
  size?: number
  active?: boolean
  disabled?: boolean
  title?: string
  ariaLabel?: string
  ariaExpanded?: boolean
  ariaPressed?: boolean
  onClick?: (e: MouseEvent<HTMLButtonElement>) => void
  onMouseDown?: (e: MouseEvent<HTMLButtonElement>) => void
  style?: React.CSSProperties
  className?: string
}

export default function IconButton({
  children,
  size = 44,
  active = false,
  disabled = false,
  title,
  ariaLabel,
  ariaExpanded,
  ariaPressed,
  onClick,
  onMouseDown,
  style,
  className,
}: IconButtonProps) {
  return (
    <motion.button
      title={title}
      aria-label={ariaLabel}
      aria-expanded={ariaExpanded}
      aria-pressed={ariaPressed}
      className={className}
      onClick={onClick}
      onMouseDown={onMouseDown}
      disabled={disabled}
      whileTap={disabled ? undefined : { scale: 0.92 }}
      transition={{ duration: 0.15 }}
      style={{
        width: size,
        height: size,
        display: 'flex',
        alignItems: 'center',
        justifyContent: 'center',
        borderRadius: '8px',
        border: 'none',
        cursor: disabled ? 'not-allowed' : 'pointer',
        transition: 'background 0.15s, color 0.15s',
        background: active ? 'var(--accent-muted)' : 'transparent',
        color: active ? 'var(--accent)' : 'var(--text-secondary)',
        ...style,
      }}
      onMouseEnter={(e) => {
        if (!active && !disabled) {
          e.currentTarget.style.background = 'var(--bg-hover)'
          e.currentTarget.style.color = 'var(--text-primary)'
        }
      }}
      onMouseLeave={(e) => {
        if (!active && !disabled) {
          e.currentTarget.style.background = 'transparent'
          e.currentTarget.style.color = 'var(--text-secondary)'
        }
      }}
    >
      {children}
    </motion.button>
  )
}
