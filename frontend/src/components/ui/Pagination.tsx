import { useMemo } from 'react'

export interface PaginationProps {
  /** 当前页（1-based）*/
  current: number
  /** 总页数 */
  total: number
  /** 每页大小（用于显示）*/
  pageSize?: number
  /** 总条数（用于显示）*/
  totalItems?: number
  /** 页码变化回调 */
  onChange: (page: number) => void
  /** 快速跳转 */
  showQuickJumper?: boolean
  /** 显示总数 */
  showTotal?: boolean
  /** 兄弟节点数（默认 1）*/
  siblingCount?: number
  size?: 'sm' | 'md' | 'lg'
  style?: React.CSSProperties
  className?: string
}

/**
 * 计算分页器中显示的页码列表（含省略号）。
 *
 * 例如 total=10, current=5, siblingCount=1 → [1, '...', 4, 5, 6, '...', 10]
 */
function getPageNumbers(current: number, total: number, siblingCount: number): (number | 'ellipsis')[] {
  // 总页数 <= 兄弟节点 + 5，全部显示
  const totalNumbers = siblingCount * 2 + 5
  if (total <= totalNumbers) {
    return Array.from({ length: total }, (_, i) => i + 1)
  }

  const leftSibling = Math.max(current - siblingCount, 1)
  const rightSibling = Math.min(current + siblingCount, total)

  const showLeftEllipsis = leftSibling > 2
  const showRightEllipsis = rightSibling < total - 1

  const items: (number | 'ellipsis')[] = [1]

  if (showLeftEllipsis) {
    items.push('ellipsis')
  } else {
    for (let i = 2; i < leftSibling; i++) items.push(i)
  }

  for (let i = leftSibling; i <= rightSibling; i++) {
    if (i !== 1 && i !== total) items.push(i)
  }

  if (showRightEllipsis) {
    items.push('ellipsis')
  } else {
    for (let i = rightSibling + 1; i < total; i++) items.push(i)
  }

  if (total !== 1) items.push(total)

  return items
}

/**
 * Pagination 分页器。
 *
 * 支持页码跳转、省略号、当前页高亮。
 * 视觉样式由 styles/ui.css 的 .ui-pagination 类族承载。
 */
export default function Pagination({
  current,
  total,
  pageSize,
  totalItems,
  onChange,
  showQuickJumper = false,
  showTotal = false,
  siblingCount = 1,
  size = 'md',
  style,
  className,
}: PaginationProps) {
  const pages = useMemo(
    () => getPageNumbers(current, total, siblingCount),
    [current, total, siblingCount],
  )

  const canPrev = current > 1
  const canNext = current < total

  const renderButton = (
    key: string,
    content: React.ReactNode,
    onClick: () => void,
    isActive = false,
    isDisabled = false,
  ) => (
    <button
      key={key}
      type="button"
      onClick={onClick}
      disabled={isDisabled}
      className={['ui-pagination__btn', isActive && 'ui-pagination__btn--active']
        .filter(Boolean)
        .join(' ')}
    >
      {content}
    </button>
  )

  return (
    <div
      className={['ui-pagination', `ui-pagination--${size}`, className].filter(Boolean).join(' ')}
      style={style}
    >
      {showTotal && (totalItems !== undefined || pageSize !== undefined) && (
        <span className="ui-pagination__total">
          共 {totalItems ?? (pageSize ? pageSize * total : total)} 条 · {total} 页
        </span>
      )}

      {renderButton('prev', '上一页', () => onChange(current - 1), false, !canPrev)}

      {pages.map((p, i) => {
        if (p === 'ellipsis') {
          return (
            <span key={`e-${i}`} className="ui-pagination__ellipsis">
              ···
            </span>
          )
        }
        return renderButton(`p-${p}`, String(p), () => onChange(p), p === current)
      })}

      {renderButton('next', '下一页', () => onChange(current + 1), false, !canNext)}

      {showQuickJumper && (
        <span className="ui-pagination__jumper">
          跳至
          <input
            type="number"
            min={1}
            max={total}
            defaultValue={current}
            className="ui-pagination__input"
            onKeyDown={e => {
              if (e.key === 'Enter') {
                const v = parseInt((e.target as HTMLInputElement).value)
                if (v >= 1 && v <= total) onChange(v)
              }
            }}
          />
          页
        </span>
      )}
    </div>
  )
}
