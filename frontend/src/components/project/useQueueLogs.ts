/** Queue log state — expanded docs, per-doc merge map, and log sources. */

import { createElement, useCallback, useEffect, useState, type ReactNode } from 'react'
import { useIngestLogs } from '@/api/query/hooks'
import type { IngestLogEvent, IngestTask } from '@/api/http/ingest_queue'

const LOGS_PER_DOC_CAP = 200
const MAX_LOG_DOCS = 50

export interface UseQueueLogsResult {
  /** Merged, sorted, capped log records per document. */
  logMap: Map<string, IngestLogEvent[]>
  /** Documents whose log panel is currently expanded. */
  expandedLogDocs: Set<string>
  /** Toggle a document's log panel. */
  toggleLogs: (docId: string) => void
  /** One headless bridge per expanded document, feeding the merge map. */
  logSources: ReactNode
}

export interface UseQueueLogsArgs {
  libraryRoot: string
  tasks: IngestTask[]
}

/**
 * Owns the queue log map. The records themselves come from the
 * `useIngestLogs` query hook (one `IngestLogsBridge` per expanded document,
 * returned here as `logSources`). The merge keeps the historical
 * append/dedupe/cap semantics: repeated fetches for one doc accumulate, then
 * sort and cap at LOGS_PER_DOC_CAP.
 */
export function useQueueLogs({ libraryRoot, tasks }: UseQueueLogsArgs): UseQueueLogsResult {
  const [logMap, setLogMap] = useState<Map<string, IngestLogEvent[]>>(new Map())
  const [expandedLogDocs, setExpandedLogDocs] = useState<Set<string>>(new Set())

  const mergeLogsForDoc = useCallback(
    (docId: string, records: IngestLogEvent[]) => {
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
    },
    [],
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

  const toggleLogs = useCallback((docId: string) => {
    setExpandedLogDocs((prev) => {
      const next = new Set(prev)
      if (next.has(docId)) next.delete(docId)
      else next.add(docId)
      return next
    })
  }, [])

  const logSources: ReactNode = [...expandedLogDocs].map((docId) =>
    createElement(IngestLogsBridge, {
      key: docId,
      libraryRoot,
      docId,
      onRecords: mergeLogsForDoc,
    }),
  )

  return { logMap, expandedLogDocs, toggleLogs, logSources }
}

/**
 * Headless bridge that fetches one expanded document's logs through the
 * `useIngestLogs` query hook and streams them into the parent's merge map.
 * Mounting it is equivalent to the old on-demand fetch; unmounting (collapse)
 * simply stops observing.
 */
function IngestLogsBridge({
  libraryRoot,
  docId,
  onRecords,
}: {
  libraryRoot: string
  docId: string
  onRecords: (docId: string, records: IngestLogEvent[]) => void
}) {
  const { data } = useIngestLogs(libraryRoot, docId)

  useEffect(() => {
    if (data) onRecords(docId, data)
  }, [data, docId, onRecords])

  return null
}
