import { useMemo } from 'react'
import { SectionTitle, Button, ResponsiveGrid } from '../ui'
import { ExternalLinkIcon } from '../icons'
import { showToast } from '@/hooks/useToast'
import CompoundCard from './CompoundCard'
import type { SARSession } from '@/types'

interface OverviewTabProps {
  session: SARSession
  selectedCompoundId: string | null
  onSelect: (id: string) => void
}

export default function OverviewTab({ session, selectedCompoundId, onSelect }: OverviewTabProps) {
  const sorted = useMemo(() => {
    return [...session.compounds].sort((a, b) => {
      const aA = a.activity ?? Infinity
      const bA = b.activity ?? Infinity
      return aA - bA
    })
  }, [session.compounds])

  return (
    <div>
      <div className="sar-tab-header">
        <SectionTitle style={{ margin: 0 }}>化合物列表</SectionTitle>
        <Button variant="ghost" size="sm" onClick={() => showToast('导出功能开发中', 'info')}>
          <ExternalLinkIcon size={14} /> 导出
        </Button>
      </div>
      <ResponsiveGrid mobileColumns={1} tabletColumns={2} desktopColumns={3} gap={12}>
        {sorted.map(cmp => (
          <CompoundCard
            key={cmp.id}
            compound={cmp}
            selected={selectedCompoundId === cmp.id}
            onClick={() => onSelect(cmp.id)}
            thumbnailSize={180}
          />
        ))}
      </ResponsiveGrid>
    </div>
  )
}
