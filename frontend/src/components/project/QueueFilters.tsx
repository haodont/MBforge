/** Queue filters — status chip row and the hide-done toggle. */

import { useTranslation } from 'react-i18next'
import Chip from '../ui/Chip'
import Switch from '../ui/Switch'
import type { FilterKey } from './queueUtils'

interface QueueFiltersProps {
  filter: FilterKey
  counts: Record<FilterKey, number>
  onFilterChange: (key: FilterKey) => void
}

export function QueueFilters({ filter, counts, onFilterChange }: QueueFiltersProps) {
  const { t } = useTranslation()

  const filters: { key: FilterKey; label: string }[] = [
    { key: 'all', label: t('queue.all') },
    { key: 'pending', label: t('queue.pending') },
    { key: 'processing', label: t('queue.processing') },
    { key: 'failed', label: t('queue.failed') },
    { key: 'cancelled', label: t('queue.cancelled') },
    { key: 'done', label: t('queue.done') },
  ]

  return (
    <div className="queue-filters" role="group" aria-label="状态筛选">
      {filters.map((f) => {
        const isActive = filter === f.key
        const count = counts[f.key]
        return (
          <Chip
            key={f.key}
            label={f.label}
            count={count}
            active={isActive}
            className={`queue-filter-chip${isActive ? ' is-active' : ''}`}
            onClick={() => onFilterChange(f.key)}
          />
        )
      })}
    </div>
  )
}

interface QueueHideDoneToggleProps {
  hideDone: boolean
  onChange: (next: boolean) => void
}

export function QueueHideDoneToggle({ hideDone, onChange }: QueueHideDoneToggleProps) {
  const { t } = useTranslation()

  return (
    <div className="queue-hide-done-toggle">
      <Switch
        size="sm"
        checked={hideDone}
        onChange={onChange}
      />
      <span className="queue-hide-done-label">{t('queue.hideDone')}</span>
    </div>
  )
}
