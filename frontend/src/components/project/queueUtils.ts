/** Shared helpers for the processing-queue module. */

import type { IngestTask } from '@/api/http/ingest_queue'

export type StatusKey = IngestTask['status']
export type FilterKey = 'all' | StatusKey

// Sort priority: actionable first (processing > pending > failed),
// then non-actionable (cancelled > done).
export const STATUS_RANK: Record<StatusKey, number> = {
  processing: 0,
  pending: 1,
  failed: 2,
  cancelled: 3,
  done: 4,
}

export function deduplicateTasksByDocId(tasks: IngestTask[]): IngestTask[] {
  const byDocId = new Map<string, IngestTask>()
  for (const task of tasks) {
    const current = byDocId.get(task.doc_id)
    if (!current || isPreferredTask(task, current)) byDocId.set(task.doc_id, task)
  }
  return [...byDocId.values()]
}

/** Unique run ids across tasks — a run may span multiple stage rows. */
export function deduplicateRunIds(tasks: IngestTask[]): string[] {
  return [...new Set(tasks.map((task) => task.run_id).filter((id): id is string => Boolean(id)))]
}

export function isPreferredTask(candidate: IngestTask, current: IngestTask): boolean {
  const statusRank = STATUS_RANK[candidate.status] - STATUS_RANK[current.status]
  if (statusRank !== 0) return statusRank < 0
  if (candidate.updated_at !== current.updated_at) return candidate.updated_at > current.updated_at
  return candidate.created_at > current.created_at
}

/** Format elapsed milliseconds as "1m 23s" / "12s" / "2h 3m". */
export function formatElapsed(ms: number): string {
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
