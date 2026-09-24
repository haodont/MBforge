/** Bridge between the inline SSE subscription and React Query cache.
 *
 *  On mount, subscribes to pipeline SSE events for a given task and
 *  writes stage changes into the React Query cache so polling consumers see
 *  the current pipeline stage without waiting for the next refetch interval.
 *
 *  This is layered ON TOP of the existing polling (useIngestQueue).
 *  It does NOT replace it — it only shortens the feedback loop for
 *  in-progress tasks.
 */

import { useEffect, useRef } from 'react'
import { useQueryClient } from '@tanstack/react-query'
import { subscribeIngestEvents } from '../http/ingest_queue'
import { queryKeys } from './keys'
import type { IngestTask } from '../http/ingest_queue'

const PIPELINE_STAGES = new Set([
  'extract',
  'join',
  'markdown',
  'patent',
])

interface UseIngestSSEOptions {
  libraryRoot: string
  runId: string | null
  /** If true, do not subscribe (e.g. no run is active). */
  disabled?: boolean
}

/**
 * Subscribe to SSE events for a single pipeline run and merge
 * stage updates into the React Query cache.
 *
 * Usage (inside ProcessingQueue or similar):
 *   useIngestSSE({ libraryRoot, runId: activeRunId })
 */
export function useIngestSSE({
  libraryRoot,
  runId,
  disabled,
}: UseIngestSSEOptions): void {
  const qc = useQueryClient()
  const cleanupRef = useRef<(() => void) | null>(null)

  useEffect(() => {
    if (disabled || !runId) return

    // Clean up previous subscription before creating a new one.
    cleanupRef.current?.()
    cleanupRef.current = null

    const sub = subscribeIngestEvents(libraryRoot, runId, {
      onEvent: (event) => {
        // Optimistically update the matching task in the cached queue.
        // The next 10-second refetch will correct anything we miss.
        const ev = event as unknown as Record<string, unknown>
        qc.setQueryData<IngestTask[]>(
          queryKeys.ingest.queue(libraryRoot),
          (prev) => {
            if (!Array.isArray(prev)) return []
            const eventTimestamp = typeof ev.ts_ms === 'number' ? ev.ts_ms : null
            const stage = typeof ev.stage === 'string' ? ev.stage : ''
            const stageStatus =
              ev.event === 'start'
                ? 'running'
                : ev.event === 'success'
                  ? 'success'
                  : ev.event === 'error'
                    ? 'error'
                    : null

            return prev.map((t) => {
              if (t.run_id !== runId) return t
              if (eventTimestamp !== null && eventTimestamp < t.updated_at * 1000) {
                return t
              }

              return {
                ...t,
                stage: 'stage' in ev ? (ev.stage as string) : t.stage,
                stage_statuses:
                  stageStatus !== null && PIPELINE_STAGES.has(stage)
                    ? { ...t.stage_statuses, [stage]: stageStatus }
                    : t.stage_statuses,
                updated_at:
                  eventTimestamp !== null
                    ? Math.floor(eventTimestamp / 1000)
                    : t.updated_at,
              }
            })
          },
        )
      },
      onError: () => {
        // SSE error — the browser EventSource will auto-reconnect.
        // We do not need to do anything; the polling fallback covers us.
      },
    })

    cleanupRef.current = sub.close

    return () => {
      sub.close()
      cleanupRef.current = null
    }
  }, [libraryRoot, runId, disabled, qc])
}
