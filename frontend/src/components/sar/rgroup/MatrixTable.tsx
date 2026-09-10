import { Card } from '../../ui'
import type { SARCompound } from '../../../types'
import type { RGroupMatrix as RGroupMatrixData } from '../../../api/http/sar'
import {
  activityColor,
  formatActivity,
  pActScale,
  shortSmiles,
} from './helpers'

export interface MatrixTableProps {
  matrix: RGroupMatrixData
  onCompoundClick?: (c: SARCompound) => void
}

/**
 * R-group 矩阵主表格.
 *
 * 行 = 化合物，列 = R 位置 (R1/R2/...).
 * 单元格 = 该化合物在该位置的取代基 SMILES (空用 `—` 占位).
 * 末列 = 活性数值 (pIC50 颜色编码).
 *
 * 行点击触发 onCompoundClick 回调 (用于跳转分子详情).
 */
export default function MatrixTable({ matrix, onCompoundClick }: MatrixTableProps) {
  return (
    <Card padding={0}>
      <div style={{ overflowX: 'auto' }}>
        <table style={{ width: '100%', borderCollapse: 'collapse', fontSize: 12 }}>
          <thead>
            <tr style={{ background: 'var(--bg-base)' }}>
              <th
                style={{
                  padding: '10px 12px',
                  textAlign: 'left',
                  fontWeight: 600,
                  color: 'var(--text-muted)',
                  borderBottom: '1px solid var(--border)',
                  minWidth: 120,
                }}
              >
                化合物
              </th>
              {matrix.r_labels.map(label => (
                <th
                  key={label}
                  style={{
                    padding: '10px 12px',
                    textAlign: 'center',
                    fontWeight: 600,
                    color: 'var(--accent)',
                    borderBottom: '1px solid var(--border)',
                    minWidth: 100,
                  }}
                >
                  {label}
                </th>
              ))}
              <th
                style={{
                  padding: '10px 12px',
                  textAlign: 'right',
                  fontWeight: 600,
                  color: 'var(--text-muted)',
                  borderBottom: '1px solid var(--border)',
                }}
              >
                活性
              </th>
            </tr>
          </thead>
          <tbody>
            {matrix.compounds.map((c, rowIdx) => {
              const activity = c.activity
              const units = (c.units) ?? ''
              const matches = c.matches
              const pAct = pActScale(activity, units)
              return (
                <tr
                  key={c.id || rowIdx}
                  onClick={() => {
                    if (matches && onCompoundClick) {
                      onCompoundClick({
                        id: c.id,
                        esmiles: c.smiles,
                        name: c.name,
                        rGroups: {},
                        activity,
                        activityType: c.activity_type,
                        units,
                      })
                    }
                  }}
                  style={{
                    cursor: matches && onCompoundClick ? 'pointer' : 'default',
                    borderBottom: '1px solid var(--border)',
                    transition: 'background 0.1s',
                  }}
                  onMouseEnter={e => {
                    if (matches && onCompoundClick) {
                      e.currentTarget.style.background = 'var(--bg-elevated)'
                    }
                  }}
                  onMouseLeave={e => {
                    e.currentTarget.style.background = 'transparent'
                  }}
                >
                  <td style={{ padding: '8px 12px' }}>
                    <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
                      <span style={{ fontWeight: 500, color: 'var(--text-primary)' }}>
                        {c.name}
                      </span>
                      {!matches && (
                        <span style={{ fontSize: 10, color: 'var(--text-muted)' }}>未匹配</span>
                      )}
                    </div>
                  </td>
                  {matrix.r_labels.map((label, colIdx) => {
                    const sub = matrix.rows[rowIdx]?.[colIdx] ?? '—'
                    return (
                      <td
                        key={label}
                        style={{
                          padding: '8px 12px',
                          textAlign: 'center',
                          fontFamily: 'monospace',
                          fontSize: 11,
                          color: sub === '—' ? 'var(--text-muted)' : 'var(--text-primary)',
                        }}
                        title={sub}
                      >
                        {shortSmiles(sub)}
                      </td>
                    )
                  })}
                  <td style={{ padding: '8px 12px', textAlign: 'right' }}>
                    <span
                      style={{
                        display: 'inline-block',
                        padding: '2px 8px',
                        borderRadius: 4,
                        background: activityColor(pAct),
                        color: pAct != null && pAct > 6 ? 'white' : 'var(--text-primary)',
                        fontFamily: 'monospace',
                        fontSize: 11,
                        fontWeight: 500,
                      }}
                    >
                      {formatActivity(activity, units)}
                    </span>
                  </td>
                </tr>
              )
            })}
          </tbody>
        </table>
      </div>
    </Card>
  )
}
