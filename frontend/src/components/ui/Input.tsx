import type { ChangeEvent, KeyboardEvent, FocusEvent, Ref } from 'react'

export interface InputProps {
  value?: string
  defaultValue?: string
  onChange?: (e: ChangeEvent<HTMLInputElement>) => void
  onKeyDown?: (e: KeyboardEvent<HTMLInputElement>) => void
  onFocus?: (e: FocusEvent<HTMLInputElement>) => void
  onBlur?: (e: FocusEvent<HTMLInputElement>) => void
  placeholder?: string
  type?: string
  min?: number | string
  max?: number | string
  step?: number | string
  disabled?: boolean
  error?: boolean
  autoFocus?: boolean
  list?: string
  id?: string
  ariaLabel?: string
  /** React 19:ref 作为普通 prop 透传到原生 input */
  ref?: Ref<HTMLInputElement>
  style?: React.CSSProperties
  className?: string
}

/**
 * Input 输入框组件。
 *
 * 视觉样式由 styles/ui.css 的 .ui-input 承载；保留 base.css 的 .input 类以兼容旧选择器。
 */
export default function Input({
  value,
  defaultValue,
  onChange,
  onKeyDown,
  onFocus,
  onBlur,
  placeholder,
  type = 'text',
  min,
  max,
  step,
  disabled = false,
  error = false,
  autoFocus,
  list,
  id,
  ariaLabel,
  ref,
  style,
  className,
}: InputProps) {
  const cls = ['ui-input', error && 'ui-input--error', className]
    .filter(Boolean)
    .join(' ')

  return (
    <input
      type={type}
      value={value}
      defaultValue={defaultValue}
      onChange={onChange}
      onKeyDown={onKeyDown}
      onFocus={onFocus}
      onBlur={onBlur}
      placeholder={placeholder}
      min={min}
      max={max}
      step={step}
      disabled={disabled}
      autoFocus={autoFocus}
      list={list}
      id={id}
      aria-label={ariaLabel}
      ref={ref}
      className={cls}
      style={style}
    />
  )
}
