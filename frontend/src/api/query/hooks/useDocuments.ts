/** React Query hooks for document CRUD. */

import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import { listDocuments, importDocument, deleteDocuments } from '../../http/library'
import type { DocumentInfo } from '../../http/library'
import { queryKeys } from '../keys'

/**
 * List documents, optionally filtered by collection.
 *
 * The document list changes when the user imports / deletes / refreshes,
 * so we keep the default staleTime.
 */
export function useDocuments(collectionId?: string) {
  return useQuery({
    queryKey: queryKeys.documents.list(collectionId),
    queryFn: () => listDocuments(collectionId),
  })
}

/**
 * Upload a PDF and enqueue it for pipeline processing.
 *
 * Intentionally does not invalidate the document list: a batch import calls
 * this once per file, and refetching the whole list after every file dominates
 * upload time. Batch callers invalidate the same keys once the batch settles.
 */
export function useImportDocument() {
  return useMutation({
    mutationFn: ({ file, title, onProgress }: { file: File; title?: string; onProgress?: (percent: number) => void }) =>
      importDocument(file, title, onProgress),
  })
}

/** Delete one or more documents and their pipeline tasks in a single request. */
export function useDeleteDocuments() {
  const qc = useQueryClient()

  return useMutation({
    mutationFn: (docIds: string[]) => deleteDocuments(docIds),
    onMutate: async (docIds) => {
      await qc.cancelQueries({ queryKey: queryKeys.documents.all })

      const previous = qc.getQueriesData<{ documents: DocumentInfo[] }>({
        queryKey: queryKeys.documents.all,
      })

      const removed = new Set(docIds)
      qc.setQueriesData<{ documents: DocumentInfo[] }>(
        { queryKey: queryKeys.documents.all },
        (current) => {
          if (!current) return current
          return {
            ...current,
            documents: current.documents.filter((document) => !removed.has(document.doc_id)),
          }
        },
      )

      return { previous }
    },
    onError: (_error, _docIds, context) => {
      context?.previous.forEach(([queryKey, data]) => {
        qc.setQueryData(queryKey, data)
      })
    },
    onSettled: () => {
      void qc.invalidateQueries({ queryKey: queryKeys.documents.all })
      // The document's molecules may sit in the review center queue; drop
      // those cached rows so an open review center does not show stale items.
      void qc.invalidateQueries({ queryKey: queryKeys.review.all })
    },
  })
}
