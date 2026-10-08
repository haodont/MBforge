/** Queue filtering — status filter, hide-done toggle, visible tasks, counts. */

import { useMemo, useState, type Dispatch, type SetStateAction } from 'react'
import type { IngestTask } from '@/api/http/ingest_queue'
import { STATUS_RANK, type FilterKey } from './queueUtils'

export interface UseQueueFiltersResult {
  filter: FilterKey
  setFilter: Dispatch<SetStateAction<FilterKey>>
  hideDone: boolean
  setHideDone: Dispatch<SetStateAction<boolean>>
  /** Filtered + ranked tasks currently rendered. */
  visibleTasks: IngestTask[]
  /** Task count per filter chip. */
  counts: Record<FilterKey, number>
}

export function useQueueFilters(queueTasks: IngestTask[]): UseQueueFiltersResult {
  const [filter, setFilter] = useState<FilterKey>('all')
  const [hideDone, setHideDone] = useState(true)

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

  return { filter, setFilter, hideDone, setHideDone, visibleTasks, counts }
}
