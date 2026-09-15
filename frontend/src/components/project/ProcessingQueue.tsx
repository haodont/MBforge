import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { AnimatePresence } from 'framer-motion'
import { useVirtualizer } from '@tanstack/react-virtual'
import PageContainer from '../ui/PageContainer'
import { useTranslation } from 'react-i18next'
import Button from '../ui/Button'
import Chip from '../ui/Chip'
import Switch from '../ui/Switch'
import { LoadingState } from '../ui/LoadingState'
import EmptyState from '../ui/EmptyState'
import ConfirmDialog from '../ui/ConfirmDialog'
import { QueueIcon, RefreshCwIcon, TrashIcon, XIcon } from '../icons'
import { WorkerStatusBadge } from './WorkerStatusBadge'
import { StatPill } from './StatPill'
import { TaskRow } from './TaskRow'
import { getUserFacingError } from '@/utils/errors'
import {
  ingestGetLogs,
  type IngestLogEvent,
  type IngestTask,
} from '@/api/http/ingest_queue'
import {
  useIngestQueue,
  useIngestStats,
  useWorkerStatus,
  useCancelTask,
  useRetryTask,
  useDeleteTask,
  useCancelBatch,
  useRetryBatch,
  useCleanupTasks,
  useSetTaskPriority,
} from '@/api/query/hooks'
import { useIngestSSE } from '@/api/query/useIngestSSE'
import { showToast } from '@/hooks/useToast'

import { useAppContext } from '../../context/AppContext'
import { logger } from '@/utils/logger'

type StatusKey = IngestTask['status']
type FilterKey = 'all' | StatusKey

// Sort priority: actionable first (processing > pending > failed),
// then non-actionable (cancelled > done).
const STATUS_RANK: Record<StatusKey, number> = {
  processing: 0,
  pending: 1,
  failed: 2,
  cancelled: 3,
  done: 4,
}

const LOG_FETCH_LIMIT = 200
const LOGS_PER_DOC_CAP = 200
const MAX_LOG_DOCS = 50
// Stable identity so memoized rows without logs skip re-renders.
const EMPTY_LOGS: IngestLogEvent[] = []

type QueueConfirm =
  | { type: 'cancel-all' }
  | { type: 'cleanup' }
  | { type: 'delete'; task: IngestTask }
  | null

