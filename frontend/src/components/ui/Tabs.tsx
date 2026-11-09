import { useState, type ReactNode } from 'react'
import { motion } from 'framer-motion'

export interface TabItem {
  /** 唯一标识 */
  key: string
  /** 标签文本 */
  label: ReactNode
  /** 是否禁用 */
  disabled?: boolean
  /** 角标（如未读数）*/
  badge?: string | number
  /** 显示关闭按钮（需配合 Tabs.onTabClose） */
  closable?: boolean
}

export interface TabsProps {
  items: TabItem[]
  /** 当前激活的 tab key */
  activeKey?: string
  /** 默认激活的 tab key（非受控）*/
  defaultActiveKey?: string
  /** tab 切换回调 */
  onChange?: (key: string) => void
  /** 可关闭 tab 的关闭回调（配合 TabItem.closable） */
  onTabClose?: (key: string) => void
  /** 关闭按钮的无障碍标签 */
  closeLabel?: string
  /** 标签位置（预留字段，未来支持 bottom 布局）*/
  position?: 'top' | 'bottom'
  /** 变体 */
  variant?: 'default' | 'pills' | 'underline' | 'segment'
  size?: 'sm' | 'md' | 'lg'
  /** 是否填满整行 */
  fullWidth?: boolean
  /** Tabs 根节点 id，用于 ARIA 关联 */
  id?: string
  style?: React.CSSProperties
  className?: string
}

interface TabButtonProps {
  item: TabItem
  isActive: boolean
  variant: TabsProps['variant']
  size: TabsProps['size']
  tabsId?: string
  className?: string
  onClick: (key: string, disabled?: boolean) => void
  onClose?: (key: string) => void
  closeLabel?: string
}

function TabButton({
  item,
  isActive,
  variant = 'default',
  size = 'md',
  tabsId,
  className,
  onClick,
  onClose,
  closeLabel = 'Close tab',
}: TabButtonProps) {
  const cls = [
    'ui-tabs__tab',
    `ui-tabs__tab--${size}`,
    isActive && 'ui-tabs__tab--active',
    item.closable && onClose && 'ui-tabs__tab--closable',
    className,
  ]
    .filter(Boolean)
    .join(' ')

  const tab = (
    <button
      type="button"
      role="tab"
      aria-selected={isActive}
      id={tabsId ? `${tabsId}-${item.key}-tab` : undefined}
      aria-controls={tabsId ? `${tabsId}-${item.key}-panel` : undefined}
      onClick={() => onClick(item.key, item.disabled)}
      disabled={item.disabled}
      className={cls}
    >
      <span className="ui-tabs__tab-label">{item.label}</span>
      {item.badge !== undefined && <span className="ui-tabs__badge">{item.badge}</span>}
      {variant === 'underline' && isActive && (
        <motion.span
          layoutId="tabs-underline"
          className="ui-tabs__underline"
          transition={{ type: 'spring', stiffness: 400, damping: 30 }}
        />
      )}
    </button>
  )

  if (!item.closable || !onClose) return tab

  return (
    <span className="ui-tabs__tab-wrap">
      {tab}
      <button
        type="button"
        className="ui-tabs__close"
        aria-label={typeof item.label === 'string' ? `${closeLabel}: ${item.label}` : closeLabel}
        disabled={item.disabled}
        onClick={e => {
          e.stopPropagation()
          onClose(item.key)
        }}
      >
        <svg width="12" height="12" viewBox="0 0 12 12" fill="none" aria-hidden="true">
          <path d="M3 3l6 6M9 3L3 9" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" />
        </svg>
      </button>
    </span>
  )
}

/**
 * Tabs 标签页组件。
 *
 * 支持受控/非受控两种模式，4 种视觉变体，键盘可访问。
 * 视觉样式由 styles/ui.css 的 .ui-tabs 类族承载。
 */
export default function Tabs({
  items,
  activeKey,
  defaultActiveKey,
  onChange,
  onTabClose,
  closeLabel,

  position: _position = 'top',
  variant = 'default',
  size = 'md',
  fullWidth = false,
  id,
  style,
  className,
}: TabsProps) {
  const [internalKey, setInternalKey] = useState(defaultActiveKey ?? items[0]?.key)
  const isControlled = activeKey !== undefined
  const currentKey = isControlled ? activeKey : internalKey

  const handleClick = (key: string, disabled?: boolean) => {
    if (disabled) return
    if (!isControlled) setInternalKey(key)
    onChange?.(key)
  }

  const renderTab = (item: TabItem) => {
    const isActive = item.key === currentKey
    return (
      <TabButton
        key={item.key}
        item={item}
        isActive={isActive}
        variant={variant}
        size={size}
        tabsId={id}
        className={className}
        onClick={handleClick}
        onClose={onTabClose}
        closeLabel={closeLabel}
      />
    )
  }

  const listCls = ['ui-tabs', `ui-tabs--${variant}`, fullWidth && 'ui-tabs--full']
    .filter(Boolean)
    .join(' ')

  return (
    <div role="tablist" className={listCls} style={style}>
      {items.map(renderTab)}
    </div>
  )
}

// ============================================================================
// TabPanel - 内容容器（使用 TabsContext 或 activeKey 显式指定）
// ============================================================================

export interface TabPanelProps {
  activeKey: string
  tabKey: string
  children: ReactNode
  /** 强制挂载（保留 DOM）*/
  forceMount?: boolean
  /** 与 Tabs 的 id 关联，用于 ARIA */
  tabsId?: string
}

export function TabPanel({ activeKey, tabKey, children, forceMount = false, tabsId }: TabPanelProps) {
  if (activeKey !== tabKey && !forceMount) return null
  return (
    <div
      role="tabpanel"
      id={tabsId ? `${tabsId}-${tabKey}-panel` : undefined}
      aria-labelledby={tabsId ? `${tabsId}-${tabKey}-tab` : undefined}
      className="ui-tabs__panel"
    >
      {children}
    </div>
  )
}
