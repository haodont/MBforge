import { useEffect, useMemo, useState } from 'react'
import PageContainer from '../ui/PageContainer'
import { useTranslation } from 'react-i18next'
import Button from '../ui/Button'
import { LoadingState } from '../ui/LoadingState'
import EmptyState from '../ui/EmptyState'
import InlineAlert from '../ui/InlineAlert'
import ConfirmDialog from '../ui/ConfirmDialog'
import { QueueIcon, RefreshCwIcon, XIcon } from '../icons'
import { WorkerStatusBadge } from './WorkerStatusBadge'
import { QueueStatsRow } from './QueueStatsRow'
import { QueueFilters, QueueHideDoneToggle } from './QueueFilters'
import { QueueTaskList } from './QueueTaskList'
import { useQueueActions } from './useQueueActions'
import { useQueueFilters } from './useQueueFilters'
import { useQueueLogs } from './useQueueLogs'
import { deduplicateTasksByDocId } from './queueUtils'
import {
  useIngestQueue,
  useIngestStats,
  useWorkerStatus,
} from '@/api/query/hooks'
import { useIngestSSE } from '@/api/query/useIngestSSE'

import { useAppContext } from '../../context/AppContext'

export default function ProcessingQueue() {
  const { libraryRoot } = useAppContext()
  const { t } = useTranslation()

  // ── React Query data ─────────────────────────────────────────
  const { data: tasks = [], isLoading, refetch: refetchQueue } = useIngestQueue(libraryRoot)
  const { data: stats, refetch: refetchStats } = useIngestStats(libraryRoot)
  const { data: workerData } = useWorkerStatus()
  const workerStatus = workerData?.status === 'online' ? 'online' : 'offline' as 'online' | 'offline' | 'unknown'
  const queueTasks = useMemo(() => deduplicateTasksByDocId(tasks), [tasks])

  // ── Feature hooks ────────────────────────────────────────────
  const { filter, setFilter, hideDone, setHideDone, visibleTasks, counts } = useQueueFilters(queueTasks)
  const { logMap, expandedLogDocs, toggleLogs, logSources } = useQueueLogs({ libraryRoot, tasks })
  const {
    actionId,
    bulkAction,
    confirm,
    setConfirm,
    handleCancel,
    handleRetry,
    handleRetryAllFailed,
    runCancelAllPending,
    handleSetPriority,
    runDelete,
  } = useQueueActions({ libraryRoot, queueTasks, refetchQueue, refetchStats })

  // Track the "most interesting" processing run for SSE subscription.
  const activeRunId = useMemo(() => {
    const processing = queueTasks.find(t => t.status === 'processing')
    return processing?.run_id ?? null
  }, [queueTasks])

  // SSE bridge — pushes real-time stage changes into the query cache.
  useIngestSSE({ libraryRoot, runId: activeRunId })

  // Live "now" timestamp for elapsed-time displays.
  const [now, setNow] = useState(() => Date.now())
  useEffect(() => {
    const hasProcessing = queueTasks.some((t) => t.status === 'processing')
    if (!hasProcessing) return
    const id = window.setInterval(() => setNow(Date.now()), 1000)
    return () => window.clearInterval(id)
  }, [queueTasks])

  if (isLoading) {
    return (
      <PageContainer>
        <div className="workspace-loading">
          <LoadingState variant="spinner" message="Loading..." />
        </div>
      </PageContainer>
    )
  }

  return (
    <PageContainer>
      <div className="queue-page">
        {/* ----- Hero / header ----- */}
        <header className="queue-page-header">
          <div className="queue-page-title-row">
            <div className="queue-page-title">
              <span className="queue-page-icon" aria-hidden>
                <QueueIcon size={22} />
              </span>
              <h1 className="queue-page-title-text">{t('queue.title')}</h1>
              <WorkerStatusBadge status={workerStatus} />
            </div>
            <div className="queue-page-header-actions">
              <QueueHideDoneToggle hideDone={hideDone} onChange={setHideDone} />
              {queueTasks.length > 0 && (
                <div className="queue-bulk-actions" role="toolbar" aria-label={t('queue.bulkActions')}>
                  <Button
                    variant="secondary"
                    size="sm"
                    icon={<RefreshCwIcon size={14} />}
                    onClick={() => void handleRetryAllFailed()}
                    loading={bulkAction === 'retry'}
                    disabled={bulkAction !== null || counts.failed === 0}
                  >
                    {t('queue.retryAllFailed')}
                  </Button>
                  <Button
                    variant="secondary"
                    size="sm"
                    icon={<XIcon size={14} />}
                    onClick={() => setConfirm({ type: 'cancel-all' })}
                    loading={bulkAction === 'cancel'}
                    disabled={bulkAction !== null || counts.pending === 0}
                  >
                    {t('queue.cancelAllPending')}
                  </Button>
                </div>
              )}
            </div>
          </div>

          {/* ----- Stats row ----- */}
          <QueueStatsRow stats={stats} hasTasks={queueTasks.length > 0} />
        </header>

        {/* ----- Model gate banner ----- */}
        {workerData?.model_gate && !workerData.model_gate.ready && (
          <InlineAlert tone="warning" title={t('queue.modelsBlockedTitle')}>
            {t('queue.modelsBlockedBody', {
              models: workerData.model_gate.missing.map((m) => m.name).join(', '),
            })}
          </InlineAlert>
        )}

        {/* ----- Filter chips ----- */}
        {queueTasks.length > 0 && (
          <QueueFilters filter={filter} counts={counts} onFilterChange={setFilter} />
        )}

        {/* ----- Log sources ----- */}
        {/* One query-backed bridge per expanded document feeds the merge map. */}
        {logSources}

        {/* ----- Task list ----- */}
        {visibleTasks.length === 0 ? (
          <EmptyState
            className="queue-empty"
            message={queueTasks.length === 0 ? t('queue.emptyHint') : t('queue.filterHint')}
            icon={
              <div className="queue-empty-icon">
                <QueueIcon size={28} />
              </div>
            }
          />
        ) : (
          <QueueTaskList
            tasks={visibleTasks}
            now={now}
            expandedLogDocs={expandedLogDocs}
            logMap={logMap}
            actionId={actionId}
            onToggleLogs={toggleLogs}
            onCancel={handleCancel}
            onRetry={handleRetry}
            onDelete={(task) => setConfirm({ type: 'delete', task })}
            onTogglePin={handleSetPriority}
          />
        )}
      </div>

      <ConfirmDialog
        open={confirm !== null}
        title={confirm === null ? '' : confirm.type === 'cancel-all' ? t('queue.cancelAllPending') : t('queue.deleteTask')}
        message={confirm === null ? '' : confirm.type === 'cancel-all'
          ? t('queue.cancelAllConfirm', { count: queueTasks.filter((task) => task.status === 'pending').length })
          : t('queue.deleteConfirm')}
        confirmLabel={confirm === null ? '' : confirm.type === 'delete' ? t('queue.deleteTask') : t('common.confirm')}
        loading={bulkAction !== null || actionId !== null}
        onConfirm={() => {
          if (confirm?.type === 'cancel-all') void runCancelAllPending()
          else if (confirm?.type === 'delete') void runDelete(confirm.task)
        }}
        onCancel={() => setConfirm(null)}
      />
    </PageContainer>
  )
}
