/** Worker status badge — live status indicator for the pipeline worker. */

import { useTranslation } from 'react-i18next'

interface WorkerStatusBadgeProps {
  status: 'online' | 'offline' | 'unknown'
}

const WORKER_STATUS_CONFIG = {
  online:  { i18nKey: 'queue.workerOnline',  titleKey: 'queue.workerOnlineTitle' },
  offline: { i18nKey: 'queue.workerOffline', titleKey: 'queue.workerOfflineTitle' },
  unknown: { i18nKey: 'queue.workerUnknown', titleKey: 'queue.workerUnknownTitle' },
} as const

export function WorkerStatusBadge({ status }: WorkerStatusBadgeProps) {
  const { t } = useTranslation()
  const config = WORKER_STATUS_CONFIG[status]
  return (
    <span
      className={`queue-worker-status is-${status}`}
      title={t(config.titleKey)}
    >
      <span className="queue-worker-dot" />
      {t(config.i18nKey)}
    </span>
  )
}