export default function ProcessingQueue() {
  const { libraryRoot } = useAppContext()
  const { t } = useTranslation()

  // ── React Query data ─────────────────────────────────────────
  const { data: tasks = [], isLoading, refetch: refetchQueue } = useIngestQueue(libraryRoot)
  const { data: stats, refetch: refetchStats } = useIngestStats(libraryRoot)
  const { data: workerData } = useWorkerStatus()
  const workerStatus = workerData?.status === 'online' ? 'online' : 'offline' as 'online' | 'offline' | 'unknown'
  const queueTasks = useMemo(() => deduplicateTasksByDocId(tasks), [tasks])

  // ── Local UI state ────────────────────────────────────────────
  const [actionId, setActionId] = useState<string | null>(null)
  const [filter, setFilter] = useState<FilterKey>('all')
  const [hideDone, setHideDone] = useState(true)
  const [logMap, setLogMap] = useState<Map<string, IngestLogEvent[]>>(new Map())
  const [expandedLogDocs, setExpandedLogDocs] = useState<Set<string>>(new Set())
  const [bulkAction, setBulkAction] = useState<'retry' | 'cancel' | null>(null)
  const [confirm, setConfirm] = useState<QueueConfirm>(null)

  const refreshQueue = useCallback(() => {
    void refetchQueue()
    void refetchStats()
  }, [refetchQueue, refetchStats])

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

  // ── Filters ───────────────────────────────────────────────────
  const FILTERS: { key: FilterKey; label: string }[] = useMemo(() => [
    { key: 'all', label: t('queue.all') },
    { key: 'pending', label: t('queue.pending') },
    { key: 'processing', label: t('queue.processing') },
    { key: 'failed', label: t('queue.failed') },
    { key: 'cancelled', label: t('queue.cancelled') },
    { key: 'done', label: t('queue.done') },
  ], [t])

  // ── Log fetching ──────────────────────────────────────────────
  const fetchLogsForDoc = useCallback(
    async (docId: string) => {
      try {
        const records = await ingestGetLogs(libraryRoot, docId, LOG_FETCH_LIMIT)
        if (records.length === 0) return
        setLogMap((prev) => {
          const list = prev.get(docId) ?? []
          const seen = new Set(list.map((e) => `${e.ts_ms}::${e.message}`))
          const merged = [...list]
          for (const r of records) {
            const key = `${r.ts_ms}::${r.message}`
            if (!seen.has(key)) {
              seen.add(key)
              merged.push(r)
            }
          }
          merged.sort((a, b) => a.ts_ms - b.ts_ms)
          const trimmed = merged.length > LOGS_PER_DOC_CAP ? merged.slice(-LOGS_PER_DOC_CAP) : merged
          const next = new Map(prev)
          next.set(docId, trimmed)
          // Bound the total number of docs we keep logs for.
          while (next.size > MAX_LOG_DOCS) {
            const first = next.keys().next().value
            if (first === undefined) break
            next.delete(first)
          }
          return next
        })
      } catch (e) {
        logger.error('[ProcessingQueue] fetchLogsForDoc failed:', e)
      }
    },
    [libraryRoot],
  )

  // Prune logMap when tasks change so we don't retain logs for removed docs.
  useEffect(() => {
    const docIds = new Set(tasks.map((t) => t.doc_id))
    setLogMap((prev) => {
      let changed = false
      const next = new Map(prev)
      for (const k of next.keys()) {
        if (!docIds.has(k)) {
          next.delete(k)
          changed = true
        }
      }
      return changed ? next : prev
    })
  }, [tasks])

  const cancelMutation = useCancelTask()
  const retryMutation = useRetryTask()
  const deleteMutation = useDeleteTask()
  const cancelBatchMutation = useCancelBatch()
  const retryBatchMutation = useRetryBatch()
  const cleanupMutation = useCleanupTasks()
  const priorityMutation = useSetTaskPriority()

  // ── Action handlers ───────────────────────────────────────────
  const handleCancel = useCallback(
    async (task: IngestTask) => {
      if (!libraryRoot) return
      setActionId(task.id)
      try {
        await cancelMutation.mutateAsync({ libraryRoot, runId: task.run_id })
        showToast(t('queue.taskCancelled'), 'success')
      } catch (e) {
        logger.error('[ProcessingQueue] cancel failed:', e)
        showToast(t('queue.cancelFailed', { error: getUserFacingError(e) }), 'error')
      } finally {
        setActionId(null)
        refreshQueue()
      }
    },
    [libraryRoot, refreshQueue, t, cancelMutation],
  )

  const handleRetry = useCallback(
    async (task: IngestTask, resumeFromStage?: string) => {
      if (!libraryRoot) return
      setActionId(task.id)
      try {
        const ok = await retryMutation.mutateAsync({
          libraryRoot,
          runId: task.run_id,
          resumeFromStage,
        })
        if (ok) {
          showToast(t('queue.taskRetried'), 'success')
        } else {
          showToast(t('queue.taskNotRetryable'), 'warning')
        }
      } catch (e) {
        logger.error('[ProcessingQueue] retry failed:', e)
        showToast(t('queue.retryFailed', { error: getUserFacingError(e) }), 'error')
      } finally {
        setActionId(null)
        refreshQueue()
      }
    },
    [libraryRoot, refreshQueue, t, retryMutation],
  )

  const handleRetryAllFailed = useCallback(async () => {
    if (!libraryRoot) return
    const failedTasks = queueTasks.filter((task) => task.status === 'failed')
    if (failedTasks.length === 0) return
    setBulkAction('retry')
    try {
      const result = await retryBatchMutation.mutateAsync({
        libraryRoot,
        runIds: deduplicateRunIds(failedTasks),
      })
      showToast(t('queue.bulkRetryDone', { retried: result.updated, skipped: result.skipped }), result.skipped > 0 ? 'warning' : 'success')
    } catch (error) {
        showToast(t('queue.bulkRetryFailed', { error: getUserFacingError(error) }), 'error')
    } finally {
      setBulkAction(null)
      refreshQueue()
    }
  }, [libraryRoot, refreshQueue, t, queueTasks, retryBatchMutation])

  const runCancelAllPending = useCallback(async () => {
    if (!libraryRoot) return
    setConfirm(null)
    const pendingTasks = queueTasks.filter((task) => task.status === 'pending')
    if (pendingTasks.length === 0) return
    setBulkAction('cancel')
    try {
      const result = await cancelBatchMutation.mutateAsync({
        libraryRoot,
        runIds: deduplicateRunIds(pendingTasks),
      })
      showToast(t('queue.bulkCancelDone', { cancelled: result.updated, failed: result.skipped }), result.skipped > 0 ? 'warning' : 'success')
    } catch (error) {
        showToast(t('queue.bulkCancelFailed', { error: getUserFacingError(error) }), 'error')
    } finally {
      setBulkAction(null)
      refreshQueue()
    }
  }, [libraryRoot, refreshQueue, t, queueTasks, cancelBatchMutation])

  const runCleanup = useCallback(async () => {
    if (!libraryRoot) return
    setConfirm(null)
    try {
      const removed = await cleanupMutation.mutateAsync(libraryRoot)
      showToast(t('queue.cleanedUp', { count: removed }), 'success')
    } catch (e) {
      logger.error('[ProcessingQueue] cleanup failed:', e)
      showToast(t('queue.cleanupFailed', { error: getUserFacingError(e) }), 'error')
    } finally {
      refreshQueue()
    }
  }, [libraryRoot, refreshQueue, t, cleanupMutation])

  const handleSetPriority = useCallback(
    async (task: IngestTask) => {
      if (!libraryRoot) return
      setActionId(task.id)
      try {
        const nextPriority = task.priority > 0 ? 0 : 1
        await priorityMutation.mutateAsync({
          libraryRoot,
          runId: task.run_id,
          priority: nextPriority,
        })
        showToast(nextPriority > 0 ? t('queue.taskPinned') : t('queue.taskUnpinned'), 'success')
      } catch (e) {
        logger.error('[ProcessingQueue] set priority failed:', e)
        showToast(t('queue.pinFailed', { error: getUserFacingError(e) }), 'error')
      } finally {
        setActionId(null)
      }
    },
    [libraryRoot, t, priorityMutation],
  )

  const runDelete = useCallback(
    async (task: IngestTask) => {
      if (!libraryRoot) return
      setConfirm(null)
      setActionId(task.id)
      try {
        const ok = await deleteMutation.mutateAsync({ libraryRoot, runId: task.run_id })
        if (ok) {
          showToast(t('queue.taskDeleted'), 'success')
        } else {
          showToast(t('queue.canOnlyDeleteFinished'), 'warning')
        }
      } catch (e) {
        logger.error('[ProcessingQueue] delete failed:', e)
        showToast(t('queue.deleteFailed', { error: getUserFacingError(e) }), 'error')
      } finally {
        setActionId(null)
        refreshQueue()
      }
    },
    [libraryRoot, refreshQueue, t, deleteMutation],
  )

  const toggleLogs = useCallback(
    (docId: string) => {
      setExpandedLogDocs((prev) => {
        const next = new Set(prev)
        if (next.has(docId)) next.delete(docId)
        else next.add(docId)
        return next
      })
      void fetchLogsForDoc(docId)
    },
    [fetchLogsForDoc],
  )

  // ── Filter + sort ─────────────────────────────────────────────
  const visibleTasks = useMemo(() => {
    let xs = queueTasks
    if (filter !== 'all') xs = xs.filter((t) => t.status === filter)
    if (hideDone && filter === 'all') xs = xs.filter((t) => t.status !== 'done')
    return [...xs].sort((a, b) => {
      const r = STATUS_RANK[a.status] - STATUS_RANK[b.status]
      if (r !== 0) return r
      return b.created_at - a.created_at
    })
  }, [queueTasks, filter, hideDone])

  const counts = useMemo(() => {
    const c: Record<FilterKey, number> = {
      all: queueTasks.length,
      pending: 0,
      processing: 0,
      done: 0,
      failed: 0,
      cancelled: 0,
    }
    for (const t of queueTasks) c[t.status]++
    return c
  }, [queueTasks])

  const avgTotalMs = stats?.avg_stage_durations_ms?.reduce((a: number, b: number) => a + b, 0) ?? 0

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
              <div className="queue-hide-done-toggle">
                <Switch
                  size="sm"
                  checked={hideDone}
                  onChange={setHideDone}
                />
                <span className="queue-hide-done-label">{t('queue.hideDone')}</span>
              </div>
              <Button
                variant="secondary"
                size="sm"
                icon={<TrashIcon size={14} />}
                onClick={() => setConfirm({ type: 'cleanup' })}
                disabled={!stats || stats.done === 0}
              >
                {t('queue.cleanupDone')}
              </Button>
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
          {stats && queueTasks.length > 0 && (
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
          )}
        </header>

        {queueTasks.length > 0 && <>
        {/* ----- Filter chips ----- */}
        <div className="queue-filters" role="group" aria-label="状态筛选">
          {FILTERS.map((f) => {
            const isActive = filter === f.key
            const count = counts[f.key]
            return (
              <Chip
                key={f.key}
                label={f.label}
                count={count}
                active={isActive}
                className={`queue-filter-chip${isActive ? ' is-active' : ''}`}
                onClick={() => setFilter(f.key)}
              />
            )
          })}
        </div>

        </>}

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
        title={confirm === null ? '' : confirm.type === 'cancel-all' ? t('queue.cancelAllPending') : confirm.type === 'cleanup' ? t('queue.cleanupDone') : t('queue.deleteTask')}
        message={confirm === null ? '' : confirm.type === 'cancel-all'
          ? t('queue.cancelAllConfirm', { count: queueTasks.filter((task) => task.status === 'pending').length })
          : confirm.type === 'cleanup' ? t('queue.cleanupConfirm') : t('queue.deleteConfirm')}
        confirmLabel={confirm === null ? '' : confirm.type === 'delete' ? t('queue.deleteTask') : t('common.confirm')}
        loading={bulkAction !== null || actionId !== null}
        onConfirm={() => {
          if (confirm?.type === 'cancel-all') void runCancelAllPending()
          else if (confirm?.type === 'cleanup') void runCleanup()
          else if (confirm?.type === 'delete') void runDelete(confirm.task)
        }}
        onCancel={() => setConfirm(null)}
      />
    </PageContainer>
  )
}

