/** React Query hooks for the ingest queue (pipeline tasks). */

import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import {
  ingestList,
  ingestStats,
  ingestWorkerStatus,
  ingestCancel,
  ingestCancelBatch,
  ingestCleanup,
  ingestDeleteTask,
  ingestEnqueue,
  ingestGetLogs,
  ingestRetry,
  ingestRetryBatch,
  ingestSetPriority,
} from '../../http/ingest_queue'
import type { IngestTask } from '../../http/ingest_queue'
import { queryKeys } from '../keys'

/**
 * Polling-based queue task list.
 *
 * Refetches every 10 s to keep the ProcessingQueue in sync with the
 * backend — replaces the previous `useEffect` + `setInterval` pattern.
 */
export function useIngestQueue(libraryRoot: string) {
  return useQuery({
    queryKey: queryKeys.ingest.queue(libraryRoot),
    queryFn: () => ingestList(libraryRoot),
    // Keep the queue page resilient to stale caches or older backend payloads.
    select: (tasks) => (Array.isArray(tasks) ? tasks : []),
    refetchInterval: (query) => {
      const tasks = query.state.data
      return tasks?.some((task) => task.status === 'pending' || task.status === 'processing')
        ? 10_000
        : false
    },
  })
}

/** Queue statistics (total / pending / processing / done / failed / …). */
export function useIngestStats(libraryRoot: string) {
  return useQuery({
    queryKey: queryKeys.ingest.stats(libraryRoot),
    queryFn: () => ingestStats(libraryRoot),
    refetchInterval: 10_000,
  })
}

/** Background worker status (alive / offline). */
export function useWorkerStatus() {
  return useQuery({
    queryKey: queryKeys.ingest.workerStatus(),
    queryFn: ingestWorkerStatus,
    refetchInterval: 30_000,
  })
}

// ── Mutations ────────────────────────────────────────────────────────

/** Cancel a running / pending pipeline task. */
export function useCancelTask() {
  const qc = useQueryClient()

  return useMutation({
    mutationFn: ({
      libraryRoot,
      runId,
    }: {
      libraryRoot: string
      runId: string
    }) => ingestCancel(libraryRoot, runId),
    onSuccess: () => {
      void qc.invalidateQueries({ queryKey: queryKeys.ingest.all })
    },
  })
}

/** Retry a failed pipeline task, optionally resuming from a specific stage. */
export function useRetryTask() {
  const qc = useQueryClient()

  return useMutation({
    mutationFn: ({
      libraryRoot,
      runId,
      resumeFromStage,
    }: {
      libraryRoot: string
      runId: string
      resumeFromStage?: string
    }) => ingestRetry(libraryRoot, runId, resumeFromStage),
    onSuccess: () => {
      void qc.invalidateQueries({ queryKey: queryKeys.ingest.all })
    },
  })
}

/** Delete a pipeline task record. */
export function useDeleteTask() {
  const qc = useQueryClient()

  return useMutation({
    mutationFn: ({
      libraryRoot,
      runId,
    }: {
      libraryRoot: string
      runId: string
    }) => ingestDeleteTask(libraryRoot, runId),
    onSuccess: () => {
      void qc.invalidateQueries({ queryKey: queryKeys.ingest.all })
    },
  })
}

/** Enqueue a document into the ingest queue. */
export function useEnqueueTask() {
  const qc = useQueryClient()

  return useMutation({
    mutationFn: ({
      libraryRoot,
      filePath,
      docId,
      force,
    }: {
      libraryRoot: string
      filePath: string
      docId: string
      force?: boolean
    }) => ingestEnqueue(libraryRoot, filePath, docId, force),
    onSuccess: () => {
      void qc.invalidateQueries({ queryKey: queryKeys.ingest.all })
    },
  })
}

/** Batch-cancel multiple pending / running tasks. */
export function useCancelBatch() {
  const qc = useQueryClient()

  return useMutation({
    mutationFn: ({
      libraryRoot,
      runIds,
    }: {
      libraryRoot: string
      runIds: string[]
    }) => ingestCancelBatch(libraryRoot, runIds),
    onSuccess: () => {
      void qc.invalidateQueries({ queryKey: queryKeys.ingest.all })
    },
  })
}

/** Batch-retry multiple failed tasks. */
export function useRetryBatch() {
  const qc = useQueryClient()

  return useMutation({
    mutationFn: ({
      libraryRoot,
      runIds,
    }: {
      libraryRoot: string
      runIds: string[]
    }) => ingestRetryBatch(libraryRoot, runIds),
    onSuccess: () => {
      void qc.invalidateQueries({ queryKey: queryKeys.ingest.all })
    },
  })
}

/** Clean up finished tasks and free disk space. */
export function useCleanupTasks() {
  const qc = useQueryClient()

  return useMutation({
    mutationFn: (libraryRoot: string) => ingestCleanup(libraryRoot),
    onSuccess: () => {
      void qc.invalidateQueries({ queryKey: queryKeys.ingest.all })
    },
  })
}

/** Toggle a task's priority (pin / unpin). */
export function useSetTaskPriority() {
  const qc = useQueryClient()

  return useMutation({
    mutationFn: ({
      libraryRoot,
      runId,
      priority,
    }: {
      libraryRoot: string
      runId: string
      priority: number
    }) => ingestSetPriority(libraryRoot, runId, priority),
    onSuccess: () => {
      void qc.invalidateQueries({ queryKey: queryKeys.ingest.all })
    },
  })
}

/** The ingest log records for one document. */
export function useIngestLogs(libraryRoot: string, docId: string | null) {
  return useQuery({
    queryKey: queryKeys.ingest.logs(libraryRoot, docId ?? ''),
    queryFn: () => ingestGetLogs(libraryRoot, docId as string, 200),
    enabled: Boolean(libraryRoot) && Boolean(docId),
    select: (records) => (Array.isArray(records) ? records : []),
  })
}

/** Helper: find a task by id inside the cached queue list. */
export function getCachedTask(
  qc: ReturnType<typeof useQueryClient>,
  libraryRoot: string,
  taskId: string,
): IngestTask | undefined {
  const tasks = qc.getQueryData<IngestTask[]>(queryKeys.ingest.queue(libraryRoot))
  return tasks?.find((task) => task.id === taskId)
}
