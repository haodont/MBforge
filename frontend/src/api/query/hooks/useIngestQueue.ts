/** React Query hooks for the ingest queue (pipeline tasks). */

import { useQuery, useQueryClient } from '@tanstack/react-query'
import {
  ingestList,
  ingestStats,
  ingestWorkerStatus,
  ingestGetLogs,
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
