import type { ReactNode, MouseEvent } from 'react'

export type ButtonVariant = 'primary' | 'secondary' | 'ghost' | 'danger' | 'dashed' | 'success'
export type ButtonSize = 'sm' | 'md' | 'lg'

export interface ButtonProps {
  children?: ReactNode
  variant?: ButtonVariant
  size?: ButtonSize
  loading?: boolean
  disabled?: boolean
  icon?: ReactNode
  onClick?: (e: MouseEvent<HTMLButtonElement>) => void
  onMouseDown?: (e: MouseEvent<HTMLButtonElement>) => void
  onContextMenu?: (e: MouseEvent<HTMLButtonElement>) => void
  type?: 'button' | 'submit' | 'reset'
  style?: React.CSSProperties
  className?: string
  title?: string
  ariaLabel?: string
  ariaPressed?: boolean
}

/**
 * Button 按钮组件。
 *
 * 视觉样式由 styles/ui.css 的 .ui-btn 类族承载，随主题令牌切换。
 */
export default function Button({
  children,
  variant = 'secondary',
  size = 'md',
  loading = false,
  disabled = false,
  icon,
  onClick,
  onMouseDown,
  onContextMenu,
  type = 'button',
  style,
  className,
  title,
  ariaLabel,
  ariaPressed,
}: ButtonProps) {
  const isDisabled = disabled || loading
  const cls = ['ui-btn', `ui-btn--${variant}`, `ui-btn--${size}`, className]
    .filter(Boolean)
    .join(' ')

  return (
    <button
      type={type}
      title={title}
      aria-label={ariaLabel}
      aria-pressed={ariaPressed}
      className={cls}
      onClick={isDisabled ? undefined : onClick}
      onMouseDown={onMouseDown}
      onContextMenu={onContextMenu}
      disabled={isDisabled}
      style={style}
    >
      {loading && <span className="ui-btn__spinner" />}
      {icon}
      {children}
    </button>
  )
}
