import { useTranslation } from 'react-i18next'
import { FilterIcon } from '../icons'
import Input from '../ui/Input'
import Select from '../ui/Select'
import type {
  MoleculeFilters as MoleculeFiltersType,
} from '@/hooks/useMoleculeLibrary'

interface MoleculeFiltersProps {
  filters: MoleculeFiltersType
  onFiltersChange: React.Dispatch<React.SetStateAction<MoleculeFiltersType>>
  sourceTypeOptions: string[]
  sourceDocOptions: string[]
  disabled?: boolean
}

export default function MoleculeFilters({
  filters,
  onFiltersChange,
  sourceTypeOptions,
  sourceDocOptions,
  disabled = false,
}: MoleculeFiltersProps) {
  const { t } = useTranslation()
  const handleStatusChange = (status: MoleculeFiltersType['status']) => {
    onFiltersChange((prev) => ({ ...prev, status }))
  }

  return (
    <div className="molecule-filters">
      <div className="molecule-filters__controls">
        <FilterIcon size={14} />
        <Select
          value={filters.status}
          onChange={(value) => handleStatusChange(value as MoleculeFiltersType['status'])}
          disabled={disabled}
          className="molecule-filters__select"
          showPlaceholder={false}
          ariaLabel={t('mol.statusFilter')}
          options={[
            { value: 'all', label: t('mol.status.all') },
            { value: 'confirmed', label: t('mol.status.confirmed') },
            { value: 'pending', label: t('mol.status.pending') },
            { value: 'corrected', label: t('mol.status.corrected') },
            { value: 'rejected', label: t('mol.status.rejected') },
          ]}
        />

        <Select
          value={filters.sourceType}
          onChange={(value) => onFiltersChange((prev) => ({ ...prev, sourceType: value }))}
          disabled={disabled}
          className="molecule-filters__select"
          showPlaceholder={false}
          ariaLabel={t('mol.sourceType.label')}
          options={[
            { value: 'all', label: t('mol.sourceType.all') },
            ...sourceTypeOptions.map((st) => ({ value: st, label: st })),
          ]}
        />

        <Select
          value={filters.sourceDoc}
          onChange={(value) => onFiltersChange((prev) => ({ ...prev, sourceDoc: value }))}
          disabled={disabled}
          className="molecule-filters__select"
          showPlaceholder={false}
          ariaLabel={t('mol.sourceDoc.label')}
          options={[
            { value: 'all', label: t('mol.sourceDoc.all') },
            ...sourceDocOptions.map((doc) => ({ value: doc, label: doc })),
          ]}
        />

        <Select
          value={filters.activityPresence}
          onChange={(value) =>
            onFiltersChange((prev) => ({
              ...prev,
              activityPresence: value as MoleculeFiltersType['activityPresence'],
            }))
          }
          disabled={disabled}
          className="molecule-filters__select"
          showPlaceholder={false}
          ariaLabel={t('mol.activityFilter.label')}
          options={[
            { value: 'all', label: t('mol.activityFilter.all') },
            { value: 'present', label: t('mol.activityFilter.present') },
            { value: 'missing', label: t('mol.activityFilter.missing') },
          ]}
        />

        <div className="molecule-filters__range">
          <Input
            type="number"
            placeholder="Min activity"
            value={filters.activityMin === null ? '' : String(filters.activityMin)}
            onChange={(e) =>
              onFiltersChange((prev) => ({
                ...prev,
                activityMin: e.target.value === '' ? null : Number(e.target.value),
              }))
            }
            disabled={disabled}
            className="molecule-filters__range-input"
            ariaLabel="Min activity"
          />
          <span className="molecule-filters__range-separator">-</span>
          <Input
            type="number"
            placeholder="Max activity"
            value={filters.activityMax === null ? '' : String(filters.activityMax)}
            onChange={(e) =>
              onFiltersChange((prev) => ({
                ...prev,
                activityMax: e.target.value === '' ? null : Number(e.target.value),
              }))
            }
            disabled={disabled}
            className="molecule-filters__range-input"
            ariaLabel="Max activity"
          />
        </div>
      </div>
    </div>
  )
}
