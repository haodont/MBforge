import { memo, useCallback } from 'react'
import type { MouseEvent } from 'react'
import { useTranslation } from 'react-i18next'
import type { MoleculeRecord } from '@/types'
import { Card, CardGrid, Skeleton, EmptyState, Badge } from '@/components/ui'
import type { BadgeVariant } from '@/components/ui/Badge'
import MoleculeDisplay from './MoleculeDisplay'
import './MoleculeCardGrid.css'

export interface MoleculeCardGridProps {
  molecules: MoleculeRecord[]
  loading: boolean
  selectedIds: Set<string>
  onToggleSelect: (molId: string) => void
  onCardClick: (mol: MoleculeRecord) => void
}

const statusVariantMap: Record<string, BadgeVariant> = {
  confirmed: 'success',
  corrected: 'info',
  rejected: 'danger',
  pending: 'warning',
}

const statusLabelMap: Record<string, string> = {
  confirmed: 'Confirmed',
  corrected: 'Corrected',
  rejected: 'Rejected',
  pending: 'Needs review',
}

export default function MoleculeCardGrid({
  molecules,
  loading,
  selectedIds,
  onToggleSelect,
  onCardClick,
}: MoleculeCardGridProps) {
  const { t } = useTranslation()

  if (loading) {
    return (
      <CardGrid minWidth={240} gap={16}>
        {Array.from({ length: 6 }, (_, i) => (
          <Skeleton key={i} variant="card" height={260} />
        ))}
      </CardGrid>
    )
  }

  if (molecules.length === 0) {
    return <EmptyState message={t('mol.empty')} />
  }

  return (
    <CardGrid minWidth={240} gap={16}>
      {molecules.map((mol) => (
        <MoleculeCard
          key={mol.mol_id}
          molecule={mol}
          isSelected={selectedIds.has(mol.mol_id)}
          onToggleSelect={onToggleSelect}
          onCardClick={onCardClick}
        />
      ))}
    </CardGrid>
  )
}

interface MoleculeCardProps {
  molecule: MoleculeRecord
  isSelected: boolean
  onToggleSelect: (molId: string) => void
  onCardClick: (mol: MoleculeRecord) => void
}

const MoleculeCard = memo(function MoleculeCard({
  molecule,
  isSelected,
  onToggleSelect,
  onCardClick,
}: MoleculeCardProps) {
  const { t } = useTranslation()

  const handleCardClick = useCallback((event: MouseEvent<HTMLDivElement>) => {
    if ((event.target as HTMLElement).closest('button, input, a, select, textarea')) return
    onCardClick(molecule)
  }, [molecule, onCardClick])

  const sourceImageUrl = molecule.evidence?.find(
    (item) => item.kind === 'figure' && item.crop_url,
  )?.crop_url ?? undefined

  return (
    <Card
      hoverable
      padding={16}
      onClick={handleCardClick}
      className="molecule-card"
      style={{
        borderColor: isSelected ? 'var(--accent)' : undefined,
        background: isSelected ? 'var(--accent-muted)' : undefined,
      }}
    >
      <input
        type="checkbox"
        checked={isSelected}
        onClick={(e) => e.stopPropagation()}
        onChange={() => onToggleSelect(molecule.mol_id)}
        aria-label={`Select ${molecule.name || molecule.mol_id}`}
        className="molecule-card__checkbox"
      />
      <MoleculeDisplay
        smiles={molecule.esmiles}
        name={molecule.name || molecule.mol_id}
        size={180}
        background="transparent"
        validateRemotely={false}
        sourceImageUrl={sourceImageUrl}
      />

      <div style={{ marginTop: 12, textAlign: 'center' }}>
        <div
          className="molecule-card__name"
          title={molecule.name || molecule.mol_id}
        >
          {molecule.name || molecule.mol_id}
        </div>
        <div
          className="molecule-card__meta"
          title={molecule.source_doc || undefined}
        >
          {molecule.source_doc || '-'}
        </div>
        <div className="molecule-card__activity">
          <span>
            {molecule.activity != null
              ? `${molecule.activity.toFixed(2)} ${molecule.units || 'nM'}`
              : <span className="activity-missing-badge">{t('mol.activityMissing')}</span>}
          </span>
          <span
            className="molecule-card__status"
            title={molecule.status === 'pending' ? '由图像或文本自动提取，尚未人工确认' : undefined}
          >
            <Badge variant={statusVariantMap[molecule.status] ?? 'warning'} dot>
              {t(`mol.status.${molecule.status}`, { defaultValue: statusLabelMap[molecule.status] })}
            </Badge>
          </span>
        </div>
      </div>
    </Card>
  )
})
