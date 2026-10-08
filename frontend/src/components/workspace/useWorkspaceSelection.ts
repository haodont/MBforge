/** Workspace document selection — selected ids, toggle, select-all, deselect. */

import { useCallback, useMemo, useState } from 'react'
import type { DocumentInfo } from '@/api/http/library'

export interface UseWorkspaceSelectionResult {
  /** Ids of the currently selected documents. */
  selectedDocumentIds: Set<string>
  /** Documents (in listing order) whose id is selected. */
  selectedDocuments: DocumentInfo[]
  /** True when every listed document is selected. */
  allDocumentsSelected: boolean
  handleToggleSelect: (doc: DocumentInfo, selected: boolean) => void
  /** Select every listed document, or clear the selection when all are selected. */
  toggleSelectAll: () => void
  /** Drop ids from the selection (no-op for ids that are not selected). */
  removeFromSelection: (docIds: Iterable<string>) => void
}

export function useWorkspaceSelection(documents: DocumentInfo[]): UseWorkspaceSelectionResult {
  const [selectedDocumentIds, setSelectedDocumentIds] = useState<Set<string>>(() => new Set())

  const selectedDocuments = useMemo(
    () => documents.filter((doc) => selectedDocumentIds.has(doc.doc_id)),
    [documents, selectedDocumentIds],
  )
  const allDocumentsSelected = documents.length > 0 && selectedDocuments.length === documents.length

  const handleToggleSelect = useCallback((doc: DocumentInfo, selected: boolean) => {
    setSelectedDocumentIds((current) => {
      const next = new Set(current)
      if (selected) next.add(doc.doc_id)
      else next.delete(doc.doc_id)
      return next
    })
  }, [])

  const toggleSelectAll = useCallback(() => {
    setSelectedDocumentIds((current) => {
      const allSelected =
        documents.length > 0 && documents.every((doc) => current.has(doc.doc_id))
      return allSelected ? new Set() : new Set(documents.map((doc) => doc.doc_id))
    })
  }, [documents])

  const removeFromSelection = useCallback((docIds: Iterable<string>) => {
    setSelectedDocumentIds((current) => {
      let changed = false
      const next = new Set(current)
      for (const id of docIds) {
        if (next.delete(id)) changed = true
      }
      return changed ? next : current
    })
  }, [])

  return {
    selectedDocumentIds,
    selectedDocuments,
    allDocumentsSelected,
    handleToggleSelect,
    toggleSelectAll,
    removeFromSelection,
  }
}