function deduplicateTasksByDocId(tasks: IngestTask[]): IngestTask[] {
  const byDocId = new Map<string, IngestTask>()
  for (const task of tasks) {
    const current = byDocId.get(task.doc_id)
    if (!current || isPreferredTask(task, current)) byDocId.set(task.doc_id, task)
  }
  return [...byDocId.values()]
}

/** Unique run ids across tasks — a run may span multiple stage rows. */
function deduplicateRunIds(tasks: IngestTask[]): string[] {
  return [...new Set(tasks.map((task) => task.run_id).filter((id): id is string => Boolean(id)))]
}

function isPreferredTask(candidate: IngestTask, current: IngestTask): boolean {
  const statusRank = STATUS_RANK[candidate.status] - STATUS_RANK[current.status]
  if (statusRank !== 0) return statusRank < 0
  if (candidate.updated_at !== current.updated_at) return candidate.updated_at > current.updated_at
  return candidate.created_at > current.created_at
}

interface QueueTaskListProps {
  tasks: IngestTask[]
  now: number
  expandedLogDocs: Set<string>
  logMap: Map<string, IngestLogEvent[]>
  actionId: string | null
  onToggleLogs: (docId: string) => void
  onCancel: (task: IngestTask) => void
  onRetry: (task: IngestTask, resumeFromStage?: string) => void
  onDelete: (task: IngestTask) => void
  onTogglePin: (task: IngestTask) => void
}

