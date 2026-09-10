import type { ReactNode } from 'react'

export interface ChipProps {
  label: ReactNode
  active?: boolean
  count?: number
  disabled?: boolean
  onClick?: () => void
  className?: string
  style?: React.CSSProperties
}

/**
 * Chip 过滤标签（筛选 pill）。
 *
 * 用于列表/队列页的维度筛选（复核类型、任务状态、笔记标签等）。
 * 视觉样式由 styles/ui.css 的 .ui-chip 类族承载。
 */
export default function Chip({
  label,
  active = false,
  count,
  disabled = false,
  onClick,
  className,
  style,
}: ChipProps) {
  const cls = ['ui-chip', active && 'ui-chip--active', disabled && 'ui-chip--disabled', className]
    .filter(Boolean)
    .join(' ')

  return (
    <button type="button" className={cls} disabled={disabled} onClick={onClick} style={style} aria-pressed={active}>
      <span className="ui-chip__label">{label}</span>
      {count !== undefined && <span className="ui-chip__count">{count}</span>}
    </button>
  )
}
