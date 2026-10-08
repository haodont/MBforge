/** Queue actions — cancel/retry/delete/batch/priority handlers + confirm state. */

import { useCallback, useState } from 'react'
import { useTranslation } from 'react-i18next'
import { getUserFacingError } from '@/utils/errors'
import { logger } from '@/utils/logger'
import { showToast } from '@/hooks/useToast'
import {
  useCancelTask,
  useRetryTask,
  useDeleteTask,
  useCancelBatch,
  useRetryBatch,
  useSetTaskPriority,
} from '@/api/query/hooks'
import type { IngestTask } from '@/api/http/ingest_queue'
import { deduplicateRunIds } from './queueUtils'

export type QueueConfirm =
  | { type: 'cancel-all' }
  | { type: 'delete'; task: IngestTask }
  | null

export interface UseQueueActionsArgs {
  libraryRoot: string
  queueTasks: IngestTask[]
  refetchQueue: () => unknown
  refetchStats: () => unknown
}

export interface UseQueueActionsResult {
  /** Task id with an in-flight per-task action (buttons show a spinner). */
  actionId: string | null
  /** Bulk action currently in flight, if any. */
  bulkAction: 'retry' | 'cancel' | null
  confirm: QueueConfirm
  setConfirm: (next: QueueConfirm) => void
  refreshQueue: () => void
  handleCancel: (task: IngestTask) => Promise<void>
  handleRetry: (task: IngestTask, resumeFromStage?: string) => Promise<void>
  handleRetryAllFailed: () => Promise<void>
  runCancelAllPending: () => Promise<void>
  handleSetPriority: (task: IngestTask) => Promise<void>
  runDelete: (task: IngestTask) => Promise<void>
}

export function useQueueActions({
  libraryRoot,
  queueTasks,
  refetchQueue,
  refetchStats,
}: UseQueueActionsArgs): UseQueueActionsResult {
  const { t } = useTranslation()

  const [actionId, setActionId] = useState<string | null>(null)
  const [bulkAction, setBulkAction] = useState<'retry' | 'cancel' | null>(null)
  const [confirm, setConfirm] = useState<QueueConfirm>(null)

  const cancelMutation = useCancelTask()
  const retryMutation = useRetryTask()
  const deleteMutation = useDeleteTask()
  const cancelBatchMutation = useCancelBatch()
  const retryBatchMutation = useRetryBatch()
  const priorityMutation = useSetTaskPriority()

  const refreshQueue = useCallback(() => {
    void refetchQueue()
    void refetchStats()
  }, [refetchQueue, refetchStats])

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

  return {
    actionId,
    bulkAction,
    confirm,
    setConfirm,
    refreshQueue,
    handleCancel,
    handleRetry,
    handleRetryAllFailed,
    runCancelAllPending,
    handleSetPriority,
    runDelete,
  }
}
