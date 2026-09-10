import { Card, EmptyState } from '../../ui'
import type { ActivityHeatmapEntry } from '../../../api/http/sar'
import { activityColor, shortSmiles } from './helpers'

// ============================================================================
// HeatmapPanel — R 位置 × 取代基 热力图
// ============================================================================

export interface HeatmapPanelProps {
  heatmaps: ActivityHeatmapEntry[]
  stats: { min: number; max: number } | null
  lowerIsBetter: boolean
}

export default function HeatmapPanel({
  heatmaps,
  stats,
  lowerIsBetter,
}: HeatmapPanelProps) {
  if (heatmaps.length === 0) {
    return (
      <Card padding={20}>
        <EmptyState message="无活性数据" />
      </Card>
    )
  }

  return (
    <Card padding={20}>
      <h3 style={{ margin: '0 0 4px 0', fontSize: 14, fontWeight: 600 }}>活性热力图</h3>
      <p style={{ margin: '0 0 16px 0', fontSize: 11, color: 'var(--text-muted)' }}>
        按 R 位置 × 取代基聚合均值活性（pIC50 颜色编码，{lowerIsBetter ? '数值越低越好' : '数值越高越好'}）
      </p>

      <div style={{ display: 'flex', flexDirection: 'column', gap: 16 }}>
        {heatmaps.map(h => (
          <HeatmapRow key={h.r_label} entry={h} />
        ))}
      </div>

      {stats && <ColorLegend min={stats.min} max={stats.max} lowerIsBetter={lowerIsBetter} />}
    </Card>
  )
}

// ============================================================================
// HeatmapRow — 单个 R 位置的取代基列表
// ============================================================================

function HeatmapRow({ entry }: { entry: ActivityHeatmapEntry }) {
  if (entry.cells.length === 0) {
    return (
      <div>
        <div style={{ fontSize: 12, fontWeight: 600, marginBottom: 6, color: 'var(--accent)' }}>
          {entry.r_label}
        </div>
        <div style={{ fontSize: 11, color: 'var(--text-muted)' }}>无数据</div>
      </div>
    )
  }

  return (
    <div>
      <div style={{ fontSize: 12, fontWeight: 600, marginBottom: 6, color: 'var(--accent)' }}>
        {entry.r_label}{' '}
        <span style={{ fontSize: 10, color: 'var(--text-muted)' }}>
          ({entry.cells.length} 种取代基)
        </span>
      </div>
      <div style={{ display: 'flex', flexDirection: 'column', gap: 4 }}>
        {entry.cells.map((cell, idx) => (
          <HeatmapCellRow
            key={`${cell.substituent_smiles}-${idx}`}
            cell={cell}
            rank={idx + 1}
            best={idx === 0}
          />
        ))}
      </div>
    </div>
  )
}

// ============================================================================
// HeatmapCellRow — 单个取代基的活性行
// ============================================================================

interface HeatmapCellRowProps {
  cell: ActivityHeatmapEntry['cells'][number]
  rank: number
  best: boolean
}

function HeatmapCellRow({ cell, rank, best }: HeatmapCellRowProps) {
  const pAct = 9 - Math.log10(cell.avg_activity)
  return (
    <div
      style={{
        display: 'flex',
        alignItems: 'center',
        gap: 8,
        padding: '6px 10px',
        background: activityColor(pAct),
        borderRadius: 4,
        fontSize: 11,
        color: pAct > 6 ? 'white' : 'var(--text-primary)',
        transition: 'transform 0.1s',
      }}
    >
      <span style={{ fontWeight: 600, minWidth: 20 }}>#{rank}</span>
      <code
        style={{ flex: 1, fontFamily: 'monospace', fontSize: 11 }}
        title={cell.substituent_smiles}
      >
        {shortSmiles(cell.substituent_smiles, 24)}
      </code>
      <span style={{ fontWeight: 600, fontFamily: 'monospace' }}>
        {cell.avg_activity < 0.01
          ? cell.avg_activity.toFixed(3)
          : cell.avg_activity.toFixed(2)}
      </span>
      {best && <span style={{ fontSize: 10, fontWeight: 600 }}>★</span>}
      {cell.count > 1 && (
        <span style={{ fontSize: 10, opacity: 0.8 }}>n={cell.count}</span>
      )}
    </div>
  )
}

// ============================================================================
// ColorLegend — 渐变图例
// ============================================================================

interface ColorLegendProps {
  min: number
  max: number
  lowerIsBetter: boolean
}

function ColorLegend({ min, max, lowerIsBetter }: ColorLegendProps) {
  const steps = 10
  return (
    <div style={{ marginTop: 16, paddingTop: 12, borderTop: '1px solid var(--border)' }}>
      <div style={{ fontSize: 10, color: 'var(--text-muted)', marginBottom: 4 }}>
        pIC50 颜色图例（{lowerIsBetter ? '绿=高活性' : '绿=低活性'}）
      </div>
      <div
        style={{
          display: 'flex',
          height: 8,
          borderRadius: 4,
          overflow: 'hidden',
        }}
      >
        {Array.from({ length: steps }).map((_, i) => (
          <div
            key={i}
            style={{
              flex: 1,
              background: activityColor(min + ((max - min) * i) / (steps - 1)),
            }}
          />
        ))}
      </div>
      <div
        style={{
          display: 'flex',
          justifyContent: 'space-between',
          fontSize: 10,
          color: 'var(--text-muted)',
          marginTop: 4,
        }}
      >
        <span>pIC50 {min.toFixed(1)}</span>
        <span>pIC50 {max.toFixed(1)}</span>
      </div>
    </div>
  )
}
