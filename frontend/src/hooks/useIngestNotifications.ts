import { useEffect, useRef } from 'react'
import { useLocation } from 'react-router-dom'
import {
  ingestList,
  isSelfTriggeredDoc,
  removeSelfTriggeredDoc,
  type IngestTask,
} from '../api/http/ingest_queue'
import { toast } from '../components/ui/Toast'
import { queryClient } from '../api/query/client'
import { queryKeys } from '../api/query/keys'
import { usePolling } from './usePolling'

export function useIngestNotifications(libraryRoot: string): void {
  const location = useLocation()
  const libraryRootRef = useRef(libraryRoot)
  const lastStatusRef = useRef<Record<string, IngestTask['status']>>({})
  const locationPathRef = useRef(location.pathname)

  useEffect(() => {
    libraryRootRef.current = libraryRoot
  }, [libraryRoot])

  useEffect(() => {
    locationPathRef.current = location.pathname
  }, [location.pathname])

  useEffect(() => {
    lastStatusRef.current = {}
  }, [libraryRoot])

  usePolling<IngestTask[]>({
    intervalMs: 5000,
    fetcher: () => {
      const root = libraryRootRef.current
      if (!root) return Promise.resolve([])
      return ingestList(root)
    },
    onResult: tasks => {
      const currentMap: Record<string, IngestTask['status']> = {}
      for (const task of tasks) {
        currentMap[task.id] = task.status
      }
      const prevMap = lastStatusRef.current
      if (Object.keys(prevMap).length === 0) {
        lastStatusRef.current = currentMap
        return
      }
      const root = libraryRootRef.current
      const pathname = locationPathRef.current
      for (const task of tasks) {
        const becameDone = task.status === 'done' && prevMap[task.id] !== 'done'
        const becameFailed = task.status === 'failed' && prevMap[task.id] !== 'failed'
        if (becameDone || becameFailed) {
          // Pipeline outcomes change both the document list and molecule library.
          if (root) {
            void queryClient.invalidateQueries({ queryKey: queryKeys.documents.all })
            void queryClient.invalidateQueries({ queryKey: queryKeys.molecules.list(root) })
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
    },
    onError: e => {
      if (import.meta.env.DEV) console.error('[useIngestNotifications] poll failed:', e)
    },
  })
}