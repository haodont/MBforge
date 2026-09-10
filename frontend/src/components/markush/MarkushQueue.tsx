/** Left column: filterable list of pending candidates. */

import { useTranslation } from 'react-i18next'
import type { MarkushCandidate } from '@/api/http/markush'
import EmptyState from '../ui/EmptyState'
import { ErrorState } from '../ui/ErrorState'
import { LoadingState } from '../ui/LoadingState'
import Select from '../ui/Select'

interface MarkushQueueProps {
  title: string
  loading: boolean
  error: string | null
  items: MarkushCandidate[]
  total: number
  filterStatus: string
  onFilterChange: (next: string) => void
  selectedCandidateId: string | null
  onSelect: (candidateId: string) => void
}

const STATUS_OPTIONS = ['all', 'pending', 'confirmed', 'rejected'] as const

export default function MarkushQueue({
  title,
  loading,
  error,
  items,
  total,
  filterStatus,
  onFilterChange,
  selectedCandidateId,
  onSelect,
}: MarkushQueueProps) {
  const { t } = useTranslation()
  return (
    <section
      aria-label={title}
      style={{
        background: 'var(--bg-surface)',
        border: '1px solid var(--border)',
        borderRadius: 12,
        display: 'flex',
        flexDirection: 'column',
        minHeight: 0,
      }}
    >
      <header
        style={{
          padding: '12px 14px',
          borderBottom: '1px solid var(--border)',
          display: 'flex',
          flexDirection: 'column',
          gap: 8,
        }}
      >
        <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
          <div style={{ fontSize: 14, fontWeight: 600 }}>{title}</div>
          <div style={{ fontSize: 12, color: 'var(--text-muted)' }}>
            {t('markush.queue.total', '{{count}} 项', { count: total })}
          </div>
        </div>
        <Select
          value={filterStatus}
          onChange={onFilterChange}
          showPlaceholder={false}
          ariaLabel={t('markush.queue.filter', '筛选状态')}
          options={STATUS_OPTIONS.map((value) => ({
            value,
            label: value === 'all' ? t('markush.queue.all', '全部') : value,
          }))}
        />
      </header>
      <div style={{ overflowY: 'auto', flex: 1, minHeight: 0 }}>
        {loading ? (
          <LoadingState variant="spinner" message={t('common.loading', '加载中…')} />
        ) : error ? (
          <ErrorState error={error} compact />
        ) : items.length === 0 ? (
          <EmptyState
            message={t('markush.queue.empty', '没有匹配的候选。')}
            testId="markush-empty"
          />
        ) : (
          items.map((item) => (
            <button
              key={item.candidate_id}
              type="button"
              data-testid="markush-queue-row"
              onClick={() => onSelect(item.candidate_id)}
              style={{
                display: 'block',
                width: '100%',
                padding: '10px 12px',
                textAlign: 'left',
                background:
                  selectedCandidateId === item.candidate_id
                    ? 'var(--bg-hover)'
                    : 'transparent',
                border: 'none',
                borderBottom: '1px solid var(--border)',
                cursor: 'pointer',
                color: 'var(--text-primary)',
              }}
            >
              <div style={{ fontSize: 13, fontWeight: 600 }}>
                {item.normalized_label || item.raw_label || '—'}
              </div>
              <div style={{ fontSize: 11, color: 'var(--text-muted)', marginTop: 4 }}>
                {item.doc_id}
                {item.page != null ? ` · 第 ${item.page} 页` : ''}
              </div>
              <div style={{ fontSize: 11, color: 'var(--text-secondary)', marginTop: 4 }}>
                {item.smiles || item.esmiles || '（无结构）'}
              </div>
            </button>
          ))
        )}
      </div>
    </section>
  )
}
