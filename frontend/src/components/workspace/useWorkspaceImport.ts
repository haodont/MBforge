/** Workspace file import — picker, drag & drop, batch upload with progress. */

import { useCallback, useRef, useState } from 'react'
import type { DragEvent } from 'react'
import { useTranslation } from 'react-i18next'
import { useQueryClient } from '@tanstack/react-query'
import { useImportDocument } from '@/api/query/hooks'
import { queryKeys } from '@/api/query/keys'
import { showToast } from '@/hooks/useToast'
import { AppError, getUserFacingError } from '@/utils/errors'
import { runWithConcurrency } from '@/utils/concurrency'

/** PDFs uploaded at once; more only queue on the server's per-library lock. */
const UPLOAD_CONCURRENCY = 3

/** Position within a multi-file import batch. */
export type UploadBatch = {
  current: number
  total: number
}

export interface UseWorkspaceImportResult {
  /** A batch picker/drop import is running. */
  isImporting: boolean
  /** Either the batch flow or its mutation is busy — disables import buttons. */
  busy: boolean
  /** Aggregate upload percent (0-100) while uploading, else null. */
  uploadProgress: number | null
  /** Position within a multi-file batch, else null. */
  uploadBatch: UploadBatch | null
  /** A file is hovering the empty-state drop zone. */
  isDraggingFile: boolean
  /** Open the native file picker. */
  handleImport: () => void
  /** Accept a file drop. */
  handleDrop: (event: DragEvent<HTMLDivElement>) => void
  handleDragEnter: (event: DragEvent<HTMLDivElement>) => void
  handleDragLeave: () => void
  handleDragOver: (event: DragEvent<HTMLDivElement>) => void
}

export function useWorkspaceImport(): UseWorkspaceImportResult {
  const { t } = useTranslation()
  const queryClient = useQueryClient()
  const importMutation = useImportDocument()
  const [isDraggingFile, setIsDraggingFile] = useState(false)
  const [uploadProgress, setUploadProgress] = useState<number | null>(null)
  const [uploadBatch, setUploadBatch] = useState<UploadBatch | null>(null)
  const [isImporting, setIsImporting] = useState(false)
  const importInProgressRef = useRef(false)

  const handleImportFiles = useCallback(async (fileList: FileList | File[]) => {
    const files = Array.from(fileList)
    if (files.length === 0 || importInProgressRef.current) return

    const isPdfFile = (file: File) =>
      file.type === 'application/pdf' || file.name.toLowerCase().endsWith('.pdf')
    const failures = files
      .filter(file => !isPdfFile(file))
      .map(file => ({ file, message: t('library.pdfFilesOnly') }))
    const pdfFiles = files.filter(isPdfFile)

    if (files.length === 1 && pdfFiles.length === 0) {
      showToast(t('library.importError', { error: failures[0].message }), 'error')
      return
    }

    importInProgressRef.current = true
    setIsImporting(true)
    let successCount = 0
    let completedCount = 0
    // One fraction per file: the aggregate bar is their mean, so one file
    // finishing while another is mid-flight cannot make the bar jump back.
    const perFileProgress = pdfFiles.map(() => 0)
    const publishProgress = () => {
      const total = perFileProgress.reduce((sum, value) => sum + value, 0)
      setUploadProgress(Math.round((total / pdfFiles.length) * 100))
    }
    try {
      if (pdfFiles.length > 0) setUploadProgress(0)
      if (files.length > 1) setUploadBatch({ current: 0, total: pdfFiles.length })
      await runWithConcurrency(pdfFiles, UPLOAD_CONCURRENCY, async (file, index) => {
        try {
          await importMutation.mutateAsync({
            file,
            onProgress: (percent) => {
              perFileProgress[index] = percent / 100
              publishProgress()
            },
          })
          successCount += 1
        } catch (error) {
          const message = error instanceof AppError && error.context?.backend_code === 'duplicate_filename'
            ? t('library.duplicateFilename', { filename: file.name })
            : getUserFacingError(error, t('common.unknownError'))
          failures.push({ file, message })
        }
        completedCount += 1
        perFileProgress[index] = 1
        publishProgress()
        if (files.length > 1) setUploadBatch({ current: completedCount, total: pdfFiles.length })
      })
      // One refetch for the whole batch, instead of one per uploaded file.
      void queryClient.invalidateQueries({ queryKey: queryKeys.documents.all })
      void queryClient.invalidateQueries({ queryKey: queryKeys.ingest.all })
    } finally {
      importInProgressRef.current = false
      setIsImporting(false)
      setUploadProgress(null)
      setUploadBatch(null)
    }

    if (files.length === 1) {
      if (failures.length > 0) {
        showToast(t('library.importError', { error: failures[0].message }), 'error')
      } else {
        showToast(t('library.importSuccess'), 'success')
      }
    } else if (failures.length > 0) {
      const firstFailure = failures[0]
      showToast(t('library.importBatchPartial', {
        success: successCount,
        failed: failures.length,
        error: `${firstFailure.file.name}: ${firstFailure.message}`,
      }), 'error')
    } else {
      showToast(t('library.importBatchSuccess', { count: successCount }), 'success')
    }
  }, [importMutation, queryClient, t])

  const handleImport = useCallback(() => {
    const input = document.createElement('input')
    input.type = 'file'
    input.accept = '.pdf,application/pdf'
    input.multiple = true
    input.onchange = () => {
      if (input.files?.length) void handleImportFiles(input.files)
    }
    input.click()
  }, [handleImportFiles])

  const handleDrop = useCallback((event: DragEvent<HTMLDivElement>) => {
    event.preventDefault()
    setIsDraggingFile(false)
    void handleImportFiles(event.dataTransfer.files)
  }, [handleImportFiles])

  const handleDragEnter = useCallback((event: DragEvent<HTMLDivElement>) => {
    event.preventDefault()
    setIsDraggingFile(true)
  }, [])

  const handleDragLeave = useCallback(() => {
    setIsDraggingFile(false)
  }, [])

  const handleDragOver = useCallback((event: DragEvent<HTMLDivElement>) => {
    event.preventDefault()
  }, [])

  return {
    isImporting,
    busy: isImporting || importMutation.isPending,
    uploadProgress,
    uploadBatch,
    isDraggingFile,
    handleImport,
    handleDrop,
    handleDragEnter,
    handleDragLeave,
    handleDragOver,
  }
}
