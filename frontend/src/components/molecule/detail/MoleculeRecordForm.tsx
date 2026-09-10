import type { ReactNode } from 'react'
import Button from '@/components/ui/Button'
import Input from '@/components/ui/Input'
import Select from '@/components/ui/Select'
import { EditIcon } from '@/components/icons'
import type { MoleculeRecord } from '@/types'
import { compactInputStyle } from '@/components/ui/formInputStyle'
import FormField from './FormField'

const VALID_STATUSES = ['confirmed', 'pending', 'corrected', 'rejected'] as const

interface Props {
  record: MoleculeRecord
  saving: boolean
  onChange: <K extends keyof MoleculeRecord>(field: K, value: MoleculeRecord[K]) => void
  onSave: () => void
  onEditStructure: () => void
  evidence: ReactNode
}

export default function MoleculeRecordForm({
  record,
  saving,
  onChange,
  onSave,
  onEditStructure,
  evidence,
}: Props) {
  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 12 }}>
      <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between' }}>
        <div style={{ fontSize: '16px', fontWeight: 600 }}>{record.name || record.mol_id}</div>
        <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
          <Button
            variant="secondary"
            size="sm"
            icon={<EditIcon size={13} />}
            onClick={onEditStructure}
          >
            编辑结构
          </Button>
          <Button variant="primary" size="sm" onClick={onSave} disabled={saving}>
            {saving ? '保存中...' : '保存'}
          </Button>
        </div>
      </div>

      {evidence}

      <FormField label="名称">
        <Input
          value={record.name || ''}
          onChange={e => onChange('name', e.target.value)}
          style={compactInputStyle}
        />
      </FormField>

      <FormField label="E-SMILES">
        <Input
          value={record.esmiles}
          onChange={e => onChange('esmiles', e.target.value)}
          style={compactInputStyle}
        />
      </FormField>

      <div style={{ display: 'grid', gridTemplateColumns: 'repeat(3, 1fr)', gap: 10 }}>
        <FormField label="活性">
          <Input
            type="number"
            value={record.activity?.toString() ?? ''}
            onChange={e =>
              onChange('activity', e.target.value === '' ? null : Number(e.target.value))
            }
            style={compactInputStyle}
          />
        </FormField>

        <FormField label="活性类型">
          <Input
            value={record.activity_type || ''}
            onChange={e => onChange('activity_type', e.target.value)}
            style={compactInputStyle}
          />
        </FormField>

        <FormField label="单位">
          <Input
            value={record.units || ''}
            onChange={e => onChange('units', e.target.value)}
            style={compactInputStyle}
          />
        </FormField>
      </div>

      <FormField label="状态">
        <Select
          value={record.status}
          onChange={(value) => onChange('status', value)}
          showPlaceholder={false}
          style={compactInputStyle}
          options={VALID_STATUSES.map((status) => ({ value: status, label: status }))}
        />
      </FormField>
    </div>
  )
}