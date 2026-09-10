import { Card } from '../../ui'
import MoleculeDisplay from '@/components/molecule/MoleculeDisplay'

export interface CoreScaffoldCardProps {
  coreSmiles: string
  compoundCount: number
  unmatched: number
}

/**
 * 共同骨架展示卡.
 *
 * 显示 R-Group 矩阵的"核心"——所有衍生物共享的骨架结构.
 * 包含 2D 渲染 + SMILES 字符串 + 匹配/未匹配统计.
 */
export default function CoreScaffoldCard({
  coreSmiles,
  compoundCount,
  unmatched,
}: CoreScaffoldCardProps) {
  return (
    <Card padding={20}>
      <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: 12 }}>
        <div>
          <h3 style={{ margin: 0, fontSize: 15, fontWeight: 600 }}>核心骨架（Core Scaffold）</h3>
          <p style={{ margin: '4px 0 0 0', fontSize: 12, color: 'var(--text-muted)' }}>
            所有化合物共享的结构（MCS 自动提取）
          </p>
        </div>
        <div style={{ display: 'flex', gap: 6, alignItems: 'center' }}>
          {unmatched > 0 && (
            <span
              style={{
                fontSize: 11,
                padding: '2px 8px',
                background: 'var(--warning-muted)',
                color: 'var(--warning)',
                borderRadius: 4,
              }}
            >
              {unmatched} 个未匹配
            </span>
          )}
          <span
            style={{
              fontSize: 11,
              padding: '2px 8px',
              background: 'var(--accent-muted)',
              color: 'var(--accent)',
              borderRadius: 4,
              fontWeight: 500,
            }}
          >
            {compoundCount} 个衍生物
          </span>
        </div>
      </div>
      <div
        style={{
          background: 'var(--bg-base)',
          borderRadius: 8,
          padding: 16,
          display: 'flex',
          alignItems: 'center',
          gap: 16,
        }}
      >
        <MoleculeDisplay
          smiles={coreSmiles}
          name="Core Scaffold"
          size={120}
          showMetadata={false}
          mode="view"
          style={{ border: 'none', padding: 0, background: 'transparent' }}
        />
        <code
          style={{
            flex: 1,
            fontFamily: 'monospace',
            fontSize: 12,
            color: 'var(--text-primary)',
            wordBreak: 'break-all',
          }}
        >
          {coreSmiles}
        </code>
      </div>
    </Card>
  )
}
