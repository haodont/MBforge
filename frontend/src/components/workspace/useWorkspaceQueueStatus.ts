/** Workspace queue overlay — processing count and per-document status derivation. */

import { useCallback, useMemo } from 'react'
import { useIngestQueue } from '@/api/query/hooks'
import type { IngestTask } from '@/api/http/ingest_queue'
import type { DocumentInfo } from '@/api/http/library'
import { deduplicateTasksByDocId } from '@/components/project/queueUtils'

/** Status + progress shown by a document's badge. */
export interface WorkspaceDocStatus {
  status: string
  progress: number | null
}

export interface UseWorkspaceQueueStatusResult {
  /** Distinct documents with a pending or processing queue row. */
  processingCount: number
  /** Most relevant queue row per document. */
  queueByDoc: Map<string, IngestTask>
  /** Resolve a document's display status (queue overlay + progress). */
  getDocStatus: (doc: DocumentInfo) => WorkspaceDocStatus
}

/** Keep the most relevant queue row per document for status overlay. */
function buildQueueByDoc(tasks: IngestTask[]): Map<string, IngestTask> {
  const byDoc = new Map<string, IngestTask>()
  for (const task of deduplicateTasksByDocId(tasks)) {
    if (!task.doc_id) continue
    byDoc.set(task.doc_id, task)
  }
  return byDoc
}

/** Percent of a run's stages that finished successfully (null when unknown). */
function queueProgress(task: IngestTask | undefined): number | null {
  if (!task) return null
  const statuses = Object.values(task.stage_statuses)
  if (statuses.length === 0) return null
  const done = statuses.filter((status) => status === 'success').length
  return Math.round((done / statuses.length) * 100)
}

export function useWorkspaceQueueStatus(libraryRoot: string): UseWorkspaceQueueStatusResult {
  const { data: queueTasks = [] } = useIngestQueue(libraryRoot)

  // Documents under processing are deliberately absent from the listing, so
  // the queue is what tells the user their import is being worked on. The queue
  // holds one row per stage per run, so count distinct documents (a retry can
  // leave more than one row of a run active at once).
  const processingCount = useMemo(() => {
    const docIds = new Set<string>()
    for (const task of queueTasks) {
      if (task.doc_id && (task.status === 'pending' || task.status === 'processing')) {
        docIds.add(task.doc_id)
      }
    }
    return docIds.size
  }, [queueTasks])

  const queueByDoc = useMemo(() => buildQueueByDoc(queueTasks), [queueTasks])

  const getDocStatus = useCallback((doc: DocumentInfo): WorkspaceDocStatus => {
    const task = queueByDoc.get(doc.doc_id)
    // A live queue row ("pending"/"processing") reflects the run in progress;
    // otherwise fall back to the document's resting status.
    const status =
      task && (task.status === 'processing' || task.status === 'pending')
        ? task.status
        : doc.status === 'indexing'
          ? 'pending'
          : doc.status
    const progress = task && task.status === 'processing' ? queueProgress(task) : null
    return { status, progress }
  }, [queueByDoc])

  return { processingCount, queueByDoc, getDocStatus }
}
