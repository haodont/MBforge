/** Stat pill — compact stat display with icon and pulse support. */

import type { ReactNode } from 'react'

interface StatPillProps {
  label: string
  value: number | string
  tone: 'neutral' | 'info' | 'success' | 'warning' | 'danger'
  icon?: ReactNode
  pulse?: boolean
}

export function StatPill({ label, value, tone, icon, pulse = false }: StatPillProps) {
  return (
    <div className={`queue-stat-pill is-${tone}`}>
      {icon && <span className="queue-stat-pill-icon">{icon}</span>}
      <div className="queue-stat-pill-body">
        <div className="queue-stat-pill-label">{label}</div>
        <div className={`queue-stat-pill-value${pulse ? ' is-pulse' : ''}`}>{value}</div>
      </div>
    </div>
  )
}
