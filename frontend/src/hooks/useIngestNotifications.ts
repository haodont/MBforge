import { useEffect, useRef } from 'react'
import { useLocation } from 'react-router-dom'
import {
  isSelfTriggeredDoc,
  removeSelfTriggeredDoc,
  type IngestTask,
} from '../api/http/ingest_queue'
import { toast } from '../components/ui/Toast'
import { queryClient } from '../api/query/client'
import { queryKeys } from '../api/query/keys'
import { useIngestQueue } from '../api/query/hooks/useIngestQueue'

/**
 * Toast pipeline outcomes app-wide.
 *
 * Subscribes to the shared `useIngestQueue` query — the single `ingestList`
 * client — instead of polling the endpoint a second time, and mirrors the
 * status transitions (done/failed) into toasts and cache invalidations.
 */
export function useIngestNotifications(libraryRoot: string): void {
  const location = useLocation()
  const { data: tasks } = useIngestQueue(libraryRoot)
  const lastStatusRef = useRef<Record<string, IngestTask['status']>>({})
  const locationPathRef = useRef(location.pathname)

  useEffect(() => {
    locationPathRef.current = location.pathname
  }, [location.pathname])

  useEffect(() => {
    lastStatusRef.current = {}
  }, [libraryRoot])

  useEffect(() => {
    if (!tasks) return
    const currentMap: Record<string, IngestTask['status']> = {}
    for (const task of tasks) {
      currentMap[task.id] = task.status
    }
    const prevMap = lastStatusRef.current
    if (Object.keys(prevMap).length === 0) {
      lastStatusRef.current = currentMap
      return
    }
    const pathname = locationPathRef.current
    for (const task of tasks) {
      const becameDone = task.status === 'done' && prevMap[task.id] !== 'done'
      const becameFailed = task.status === 'failed' && prevMap[task.id] !== 'failed'
      if (becameDone || becameFailed) {
        // Pipeline outcomes change both the document list and molecule library.
        void queryClient.invalidateQueries({ queryKey: queryKeys.documents.all })
        if (libraryRoot) {
          void queryClient.invalidateQueries({
            queryKey: queryKeys.molecules.list(libraryRoot),
          })
        }
      }
      if (becameDone) {
        if (isSelfTriggeredDoc(task.doc_id)) {
          removeSelfTriggeredDoc(task.doc_id)
        } else if (pathname !== '/queue') {
          toast.success(`文档处理完成：${task.doc_id}`, { duration: 4000 })
        }
      }
      if (becameFailed) {
        if (isSelfTriggeredDoc(task.doc_id)) {
          removeSelfTriggeredDoc(task.doc_id)
        } else if (pathname !== '/queue') {
          toast.error(`文档处理失败：${task.doc_id}`, { duration: 4000 })
        }
      }
    }
    lastStatusRef.current = currentMap
  }, [tasks, libraryRoot])
}
