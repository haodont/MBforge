import type { ReactNode } from 'react'

export interface AvatarItem {
  /** 唯一标识 */
  id: string
  /** 显示文本（首字母会用作 fallback）*/
  name: string
  /** 头像图片 URL */
  src?: string
  /** 背景色（无 src 时生效）*/
  color?: string
  /** 状态指示 */
  status?: 'online' | 'offline' | 'busy' | 'away'
  /** Tooltip / Title */
  title?: string
}

export interface AvatarGroupProps {
  items: AvatarItem[]
  /** 头像尺寸 */
  size?: number
  /** 重叠宽度（负数 margin）*/
  overlap?: number
  /** 最多显示几个，其余折叠为 +N */
  max?: number
  /** 点击回调 */
  onItemClick?: (id: string) => void
  /** 自定义 fallback（无 src 时显示）*/
  renderFallback?: (item: AvatarItem) => ReactNode
  style?: React.CSSProperties
  className?: string
}

const statusColors: Record<NonNullable<AvatarItem['status']>, string> = {
  online: 'var(--success)',
  offline: 'var(--text-muted)',
  busy: 'var(--danger)',
  away: 'var(--warning)',
}

/**
 * AvatarGroup 头像组。
 *
 * 显示多个头像并自动重叠，可限制最多显示数量。
 */
export default function AvatarGroup({
  items,
  size = 32,
  overlap = 8,
  max,
  onItemClick,
  renderFallback,
  style,
  className,
}: AvatarGroupProps) {
  const visible = max ? items.slice(0, max) : items
  const overflow = max ? items.length - max : 0
  const displayItems: (AvatarItem | { id: '__overflow'; name: string })[] = [...visible]
  if (overflow > 0) {
    displayItems.push({ id: '__overflow', name: `+${overflow}` })
  }

  return (
    <div
      className={className}
      style={{
        display: 'inline-flex',
        alignItems: 'center',
        ...style,
      }}
    >
      {displayItems.map((item, i) => {
        const isOverflow = item.id === '__overflow'
        const initials = isOverflow
          ? (item as { name: string }).name
          : (item as AvatarItem).name.trim().slice(0, 2).toUpperCase()
        const itemColor = isOverflow ? 'var(--bg-elevated)' : (item as AvatarItem).color

        return (
          <div
            key={item.id}
            onClick={isOverflow ? undefined : onItemClick ? () => onItemClick(item.id) : undefined}
            title={isOverflow ? `${overflow} more` : (item as AvatarItem).title ?? (item as AvatarItem).name}
            style={{
              position: 'relative',
              width: size,
              height: size,
              borderRadius: '50%',
              background: itemColor,
              color: 'white',
              display: 'flex',
              alignItems: 'center',
              justifyContent: 'center',
              fontSize: size * 0.4,
              fontWeight: 600,
              border: `2px solid var(--bg-base)`,
              marginLeft: i === 0 ? 0 : -overlap,
              cursor: isOverflow ? 'default' : (onItemClick ? 'pointer' : 'default'),
              overflow: 'hidden',
              zIndex: displayItems.length - i,
              boxShadow: '0 1px 3px rgba(0,0,0,0.1)',
            }}
          >
            {!isOverflow && (item as AvatarItem).src ? (
              <img
                src={(item as AvatarItem).src}
                alt={(item as AvatarItem).name}
                style={{ width: '100%', height: '100%', objectFit: 'cover' }}
              />
            ) : renderFallback && !isOverflow ? (
              renderFallback(item)
            ) : (
              initials
            )}
            {!isOverflow && (item as AvatarItem).status && (
              <span style={{
                position: 'absolute',
                right: 0,
                bottom: 0,
                width: size * 0.28,
                height: size * 0.28,
                borderRadius: '50%',
                background: statusColors[(item as AvatarItem).status as keyof typeof statusColors],
                border: `2px solid var(--bg-base)`,
              }} />
            )}
          </div>
        )
      })}
    </div>
  )
}
