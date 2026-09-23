import { useCallback, useEffect, useRef, useState, type ReactNode } from 'react'
import { AnimatePresence, motion } from 'framer-motion'
import { CheckIcon } from '../icons'

export interface MenuActionItem {
  /** 省略或 'item' 均可 —— 旧式纯 item 写法保持兼容 */
  type?: 'item'
  key: string
  label: ReactNode
  icon?: ReactNode
  danger?: boolean
  disabled?: boolean
  checked?: boolean
  onClick?: () => void
  onSelect?: () => void
}

export interface MenuSeparator {
  type: 'separator'
  key?: string
}

export interface MenuGroup {
  type: 'group'
  key?: string
  label?: string
  items: MenuActionItem[]
}

export type MenuItem = MenuActionItem | MenuSeparator | MenuGroup

export interface MenuProps {
  /** 触发器;省略时组件为纯受控模式,由 open/onOpenChange 驱动 */
  trigger?: (open: () => void) => ReactNode
  items: MenuItem[]
  /** 弹出方向 */
  align?: 'left' | 'right'
  /** 受控打开(纯受控模式或希望外部控制时传入) */
  open?: boolean
  onOpenChange?: (open: boolean) => void
  className?: string
  style?: React.CSSProperties
}

/**
 * Menu 下拉菜单。
 *
 * 支持普通项 / 分隔符(type='separator') / 分组(type='group' + label + items),
 * 每项可带 icon/danger/disabled/checked。受控或非受控:内部默认自管 open,
 * 也可由调用方经 ``open``/``onOpenChange`` 控制(trigger 可省略)。
 * 点击外部/Escape 关闭。视觉样式由 styles/ui.css 的 .ui-menu 类族承载。
 */
export default function Menu({
  trigger,
  items,
  align = 'right',
  open: controlledOpen,
  onOpenChange,
  className,
  style,
}: MenuProps) {
  const [internalOpen, setInternalOpen] = useState(false)
  const isControlled = controlledOpen !== undefined
  const open = isControlled ? controlledOpen : internalOpen
  const rootRef = useRef<HTMLDivElement>(null)

  const setOpen = useCallback((next: boolean) => {
    if (!isControlled) setInternalOpen(next)
    onOpenChange?.(next)
  }, [isControlled, onOpenChange])
  const toggle = useCallback(() => setOpen(!open), [open, setOpen])
  const close = useCallback(() => setOpen(false), [setOpen])

  useEffect(() => {
    if (!open) return
    const onPointerDown = (e: MouseEvent) => {
      if (rootRef.current && !rootRef.current.contains(e.target as Node)) close()
    }
    const onKeyDown = (e: KeyboardEvent) => {
      if (e.key === 'Escape') close()
    }
    document.addEventListener('mousedown', onPointerDown)
    document.addEventListener('keydown', onKeyDown)
    return () => {
      document.removeEventListener('mousedown', onPointerDown)
      document.removeEventListener('keydown', onKeyDown)
    }
  }, [close, open])

  const handleItem = (item: MenuActionItem) => {
    close()
    item.onClick?.()
    item.onSelect?.()
  }

  const renderAction = (item: MenuActionItem) => (
    <button
      key={item.key}
      type="button"
      role="menuitem"
      disabled={item.disabled}
      className={['ui-menu__item', item.danger && 'ui-menu__item--danger'].filter(Boolean).join(' ')}
      onClick={() => handleItem(item)}
    >
      {item.icon && <span className="ui-menu__icon">{item.icon}</span>}
      <span className="ui-menu__label">{item.label}</span>
      {item.checked && (
        <span className="ui-menu__check" aria-hidden>
          <CheckIcon size={13} />
        </span>
      )}
    </button>
  )

  const renderItems = (list: MenuItem[]) => (
    <>
      {list.map((item, index) => {
        if (item.type === 'separator') {
          return <div key={item.key ?? `sep-${index}`} className="ui-menu__separator" role="separator" />
        }
        if (item.type === 'group') {
          return (
            <div key={item.key ?? `group-${index}`} className="ui-menu__group" role="group">
              {item.label && <div className="ui-menu__group-label">{item.label}</div>}
              {item.items.map(renderAction)}
            </div>
          )
        }
        return renderAction(item)
      })}
    </>
  )

  return (
    <div ref={rootRef} className={['ui-menu', className].filter(Boolean).join(' ')} style={style}>
      {trigger && trigger(toggle)}
      <AnimatePresence>
        {open && (
          <motion.div
            className={`ui-menu__popover ui-menu__popover--${align}`}
            role="menu"
            initial={{ opacity: 0, y: -4, scale: 0.98 }}
            animate={{ opacity: 1, y: 0, scale: 1 }}
            exit={{ opacity: 0, y: -4, scale: 0.98 }}
            transition={{ duration: 0.15 }}
          >
            {renderItems(items)}
          </motion.div>
        )}
      </AnimatePresence>
    </div>
  )
}
