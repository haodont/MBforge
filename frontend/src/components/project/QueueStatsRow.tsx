/** Queue stat pills — a compact row of per-status counters. */

import { useTranslation } from 'react-i18next'
import { StatPill } from './StatPill'
import { formatElapsed } from './queueUtils'
import type { QueueStats } from '@/api/http/ingest_queue'

interface QueueStatsRowProps {
  stats: QueueStats | undefined
  hasTasks: boolean
}

export function QueueStatsRow({ stats, hasTasks }: QueueStatsRowProps) {
  const { t } = useTranslation()
  if (!stats || !hasTasks) return null

  const avgTotalMs = stats.avg_stage_durations_ms?.reduce((a, b) => a + b, 0) ?? 0

  return (
    <div className="queue-stats-row">
      {stats.processing !== undefined && stats.processing > 0 && (
        <StatPill
          label={t('queue.processing')}
          value={stats.processing}
          tone="info"
          pulse
        />
      )}
      {stats.pending !== undefined && stats.pending > 0 && (
        <StatPill
          label={t('queue.pending')}
          value={stats.pending}
          tone="warning"
        />
      )}
      {stats.failed !== undefined && stats.failed > 0 && (
        <StatPill
          label={t('queue.failed')}
          value={stats.failed}
          tone="danger"
        />
      )}
      {stats.done !== undefined && stats.done > 0 && (
        <StatPill
          label={t('queue.done')}
          value={stats.done}
          tone="success"
        />
      )}
      {stats.cancelled !== undefined && stats.cancelled > 0 && (
        <StatPill
          label={t('queue.cancelled')}
          value={stats.cancelled}
          tone="neutral"
        />
      )}
      {avgTotalMs > 0 && (
        <StatPill
          label={t('queue.recent5')}
          value={t('queue.avgPer', { time: formatElapsed(avgTotalMs) })}
          tone="neutral"
        />
      )}
    </div>
  )
}
