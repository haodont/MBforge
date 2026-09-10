import type { SARCompound } from '@/types'
import MoleculeDisplay from '@/components/molecule/MoleculeDisplay'
import Badge from '../ui/Badge'

interface Props {
  compound: SARCompound
  onClick?: () => void
  selected?: boolean
  /** 缩略图尺寸 */
  thumbnailSize?: number
}

/** 比较活性的辅助函数（越小越活性高 = 越好） */
function formatActivity(value: number | undefined, _type?: string, units?: string): string {
  if (value == null) return '—'
  const formatted = value < 0.01 ? value.toFixed(3) : value.toFixed(2)
  return `${formatted} ${units ?? ''}`
}

/** 活性等级（基于 IC50 nM） */
function activityLevel(value?: number, units?: string): {
  level: 'high' | 'medium' | 'low' | 'none'
  label: string
  variant: 'success' | 'warning' | 'danger' | 'neutral'
} {
  if (value == null) return { level: 'none', label: '未测', variant: 'neutral' }
  // 转换为 nM
  let nM = value
  if (units === 'uM') nM = value * 1000
  if (units === 'mM') nM = value * 1e6
  if (nM < 10) return { level: 'high', label: '高活性', variant: 'success' }
  if (nM < 1000) return { level: 'medium', label: '中等', variant: 'warning' }
  return { level: 'low', label: '低活性', variant: 'danger' }
}

/**
 * CompoundCard 化合物卡片。
 *
 * 紧凑显示：缩略图 + 名称 + 活性数据。
 */
export default function CompoundCard({ compound, onClick, selected, thumbnailSize = 140 }: Props) {
  const actLevel = activityLevel(compound.activity, compound.units)

  return (
    <div
      onClick={onClick}
      style={{
        display: 'flex',
        flexDirection: 'column',
        gap: 8,
        background: 'var(--bg-surface)',
        border: `2px solid ${selected ? 'var(--accent)' : 'var(--border)'}`,
        borderRadius: 12,
        padding: 10,
        cursor: onClick ? 'pointer' : 'default',
        transition: 'border-color 0.15s, box-shadow 0.15s',
        ...(selected && { boxShadow: 'var(--accent-shadow)' }),
      }}
    >
      <MoleculeDisplay
        smiles={compound.esmiles}
        name={compound.name}
        size={thumbnailSize}
        showMetadata={false}
        mode="view"
        style={{ border: 'none', padding: 0, background: 'transparent' }}
      />
      <div style={{ display: 'flex', flexDirection: 'column', gap: 4 }}>
        <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between' }}>
          <Badge variant={actLevel.variant} dot>{actLevel.label}</Badge>
          {compound.activityType && (
            <span style={{ fontSize: 10, color: 'var(--text-muted)' }}>{compound.activityType}</span>
          )}
        </div>
        <div style={{
          fontSize: 11,
          fontFamily: 'monospace',
          color: 'var(--text-primary)',
          textAlign: 'right',
        }}>
          {formatActivity(compound.activity, compound.activityType, compound.units)}
        </div>
      </div>
    </div>
  )
}
