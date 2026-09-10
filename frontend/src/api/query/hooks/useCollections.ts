/** React Query hooks for collection / group management. */

import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import {
  addDocumentToCollection,
  createCollection,
  deleteCollection,
  listCollections,
  removeDocumentFromCollection,
  renameCollection,
} from '../../http/library'
import { queryKeys } from '../keys'

/** List all collections in the current library. */
export function useCollections() {
  return useQuery({
    queryKey: queryKeys.collections.list(),
    queryFn: () => listCollections(),
    staleTime: 30_000,
  })
}

/** Create a collection (optionally nested under a parent). */
export function useCreateCollection() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: ({ name, parentId }: { name: string; parentId?: string }) =>
      createCollection(name, parentId),
    onSuccess: () => {
      void qc.invalidateQueries({ queryKey: queryKeys.collections.list() })
    },
  })
}

/** Rename a collection. */
export function useRenameCollection() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: ({ collectionId, name }: { collectionId: string; name: string }) =>
      renameCollection(collectionId, name),
    onSuccess: () => {
      void qc.invalidateQueries({ queryKey: queryKeys.collections.list() })
    },
  })
}

/** Delete a collection (and its descendants). */
export function useDeleteCollection() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: (collectionId: string) => deleteCollection(collectionId),
    onSuccess: () => {
      void qc.invalidateQueries({ queryKey: queryKeys.collections.list() })
      void qc.invalidateQueries({ queryKey: queryKeys.documents.all })
    },
  })
}

/** Move a document between collections.
 *
 * ``fromCollectionId`` is optional: when the document is at the library
 * root (no group), only ``toCollectionId`` is consulted. Passing
 * ``null`` for ``toCollectionId`` clears the document's group.
 */
export function useMoveDocument() {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: async ({
      docId,
      fromCollectionId,
      toCollectionId,
    }: {
      docId: string
      fromCollectionId?: string | null
      toCollectionId: string | null
    }) => {
      if (fromCollectionId && fromCollectionId !== toCollectionId) {
        await removeDocumentFromCollection(fromCollectionId, docId)
      }
      if (toCollectionId) {
        await addDocumentToCollection(toCollectionId, docId)
      }
    },
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: queryKeys.documents.all })
      void queryClient.invalidateQueries({ queryKey: queryKeys.collections.list() })
    },
  })
}
