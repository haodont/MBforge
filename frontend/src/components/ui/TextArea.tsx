import type { ChangeEvent, KeyboardEvent } from 'react'

export interface TextAreaProps {
  value?: string
  onChange?: (e: ChangeEvent<HTMLTextAreaElement>) => void
  onKeyDown?: (e: KeyboardEvent<HTMLTextAreaElement>) => void
  placeholder?: string
  disabled?: boolean
  rows?: number
  maxHeight?: number | string
  autoFocus?: boolean
  style?: React.CSSProperties
  className?: string
}

export default function TextArea({
  value,
  onChange,
  onKeyDown,
  placeholder,
  disabled = false,
  rows = 3,
  maxHeight = 120,
  autoFocus,
  style,
  className,
}: TextAreaProps) {
  return (
    <textarea
      value={value}
      onChange={onChange}
      onKeyDown={onKeyDown}
      placeholder={placeholder}
      disabled={disabled}
      rows={rows}
      autoFocus={autoFocus}
      className={className}
      style={{
        flex: 1,
        background: 'transparent',
        border: 'none',
        outline: 'none',
        fontSize: '14px',
        color: 'var(--text-primary)',
        resize: 'none',
        maxHeight,
        fontFamily: 'inherit',
        lineHeight: 1.5,
        ...style,
      }}
    />
  )
}
