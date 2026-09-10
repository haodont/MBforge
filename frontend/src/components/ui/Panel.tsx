/** Generic panel container with title bar, body, and optional footer. */

import { useState, type ReactNode } from 'react'
import { ChevronDownIcon, ChevronUpIcon } from '../icons'

interface PanelProps {
  title: string | ReactNode
  actions?: ReactNode
  children: ReactNode
  footer?: ReactNode
  variant?: 'default' | 'elevated'
  collapsible?: boolean
  defaultCollapsed?: boolean
  className?: string
}

export function Panel({
  title,
  actions,
  children,
  footer,
  variant = 'default',
  collapsible = false,
  defaultCollapsed = false,
  className = '',
}: PanelProps) {
  const [collapsed, setCollapsed] = useState(defaultCollapsed)
  const isCollapsible = collapsible

  const headerContent = (
    <div className="ui-panel-header">
      <div className="ui-panel-title">
        {typeof title === 'string' ? <span>{title}</span> : title}
      </div>
      <div className="ui-panel-header-actions">
        {actions}
        {isCollapsible && (
          <button
            type="button"
            className="ui-panel-collapse-btn"
            onClick={() => setCollapsed((v) => !v)}
            aria-label={collapsed ? '展开' : '折叠'}
            aria-expanded={!collapsed}
          >
            {collapsed ? <ChevronDownIcon size={14} /> : <ChevronUpIcon size={14} />}
          </button>
        )}
      </div>
    </div>
  )

  return (
    <div className={`ui-panel ui-panel--${variant} ${className}`}>
      {headerContent}
      {!collapsed && <div className="ui-panel-body">{children}</div>}
      {!collapsed && footer && <div className="ui-panel-footer">{footer}</div>}
    </div>
  )
}
