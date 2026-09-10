import type { ReactNode } from 'react'
import { ChevronRightIcon, FolderIcon } from '../icons'

export interface BreadcrumbItem {
  /** 显示文本 */
  label: ReactNode
  /** 点击回调（不传则不可点击）*/
  onClick?: () => void
  /** 链接地址（替代 onClick）*/
  href?: string
  /** 是否为当前页 */
  current?: boolean
  /** 自定义图标 */
  icon?: ReactNode
}

export interface BreadcrumbProps {
  items: BreadcrumbItem[]
  /** 自定义分隔符 */
  separator?: ReactNode
  size?: 'sm' | 'md' | 'lg'
  style?: React.CSSProperties
  className?: string
}

const sizeMap = {
  sm: { fontSize: '12px' },
  md: { fontSize: '13px' },
  lg: { fontSize: '14px' },
}

/**
 * Breadcrumb 面包屑导航。
 *
 * 显示当前位置的层级路径，支持点击跳转。
 */
export default function Breadcrumb({
  items,
  separator,
  size = 'md',
  style,
  className,
}: BreadcrumbProps) {
  const sizeStyle = sizeMap[size]

  return (
    <nav aria-label="breadcrumb" className={className} style={style}>
      <ol style={{
        display: 'flex',
        alignItems: 'center',
        flexWrap: 'wrap',
        gap: 6,
        margin: 0,
        padding: 0,
        listStyle: 'none',
        ...sizeStyle,
      }}>
        {items.map((item, idx) => {
          const isLast = idx === items.length - 1
          const interactive = Boolean(item.onClick || item.href)

          return (
            <li
              key={idx}
              style={{ display: 'flex', alignItems: 'center', gap: 6 }}
            >
              {item.icon && (
                <span style={{ display: 'inline-flex', color: 'var(--text-muted)' }}>
                  {item.icon}
                </span>
              )}
              {interactive ? (
                item.href ? (
                  <a
                    href={item.href}
                    onClick={item.onClick}
                    aria-current={item.current ? 'page' : undefined}
                    style={{
                      color: 'var(--text-secondary)',
                      textDecoration: 'none',
                      cursor: 'pointer',
                      transition: 'color 0.15s',
                    }}
                    onMouseEnter={e => { e.currentTarget.style.color = 'var(--accent)' }}
                    onMouseLeave={e => { e.currentTarget.style.color = 'var(--text-secondary)' }}
                  >
                    {item.label}
                  </a>
                ) : (
                  <button
                    type="button"
                    onClick={item.onClick}
                    aria-current={item.current ? 'page' : undefined}
                    style={{
                      background: 'none',
                      border: 'none',
                      padding: 0,
                      color: 'var(--text-secondary)',
                      cursor: 'pointer',
                      fontSize: 'inherit',
                      fontWeight: 'inherit',
                      transition: 'color 0.15s',
                    }}
                    onMouseEnter={e => { e.currentTarget.style.color = 'var(--accent)' }}
                    onMouseLeave={e => { e.currentTarget.style.color = 'var(--text-secondary)' }}
                  >
                    {item.label}
                  </button>
                )
              ) : (
                <span style={{
                  color: isLast ? 'var(--text-primary)' : 'var(--text-secondary)',
                  fontWeight: isLast ? 500 : 400,
                }}>
                  {item.label}
                </span>
              )}
              {!isLast && (
                <span style={{ color: 'var(--text-muted)', display: 'inline-flex' }}>
                  {separator ?? <ChevronRightIcon size={12} />}
                </span>
              )}
            </li>
          )
        })}
      </ol>
    </nav>
  )
}

/** 预设：文件树风格的面包屑 */
export function FileBreadcrumb({
  segments,
  onNavigate,
}: {
  segments: string[]
  onNavigate?: (depth: number) => void
}) {
  return (
    <Breadcrumb
      items={segments.map((seg, i) => ({
        label: seg,
        onClick: onNavigate ? () => onNavigate(i) : undefined,
        current: i === segments.length - 1,
        icon: i === 0 ? <FolderIcon size={12} /> : undefined,
      }))}
      size="sm"
    />
  )
}
