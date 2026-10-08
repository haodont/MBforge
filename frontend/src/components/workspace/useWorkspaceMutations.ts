/** Workspace mutations — delete / bulk-enqueue / patent handlers + confirm state. */

import { useCallback, useRef, useState } from 'react'
import { useTranslation } from 'react-i18next'
import { useDeleteDocuments, useEnqueueTask, usePatentAnalysis } from '@/api/query/hooks'
import { showToast } from '@/hooks/useToast'
import { getUserFacingError } from '@/utils/errors'
import type { DocumentInfo } from '@/api/http/library'

export type DocConfirmAction =
  | { doc: DocumentInfo; action: 'delete' }
  | { docs: DocumentInfo[]; action: 'delete-selected' }

export interface UseWorkspaceMutationsArgs {
  libraryRoot: string
  /** Drop ids from the workspace selection once their documents are gone/queued. */
  removeFromSelection: (docIds: Iterable<string>) => void
}

export interface UseWorkspaceMutationsResult {
  deletePending: boolean
  patentPending: boolean
  isEnqueueingSelected: boolean
  pendingConfirm: DocConfirmAction | null
  /** Queue the delete confirmation for a single document. */
  requestDelete: (doc: DocumentInfo) => void
  /** Queue the delete confirmation for the current selection. */
  requestDeleteSelected: (docs: DocumentInfo[]) => void
  /** Dismiss the confirmation dialog. */
  cancelConfirm: () => void
  handleEnqueueSelected: (docs: DocumentInfo[]) => Promise<void>
  handlePatentAnalysis: (docs: DocumentInfo[]) => Promise<void>
  confirmDocAction: (target: DocConfirmAction) => Promise<void>
  confirmDialogTitle: string
  confirmDialogMessage: string
  confirmDialogLabel: string
}

export function useWorkspaceMutations({
  libraryRoot,
  removeFromSelection,
}: UseWorkspaceMutationsArgs): UseWorkspaceMutationsResult {
  const { t } = useTranslation()
  const deleteMutation = useDeleteDocuments()
  const bulkEnqueueMutation = useEnqueueTask()
  const patentMutation = usePatentAnalysis()
  const [isEnqueueingSelected, setIsEnqueueingSelected] = useState(false)
  const enqueueSelectedInProgressRef = useRef(false)
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

  const handleEnqueueSelected = useCallback(async (docs: DocumentInfo[]) => {
    if (!libraryRoot || docs.length === 0 || enqueueSelectedInProgressRef.current) return
    enqueueSelectedInProgressRef.current = true
    setIsEnqueueingSelected(true)
    const queuedIds = new Set<string>()
    const failures: { doc: DocumentInfo; message: string }[] = []
    try {
      for (const doc of docs) {
        try {
          await bulkEnqueueMutation.mutateAsync({
            libraryRoot,
            filePath: '',
            docId: doc.doc_id,
          })
          queuedIds.add(doc.doc_id)
        } catch (error) {
          failures.push({
            doc,
            message: getUserFacingError(error, t('common.unknownError')),
          })
        }
      }
    } finally {
      enqueueSelectedInProgressRef.current = false
      setIsEnqueueingSelected(false)
    }
    removeFromSelection(queuedIds)
    if (failures.length > 0) {
      const firstFailure = failures[0]
      showToast(t('workspace.bulkEnqueuePartial', {
        queued: queuedIds.size,
        failed: failures.length,
        filename: firstFailure.doc.file_name,
        error: firstFailure.message,
      }), 'error')
    } else {
      showToast(t('workspace.bulkEnqueueSuccess', { count: queuedIds.size }), 'success')
    }
  }, [libraryRoot, bulkEnqueueMutation, removeFromSelection, t])

  // Patent analysis is decoupled from import: the document is extensible as
  // soon as it is extracted, and this queues a Patent-only run for each target.
  const handlePatentAnalysis = useCallback(async (docs: DocumentInfo[]) => {
    const docIds = docs.map((doc) => doc.doc_id)
    if (docIds.length === 0) return
    try {
      const result = await patentMutation.mutateAsync(docIds)
      showToast(t('workspace.patentAnalysisSuccess', { count: result.enqueued }), 'success')
    } catch (e) {
      showToast(t('workspace.patentAnalysisError', { error: getUserFacingError(e, t('common.unknownError')) }), 'error')
    }
  }, [patentMutation, t])

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
    patentPending: patentMutation.isPending,
    isEnqueueingSelected,
    pendingConfirm,
    requestDelete,
    requestDeleteSelected,
    cancelConfirm,
    handleEnqueueSelected,
    handlePatentAnalysis,
    confirmDocAction,
    confirmDialogTitle,
    confirmDialogMessage,
    confirmDialogLabel,
  }
}
