import type { ChangeEvent } from 'react'

export interface SelectOption {
  value: string
  label: string
}

export interface SelectProps {
  value: string
  onChange: (value: string) => void
  options: SelectOption[]
  placeholder?: string
  /** 是否渲染占位空选项（value=""）。默认 true；枚举型筛选用 false 避免多余空项 */
  showPlaceholder?: boolean
  disabled?: boolean
  id?: string
  ariaLabel?: string
  style?: React.CSSProperties
  className?: string
}

/**
 * Select 下拉选择组件。
 *
 * 统一封装原生 select 的样式，替换散落在各处的重复内联样式。
 * 视觉样式由 styles/ui.css 的 .ui-select 承载。
 */
export default function Select({
  value,
  onChange,
  options,
  placeholder = '请选择…',
  showPlaceholder = true,
  disabled = false,
  id,
  ariaLabel,
  style,
  className,
}: SelectProps) {
  const handleChange = (e: ChangeEvent<HTMLSelectElement>) => {
    onChange(e.target.value)
  }

  return (
    <select
      value={value}
      onChange={handleChange}
      disabled={disabled}
      id={id}
      aria-label={ariaLabel}
      className={['ui-select', className].filter(Boolean).join(' ')}
      style={style}
    >
      {showPlaceholder && <option value="">{placeholder}</option>}
      {options.map((opt) => (
        <option key={opt.value} value={opt.value}>
          {opt.label}
        </option>
      ))}
    </select>
  )
}
