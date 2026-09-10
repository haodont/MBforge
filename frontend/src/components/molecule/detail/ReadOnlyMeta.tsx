import type { MoleculeRecord } from '@/types'

interface Props {
  record: MoleculeRecord
}

export default function ReadOnlyMeta({ record }: Props) {
  return (
    <div
      style={{
        display: 'grid',
        gridTemplateColumns: 'repeat(2, 1fr)',
        gap: 8,
        padding: '8px 10px',
        background: 'var(--bg-base)',
        borderRadius: 6,
        border: '1px solid var(--border)',
        fontSize: 12,
        color: 'var(--text-muted)',
      }}
    >
      <div>来源文档: {record.source_doc || '-'}</div>
      <div>来源类型: {record.source_type || '-'}</div>
      <div>创建时间: {new Date(record.created_at).toLocaleString()}</div>
      <div>ID: {record.mol_id}</div>
    </div>
  )
}