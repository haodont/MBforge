/**
 * 通用 Slider — 数字范围选择器。
 *
 * 样式与现有 `.setting-range` (global.css:733) 一致，
 * 保持视觉统一（设置面板、矫正面板、过滤面板通用）。
 *
 * 与 HTML `<input type="range">` 区别：
 *   - 提供受控/非受控两种模式
 *   - 自动显示当前值（右侧）
 *   - label + value 同行布局
 */

import type { ChangeEvent } from 'react'

export interface SliderProps {
  /** 受控值 */
  value?: number
  /** 非受控初始值 */
  defaultValue?: number
  /** 变更回调 */
  onChange?: (value: number) => void
  /** 最小值 */
  min?: number
  /** 最大值 */
  max?: number
  /** 步长 */
  step?: number
  /** 左侧标签 */
  label?: string
  /** 显示格式（默认 Math.round(value*100) + "%"）*/
  formatValue?: (value: number) => string
  /** 是否禁用 */
  disabled?: boolean
  style?: React.CSSProperties
  className?: string
}

export default function Slider({
  value,
  defaultValue,
  onChange,
  min = 0,
  max = 1,
  step = 0.05,
  label,
  formatValue,
  disabled = false,
  style,
  className,
}: SliderProps) {
  const isControlled = value !== undefined
  const displayValue = isControlled ? value : defaultValue ?? min
  const displayText = formatValue
    ? formatValue(displayValue)
    : `${Math.round(displayValue * 100)}%`

  const handleChange = (e: ChangeEvent<HTMLInputElement>) => {
    onChange?.(Number(e.target.value))
  }

  return (
    <div className={`range-wrapper ${className || ''}`} style={style}>
      {label && (
        <label
          style={{
            fontSize: 13,
            color: 'var(--text-secondary)',
            minWidth: 0,
            flexShrink: 0,
          }}
        >
          {label}
        </label>
      )}
      <input
        type="range"
        className="setting-range"
        min={min}
        max={max}
        step={step}
        value={isControlled ? value : undefined}
        defaultValue={isControlled ? undefined : defaultValue}
        onChange={handleChange}
        disabled={disabled}
        style={{ flex: 1 }}
      />
      <span
        className="range-value"
        style={{
          fontVariantNumeric: 'tabular-nums',
          fontWeight: 600,
          color: 'var(--text-primary)',
        }}
      >
        {displayText}
      </span>
    </div>
  )
}
