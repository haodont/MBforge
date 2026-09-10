import { useMemo } from 'react'
import { Card, ResponsiveGrid } from '../ui'
import { FlaskIcon, BarChartIcon, SparklesIcon, TargetIcon } from '../icons'
import type { SARSession, SARCompound } from '@/types'

interface SessionOverviewProps {
  session: SARSession
}

export default function SessionOverview({ session }: SessionOverviewProps) {
  const stats = useMemo(() => {
    const compounds = session.compounds
    const withActivity = compounds.filter(c => c.activity != null)
    const highActivity = compounds.filter(c => {
      if (c.activity == null) return false
      const nM = c.units === 'uM' ? c.activity * 1000 : c.units === 'mM' ? c.activity * 1e6 : c.activity
      return nM < 10
    }).length

    const best = compounds.reduce<SARCompound | null>((min, c) => {
      if (c.activity == null) return min
      if (min == null || min.activity == null || c.activity < min.activity) return c
      return min
    }, null)

    return {
      total: compounds.length,
      tested: withActivity.length,
      high: highActivity,
      best,
    }
  }, [session])

  return (
    <ResponsiveGrid mobileColumns={1} tabletColumns={2} desktopColumns={4} gap={12}>
      <StatBox label="化合物总数" value={stats.total} icon={<FlaskIcon size={20} />} />
      <StatBox label="已测活性" value={stats.tested} icon={<BarChartIcon size={20} />} variant="info" />
      <StatBox label="高活性 (<10 nM)" value={stats.high} icon={<SparklesIcon size={20} />} variant="success" />
      <StatBox
        label="最佳化合物"
        value={stats.best?.name ?? '—'}
        subValue={stats.best ? `${stats.best.activity} ${stats.best.units}` : undefined}
        icon={<TargetIcon size={20} />}
        variant="warning"
      />
    </ResponsiveGrid>
  )
}

interface StatBoxProps {
  label: string
  value: string | number
  subValue?: string
  icon: React.ReactNode
  variant?: 'default' | 'success' | 'info' | 'warning' | 'danger'
}

function StatBox({ label, value, subValue, icon, variant = 'default' }: StatBoxProps) {
  const variantBg: Record<string, string> = {
    default: 'var(--bg-surface)',
    success: 'rgba(22,163,74,0.08)',
    info: 'rgba(59,130,246,0.08)',
    warning: 'rgba(245,158,11,0.08)',
    danger: 'rgba(220,38,38,0.08)',
  }
  const variantColor: Record<string, string> = {
    default: 'var(--text-primary)',
    success: 'var(--success)',
    info: 'var(--info)',
    warning: 'var(--warning)',
    danger: 'var(--danger)',
  }
  return (
    <Card padding="16px" className="sar-stat-box" style={{ background: variantBg[variant] }}>
      <div className="sar-stat-icon" style={{ color: variantColor[variant] }}>
        {icon}
      </div>
      <div className="sar-stat-content">
        <div className="sar-stat-label">{label}</div>
        <div className="sar-stat-value" style={{ color: variantColor[variant] }}>
          {value}
        </div>
        {subValue && <div className="sar-stat-sub">{subValue}</div>}
      </div>
    </Card>
  )
}