/** Keep the common queue small and animated; virtualize only genuinely long queues. */
function QueueTaskList({
  tasks,
  now,
  expandedLogDocs,
  logMap,
  actionId,
  onToggleLogs,
  onCancel,
  onRetry,
  onDelete,
  onTogglePin,
}: QueueTaskListProps) {
  const parentRef = useRef<HTMLDivElement>(null)
  const shouldVirtualize = tasks.length > 80
  // TanStack Virtual exposes mutable functions that React Compiler cannot memoize.
  // eslint-disable-next-line react-hooks/incompatible-library
  const virtualizer = useVirtualizer({
    count: shouldVirtualize ? tasks.length : 0,
    getScrollElement: () => parentRef.current,
    estimateSize: () => 116,
    measureElement: (element) => element.getBoundingClientRect().height,
    overscan: 6,
  })

  const renderTask = (task: IngestTask) => (
    <TaskRow
      key={task.id}
      task={task}
      // Terminal rows never display elapsed/ETA — freeze `now` so the 1s
      // tick re-renders only rows that actually show a live clock.
      now={task.status === 'done' || task.status === 'cancelled' ? 0 : now}
      isLogsExpanded={expandedLogDocs.has(task.doc_id)}
      logs={logMap.get(task.doc_id) ?? EMPTY_LOGS}
      isActioning={actionId === task.id}
      onToggleLogs={onToggleLogs}
      onCancel={onCancel}
      onRetry={onRetry}
      onDelete={onDelete}
      onTogglePin={onTogglePin}
    />
  )

  if (!shouldVirtualize) {
    return (
      <div className="queue-list">
        <AnimatePresence initial={false}>
          {tasks.map(renderTask)}
        </AnimatePresence>
      </div>
    )
  }

  return (
    <div ref={parentRef} className="queue-list queue-list-virtual">
      <div
        className="queue-list-virtual-inner"
        style={{ height: `${virtualizer.getTotalSize()}px` }}
      >
        {virtualizer.getVirtualItems().map((virtualItem) => (
          <div
            key={tasks[virtualItem.index].id}
            ref={virtualizer.measureElement}
            data-index={virtualItem.index}
            className="queue-list-virtual-item"
            style={{ transform: `translateY(${virtualItem.start}px)` }}
          >
            {renderTask(tasks[virtualItem.index])}
          </div>
        ))}
      </div>
    </div>
  )
}

/** Format elapsed milliseconds as "1m 23s" / "12s" / "2h 3m". */
function formatElapsed(ms: number): string {
  if (ms < 0 || !Number.isFinite(ms)) return '—'
  const totalSec = Math.floor(ms / 1000)
  if (totalSec < 60) return `${totalSec}s`
  const min = Math.floor(totalSec / 60)
  const sec = totalSec % 60
  if (min < 60) return `${min}m ${sec}s`
  const hr = Math.floor(min / 60)
  const m = min % 60
  return `${hr}h ${m}m`
}
