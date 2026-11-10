/** Workspace document deletion and its confirmation state. */

import { useCallback, useState } from 'react'
import { useTranslation } from 'react-i18next'
import { useDeleteDocuments } from '@/api/query/hooks'
import { showToast } from '@/hooks/useToast'
import { getUserFacingError } from '@/utils/errors'
import type { DocumentInfo } from '@/api/http/library'

export type DocConfirmAction =
  | { doc: DocumentInfo; action: 'delete' }
  | { docs: DocumentInfo[]; action: 'delete-selected' }

export interface UseWorkspaceMutationsArgs {
  /** Drop ids from the workspace selection once their documents are gone. */
  removeFromSelection: (docIds: Iterable<string>) => void
}

export interface UseWorkspaceMutationsResult {
  deletePending: boolean
  pendingConfirm: DocConfirmAction | null
  /** Queue the delete confirmation for a single document. */
  requestDelete: (doc: DocumentInfo) => void
  /** Queue the delete confirmation for the current selection. */
  requestDeleteSelected: (docs: DocumentInfo[]) => void
  /** Dismiss the confirmation dialog. */
  cancelConfirm: () => void
  confirmDocAction: (target: DocConfirmAction) => Promise<void>
  confirmDialogTitle: string
  confirmDialogMessage: string
  confirmDialogLabel: string
}

export function useWorkspaceMutations({
  removeFromSelection,
}: UseWorkspaceMutationsArgs): UseWorkspaceMutationsResult {
  const { t } = useTranslation()
  const deleteMutation = useDeleteDocuments()
  const [pendingConfirm, setPendingConfirm] = useState<DocConfirmAction | null>(null)

  const handleDeleteDocument = useCallback(async (doc: DocumentInfo) => {
    try {
      await deleteMutation.mutateAsync([doc.doc_id])
      removeFromSelection([doc.doc_id])
      showToast(t('doc.deleteSuccess', { filename: doc.file_name }), 'success')
    } catch (e) {
      showToast(t('doc.deleteError', { error: getUserFacingError(e, t('common.unknownError')) }), 'error')
    }
  }, [deleteMutation, removeFromSelection, t])

  const handleDeleteSelected = useCallback(async (docs: DocumentInfo[]) => {
    const docIds = docs.map((doc) => doc.doc_id)
    try {
      await deleteMutation.mutateAsync(docIds)
      removeFromSelection(docIds)
      showToast(t('workspace.bulkDeleteSuccess', { count: docIds.length }), 'success')
    } catch (e) {
      showToast(t('workspace.bulkDeleteError', { error: getUserFacingError(e, t('common.unknownError')) }), 'error')
    }
  }, [deleteMutation, removeFromSelection, t])

  const requestDelete = useCallback((doc: DocumentInfo) => {
    setPendingConfirm({ doc, action: 'delete' })
  }, [])

  const requestDeleteSelected = useCallback((docs: DocumentInfo[]) => {
    setPendingConfirm({ docs, action: 'delete-selected' })
  }, [])

  const cancelConfirm = useCallback(() => {
    setPendingConfirm(null)
  }, [])

  const confirmDocAction = useCallback(async (target: DocConfirmAction) => {
    setPendingConfirm(null)
    if (target.action === 'delete-selected') await handleDeleteSelected(target.docs)
    else await handleDeleteDocument(target.doc)
  }, [handleDeleteDocument, handleDeleteSelected])

  const confirmDialogTitle = pendingConfirm === null ? '' : t('doc.delete')
  const confirmDialogMessage = pendingConfirm === null ? '' : pendingConfirm.action === 'delete-selected'
    ? t('workspace.bulkDeleteConfirm', { count: pendingConfirm.docs.length })
    : t('doc.deleteConfirm', { filename: pendingConfirm.doc.file_name })
  const confirmDialogLabel = pendingConfirm?.action === 'delete-selected'
    ? t('workspace.deleteSelected', { count: pendingConfirm.docs.length })
    : confirmDialogTitle

  return {
    deletePending: deleteMutation.isPending,
    pendingConfirm,
    requestDelete,
    requestDeleteSelected,
    cancelConfirm,
    confirmDocAction,
    confirmDialogTitle,
    confirmDialogMessage,
    confirmDialogLabel,
  }
}
