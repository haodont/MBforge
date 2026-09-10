import type { ExtractionResult } from '@/types'
import Button from '@/components/ui/Button'
import { EditIcon } from '@/components/icons'

interface Props {
  detection: ExtractionResult
  index: number
  onEdit: () => void
}

export default function DetectionHeader({ detection, index, onEdit }: Props) {
  return (
    <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between' }}>
      <div style={{ display: 'flex', alignItems: 'center', gap: 12 }}>
        <div style={{ fontSize: '13px', fontWeight: 600 }}>分子 #{index + 1}</div>
        <div style={{ display: 'flex', gap: '8px', fontSize: '11px', color: 'var(--text-muted)' }}>
          <span>检测: {Math.round(detection.moldet_conf * 100)}%</span>
        </div>
      </div>
      <Button size="sm" variant="secondary" icon={<EditIcon size={12} />} onClick={onEdit}>
        编辑
      </Button>
    </div>
  )
}
